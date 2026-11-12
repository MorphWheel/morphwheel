"""``settings.toml``: load, atomic save, and a change signal (phase-4 §4.6, §5).

The file lives at ``%APPDATA%\\Morphwheel\\settings.toml`` (``settings.paths``). It is the only
file this module ever writes, and it is ours: the "never replace a file" rule of the engine is
about the user's files, not this one.

Rules:

- **A save never destroys what it didn't read.** The document on disk is read again right before
  every write and our values are merged into it, so keys from a newer Morphwheel (or a hand edit
  made while the app runs) survive, and a newer ``schema`` is never written back as an older one.
  When that read fails (a sync client or a scanner holds the file), the save is **refused** and
  reported, instead of writing the defaults over the user's settings.
- **Atomic:** the document goes to a temp file beside the target, is flushed to disk, and
  ``os.replace`` swaps it in. A crash leaves either the old file or the new one, never a torn one.
  ``os.replace`` is retried for a moment on a sharing violation (the ``file_ops`` idiom).
- **A corrupt file is kept.** Invalid TOML is moved aside to ``settings.toml.invalid`` and the
  defaults are used; the next change writes a fresh file. Nothing is deleted.
- **A file that couldn't be read is read again before every write, until it reads.** The store
  then holds the defaults as a stand-in, and merging those into a file that has become readable
  would replace the user's values with them. ``update`` tries the read again first; when it
  works, every change made since the start is applied on top of what the file holds. While it
  doesn't, the changes stay in force in memory and each save is refused.
- **The store sets, then saves, then signals.** ``changed(Settings)`` carries the whole value;
  every owner takes it idempotently. A failed save is reported through ``save_failed`` and the
  in-memory value stays in force: the running app uses what the user chose.
- Only ``store.py`` imports Qt in this package; ``model.py`` and ``paths.py`` stay pure, and the
  worker side (R2) imports neither.
"""

from __future__ import annotations

import contextlib
import logging
import os
import secrets
import time
import tomllib
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import tomli_w
from PySide6.QtCore import QObject, Signal

from morphwheel.settings.model import DEFAULTS, Parsed, Settings, parse_settings, to_mapping

log = logging.getLogger("morphwheel.settings.store")

INVALID_SUFFIX = ".invalid"
_TEMP_PREFIX = ".settings-"
_TEMP_SUFFIX = ".tmp"
_O_BINARY = getattr(os, "O_BINARY", 0)
_REPLACE_RETRIES = 10
_REPLACE_RETRY_S = 0.05


# --------------------------------------------------------------------------- pure functions
def load_settings(path: Path) -> Parsed:
    """Read ``path``. A missing file is the first run; anything else that goes wrong is a
    problem line (what fell back to a default, and why: for the log and the settings window)."""
    return _load(path)[0]


def _load(path: Path) -> tuple[Parsed, bool]:
    """``load_settings`` plus whether the file was actually read (or is simply not there)."""
    try:
        raw, problems = _read_document(path)
    except OSError as e:
        line = f"{path.name}: can't be read ({_reason(e)}); using the defaults"
        return Parsed(DEFAULTS, (line,)), False
    parsed = parse_settings(raw)
    return Parsed(parsed.settings, problems + parsed.problems), True


def save_settings(path: Path, settings: Settings) -> None:
    """Merge ``settings`` into the document on disk and write it atomically.

    Raises ``OSError`` when the current file can't be read back or the new one can't be written;
    in both cases the file on disk is left as it was.
    """
    raw, _ = _read_document(path)  # OSError propagates: never write over what we couldn't read
    document = _merge(raw, to_mapping(settings))
    on_disk = raw.get("schema")
    if isinstance(on_disk, int) and not isinstance(on_disk, bool) and on_disk > settings.schema:
        document["schema"] = on_disk  # a newer Morphwheel wrote it; don't downgrade its file
    _write_atomically(path, document)


def _read_document(path: Path) -> tuple[dict[str, Any], tuple[str, ...]]:
    """The document at ``path`` as a dict: ``{}`` when missing, or moved aside as corrupt."""
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return {}, ()
    try:
        return tomllib.loads(data.decode("utf-8-sig")), ()  # an editor may add a BOM
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        aside = _move_aside(path)
        where = f"moved to {aside.name}" if aside else "left in place"
        return {}, (f"{path.name}: not valid TOML ({e}); {where}, using the defaults",)


