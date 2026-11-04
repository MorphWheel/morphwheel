"""``ui.wheel.window`` offscreen: drag events through the real handlers, and the alpha floor.

Traceability (phase-4 §6): "force_copy, never Move" at the window level; "one window during a
drag, no tooltips" (C1); "alpha floor ≥ 1, no window opacity" for the S2 renderer (the S4 row
repeats it for the final renderer); "S/M/L only while hidden" (U4); "waiting: spinner, give up".
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent, QImage
from PySide6.QtWidgets import QApplication

from conftest import Clock
from morphwheel.core.catalog import MORE_SLOT, Catalog, SlotPos
from morphwheel.core.geometry import WheelGeometry, polar
from morphwheel.core.gesture import HideReason
from morphwheel.core.jobs import DropRequest
from morphwheel.core.wheel_session import GIVE_UP_AFTER_NS, HubKind
from morphwheel.ui.theme import Scheme
from morphwheel.ui.wheel.renderer import HubText
from morphwheel.ui.wheel.window import WheelWindow

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
from builtin_targets import BUILTINS, plugin

pytestmark = pytest.mark.usefixtures("qapp")

A = Qt.DropAction
EXPLORER = A.CopyAction | A.MoveAction | A.LinkAction
SHIFT = Qt.KeyboardModifier.ShiftModifier
T0 = Clock.START


@pytest.fixture
def window(clock: Clock, qtbot: Any) -> WheelWindow:
    catalog = Catalog.of([*BUILTINS, plugin("tiff")])
    cursor = QPoint(600, 400)  # well inside the offscreen screen: no clamping
    w = WheelWindow(
        catalog, clock=clock, cursor=lambda: cursor, scheme=Scheme.DARK, real_time=False
    )
    qtbot.addWidget(w)  # deterministic teardown: a GC'd window with live Qt timers can crash
    w.show_at((1200, 800), T0)
    return w


def finish_fade(window: WheelWindow, clock: Clock, ms: int = 300) -> None:
    """Step the clock past any fade and run one animation step: the window hides (C3)."""
    clock.now += ms * 1_000_000
    window.animate()


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


def test_size_changes_only_while_hidden(window: WheelWindow, clock: Clock) -> None:
    with pytest.raises(RuntimeError):
        window.apply_size("L")
    clock.now += 300_000_000
    window.animate()  # fully shown; a hide now fades (an unseen wheel hides at once)
    window.hide_wheel()
    with pytest.raises(RuntimeError):
        window.apply_size("L")  # still visible: the fade is running (U4 holds for the fade too)
    finish_fade(window, clock)
    window.apply_size("L")
    assert window.wheel_size == "L"
    assert window.width() == WheelGeometry.for_size("L").window_size  # the window never resizes


# ----------------------------------------------------------------- the safety matrix, window level
def test_drag_enter_is_always_copy_even_before_arming_and_without_a_plan(
    window: WheelWindow, clock: Clock
) -> None:
    e = enter(window, mime("photo.png"))
    assert e.isAccepted()
    assert e.dropAction() == A.CopyAction
    assert window.view is not None
    assert window.view.plan is not None
    assert window.view.plan.ok
    assert not window.view.armed  # the cursor hasn't moved: U7

    clock.now += 300_000_000
    window.animate()  # fully shown, so the hide below is a real fade
    window.hide_wheel()  # an event already in flight still arrives while the wheel fades
    frozen = window.view
    assert frozen is not None
    assert window.fading
    e = enter(window, mime("photo.png"))
    assert e.isAccepted()
    assert e.dropAction() == A.CopyAction
    assert window.session is None
    assert window.view is frozen  # the fade shows the wheel as it was; nothing re-planned


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
    assert request.paths == (Path("C:/mw-test/photo.png"), Path("C:/mw-test/b.jpg"))
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


PHASES = ("appear-0", "appear-mid", "steady", "fade-mid", "drop-flash", "drop-shrink")


def reach_phase(window: WheelWindow, clock: Clock, phase: str) -> None:
    """Drive the real animator to a frame of the appear or dismiss animation (C3 mid-fade)."""
    if phase == "appear-0":
        return  # opacity 0, scale 0.94: the first frame after show_at
    clock.now += 80 * 1_000_000 if phase == "appear-mid" else 400 * 1_000_000
    window.animate()
    if phase == "steady" or phase == "appear-mid":
        return
    window.hide_wheel(HideReason.DROPPED if phase.startswith("drop") else HideReason.CANCELLED)
    clock.now += {"fade-mid": 40, "drop-flash": 40, "drop-shrink": 160}[phase] * 1_000_000
    window.animate()
    assert window.isVisible(), phase
    assert window.fading, phase


@pytest.mark.parametrize("phase", PHASES)
@pytest.mark.parametrize("state", ["waiting", "planned", "hover", "not-supported", "halo"])
def test_every_catching_pixel_has_alpha_and_the_outside_has_none(
    window: WheelWindow, clock: Clock, state: str, phase: str
) -> None:
    m = mime("photo.png" if state != "not-supported" else "clip.mp4")
    if state != "waiting":
        enter(window, m)
    if state == "hover":
        move(window, m, at_slot(window, SlotPos.N))
    if state == "halo":
        g0 = WheelGeometry.for_size(window.wheel_size)
        move(window, m, center(window) + QPointF(g0.halo_r - 5, 0))
    reach_phase(window, clock, phase)
    assert window.windowOpacity() == 1.0  # C3: never through window opacity, mid-fade included
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


def test_window_opacity_is_never_used_anywhere_in_the_package() -> None:
    package = Path(__file__).resolve().parents[2] / "src" / "morphwheel"
    offenders = [
        p.relative_to(package)
        for p in package.rglob("*.py")
        if "setWindowOpacity" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []


# ----------------------------------------------------------------- the fade and hide() (C3, S4)
def test_a_fade_keeps_the_window_catching_and_ends_in_hide(
    window: WheelWindow, clock: Clock, signals: list[Any]
) -> None:
    m = mime("photo.png")
    enter(window, m)
    move(window, m, at_slot(window, SlotPos.N))
    clock.now += 200_000_000
    window.animate()
    window.hide_wheel(HideReason.CANCELLED)
    assert window.isVisible()
    assert window.fading
    assert window.session is None
    assert window.frame.opacity == 1.0  # the fade starts from the visible wheel
    clock.now += 40_000_000
    window.animate()
    assert 0.0 < window.frame.opacity < 1.0
    assert window.isVisible()
    # Events during the fade: DragEnter is Copy, everything else is rejected, no signal leaves.
    assert enter(window, m).dropAction() == A.CopyAction
    assert not move(window, m, at_slot(window, SlotPos.N)).isAccepted()
    assert not drop(window, m, at_slot(window, SlotPos.N)).isAccepted()
    assert signals == []
    window.hide_wheel(HideReason.CANCELLED)  # a second hide changes nothing
    clock.now += 50_000_000
    window.animate()
    assert not window.isVisible()
    assert window.view is None
    assert not window.fading
    window.hide_wheel()  # hidden: a no-op
    assert not window.isVisible()


def test_a_drop_flashes_the_dropped_slot_then_shrinks_and_hides(
    window: WheelWindow, clock: Clock, signals: list[Any]
) -> None:
    m = mime("photo.png")
    enter(window, m)
    move(window, m, at_slot(window, SlotPos.N))
    clock.now += 200_000_000
    window.animate()
    drop(window, m, at_slot(window, SlotPos.N))
    assert isinstance(signals[0], DropRequest)
    window.hide_wheel(HideReason.DROPPED)  # the controller, after the queued DropRequest
    assert window.frame.flash[SlotPos.N] == 1.0  # the dropped slot, from the drop decision
    clock.now += 160_000_000
    window.animate()
    assert window.frame.flash[SlotPos.N] == 0.0
    assert window.frame.scale < 1.0
    assert 0.0 < window.frame.opacity < 1.0
    assert window.isVisible()
    clock.now += 200_000_000
    window.animate()
    assert not window.isVisible()


def test_show_during_a_fade_cuts_it_short_and_the_old_fade_never_hides_the_new_wheel(
    window: WheelWindow, clock: Clock
) -> None:
    clock.now += 300_000_000
    window.animate()
    window.hide_wheel(HideReason.LEFT_HALO)
    clock.now += 40_000_000
    window.animate()
    mid = window.frame.opacity
    assert 0.0 < mid < 1.0
    window.show_at((0, 0), clock.now)  # Shift pressed again within the 83 ms fade
    assert not window.fading
    assert window.session is not None
    assert window.frame.opacity == pytest.approx(mid)  # no jump to 0
    clock.now += 100_000_000  # past the old fade's end
    window.animate()
    assert window.isVisible()  # the cancelled fade never fires
    assert window.frame.opacity > mid
    clock.now += 100_000_000  # the 167 ms appear is complete
    window.animate()
    assert window.frame.opacity == 1.0
    window.hide_wheel()  # and a hide after that works normally
    finish_fade(window, clock)
    assert not window.isVisible()


def test_motion_off_hides_synchronously(clock: Clock, qtbot: Any) -> None:
    catalog = Catalog.of([*BUILTINS, plugin("tiff")])
    w = WheelWindow(
        catalog,
        clock=clock,
        cursor=lambda: QPoint(600, 400),
        scheme=Scheme.DARK,
        motion_enabled=lambda: False,
        real_time=False,
    )
    qtbot.addWidget(w)
    w.show_at((0, 0), T0)
    assert w.frame.opacity == 1.0  # no appear animation (C7)
    enter(w, mime("photo.png"))
    assert w.frame.labels == 1.0
    w.hide_wheel(HideReason.DROPPED)
    assert not w.isVisible()
    assert w.view is None


def test_a_real_fade_hides_through_the_frame_timer(qtbot: Any) -> None:
    catalog = Catalog.of([*BUILTINS, plugin("tiff")])
    w = WheelWindow(catalog, cursor=lambda: QPoint(600, 400), scheme=Scheme.DARK)
    qtbot.addWidget(w)  # real timers: the window must be deleted while the app is alive
    w.show_at((0, 0), time.perf_counter_ns())
    qtbot.waitUntil(lambda: w.frame.opacity == 1.0, timeout=2000)
    w.hide_wheel(HideReason.CANCELLED)
    assert w.isVisible()
    qtbot.waitUntil(lambda: not w.isVisible(), timeout=2000)
    assert not w.fading


def test_the_second_plan_from_the_sniff_keeps_arming_and_hover(
    window: WheelWindow, clock: Clock
) -> None:
    m = mime("photo.png")
    enter(window, m)
    generation = window.generation
    move(window, m, at_slot(window, SlotPos.N))
    clock.now += 100_000_000
    window.animate()
    assert window.frame.bulge[SlotPos.N] == 1.0
    assert window.frame.labels == 1.0
    window.on_sniffed(generation, window.drop_files())  # the same files, now sniffed
    assert window.view is not None
    assert window.view.armed
    assert window.view.hub.kind is HubKind.TARGET
    assert window.frame.bulge[SlotPos.N] == 1.0  # no retract, no second label crossfade
    assert window.frame.labels == 1.0
    window.on_sniffed(generation - 1, window.drop_files())  # stale: ignored
    assert window.view.armed


def test_hover_bulge_follows_highlight_not_the_region(window: WheelWindow, clock: Clock) -> None:
    m = mime("photo.png")
    enter(window, m)
    move(window, m, at_slot(window, SlotPos.NE))  # PNG onto PNG: disabled, no highlight
    clock.now += 100_000_000
    window.animate()
    assert window.frame.bulge.get(SlotPos.NE, 0.0) == 0.0
    move(window, m, at_slot(window, SlotPos.N))
    clock.now += 100_000_000
    window.animate()
    assert window.frame.bulge[SlotPos.N] == 1.0
    content = window.content()
    assert content.hub.top == "→ JPG"
    assert content.labels[SlotPos.N] == "JPG"
    assert content.labels[MORE_SLOT] == "More"


def test_a_scheme_change_mid_drag_rebuilds_the_theme_and_still_paints(
    window: WheelWindow,
) -> None:
    m = mime("photo.png")
    enter(window, m)
    before = window.theme
    window._on_scheme_changed()  # what styleHints().colorSchemeChanged triggers
    assert window.theme == before  # the scheme is pinned in this test; the rebuild is harmless
    assert window.theme is not before  # but it was rebuilt
    image = render(window)
    c = center(window)
    assert alpha(image, c.x(), c.y()) >= 1


def test_the_floor_is_painted_even_when_the_content_painter_fails(
    window: WheelWindow, clock: Clock, caplog: pytest.LogCaptureFixture
) -> None:
    """C3: a painting bug must never leave the window drop-transparent."""
    m = mime("photo.png")
    enter(window, m)
    clock.now += 300_000_000
    window.animate()

    def broken(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("simulated painting bug")

    window._renderer.paint_content = broken  # type: ignore[method-assign]
    with caplog.at_level("ERROR", logger="morphwheel.ui.wheel"):
        image = render(window)
        again = render(window)
    g = WheelGeometry.for_size(window.wheel_size)
    c = center(window)
    for img in (image, again):
        assert alpha(img, c.x(), c.y()) >= 1
        assert alpha(img, c.x() + g.halo_r - 2, c.y()) >= 1
        assert alpha(img, c.x() + g.halo_r + 2, c.y()) == 0
    assert alpha(image, c.x(), c.y()) == 1  # the floor alone: no content was painted
    assert len([r for r in caplog.records if "failed to paint" in r.message]) == 1  # once


def test_hub_counts_read_as_proper_english(window: WheelWindow) -> None:
    m = mime("photo.png", "b.jpg", "c.webp")
    enter(window, m)
    move(window, m, at_slot(window, SlotPos.N))  # JPG: b.jpg is skipped
    hub = window.content().hub
    assert hub.top == "→ JPG"
    assert hub.bottom == "3 files, 1 skipped"
    window.hide_wheel()
    window.show_at((0, 0), T0 + 1)
    single = mime("photo.png")
    enter(window, single)
    move(window, single, center(window) + QPointF(38, 0))  # the inner gap: the files line
    assert window.content().hub == HubText("photo.png", "1 file")
