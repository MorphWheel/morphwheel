"""``ui.toasts``: the texts and buttons per outcome (phase-3 §5), and the manager's stacking,
timers, delays, holds and action signals."""

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
    ActionKind,
    Progress,
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


def kinds(model: ToastModel) -> list[ActionKind]:
    return [a.kind for a in model.actions]


def test_single_success(tmp_path: Path) -> None:
    src = tmp_path / "photo.png"
    src.write_bytes(b"x" * (3 * 1024 * 1024 + 100 * 1024))
    model = toast_for(JobResult("j", JPEG, (ok(0, src, tmp_path / "photo.jpg"),)))
    assert model.kind is ToastKind.SUCCESS
    assert model.title == "Converted to JPG"
    assert model.body == "photo.jpg · 3.1 MB → 840 KB"
    assert not model.sticky
    assert model.progress is None
    assert kinds(model) == [ActionKind.SHOW_IN_FOLDER, ActionKind.UNDO]
    assert [a.label for a in model.actions] == ["Show in folder", "Undo"]
    assert model.actions[0].payload == tmp_path / "photo.jpg"
    assert model.actions[1].payload == "j"  # the job id, never a path (D5)


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
    assert [a.label for a in model.actions] == ["Show in folder", "Undo all"]
    assert model.actions[0].payload == tmp_path / "a.jpg"  # the first output


def test_compress_outcomes(tmp_path: Path) -> None:
    out = tmp_path / "photo (compressed).jpg"
    single = toast_for(JobResult("j", COMPRESS, (ok(0, tmp_path / "photo.jpg", out, 610 * 1024),)))
    assert single.title == "Compressed"
    assert single.body.startswith("photo (compressed).jpg · ")
    assert kinds(single) == [ActionKind.SHOW_IN_FOLDER, ActionKind.UNDO]
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
    assert [a.label for a in mixed.actions] == ["Show in folder", "Undo all"]
    compact = toast_for(
        JobResult("j", COMPRESS, (failed(0, tmp_path / "d.jpg", ErrorCode.NOT_SMALLER),))
    )
    assert compact.kind is ToastKind.INFO
    assert compact.title == "Already compact"
    assert compact.body == "d.jpg — no smaller file was made"
    assert compact.actions == ()  # nothing was made, nothing to undo (phase-3 §5)


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
    assert kinds(partial) == [ActionKind.DETAILS, ActionKind.SHOW_IN_FOLDER]
    assert partial.actions[0].payload == f"{tmp_path / 'scan.tiff'} — The file couldn't be read."
    assert partial.actions[1].payload == tmp_path / "a.jpg"
    one = toast_for(
        JobResult("j", JPEG, (failed(0, tmp_path / "photo.heic", ErrorCode.ENGINE_MISSING),))
    )
    assert one.kind is ToastKind.ERROR
    assert one.title == "Couldn't convert photo.heic"
    assert one.body == "HEIC support isn't installed."
    assert kinds(one) == [ActionKind.DETAILS]
    many = toast_for(
        JobResult(
            "j",
            JPEG,
            tuple(failed(i, tmp_path / f"{i}.png", ErrorCode.TIMEOUT) for i in range(5)),
        )
    )
    assert many.title == "Couldn't convert 5 files"
    assert many.body.splitlines()[-1] == "and 2 more"
    details = str(many.actions[0].payload).splitlines()
    assert len(details) == 5  # Details has every file; the body shows three
    assert details[4].startswith(str(tmp_path / "4.png"))
    nothing = toast_for(
        JobResult("j", JPEG, (TaskResult("j", 0, tmp_path / "a.jpg", TaskStatus.SKIPPED),))
    )
    assert nothing.kind is ToastKind.INFO
    assert nothing.title == "Nothing to convert"
    assert nothing.body == "1 file already JPG"
    assert nothing.actions == ()


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
    assert kinds(model) == [ActionKind.DETAILS, ActionKind.SHOW_IN_FOLDER]
    assert model.actions[1].payload == tmp_path / "photo.png"  # the changed source
    assert str(tmp_path / "photo.png") in str(model.actions[0].payload)


def test_working_and_undo_models(tmp_path: Path) -> None:
    w = working_toast(12, "WebP", done=5)
    assert w.title == "Converting 12 files to WebP…"
    assert w.body == "5 / 12"
    assert w.sticky
    assert w.progress == Progress(5, 12)
    assert w.actions == ()
    one = working_toast(1, "JPG", name="photo.png")
    assert one.title == "Converting photo.png to JPG…"
    assert one.body == ""
    assert one.progress is None  # no bar, no shimmer: the title says it (review O1)
    done = undo_toast(UndoOutcome("j", (UndoItem(tmp_path / "a.jpg", UndoStatus.RECYCLED),)))
    assert done.title == "Moved to Recycle Bin"
    assert done.body == "a.jpg"
    assert done.actions == ()
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
    assert kinds(not_done) == [ActionKind.SHOW_IN_FOLDER]
    assert not_done.actions[0].payload == tmp_path / "b.jpg"  # still there, unlike c.jpg
    unknown = undo_toast(UndoOutcome("j", (UndoItem(Path(), UndoStatus.UNKNOWN_JOB),)))
    assert unknown.actions == ()


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
def still() -> ToastManager:
    """A manager with animations off (C7): every show and dismiss is immediate."""
    return ToastManager(motion_enabled=lambda: False)