def _move_aside(path: Path) -> Path | None:
    aside = path.with_name(path.name + INVALID_SUFFIX)
    try:
        path.replace(aside)
    except OSError as e:  # locked or read-only: the defaults still load, the file stays
        log.warning("couldn't move %s aside: %s", path.name, _reason(e))
        return None
    return aside


def _merge(raw: Mapping[str, Any], ours: Mapping[str, Any]) -> dict[str, Any]:
    """``ours`` over ``raw``: tables merge when both sides are tables, otherwise ours replaces."""
    out: dict[str, Any] = dict(raw)
    for key, value in ours.items():
        current = out.get(key)
        if isinstance(value, Mapping) and isinstance(current, Mapping):
            out[key] = _merge(current, value)
        else:
            out[key] = value
    return out


def _write_atomically(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = _create_temp_beside(path)
    try:
        with os.fdopen(fd, "wb") as f:
            tomli_w.dump(document, f)
            f.flush()
            os.fsync(f.fileno())
        _replace_with_retries(temp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            temp.unlink()
        raise


def _create_temp_beside(path: Path) -> tuple[int, Path]:
    """An exclusively created temp file in the target's folder, so the replace is a plain rename.

    Not ``tempfile.mkstemp``: on Windows it treats ``PermissionError`` as a name clash and retries
    thousands of times in a folder we may not write to, where the right answer is to fail at once.
    The random part keeps two instances apart until ``single_instance`` lands (S5 file 7).
    """
    temp = path.with_name(f"{_TEMP_PREFIX}{secrets.token_hex(8)}{_TEMP_SUFFIX}")
    return os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_BINARY, 0o600), temp


def _replace_with_retries(temp: Path, target: Path) -> None:
    for attempt in range(_REPLACE_RETRIES):
        try:
            temp.replace(target)
        except PermissionError:
            if attempt == _REPLACE_RETRIES - 1:
                raise
            time.sleep(_REPLACE_RETRY_S)  # a scanner or sync client holds the target for a moment
        else:
            return


def _reason(e: OSError) -> str:
    return e.strerror or str(e)


# --------------------------------------------------------------------------- the store
class SettingsStore(QObject):
    """The current settings, the file behind them, and the signal the app wires to its parts."""

    changed = Signal(object)  # the new Settings
    save_failed = Signal(str)  # the reason; the in-memory value is still in force

    def __init__(self, path: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._path = path
        self._settings = DEFAULTS
        self._problems: tuple[str, ...] = ()
        # ``None``: the file was read (or isn't there). A dict: it couldn't be read, the value
        # is a stand-in, and these are the changes made since, kept for the re-read.
        self._unsaved: dict[str, object] | None = None

    @property
    def path(self) -> Path:
        return self._path

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def problems(self) -> tuple[str, ...]:
        """What the last ``load`` had to fall back on; empty for a clean file or none at all."""
        return self._problems

    @property
    def unread(self) -> bool:
        """The file exists but couldn't be read at the last ``load``: the settings are the
        defaults standing in for values we haven't seen."""
        return self._unsaved is not None

    def load(self) -> Settings:
        """Read the file. Problems are logged once here and kept in ``problems``."""
        loaded, read = _load(self._path)
        self._unsaved = None if read else {}
        self._adopt(loaded)
        return loaded.settings

    def _adopt(self, loaded: Parsed) -> None:
        self._settings = loaded.settings
        self._problems = loaded.problems
        for problem in loaded.problems:
            log.warning("settings: %s", problem)
        log.info("settings loaded from %s (%d problem(s))", self._path, len(loaded.problems))

    def update(self, **changes: object) -> Settings:
        """Apply field changes, save, and emit ``changed``. Unknown fields raise ``TypeError``."""
        known = self._settings  # what the owners were last told
        reread = False
        if self._unsaved is not None:
            # Never merge stand-in defaults over a file that is readable by now: read it again,
            # and put every change of this run on top of what it holds.
            self._unsaved.update(changes)
            loaded, reread = _load(self._path)
            if reread:
                changes, self._unsaved = self._unsaved, None
                self._adopt(loaded)
        new = replace(self._settings, **changes)  # type: ignore[arg-type]
        if new == known and not reread:  # after a re-read the store itself moved: always tell
            return known
        self._settings = new
        try:
            save_settings(self._path, new)
        except OSError as e:
            reason = _reason(e)
            log.error("settings not saved to %s: %s", self._path, reason)
            self.save_failed.emit(reason)
        self.changed.emit(new)
        return new
