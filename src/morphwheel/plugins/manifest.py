"""``plugin.toml``: the schema, its validation, and the ``Target``s it declares (phase-4 §4.5).

The GUI process reads manifests with ``tomllib`` and **never imports plugin code** (R5). The
``entry`` string is carried to the workers, where ``plugins.loader`` imports it.

Rules:

- **Builtin privilege comes from the location, never from the manifest.** The caller says whether
  the manifest was found under the bundled ``builtin/`` directory (``is_builtin``). Only then is a
  ``slot`` honored; a third-party manifest claiming ``slot`` or a builtin-looking id goes to the
  More arc (U2, U3), which ``core.catalog`` enforces again.
- **Target ids.** Builtin targets keep their plain id (``"jpeg"``). Third-party targets are
  namespaced ``"<plugin id>:<target id>"`` so two plugins can both offer ``"tiff"``.
- **API compatibility.** ``api = "MAJOR.MINOR"``. While the API major is 0, major and minor must
  match ``plugins.api.API_VERSION``; from 1.0 on, only the major must match.
- **Formats are ``FormatId`` values** (``"jpeg"``, ``"heic"``…), the same vocabulary as the core.
  ``output`` names the output format of a ``convert`` target; a ``compress`` target has none.
- A manifest that fails validation raises :class:`ManifestError` with the field that failed; the
  plugin is then skipped (S6 shows it as broken in the settings).
"""

from __future__ import annotations

import re
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from morphwheel.core.catalog import SlotPos, Target, TargetKind
from morphwheel.core.formats import FormatId
from morphwheel.plugins.api import API_VERSION
from morphwheel.plugins.loader import top_module

MANIFEST_NAME = "plugin.toml"
MAX_MANIFEST_BYTES = 64 * 1024  # a manifest is a few hundred bytes; more is not one
MAX_LABEL = 16  # fits a wheel slot
BUILTIN_PLUGIN_ID = "pillow_images"  # the one bundled plugin, under ``BUILTIN_DIR``
_PLUGIN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_TARGET_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_ENTRY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*$")
_API = re.compile(r"^(\d+)\.(\d+)$")


class ManifestError(ValueError):
    """The manifest is invalid. The message names the offending field."""


@dataclass(frozen=True)
class PluginInfo:
    id: str
    name: str
    version: str
    api: tuple[int, int]
    entry: str  # "package.module:ClassName", imported in workers only


@dataclass(frozen=True)
class Manifest:
    plugin: PluginInfo
    directory: Path  # where plugin.toml was found; put on sys.path in workers (A4)
    is_builtin: bool
    targets: tuple[Target, ...]


def api_compatible(declared: tuple[int, int], current: tuple[int, int] = API_VERSION) -> bool:
    if current[0] == 0:
        return declared == current
    return declared[0] == current[0]


# --------------------------------------------------------------------------- parsing
def parse_manifest(text: str, *, directory: Path, is_builtin: bool) -> Manifest:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ManifestError(f"not valid TOML: {e}") from None
    plugin = _plugin(_table(data, "plugin"), is_builtin=is_builtin)
    raw_targets = data.get("targets")
    if not isinstance(raw_targets, list) or not raw_targets:
        raise ManifestError("targets: at least one [[targets]] table is required")
    for index, raw in enumerate(raw_targets):
        if not isinstance(raw, dict):
            raise ManifestError(f"targets[{index}]: a table is required")
    targets = tuple(_target(t, plugin.id, is_builtin, i) for i, t in enumerate(raw_targets))
    ids = [t.id for t in targets]
    if len(ids) != len(set(ids)):
        raise ManifestError("targets: ids must be unique")
    return Manifest(plugin, directory, is_builtin, targets)


def load_manifest(path: Path, *, is_builtin: bool) -> Manifest:
    """Read ``path`` (a ``plugin.toml``) and parse it. Its directory becomes the plugin's.

    At most ``MAX_MANIFEST_BYTES`` are read, whatever the file's size says: a third-party
    manifest is untrusted input, and the GUI reads it at start (S6).
    """
    try:
        with path.open("rb") as f:
            data = f.read(MAX_MANIFEST_BYTES + 1)
    except OSError as e:
        raise ManifestError(f"can't read {path.name}: {e.strerror}") from None
    if len(data) > MAX_MANIFEST_BYTES:
        raise ManifestError(f"{path.name} is larger than {MAX_MANIFEST_BYTES // 1024} KiB")
    try:
        text = data.decode("utf-8-sig")  # a BOM (PowerShell's Out-File) is tolerated
    except UnicodeDecodeError:
        raise ManifestError(f"{path.name}: not UTF-8 text") from None
    return parse_manifest(text, directory=path.parent, is_builtin=is_builtin)


BUILTIN_DIR = Path(__file__).resolve().parent.parent / "builtin"  # morphwheel/builtin, by path


