"""Find the plugins: the bundled ``builtin/`` directory and the user's plugins folder (phase-4 §5).

The GUI runs this at start, so it must never import plugin code (R5) and never block: it lists
directories and reads ``plugin.toml`` files, nothing else. What it finds goes to the registry
(enabled, order, trust) and to the Plugins page, which shows the broken folders with their reason.

Rules:

- **One plugin per folder**, ``<plugins dir>\\<plugin-id>\\plugin.toml``, no recursion. The
  folder must be named after the manifest's id (ASCII, case-insensitive), as §5 lays out, so the
  id names the folder the trust prompt shows and two folders can't claim one id. A folder whose
  name starts with ``.`` or ``_`` (``__pycache__``) is not a plugin and is skipped silently; any
  other folder that isn't a usable plugin is reported as :class:`BrokenPlugin` with a reason.
- **Links are not followed.** A junction or symlink in the plugins folder could point at a dead
  network path, and a ``stat`` through it would hang the GUI for the SMB timeout. Such an entry is
  reported broken; the user copies the folder instead. The plugins folder itself must be real too.
- **Nothing a manifest contains can stop the scan.** A manifest that is binary, nested a thousand
  levels deep or too large (``manifest.MAX_MANIFEST_BYTES``) is a broken plugin, not an exception.
- **Builtin privilege comes from the location** (``manifest.py``): manifests found under the
  bundled directory are builtin, every other one is third-party. A third-party plugin that claims
  a builtin's id is broken (workers key converters by plugin id, so a collision would route its
  targets to the builtin converter). A bundled manifest that fails is a packaging bug and raises.
- A broken plugin carries a :class:`BrokenKind` for the Plugins page's translated headline (D3a)
  and a raw English ``reason`` for the details and the log, as the settings window does for the
  settings file's problems.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from morphwheel.plugins.manifest import (
    BUILTIN_DIR,
    BUILTIN_PLUGIN_ID,
    MANIFEST_NAME,
    Manifest,
    ManifestError,
    load_manifest,
)

log = logging.getLogger("morphwheel.plugins.discovery")

BUILTIN_IDS: frozenset[str] = frozenset({BUILTIN_PLUGIN_ID})  # what the bundled directory holds


class BrokenKind(StrEnum):
    LINK = "link"  # the folder or its manifest is a junction or symlink
    NO_MANIFEST = "no_manifest"
    MISPLACED = "misplaced"  # a plugin.toml at the root of the plugins folder
    INVALID = "invalid"  # the manifest doesn't parse or validate (the reason names the field)
    NAME_MISMATCH = "name_mismatch"  # the folder isn't named after the plugin id
    ID_TAKEN = "id_taken"  # a builtin's id, or an earlier folder's
    MODULE_CLASH = "module_clash"  # the entry's module name is another plugin's (registry, RD-28)
    ERROR = "error"  # anything else; the log has the traceback


@dataclass(frozen=True)
class BrokenPlugin:
    """A folder in the plugins directory that can't be used, and why."""

    directory: Path
    kind: BrokenKind
    reason: str
    plugin_id: str | None = None  # known when the manifest parsed (a name mismatch, a collision)


@dataclass(frozen=True)
class Discovery:
    plugins: tuple[Manifest, ...]  # the builtin plugins first, then the user's, by folder name
    broken: tuple[BrokenPlugin, ...]
    user_dir: Path
    user_dir_error: str | None = None  # the user folder is there but can't be used at all

    def by_id(self) -> dict[str, Manifest]:
        return {m.plugin.id: m for m in self.plugins}


