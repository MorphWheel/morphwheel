"""``ui.toasts``: the texts per outcome (phase-3 §5), and the manager's stacking and timers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from pytestqt.qtbot import QtBot

from morphwheel.core.errors import ErrorCode
from morphwheel.core.jobs import CreatedFile, JobResult, TaskResult, TaskStatus
from morphwheel.engine.undo import UndoItem, UndoOutcome, UndoStatus
from morphwheel.ui.toasts.manager import MAX_VISIBLE, ToastManager
from morphwheel.ui.toasts.model import (
    ERROR_MS,
    STICKY,
    ToastKind,
    ToastModel,
    human_size,
    toast_for,
    undo_toast,
    working_toast,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
from builtin_targets import BUILTINS

pytestmark = pytest.mark.usefixtures("qapp")

JPEG = next(t for t in BUILTINS if t.id == "jpeg")
COMPRESS = next(t for t in BUILTINS if t.id == "compress")


def ok(n: int, src: Path, out: Path, size: int = 840 * 1024, fallback: bool = False) -> TaskResult:
    return TaskResult(
        "j", n, src, TaskStatus.OK, output=CreatedFile(out, size, 0, src), used_fallback=fallback
    )


def failed(n: int, src: Path, code: ErrorCode, intact: bool = True) -> TaskResult:
    return TaskResult("j", n, src, TaskStatus.FAILED, error=code, source_intact=intact)


def test_single_success(tmp_path: Path) -> None:
    src = tmp_path / "photo.png"
    src.write_bytes(b"x" * (3 * 1024 * 1024 + 100 * 1024))
    model = toast_for(JobResult("j", JPEG, (ok(0, src, tmp_path / "photo.jpg"),)))
    assert model.kind is ToastKind.SUCCESS
    assert model.title == "Converted to JPG"
    assert model.body == "photo.jpg · 3.1 MB → 840 KB"
    assert not model.sticky


def test_batch_success_with_a_skip_and_a_fallback(tmp_path: Path) -> None:
    results = (
        ok(0, tmp_path / "a.png", tmp_path / "a.jpg"),
        TaskResult("j", 1, tmp_path / "b.jpg", TaskStatus.SKIPPED),
        ok(2, tmp_path / "c.png", Path("C:/Users/x/Downloads/Morphwheel/c.jpg"), fallback=True),
    )
    model = toast_for(JobResult("j", JPEG, results))
    assert model.title == "2 files converted to JPG"
    assert model.body.splitlines() == [
        "1 skipped — already JPG",
        "Saved to Downloads\\Morphwheel — the source folder is read-only",
    ]


def test_compress_outcomes(tmp_path: Path) -> None:
    out = tmp_path / "photo (compressed).jpg"
    single = toast_for(JobResult("j", COMPRESS, (ok(0, tmp_path / "photo.jpg", out, 610 * 1024),)))
    assert single.title == "Compressed"
    assert single.body.startswith("photo (compressed).jpg · ")
    mixed = toast_for(
        JobResult(
            "j",
            COMPRESS,
            (
                ok(0, tmp_path / "a.jpg", tmp_path / "a (compressed).jpg"),
                ok(1, tmp_path / "b.jpg", tmp_path / "b (compressed).jpg"),
                ok(2, tmp_path / "c.jpg", tmp_path / "c (compressed).jpg"),
                failed(3, tmp_path / "d.jpg", ErrorCode.NOT_SMALLER),
            ),
        )
    )
    assert mixed.kind is ToastKind.SUCCESS
    assert mixed.title == "3 files compressed · 1 already compact"  # RD-2
    compact = toast_for(
        JobResult("j", COMPRESS, (failed(0, tmp_path / "d.jpg", ErrorCode.NOT_SMALLER),))
    )
    assert compact.kind is ToastKind.INFO
    assert compact.title == "Already compact"
    assert compact.body == "d.jpg — no smaller file was made"


def test_partial_failed_and_nothing(tmp_path: Path) -> None:
    partial = toast_for(
        JobResult(
            "j",
            JPEG,
            (
                ok(0, tmp_path / "a.png", tmp_path / "a.jpg"),
                ok(1, tmp_path / "b.png", tmp_path / "b.jpg"),
                ok(2, tmp_path / "c.png", tmp_path / "c.jpg"),
                failed(3, tmp_path / "scan.tiff", ErrorCode.UNREADABLE),
            ),
        )
    )
    assert partial.kind is ToastKind.WARNING
    assert partial.title == "3 of 4 converted"
    assert partial.body == "scan.tiff — The file couldn't be read."
    assert partial.duration_ms == ERROR_MS
    one = toast_for(
        JobResult("j", JPEG, (failed(0, tmp_path / "photo.heic", ErrorCode.ENGINE_MISSING),))
    )
    assert one.kind is ToastKind.ERROR
    assert one.title == "Couldn't convert photo.heic"
    assert one.body == "HEIC support isn't installed."
    many = toast_for(
        JobResult(
            "j",
            JPEG,
            tuple(failed(i, tmp_path / f"{i}.png", ErrorCode.TIMEOUT) for i in range(5)),
        )
    )
    assert many.title == "Couldn't convert 5 files"
    assert many.body.splitlines()[-1] == "and 2 more"
    nothing = toast_for(
        JobResult("j", JPEG, (TaskResult("j", 0, tmp_path / "a.jpg", TaskStatus.SKIPPED),))
    )
    assert nothing.kind is ToastKind.INFO
    assert nothing.title == "Nothing to convert"
    assert nothing.body == "1 file already JPG"


def test_source_changed_is_critical_and_sticky(tmp_path: Path) -> None:
    model = toast_for(
        JobResult(
            "j",
            JPEG,
            (
                ok(0, tmp_path / "a.png", tmp_path / "a.jpg"),
                failed(1, tmp_path / "photo.png", ErrorCode.SOURCE_CHANGED, intact=False),
            ),
        )
    )
    assert model.kind is ToastKind.CRITICAL
    assert model.sticky
    assert model.duration_ms == STICKY
    assert model.title == "Source file changed during conversion"
    assert model.body.splitlines() == [
        "photo.png — size or date differs.",
        "This should never happen. Please report it. Nothing was written.",
    ]


def test_working_and_undo_models(tmp_path: Path) -> None:
    w = working_toast(12, "WebP", done=5)
    assert w.title == "Converting 12 files to WebP…"
    assert w.body == "5 / 12"
    assert w.sticky
    assert working_toast(1, "JPG").body == ""
    done = undo_toast(UndoOutcome("j", (UndoItem(tmp_path / "a.jpg", UndoStatus.RECYCLED),)))
    assert done.title == "Moved to Recycle Bin"
    assert done.body == "a.jpg"
    not_done = undo_toast(
        UndoOutcome(
            "j",
            (
                UndoItem(tmp_path / "a.jpg", UndoStatus.RECYCLED),
                UndoItem(tmp_path / "b.jpg", UndoStatus.CHANGED),
                UndoItem(tmp_path / "c.jpg", UndoStatus.MISSING),
                UndoItem(tmp_path / "d.jpg", UndoStatus.REFUSED),
            ),
        )
    )
    assert not_done.kind is ToastKind.WARNING
    assert not_done.title == "Not undone"
    assert not_done.body.splitlines() == [
        "b.jpg changed after conversion.",
        "c.jpg is no longer there.",
        "d.jpg has no Recycle Bin here.",
        "1 file moved to Recycle Bin",
    ]


@pytest.mark.parametrize(
    ("size", "text"),
    [
        (0, "0 B"),
        (900, "900 B"),
        (840 * 1024, "840 KB"),
        (3_250_000, "3.1 MB"),
        (2 * 1024**3, "2.0 GB"),
    ],
)
def test_human_size(size: int, text: str) -> None:
    assert human_size(size) == text


# ----------------------------------------------------------------------------- manager
def test_manager_stacks_replaces_and_dismisses(qtbot: QtBot) -> None:
    manager = ToastManager()
    screen = QGuiApplication.primaryScreen()
    area = screen.availableGeometry()
    working = manager.show(working_toast(3, "JPG"), key="job1")
    assert working.isVisible()
    assert not working.counting_down  # sticky until replaced
    assert working.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert working.geometry().right() <= area.right()
    assert working.geometry().bottom() <= area.bottom()

    progressed = manager.show(working_toast(3, "JPG", done=2), key="job1")
    assert progressed is working  # updated in place
    assert working.model.body == "2 / 3"

    result = manager.show(ToastModel(ToastKind.SUCCESS, "Converted to JPG", "", 100), key="job1")
    assert result is not working
    assert manager.visible == (result,)
    assert result.counting_down
    qtbot.waitUntil(lambda: manager.visible == (), timeout=3000)  # the countdown ran out

    toasts = [manager.show(ToastModel(ToastKind.ERROR, f"e{i}", "", 60_000)) for i in range(5)]
    assert len(manager.visible) == MAX_VISIBLE
    assert manager.visible == tuple(toasts[2:])  # the oldest made room
    tops = [t.geometry().top() for t in manager.visible]
    assert tops == sorted(tops)  # newest lowest, stacked upward without overlap
    for a, b in zip(manager.visible, manager.visible[1:], strict=False):
        assert a.geometry().bottom() < b.geometry().top()
    manager.dismiss_all()
    assert manager.visible == ()


def test_hover_pauses_the_countdown(qtbot: QtBot) -> None:
    manager = ToastManager()
    toast = manager.show(ToastModel(ToastKind.SUCCESS, "t", "", 5_000))
    assert toast.counting_down
    toast.enterEvent(None)  # type: ignore[arg-type]
    assert not toast.counting_down
    toast.leaveEvent(None)  # type: ignore[arg-type]
    assert toast.counting_down
    toast.dismiss()
    assert not toast.isVisible()
    assert manager.visible == ()


def test_sticky_toasts_survive_the_squeeze(qtbot: QtBot) -> None:
    manager = ToastManager()
    critical = manager.show(ToastModel(ToastKind.CRITICAL, "changed", "", STICKY))
    for i in range(4):
        manager.show(ToastModel(ToastKind.SUCCESS, f"s{i}", "", 60_000))
    assert critical in manager.visible
    manager.dismiss_all()