def test_manager_stacks_replaces_and_dismisses(qtbot: QtBot) -> None:
    manager = still()
    screen = QGuiApplication.primaryScreen()
    area = screen.availableGeometry()
    working = manager.show(working_toast(3, "JPG"), key="job1")
    assert working is not None
    assert working.isVisible()
    assert not working.counting_down  # sticky until replaced
    assert working.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert working.geometry().right() <= area.right()
    assert working.geometry().bottom() <= area.bottom()
    assert working.bar.progress == (0, 3)

    progressed = manager.show(working_toast(3, "JPG", done=2), key="job1")
    assert progressed is working  # updated in place
    assert working.model.body == "2 / 3"
    assert working.bar.progress == (2, 3)

    result = manager.show(ToastModel(ToastKind.SUCCESS, "Converted to JPG", "", 100), key="job1")
    assert result is not None
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
    manager = still()
    toast = manager.show(ToastModel(ToastKind.SUCCESS, "t", "", 5_000))
    assert toast is not None
    assert toast.counting_down
    toast.enterEvent(None)  # type: ignore[arg-type]
    assert not toast.counting_down
    toast.leaveEvent(None)  # type: ignore[arg-type]
    assert toast.counting_down
    toast.dismiss()
    assert not toast.isVisible()
    assert manager.visible == ()
    toast.leaveEvent(None)  # type: ignore[arg-type]
    assert not toast.counting_down  # a dismissed toast never re-arms


def test_sticky_toasts_survive_the_squeeze(qtbot: QtBot) -> None:
    manager = still()
    critical = manager.show(ToastModel(ToastKind.CRITICAL, "changed", "", STICKY))
    for i in range(4):
        manager.show(ToastModel(ToastKind.SUCCESS, f"s{i}", "", 60_000))
    assert critical in manager.visible
    manager.dismiss_all()


def test_a_delayed_toast_shows_unless_the_result_comes_first(qtbot: QtBot) -> None:
    """Phase-3 §3: a single file shows "working" only after about a second."""
    manager = still()
    model = working_toast(1, "JPG", name="photo.png")
    manager.show_later(model, 50, key="job")
    assert manager.pending == ("job",)
    assert manager.visible == ()
    qtbot.waitUntil(lambda: manager.visible != (), timeout=2000)  # it fires…
    assert manager.visible[0].model is model
    assert manager.pending == ()
    manager.dismiss_all()

    manager.show_later(model, 50, key="job")
    result = manager.show(ToastModel(ToastKind.SUCCESS, "done", "", 60_000), key="job")
    assert manager.pending == ()  # …unless the result replaced it first
    qtbot.wait(120)
    assert manager.visible == (result,)
    manager.show_later(model, 50, key="job2")
    manager.cancel("job2")
    qtbot.wait(120)
    assert manager.visible == (result,)
    manager.show_later(model, 50, key="job3")
    manager.dismiss_all()  # shutdown drops what was waiting
    qtbot.wait(120)
    assert manager.visible == ()


def test_a_dismissed_working_toast_stays_dismissed_until_the_result(qtbot: QtBot) -> None:
    manager = still()
    working = manager.show(working_toast(5, "JPG"), key="job")
    assert working is not None
    working.close_button.click()
    assert manager.visible == ()
    assert manager.show(working_toast(5, "JPG", done=2), key="job") is None  # the user said no
    assert manager.visible == ()
    result = manager.show(ToastModel(ToastKind.SUCCESS, "done", "", 60_000), key="job")
    assert manager.visible == (result,)
    manager.dismiss_all()
    assert manager.show(working_toast(5, "JPG"), key="job") is not None  # the key is free again
    manager.dismiss_all()


def test_nothing_shows_while_the_wheel_is_up(qtbot: QtBot) -> None:
    """C1: the wheel is the only window during a drag; toasts wait for the hold to end."""
    wheel_visible = [True]
    manager = ToastManager(motion_enabled=lambda: False, hold=lambda: wheel_visible[0])
    assert manager.show(ToastModel(ToastKind.SUCCESS, "a", "", 60_000), key="a") is None
    manager.show_later(working_toast(1, "JPG", name="b.png"), 10, key="b")
    qtbot.wait(60)
    assert manager.visible == ()
    assert manager.held == 2
    manager.release()  # the wheel says it hid, but it is up again: still held
    assert manager.held == 2
    wheel_visible[0] = False
    manager.release()
    assert [t.key for t in manager.visible] == ["a", "b"]
    assert manager.held == 0
    manager.dismiss_all()
    wheel_visible[0] = True
    manager.show(ToastModel(ToastKind.SUCCESS, "c", "", 60_000))
    manager.dismiss_all()  # shutdown while held: nothing appears later
    wheel_visible[0] = False
    manager.release()
    assert manager.visible == ()


def test_actions_reach_the_manager_signals_once(qtbot: QtBot, tmp_path: Path) -> None:
    manager = still()
    model = toast_for(JobResult("j", JPEG, (ok(0, tmp_path / "a.png", tmp_path / "a.jpg"),)))
    toast = manager.show(model, key="j")
    assert toast is not None
    with qtbot.waitSignal(manager.show_in_folder_clicked, timeout=1000) as folder:
        toast.buttons[0].click()
    assert folder.args == [tmp_path / "a.jpg"]
    assert manager.visible == ()  # a button acts once and dismisses the toast
    toast = manager.show(model, key="j")
    assert toast is not None
    with qtbot.waitSignal(manager.undo_clicked, timeout=1000) as undo:
        toast.buttons[1].click()
    assert undo.args == ["j"]
    error = manager.show(
        toast_for(JobResult("j", JPEG, (failed(0, tmp_path / "x.png", ErrorCode.TIMEOUT),)))
    )
    assert error is not None
    with qtbot.waitSignal(manager.details_clicked, timeout=1000) as details:
        error.buttons[0].click()
    assert details.args[0].startswith(str(tmp_path / "x.png"))
    manager.dismiss_all()
