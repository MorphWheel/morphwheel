"""``app.controller`` offscreen: a fake monitor, a real poller (fake keys), a real wheel window.

Each scenario is a sequence of inputs and the state the machine and the window must end in.
Traceability (phase-4 §6): "pause from the tray: drags ignored, the poller stops"; "the trigger
key reaches the poller at once" (D8); "hide immediately on release without a drop" (wiring);
the S1 carry-overs (DragEnter always accepted, GiveUp fed, More arc center from the screen).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QMimeData, QObject, QPoint, QPointF, Qt, QUrl, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QApplication

from morphwheel.app.controller import Controller
from morphwheel.core.catalog import Catalog, SlotPos
from morphwheel.core.geometry import WheelGeometry, polar
from morphwheel.core.gesture import RELEASE_GRACE_NS, State
from morphwheel.platform import _win32 as w
from morphwheel.platform.modifier_poller import ModifierPoller
from morphwheel.platform.raw_input import Registration
from morphwheel.platform.window_probe import SourceInfo
from morphwheel.ui.wheel.window import WheelWindow

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
from builtin_targets import BUILTINS

pytestmark = pytest.mark.usefixtures("qapp")

EXPLORER = Qt.DropAction.CopyAction | Qt.DropAction.MoveAction | Qt.DropAction.LinkAction
SHIFT = Qt.KeyboardModifier.ShiftModifier
ALLOWED = SourceInfo(hwnd=0x100, pid=1, chain=("SHELLDLL_DefView", "CabinetWClass"), allowed=True)
TITLE_BAR = SourceInfo(
    hwnd=0x101, pid=1, chain=("TITLE_BAR_SCAFFOLDING_WINDOW_CLASS",), allowed=False
)


class FakeMonitor(QObject):
    pointer_down = Signal(int, int)
    pointer_moved = Signal()
    pointer_up = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.track_moves = False
        self.started = 0
        self.stopped = 0

    def start(self) -> Registration:
        self.started += 1
        return Registration(True)

    def stop(self) -> None:
        self.stopped += 1


class Keys:
    def __init__(self) -> None:
        self.down: set[int] = set()

    def __call__(self, vk: int) -> bool:
        return vk in self.down


class Rig:
    """One controller with every input under the test's control."""

    def __init__(self) -> None:
        self.now = 1_000_000_000
        self.cursor = (1200, 800)
        self.source = ALLOWED
        self.button = True
        self.keys = Keys()
        self.monitor = FakeMonitor()
        self.poller = ModifierPoller(reader=self.keys, clock=lambda: self.now)
        self.window = WheelWindow(
            Catalog.of(BUILTINS), clock=lambda: self.now, cursor=lambda: QPoint(600, 400)
        )
        self.drops: list[Any] = []
        self.controller = Controller(
            self.monitor,
            self.poller,
            self.window,
            source_info=lambda x, y, *, any_source=False: self.source,
            threshold=lambda hwnd, x, y: (4, 4),
            button_down=lambda: self.button,
            cursor=lambda: self.cursor,
            clock=lambda: self.now,
        )
        self.controller.drop_received.connect(self.drops.append)
        self.controller.start()

    # inputs
    def press(self) -> None:
        self.monitor.pointer_down.emit(*self.cursor)

    def move_by(self, dx: int, dy: int) -> None:
        self.cursor = (self.cursor[0] + dx, self.cursor[1] + dy)
        self.monitor.pointer_moved.emit()

    def release(self) -> None:
        self.button = False
        self.monitor.pointer_up.emit()

    def shift(self, down: bool) -> None:
        if down:
            self.keys.down.add(w.VK_SHIFT)
        else:
            self.keys.down.discard(w.VK_SHIFT)
        self.sample()

    def sample(self, advance_ms: int = 8) -> None:
        self.now += advance_ms * 1_000_000
        if self.poller.active:
            self.poller._sample()

    def drag(self, where: str, kind: str, *names: str) -> bool:
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(f"C:/mw-test/{n}") for n in names or ("photo.png",)])
        g = WheelGeometry.for_size(self.window.wheel_size)
        c = QPointF(self.window.width() / 2, self.window.height() / 2)
        if where == "hub":
            pos = c
        else:
            p = polar(
                WheelGeometry.slot_angle(SlotPos(where)), (g.slot_inner_r + g.slot_outer_r) / 2
            )
            pos = QPointF(c.x() + p.x, c.y() + p.y)
        events = {
            "enter": lambda: QDragEnterEvent(pos, EXPLORER, mime, Qt.MouseButton.LeftButton, SHIFT),
            "move": lambda: QDragMoveEvent(pos, EXPLORER, mime, Qt.MouseButton.LeftButton, SHIFT),
            "drop": lambda: QDropEvent(pos, EXPLORER, mime, Qt.MouseButton.LeftButton, SHIFT),
            "leave": QDragLeaveEvent,
        }
        event = events[kind]()
        QApplication.sendEvent(self.window, event)
        QApplication.processEvents()  # deliver the queued wheel signals
        return bool(event.isAccepted())

    @property
    def state(self) -> State:
        return self.controller.machine.state