def builtin_manifest() -> Manifest:
    """The bundled image converter. Builtin because of where it lives, not what it says.

    Located by path, not by import: the GUI never imports anything under ``builtin`` (R5), and the
    frozen app ships ``plugin.toml`` as a data file next to the code (phase-4 §8).
    """
    return load_manifest(BUILTIN_DIR / BUILTIN_PLUGIN_ID / MANIFEST_NAME, is_builtin=True)


RESERVED_TOP_NAMES = frozenset({"morphwheel", "PIL", "pillow_heif"})  # the app and what it bundles


def _reserved_name(top: str) -> bool:
    """A top-level module name a third-party plugin can't own (RD-28): a worker's import of
    it would find the app's, Pillow's or Python's module, never the plugin's file."""
    return top in RESERVED_TOP_NAMES or top in sys.stdlib_module_names


# --------------------------------------------------------------------------- fields
def _table(data: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ManifestError(f"{key}: a table is required")
    return value


def _string(table: Mapping[str, object], key: str, *, where: str, maxlen: int = 200) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{where}.{key}: a non-empty string is required")
    if len(value) > maxlen:
        raise ManifestError(f"{where}.{key}: longer than {maxlen} characters")
    return value


def _plugin(table: Mapping[str, object], *, is_builtin: bool) -> PluginInfo:
    pid = _string(table, "id", where="plugin", maxlen=64)
    if not _PLUGIN_ID.match(pid):
        raise ManifestError("plugin.id: lowercase letters, digits, '.', '_' and '-' only")
    api_text = _string(table, "api", where="plugin", maxlen=16)
    m = _API.match(api_text)
    if m is None:
        raise ManifestError('plugin.api: expected "MAJOR.MINOR"')
    api = (int(m.group(1)), int(m.group(2)))
    if not api_compatible(api):
        raise ManifestError(
            f"plugin.api: {api_text} is not compatible with {API_VERSION[0]}.{API_VERSION[1]}"
        )
    entry = _string(table, "entry", where="plugin")
    if not _ENTRY.match(entry):
        raise ManifestError('plugin.entry: expected "module.path:ClassName"')
    if not is_builtin and _reserved_name(top_module(entry)):
        raise ManifestError(
            f"plugin.entry: the module name {top_module(entry)!r} belongs to the app, Pillow or "
            f"Python; use your own (the plugin id is a safe name)"
        )
    return PluginInfo(
        id=pid,
        name=_string(table, "name", where="plugin", maxlen=80),
        version=_string(table, "version", where="plugin", maxlen=40),
        api=api,
        entry=entry,
    )


def _target(table: Mapping[str, object], plugin_id: str, is_builtin: bool, index: int) -> Target:
    where = f"targets[{index}]"
    tid = _string(table, "id", where=where, maxlen=32)
    if not _TARGET_ID.match(tid):
        raise ManifestError(f"{where}.id: lowercase letters, digits, '_' and '-' only")
    label = _string(table, "label", where=where, maxlen=MAX_LABEL)
    kind = _enum(table.get("kind", "convert"), TargetKind, f"{where}.kind")
    output_raw = table.get("output")
    output: FormatId | None = None
    if kind is TargetKind.CONVERT:
        if output_raw is None:
            raise ManifestError(f"{where}.output: a convert target needs an output format")
        output = _enum(output_raw, FormatId, f"{where}.output")
    elif output_raw is not None:
        raise ManifestError(f"{where}.output: a compress target keeps the input format")
    accepts_raw = table.get("accepts")
    if not isinstance(accepts_raw, list) or not accepts_raw:
        raise ManifestError(f"{where}.accepts: a non-empty list of formats is required")
    accepts = frozenset(_enum(f, FormatId, f"{where}.accepts") for f in accepts_raw)
    if output is not None and output in accepts:
        raise ManifestError(f"{where}.accepts: must not include the output format {output.value}")
    slot: SlotPos | None = None
    slot_raw = table.get("slot")
    if slot_raw is not None:
        slot_text = slot_raw.lower() if isinstance(slot_raw, str) else slot_raw
        slot = _enum(slot_text, SlotPos, f"{where}.slot")
        if not is_builtin:
            slot = None  # third-party slots are ignored (U2/U3); the catalog ignores them too
    return Target(
        id=tid if is_builtin else f"{plugin_id}:{tid}",
        label=label.strip(),
        kind=kind,
        output_format=output,
        accepts=accepts,
        provider=plugin_id,
        is_builtin=is_builtin,
        slot=slot,
    )


def _enum[E: (TargetKind, FormatId, SlotPos)](value: object, enum: type[E], where: str) -> E:
    if not isinstance(value, str):
        raise ManifestError(f"{where}: a string is required")
    try:
        return enum(value)
    except ValueError:
        allowed = ", ".join(m.value for m in enum)
        raise ManifestError(f"{where}: {value!r} is not one of {allowed}") from None