def discover(user_dir: Path, *, builtin_dir: Path = BUILTIN_DIR) -> Discovery:
    """Scan ``builtin_dir`` and ``user_dir``. Never imports, never raises for a user folder."""
    plugins = _builtin(builtin_dir)
    taken = {m.plugin.id for m in plugins}
    broken: list[BrokenPlugin] = []
    error: str | None = None
    try:
        if _is_link(user_dir):
            error = "the plugins folder is a link; it must be a real folder"
        elif user_dir.is_dir():  # missing: no user plugins, nothing to report
            for entry in _entries(user_dir):
                result = _scan(entry, taken)
                if isinstance(result, Manifest):
                    plugins.append(result)
                    taken.add(result.plugin.id)
                else:
                    broken.append(result)
                    log.warning("plugins: %s: %s", entry.name, result.reason)
            if os.path.lexists(user_dir / MANIFEST_NAME):
                reason = "plugin.toml must be inside a folder named after the plugin id"
                broken.append(BrokenPlugin(user_dir, BrokenKind.MISPLACED, reason))
        elif user_dir.exists():
            error = "the plugins path is a file; it must be a folder"
    except OSError as e:
        error = f"can't list the plugins folder: {e.strerror or e}"
    if error is not None:
        log.warning("plugins: %s (%s)", error, user_dir)
    return Discovery(tuple(plugins), tuple(broken), user_dir, error)


def _builtin(directory: Path) -> list[Manifest]:
    """The bundled plugins. Anything wrong here is a packaging bug, so it raises."""
    manifests: list[Manifest] = []
    for entry in _entries(directory):
        manifest_path = Path(entry.path) / MANIFEST_NAME
        if manifest_path.is_file():  # source checkouts hold other files; frozen builds data only
            manifests.append(load_manifest(manifest_path, is_builtin=True))
    found = {m.plugin.id for m in manifests}
    if found != BUILTIN_IDS:
        raise ManifestError(
            f"bundled plugins: expected {sorted(BUILTIN_IDS)}, found {sorted(found)}"
        )
    return manifests


# --------------------------------------------------------------------------- one folder
def _scan(entry: os.DirEntry[str], taken: set[str]) -> Manifest | BrokenPlugin:
    """Everything that can go wrong with one folder, as a kind and a reason. Never raises."""
    folder = Path(entry.path)
    if entry.is_symlink() or entry.is_junction():  # known from the listing, no stat
        reason = "the folder is a link; copy the plugin here instead"
        return BrokenPlugin(folder, BrokenKind.LINK, reason)
    manifest_path = folder / MANIFEST_NAME
    try:
        if _is_link(manifest_path):
            reason = "plugin.toml is a link; copy the file here instead"
            return BrokenPlugin(folder, BrokenKind.LINK, reason)
        if not os.path.lexists(manifest_path):
            nested = folder / folder.name
            hint = (
                f"; there is one in {folder.name}\\{folder.name}: move that folder up"
                if not _is_link(nested) and os.path.lexists(nested / MANIFEST_NAME)
                else ""
            )
            reason = f"no plugin.toml in this folder{hint}"
            return BrokenPlugin(folder, BrokenKind.NO_MANIFEST, reason)
        manifest = load_manifest(manifest_path, is_builtin=False)
    except ManifestError as e:
        return BrokenPlugin(folder, BrokenKind.INVALID, str(e))
    except Exception as e:  # a hostile manifest (RecursionError…) must not stop the scan
        log.warning("plugins: %s: unexpected error", entry.name, exc_info=True)
        reason = f"can't read this plugin: {type(e).__name__}"
        return BrokenPlugin(folder, BrokenKind.ERROR, reason)
    pid = manifest.plugin.id
    if not (folder.name.isascii() and folder.name.lower() == pid):
        reason = f"the folder must be named {pid}"
        return BrokenPlugin(folder, BrokenKind.NAME_MISMATCH, reason, pid)
    if pid in taken:
        return BrokenPlugin(folder, BrokenKind.ID_TAKEN, f"the id {pid} is already taken", pid)
    return manifest


# --------------------------------------------------------------------------- listing
def _entries(directory: Path) -> list[os.DirEntry[str]]:
    """The candidate folders, by name. Links are listed too, and rejected by ``_scan``.

    ``os.scandir`` answers from the listing itself, so no entry is ``stat``-ed through a link,
    and the entries keep that answer for ``_scan``.
    """
    found: list[os.DirEntry[str]] = []
    with os.scandir(directory) as entries:
        for entry in entries:
            if entry.name.startswith((".", "_")):
                continue
            if entry.is_symlink() or entry.is_junction() or entry.is_dir(follow_symlinks=False):
                found.append(entry)
    return sorted(found, key=lambda e: e.name.lower())


def _is_link(path: Path) -> bool:
    """A symlink or a junction. ``lstat`` looks at the link itself, never through it."""
    return path.is_symlink() or path.is_junction()
