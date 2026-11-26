"""Shared test setup.

Qt runs headless (``offscreen``) unless the caller overrides ``QT_QPA_PLATFORM``. That variable
must be set before pytest-qt creates the QApplication. Tests never touch the real user profile;
they use :func:`app_paths_tmp`.
"""

from __future__ import annotations

import gc
import getpass
import os
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

import pytest

import translations  # tools/, on the path through pyproject's pythonpath

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from morphwheel.settings.paths import AppPaths, app_paths


class Clock:
    """A fake monotonic clock in nanoseconds: tests step ``now`` and nothing else moves."""

    START = 1_000_000_000

    def __init__(self, now: int = START) -> None:
        self.now = now

    def __call__(self) -> int:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


# ------------------------------------------------------------------ garbage collection
# Python's cyclic GC runs on whichever thread is allocating when a threshold is crossed: in this
# suite that can be the engine's supervisor, a sniffer or an install thread. A QObject it frees
# there dies on the wrong thread, and a running timer of that object stays registered with the
# main thread's dispatcher, pointing at freed memory ("Timers cannot be stopped from another
# thread"); the main thread later crashes delivering its tick. That is the CI access violation of
# progress.md's open item, read from the dumps on 2026-11-26 (a ModifierPoller's 8 ms timer).
# So the suite collects on the main thread only: automatic collection is off for the session,
# every test ends with a collection here, and a collection on any other thread fails the test.

off_main_collections: list[str] = []


def _note_collection(phase: str, info: dict[str, int]) -> None:
    thread = threading.current_thread()
    if phase == "start" and thread is not threading.main_thread():
        off_main_collections.append(f"generation {info['generation']} on {thread.name}")


@pytest.fixture(autouse=True, scope="session")
def _no_automatic_gc() -> Iterator[None]:
    gc.disable()
    gc.callbacks.append(_note_collection)
    try:
        yield
    finally:
        gc.collect()  # the session fixtures' cycles too, here, before collection is automatic again
        gc.callbacks.remove(_note_collection)
        gc.enable()


@pytest.fixture(autouse=True)
def _collect_on_the_main_thread(_no_automatic_gc: None) -> Iterator[None]:
    """The first autouse fixture, so its teardown runs after every other fixture's: the test's
    cycles (rigs, windows, timers) are freed here, on the main thread."""
    yield
    gc.collect()
    if off_main_collections:
        seen = ", ".join(off_main_collections)
        off_main_collections.clear()
        pytest.fail(
            f"the garbage collector ran off the main thread ({seen}); see tests/conftest.py"
        )


@pytest.fixture(autouse=True)
def _own_sys_path() -> Iterator[None]:
    """Every test gets ``sys.path`` back as it found it. The loader appends plugin folders to it,
    and a worker spawned later inherits the process's path: a fixture folder left behind would
    make a plugin installed under the same module name resolve elsewhere (RD-28 refuses it)."""
    saved = list(sys.path)
    yield
    sys.path[:] = saved


@pytest.fixture
def app_paths_tmp(tmp_path: Path) -> AppPaths:
    """Morphwheel's locations, redirected into a per-test temporary directory."""
    return app_paths(
        roaming_base=tmp_path / "roaming",
        local_base=tmp_path / "local",
        downloads=tmp_path / "Downloads",
    )


@pytest.fixture
def lock_directory() -> Iterator[Callable[[Path], None]]:
    """Deny this user the right to add files to a directory (an NTFS deny ACE); restored afterwards.

    Used by the file_ops and worker tests for the read-only-folder rows of phase-4 §6. Seed the
    directory first; the ACE only blocks *new* files.
    """
    user = rf"{os.environ.get('USERDOMAIN', '')}\{getpass.getuser()}"
    locked: list[Path] = []

    def lock(directory: Path) -> None:
        done = subprocess.run(
            ["icacls", str(directory), "/deny", f"{user}:(WD)"],
            capture_output=True,
            text=True,
            check=False,
        )
        if done.returncode != 0:
            pytest.skip(f"icacls can't set a deny ACE here: {done.stderr.strip()}")
        locked.append(directory)

    try:
        yield lock
    finally:
        for directory in locked:
            subprocess.run(
                ["icacls", str(directory), "/remove:d", user], capture_output=True, check=False
            )


def render_widget(widget: object) -> object:
    """A widget painted into a transparent ``QImage``. Qt is imported lazily: unit tests stay pure.

    The image is filled with alpha 0 first, so an assertion on a corner's alpha is about what the
    widget painted and nothing else.
    """
    from PySide6.QtGui import QImage

    image = QImage(widget.size(), QImage.Format.Format_ARGB32_Premultiplied)  # type: ignore[attr-defined]
    image.fill(0)
    widget.render(image)  # type: ignore[attr-defined]
    return image


