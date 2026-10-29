"""``ui.wheel.window`` offscreen: drag events through the real handlers, and the alpha floor.

Traceability (phase-4 §6): "force_copy, never Move" at the window level; "one window during a
drag, no tooltips" (C1); "alpha floor ≥ 1, no window opacity" for the S2 renderer (the S4 row
repeats it for the final renderer); "S/M/L only while hidden" (U4); "waiting: spinner, give up".
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent, QImage
from PySide6.QtWidgets import QApplication

from morphwheel.core.catalog import MORE_SLOT, Catalog, SlotPos
from morphwheel.core.geometry import WheelGeometry, polar
from morphwheel.core.jobs import DropRequest
from morphwheel.core.wheel_session import GIVE_UP_AFTER_NS, HubKind
from morphwheel.ui.wheel.window import WheelWindow

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
from builtin_targets import BUILTINS, plugin

pytestmark = pytest.mark.usefixtures("qapp")

A = Qt.DropAction
EXPLORER = A.CopyAction | A.MoveAction | A.LinkAction
SHIFT = Qt.KeyboardModifier.ShiftModifier
T0 = 1_000_000_000


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> int:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def window(clock: Clock) -> WheelWindow:
    catalog = Catalog.of([*BUILTINS, plugin("tiff")])
    cursor = QPoint(600, 400)  # well inside the offscreen screen: no clamping
    w = WheelWindow(catalog, clock=clock, cursor=lambda: cursor)
    w.show_at((1200, 800), T0)
    return w


def mime(*names: str) -> QMimeData:
    m = QMimeData()
    m.setUrls([QUrl.fromLocalFile(f"C:/mw-test/{n}") for n in names])
    return m


def at_slot(window: WheelWindow, slot: SlotPos) -> QPointF:
    g = WheelGeometry.for_size(window.wheel_size)
    p = polar(WheelGeometry.slot_angle(slot), (g.slot_inner_r + g.slot_outer_r) / 2)
    return QPointF(window.width() / 2 + p.x, window.height() / 2 + p.y)


def center(window: WheelWindow) -> QPointF:
    return QPointF(window.width() / 2, window.height() / 2)


def enter(window: WheelWindow, m: QMimeData, offer: Qt.DropAction = EXPLORER) -> QDragEnterEvent:
    e = QDragEnterEvent(center(window), offer, m, Qt.MouseButton.LeftButton, SHIFT)
    QApplication.sendEvent(window, e)
    return e


def move(window: WheelWindow, m: QMimeData, pos: QPointF) -> QDragMoveEvent:
    e = QDragMoveEvent(pos, EXPLORER, m, Qt.MouseButton.LeftButton, SHIFT)
    QApplication.sendEvent(window, e)
    return e


def drop(
    window: WheelWindow, m: QMimeData, pos: QPointF, offer: Qt.DropAction = EXPLORER
) -> QDropEvent:
    e = QDropEvent(pos, offer, m, Qt.MouseButton.LeftButton, SHIFT)
    QApplication.sendEvent(window, e)
    return e


@pytest.fixture
def signals(window: WheelWindow) -> list[Any]:
    seen: list[Any] = []
    window.drop_requested.connect(lambda r: seen.append(r))
    window.cancelled.connect(lambda: seen.append("cancelled"))
    window.drag_left.connect(lambda: seen.append("left"))
    window.gave_up.connect(lambda: seen.append("gave_up"))
    return seen


# ----------------------------------------------------------------- window properties (C1, C4)
def test_window_is_the_single_pre_created_drop_target(window: WheelWindow) -> None:
    flags = window.windowFlags()
    for flag in (
        Qt.WindowType.Tool,
        Qt.WindowType.FramelessWindowHint,
        Qt.WindowType.WindowStaysOnTopHint,
        Qt.WindowType.WindowDoesNotAcceptFocus,
    ):
        assert flags & flag
    assert window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert window.testAttribute(Qt.WidgetAttribute.WA_NativeWindow)
    assert window.acceptDrops()
    assert window.width() == window.height() == WheelGeometry.for_size("L").window_size
    assert window.windowOpacity() == 1.0  # C3: never fade through window opacity


def test_no_tooltips_anywhere_in_the_package() -> None:
    package = Path(__file__).resolve().parents[2] / "src" / "morphwheel"
    offenders = [
        p.relative_to(package)
        for p in package.rglob("*.py")
        if "QToolTip" in p.read_text(encoding="utf-8") or "setToolTip" in p.read_text("utf-8")
    ]
    assert offenders == []


def test_size_changes_only_while_hidden(window: WheelWindow) -> None:
    with pytest.raises(RuntimeError):
        window.apply_size("L")
    window.hide_wheel()
    window.apply_size("L")
    assert window.wheel_size == "L"
    assert window.width() == WheelGeometry.for_size("L").window_size  # the window never resizes


# ----------------------------------------------------------------- the safety matrix, window level
def test_drag_enter_is_always_copy_even_before_arming_and_without_a_plan(
    window: WheelWindow,
) -> None:
    e = enter(window, mime("photo.png"))
    assert e.isAccepted()
    assert e.dropAction() == A.CopyAction
    assert window.view is not None
    assert window.view.plan is not None
    assert window.view.plan.ok
    assert not window.view.armed  # the cursor hasn't moved: U7

    window.hide_wheel()  # an event already in flight still arrives after hide
    e = enter(window, mime("photo.png"))
    assert e.isAccepted()
    assert e.dropAction() == A.CopyAction
    assert window.view is None


def test_drag_move_accepts_only_selectable_slots(window: WheelWindow) -> None:
    m = mime("photo.png")
    enter(window, m)
    e = move(window, m, center(window))  # the hub: cancel
    assert not e.isAccepted()
    assert e.dropAction() == A.IgnoreAction

    e = move(window, m, at_slot(window, SlotPos.N))  # JPG, 79 px away: armed, selectable
    assert e.isAccepted()
    assert e.dropAction() == A.CopyAction
    assert window.view is not None
    assert window.view.highlight_slot
    assert window.view.hub.kind is HubKind.TARGET

    e = move(window, m, at_slot(window, SlotPos.NE))  # PNG onto a PNG: the source, disabled
    assert not e.isAccepted()
    assert window.view.hub.kind is HubKind.DISABLED

    e = move(window, m, at_slot(window, MORE_SLOT))  # More itself is never a drop
    assert not e.isAccepted()


def test_drop_on_a_slot_is_copy_and_emits_a_request(
    window: WheelWindow, signals: list[Any], clock: Clock
) -> None:
    m = mime("photo.png", "b.jpg")
    enter(window, m)
    move(window, m, at_slot(window, SlotPos.N))
    clock.now = T0 + 300_000_000
    e = drop(window, m, at_slot(window, SlotPos.N))
    assert e.isAccepted()
    assert e.dropAction() == A.CopyAction  # Shift held, Move offered, still Copy
    assert len(signals) == 1
    request = signals[0]
    assert isinstance(request, DropRequest)
    assert request.target_id == "jpeg"
    assert request.files == (Path("C:/mw-test/photo.png"), Path("C:/mw-test/b.jpg"))
    assert request.received_at_ns == clock.now


@pytest.mark.parametrize(
    "where",
    ["hub", "source-slot", "more", "halo", "outside"],
)
def test_drop_elsewhere_is_rejected_and_cancelled(
    window: WheelWindow, signals: list[Any], where: str
) -> None:
    m = mime("photo.png")
    enter(window, m)
    move(window, m, at_slot(window, SlotPos.N))  # arm, with an accepted DragMove last
    g = WheelGeometry.for_size(window.wheel_size)
    c = center(window)
    pos = {
        "hub": c,
        "source-slot": at_slot(window, SlotPos.NE),
        "more": at_slot(window, MORE_SLOT),
        "halo": QPointF(c.x() + g.halo_r - 3, c.y()),
        "outside": QPointF(c.x() + g.halo_r + 3, c.y()),
    }[where]
    e = drop(window, m, pos)
    assert not e.isAccepted()
    assert e.dropAction() == A.IgnoreAction
    assert signals == ["cancelled"]


def test_drop_before_arming_or_without_a_plan_is_cancelled(
    window: WheelWindow, signals: list[Any]
) -> None:
    m = mime("photo.png")
    # Qt routes a Drop only after an accepted DragEnter, and so does OLE, so a Drop with no plan
    # can't come through the loop. The handler's own guard is called directly.
    e = QDropEvent(at_slot(window, SlotPos.N), EXPLORER, m, Qt.MouseButton.LeftButton, SHIFT)
    window.dropEvent(e)
    assert not e.isAccepted()
    assert signals == ["cancelled"]

    enter(window, m)
    e = drop(window, m, center(window) + QPointF(5, 0))  # 5 px: not armed (U7)
    assert not e.isAccepted()
    assert signals == ["cancelled", "cancelled"]


def test_a_move_only_source_can_never_be_accepted(window: WheelWindow, signals: list[Any]) -> None:
    m = mime("photo.png")
    e = enter(window, m, offer=A.MoveAction)
    assert not e.isAccepted()  # refused at the door: Qt then routes no DragMove or Drop here
    assert not move(window, m, at_slot(window, SlotPos.N)).isAccepted()
    assert not drop(window, m, at_slot(window, SlotPos.N), offer=A.MoveAction).isAccepted()
    assert signals == []

    # And if a Drop did reach the handler, it is refused there too.
    e = QDropEvent(at_slot(window, SlotPos.N), A.MoveAction, m, Qt.MouseButton.LeftButton, SHIFT)
    window.dropEvent(e)
    assert not e.isAccepted()
    assert e.dropAction() == A.IgnoreAction
    assert signals == ["cancelled"]


def test_events_without_a_session_are_rejected_silently(
    window: WheelWindow, signals: list[Any]
) -> None:
    m = mime("photo.png")
    enter(window, m)
    window.hide_wheel()
    assert not move(window, m, at_slot(window, SlotPos.N)).isAccepted()
    assert not drop(window, m, at_slot(window, SlotPos.N)).isAccepted()
    assert signals == []


def test_drag_leave_is_reported_for_the_controller_to_classify(
    window: WheelWindow, signals: list[Any]
) -> None:
    QApplication.sendEvent(window, QDragLeaveEvent())
    assert signals == ["left"]


def test_unsupported_drag_plans_but_never_accepts(window: WheelWindow, signals: list[Any]) -> None:
    m = mime("clip.mp4")
    e = enter(window, m)
    assert e.isAccepted()  # DragEnter: always
    assert window.view is not None
    assert window.view.plan is not None
    assert not window.view.plan.ok
    assert not move(window, m, at_slot(window, SlotPos.N)).isAccepted()
    assert window.view.hub.kind is HubKind.NOT_SUPPORTED
    assert not drop(window, m, at_slot(window, SlotPos.N)).isAccepted()
    assert signals == ["cancelled"]


# ----------------------------------------------------------------- waiting, give-up, sessions
def test_give_up_is_emitted_once_per_session(
    window: WheelWindow, signals: list[Any], clock: Clock
) -> None:
    window.tick(T0 + 200_000_000)
    assert window.view is not None
    assert window.view.hub.kind is HubKind.SPINNER
    window.tick(T0 + GIVE_UP_AFTER_NS)
    window.tick(T0 + GIVE_UP_AFTER_NS + 1)
    assert signals == ["gave_up"]

    window.hide_wheel()
    window.tick(T0 + 10 * GIVE_UP_AFTER_NS)  # no session: nothing happens
    window.show_at((0, 0), T0 + 10 * GIVE_UP_AFTER_NS)  # a fresh session: can give up again
    window.tick(T0 + 11 * GIVE_UP_AFTER_NS + GIVE_UP_AFTER_NS)
    assert signals == ["gave_up", "gave_up"]


def test_each_show_starts_a_fresh_session(window: WheelWindow) -> None:
    m = mime("photo.png")
    enter(window, m)
    move(window, m, at_slot(window, SlotPos.N))
    assert window.view is not None
    assert window.view.armed
    window.hide_wheel()
    assert window.session is None
    window.show_at((0, 0), T0 + 5)
    assert window.session is not None
    assert window.view is not None
    assert window.view.plan is None
    assert not window.view.armed


# ----------------------------------------------------------------- the alpha floor (C2, C3)
def render(window: WheelWindow) -> QImage:
    image = QImage(window.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    window.render(image)
    return image


def alpha(image: QImage, x: float, y: float) -> int:
    return image.pixelColor(round(x), round(y)).alpha()


@pytest.mark.parametrize("state", ["waiting", "planned", "hover", "not-supported", "halo"])
def test_every_catching_pixel_has_alpha_and_the_outside_has_none(
    window: WheelWindow, state: str
) -> None:
    m = mime("photo.png" if state != "not-supported" else "clip.mp4")
    if state != "waiting":
        enter(window, m)
    if state == "hover":
        move(window, m, at_slot(window, SlotPos.N))
    if state == "halo":
        g0 = WheelGeometry.for_size(window.wheel_size)
        move(window, m, center(window) + QPointF(g0.halo_r - 5, 0))
    image = render(window)
    g = WheelGeometry.for_size(window.wheel_size)
    c = center(window)
    catching = {
        "hub": (c.x(), c.y()),
        "inner gap": (c.x() + (g.hub_r + g.slot_inner_r) / 2, c.y()),
        "slot N": (c.x(), c.y() - (g.slot_inner_r + g.slot_outer_r) / 2),
        "slot gap": (
            c.x() + polar(22.5, 80).x,
            c.y() + polar(22.5, 80).y,
        ),
        "ring gap": (c.x() + (g.slot_outer_r + g.more_inner_r) / 2, c.y()),
        "more ring": (c.x() + (g.more_inner_r + g.more_outer_r) / 2, c.y()),
        "halo": (c.x() + g.halo_r - 2, c.y()),
        "halo edge": (c.x(), c.y() - g.halo_r + 1),
    }
    for name, (x, y) in catching.items():
        assert alpha(image, x, y) >= 1, f"{state}: {name} is drop-transparent"
    for name, (x, y) in {
        "outside": (c.x() + g.halo_r + 2, c.y()),
        "corner": (1, 1),
        "far corner": (window.width() - 2, window.height() - 2),
    }.items():
        assert alpha(image, x, y) == 0, f"{state}: {name} would catch drops"