@pytest.fixture
def rig() -> Rig:
    return Rig()


def open_wheel(rig: Rig) -> None:
    rig.press()
    rig.move_by(10, 0)
    rig.shift(True)
    assert rig.state is State.WHEEL_OPEN
    assert rig.window.isVisible()


def test_c1_shift_drag_and_drop_logs_a_drop_request(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    assert rig.monitor.started == 1
    assert not rig.poller.active  # idle: no polling
    rig.press()
    assert rig.state is State.PRESSED
    assert rig.poller.active
    assert rig.monitor.track_moves
    rig.move_by(2, 0)
    assert rig.state is State.PRESSED  # within the threshold
    rig.move_by(10, 0)
    assert rig.state is State.DRAGGING
    assert not rig.window.isVisible()  # no Shift yet: nothing of ours is shown
    rig.shift(True)
    assert rig.state is State.WHEEL_OPEN
    assert rig.window.isVisible()

    assert rig.drag("hub", "enter")  # always accepted
    assert rig.drag("n", "move")
    rig.release()  # the raw up comes 1-4 ms before OLE's Drop
    assert rig.state is State.RELEASING
    assert rig.window.isVisible()  # not hidden yet: the drop is still coming
    with caplog.at_level(logging.INFO, logger="morphwheel.app.controller"):
        assert rig.drag("n", "drop")
    assert rig.state is State.IDLE
    assert not rig.window.isVisible()
    assert not rig.poller.active
    assert not rig.monitor.track_moves
    assert len(rig.drops) == 1
    assert rig.drops[0].target_id == "jpeg"
    assert any("DropRequest: 1 file(s) -> jpeg" in r.message for r in caplog.records)


def test_release_without_a_drop_hides_after_the_grace_period(rig: Rig) -> None:
    open_wheel(rig)
    rig.release()
    assert rig.state is State.RELEASING
    rig.sample(advance_ms=100)
    assert rig.window.isVisible()
    rig.sample(advance_ms=RELEASE_GRACE_NS // 1_000_000)
    assert rig.state is State.IDLE
    assert not rig.window.isVisible()
    assert rig.drops == []


def test_release_over_the_hub_hides_on_drag_leave(rig: Rig) -> None:
    open_wheel(rig)
    rig.drag("hub", "enter")
    rig.release()
    rig.drag("hub", "leave")  # OLE: DragLeave, not Drop, after a release over the hub
    assert rig.state is State.IDLE
    assert not rig.window.isVisible()


def test_leaving_the_halo_dismisses_and_a_new_shift_reopens(rig: Rig) -> None:
    open_wheel(rig)
    rig.drag("hub", "enter")
    rig.drag("hub", "leave")  # button still down: the pointer left the halo (U1)
    assert rig.state is State.DISMISSED
    assert not rig.window.isVisible()
    assert rig.poller.active  # still a gesture: a new press of Shift can reopen
    rig.shift(False)
    rig.shift(True)
    assert rig.state is State.WHEEL_OPEN
    assert rig.window.isVisible()
    assert rig.window.session is not None
    assert rig.window.session.plan is None  # a fresh session


def test_rejected_drop_cancels_at_once(rig: Rig) -> None:
    open_wheel(rig)
    rig.drag("hub", "enter")
    rig.drag("n", "move")
    rig.release()
    assert not rig.drag("hub", "drop")  # released over the hub after an accepted DragMove
    assert rig.state is State.IDLE
    assert not rig.window.isVisible()
    assert rig.drops == []


def test_give_up_dismisses(rig: Rig) -> None:
    open_wheel(rig)
    for _ in range(200):  # 1.6 s of samples with no DragEnter
        rig.sample()
    QApplication.processEvents()
    assert rig.state is State.DISMISSED
    assert not rig.window.isVisible()


def test_disallowed_source_and_own_window_never_open(rig: Rig) -> None:
    rig.source = TITLE_BAR
    rig.press()
    rig.move_by(10, 0)
    rig.shift(True)
    assert rig.state is State.DRAGGING
    assert not rig.window.isVisible()
    rig.release()
    assert rig.state is State.IDLE

    rig.source = SourceInfo(int(rig.window.winId()), 1, ("Qt6QWindowToolSaveBits",), True)
    rig.press()
    assert rig.state is State.IDLE  # a press on the wheel is not a gesture


def test_pause_ends_the_gesture_and_ignores_presses(rig: Rig) -> None:
    open_wheel(rig)
    rig.controller.pause()
    assert rig.controller.paused
    assert not rig.window.isVisible()
    assert rig.state is State.IDLE
    assert not rig.poller.active
    assert not rig.monitor.track_moves
    rig.press()
    rig.move_by(10, 0)
    rig.shift(True)
    assert rig.state is State.IDLE
    assert not rig.window.isVisible()

    rig.controller.resume()
    rig.button = True
    open_wheel(rig)


def test_trigger_key_and_stop(rig: Rig) -> None:
    rig.controller.set_trigger_key("ctrl")
    rig.press()
    rig.move_by(10, 0)
    rig.shift(True)
    assert rig.state is State.DRAGGING  # Shift is no longer the trigger
    rig.keys.down.add(w.VK_CONTROL)
    rig.sample()
    assert rig.state is State.WHEEL_OPEN
    rig.controller.stop()
    assert rig.monitor.stopped == 1
    assert not rig.window.isVisible()
    assert rig.state is State.IDLE


def test_a_key_held_across_gestures_opens_the_next_wheel(rig: Rig) -> None:
    """The poller is still running during the release grace; the new press must reset it."""
    open_wheel(rig)
    rig.release()
    assert rig.state is State.RELEASING
    assert rig.poller.active
    rig.button = True
    rig.press()  # Shift is still held
    rig.move_by(10, 0)
    assert rig.state is State.DRAGGING
    rig.sample()  # the first sample of the new gesture is an edge
    assert rig.state is State.WHEEL_OPEN
    assert rig.window.isVisible()


def test_stop_then_start_registers_again(rig: Rig) -> None:
    rig.controller.stop()
    rig.controller.start()
    assert rig.monitor.started == 2
    open_wheel(rig)


def test_a_new_press_while_visible_resets(rig: Rig) -> None:
    open_wheel(rig)
    rig.release()
    rig.button = True
    rig.press()  # a new drag before the grace period ended
    assert rig.state is State.PRESSED
    assert not rig.window.isVisible()


def test_start_reports_missing_raw_input_and_connects_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    monitor = FakeMonitor()
    monitor.start = lambda: Registration(False, 1400, "no HWND")  # type: ignore[method-assign]
    seen: list[tuple[int, int]] = []
    controller = Controller(
        monitor,
        ModifierPoller(reader=Keys()),
        WheelWindow(Catalog.of(BUILTINS), cursor=lambda: QPoint(600, 400)),
        source_info=lambda x, y, *, any_source=False: TITLE_BAR,
        threshold=lambda hwnd, x, y: (4, 4),
    )
    controller.machine.feed = lambda event: seen.append(1) or []  # type: ignore[method-assign]
    with caplog.at_level(logging.WARNING, logger="morphwheel.app.controller"):
        controller.start()
        controller.start()  # registers again (the first attempt failed), but connects once
    assert len([r for r in caplog.records if "raw input is not available" in r.message]) == 2
    monitor.pointer_down.emit(1, 1)
    assert len(seen) == 1  # one connection, not two