@pytest.fixture(autouse=True)
def recorded_autostart(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """No test touches the user's Run key: the app's autostart calls are recorded instead, and
    the registry says "off". The unit tests of the module itself bind the real functions at
    import time and run them against a throwaway key."""
    from morphwheel.platform import autostart

    asked: list[bool] = []

    def sync(enabled: bool, **_: object) -> bool:
        asked.append(enabled)
        return True

    monkeypatch.setattr(autostart, "sync", sync)
    monkeypatch.setattr(autostart, "is_enabled", lambda **_: False)
    return asked


@pytest.fixture
def instance_names() -> tuple[str, str]:
    """A mutex and a pipe name for one test: never the real ones, never a running Morphwheel."""
    token = uuid.uuid4().hex[:8]
    return f"Local\\mw-test-{token}", f"mw-test-{token}"


@pytest.fixture
def unreadable() -> Callable[[Path], AbstractContextManager[None]]:
    """``with unreadable(path):`` makes reading that one file fail like a sharing violation
    (a sync client or a scanner holding it). Other files read normally."""

    @contextmanager
    def held(path: Path) -> Iterator[None]:
        original = Path.read_bytes

        def locked(self: Path) -> bytes:
            if self == path:
                raise PermissionError(32, "The process cannot access the file")
            return original(self)

        with pytest.MonkeyPatch.context() as patched:
            patched.setattr(Path, "read_bytes", locked)
            yield

    return held


@pytest.fixture
def refused_saves() -> Callable[[], AbstractContextManager[None]]:
    """``with refused_saves():`` makes every settings save fail (RD-15: reported, in force)."""

    @contextmanager
    def refusing() -> Iterator[None]:
        import morphwheel.settings.store as store_module

        def refused(path: Path, settings: object) -> None:
            raise PermissionError(32, "The process cannot access the file")

        with pytest.MonkeyPatch.context() as patched:
            patched.setattr(store_module, "save_settings", refused)
            yield

    return refusing


@pytest.fixture
def rtl() -> Iterator[None]:
    """The application mirrored (D3a) for one test; the session's qapp is put back afterwards."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    assert app is not None
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    try:
        yield
    finally:
        app.setLayoutDirection(Qt.LayoutDirection.LeftToRight)


@pytest.fixture
def opened_folders(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """What ``platform.shell`` asked the shell to open, instead of opening it (no Explorer)."""
    from morphwheel.platform import shell

    opened: list[Path] = []
    monkeypatch.setattr(shell.os, "startfile", lambda p: opened.append(Path(p)))
    return opened


@pytest.fixture
def temp_files() -> Callable[[Path], list[Path]]:
    """The ``.tmp`` files left in a folder: an atomic writer must leave none behind."""

    def scan(folder: Path) -> list[Path]:
        return [p for p in folder.iterdir() if p.suffix == ".tmp"] if folder.exists() else []

    return scan


# ------------------------------------------------------------------ a right-to-left language
HEBREW_TS = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="he" sourcelanguage="en">
<context>
    <name>Toast</name>
    <message>
        <source>Undo</source>
        <translation>בטל</translation>
    </message>
    <message numerus="yes">
        <source>%n file(s) converted to %1</source>
        <translation>
            <numerusform>קובץ אחד הומר ל-%1</numerusform>
            <numerusform>%n קבצים הומרו ל-%1</numerusform>
        </translation>
    </message>
</context>
<context>
    <name>Tray</name>
    <message>
        <source>Quit</source>
        <translation>יציאה</translation>
    </message>
</context>
</TS>
"""


def compile_hebrew(folder: Path) -> Path:
    """``morphwheel_he.qm`` in ``folder``. Skips the test when ``lrelease`` isn't installed."""
    (folder / "morphwheel_he.ts").write_text(HEBREW_TS, encoding="utf-8")
    try:
        [qm] = translations.release(folder)
    except FileNotFoundError as e:
        pytest.skip(str(e))
    return qm


@pytest.fixture(scope="session")
def hebrew_catalog(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A folder with the tests' Hebrew catalog, compiled once per session."""
    folder = tmp_path_factory.mktemp("catalog")
    compile_hebrew(folder)
    return folder


@pytest.fixture
def hebrew(hebrew_catalog: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The app's catalog folder is the Hebrew one for this test (``i18n.TRANSLATIONS_DIR``)."""
    from morphwheel import i18n

    monkeypatch.setattr(i18n, "TRANSLATIONS_DIR", hebrew_catalog)
    return hebrew_catalog


@pytest.fixture
def read_only_dir(tmp_path: Path, lock_directory: Callable[[Path], None]) -> Path:
    """An empty directory this user may not add files to."""
    d = tmp_path / "locked"
    d.mkdir()
    lock_directory(d)
    return d


def teardown_app(app: object) -> None:
    """Stop an ``Application`` built by a test and drop its log handlers, whatever the test did."""
    import logging

    app.stop()  # type: ignore[attr-defined]
    logger = logging.getLogger("morphwheel")
    for handler in [h for h in logger.handlers if getattr(h, "_morphwheel_handler", False)]:
        logger.removeHandler(handler)
        handler.close()
