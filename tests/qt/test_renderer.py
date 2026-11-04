"""``ui.wheel.renderer`` offscreen: the alpha floor under every state and frame, and the look.

Traceability (phase-4 §6): "alpha floor ≥ 1, no window opacity: offscreen render to QImage,
including mid-fade frames; alpha ≥ 1 on the disc and the halo, 0 outside" (the renderer half; the
window half is in ``test_wheel_window.py``); "the hub repeats the target under the cursor" (C5,
hover render); High Contrast (C7); M2 check 6 (paint cost).
"""

from __future__ import annotations

import logging
import statistics
import sys
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage, QPainter, QPalette

from morphwheel.core.catalog import SlotPos
from morphwheel.core.geometry import MoreArc, WheelGeometry, polar
from morphwheel.core.wheel_session import MORE_DWELL_NS, SessionView
from morphwheel.ui.theme import Scheme, Theme
from morphwheel.ui.wheel.renderer import (
    BULGE_PX,
    Content,
    Frame,
    HubText,
    WheelRenderer,
    blank_layer,
    item_labels,
    slot_labels,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
from builtin_targets import TWO_PNG_PLUGINS, planned_session

pytestmark = pytest.mark.usefixtures("qapp")

log = logging.getLogger("test.renderer")

G = WheelGeometry.for_size("M")
SIZE = QSize(WheelGeometry.for_size("L").window_size, WheelGeometry.for_size("L").window_size)
DARK = Theme.build(Scheme.DARK, accent=QColor("#0078D4"))
LIGHT = Theme.build(Scheme.LIGHT, accent=QColor("#0078D4"))
MS = 1_000_000
BESIDE = 14.0  # degrees off a slot's center: inside the wedge, clear of its label


def view_for(state: str) -> tuple[SessionView, MoreArc | None]:
    if state == "waiting":
        return planned_session(TWO_PNG_PLUGINS, (), G).tick(10 * MS), None
    files = ("clip.mp4",) if state == "not-supported" else ("a.png",)
    s = planned_session(TWO_PNG_PLUGINS, files, G)
    if state == "armed":
        return s.on_pointer(polar(0, 20), 10 * MS), None
    if state in ("hover", "not-supported"):
        return s.on_pointer(polar(0, 80), 10 * MS), None
    if state == "disabled-hover":
        return s.on_pointer(polar(45, 80), 10 * MS), None  # PNG is the source
    if state == "halo":
        return s.on_pointer(polar(0, G.halo_r - 5), 10 * MS), None
    if state == "more-open":
        s.on_pointer(polar(315, 80), 10 * MS)
        v = s.tick(10 * MS + MORE_DWELL_NS)
        assert v.more_arc is not None
        return v, v.more_arc
    raise AssertionError(state)


def content_for(state: str) -> tuple[Content, MoreArc | None]:
    view, arc = view_for(state)
    hub = HubText("→ JPG", "1 file") if state == "hover" else HubText("photo.png", "1 file")
    return Content(view, hub, slot_labels(view.plan, "More"), item_labels(view.plan)), arc


def render(
    theme: Theme,
    content: Content,
    frame: Frame,
    *,
    dpr: float = 1.0,
    geometry: WheelGeometry = G,
    renderer: WheelRenderer | None = None,
) -> QImage:
    image = blank_layer(SIZE, dpr)
    r = renderer or WheelRenderer()
    p = QPainter(image)
    r.paint_floor(p, SIZE, geometry)
    r.paint_content(p, SIZE, dpr, theme, geometry, content, frame)
    p.end()
    return image


def at(image: QImage, angle: float, radius: float) -> QColor:
    dpr = image.devicePixelRatio()
    c = SIZE.width() / 2
    pt = polar(angle, radius)
    return image.pixelColor(int((c + pt.x) * dpr), int((c + pt.y) * dpr))


def near(a: QColor, b: QColor, tolerance: int = 48) -> bool:
    return (
        abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue()) <= tolerance
    )


ARC = MoreArc(315.0, 2)
FRAMES = {
    "appear-0": Frame(opacity=0.0, scale=0.94),
    "appear-mid": Frame(opacity=0.5, scale=0.97, labels=0.0),
    "steady": Frame(),
    "fill-mid": Frame(labels=0.5),
    "hover-mid": Frame(bulge={SlotPos.N: 0.5}, halo_edge=0.5),
    "more-mid": Frame(arc=ARC, more_arc=0.5, item_bulge={0: 1.0}),
    "flash": Frame(flash={SlotPos.N: 1.0}),
    "shrink-mid": Frame(opacity=0.4, scale=0.92),
    "fade-end": Frame(opacity=0.02, scale=0.9),
}
STATES = ("waiting", "armed", "hover", "disabled-hover", "not-supported", "halo", "more-open")


# --------------------------------------------------------------------------- the floor (C2, C3)


@pytest.mark.parametrize("dpr", [1.0, 1.5])
@pytest.mark.parametrize("frame_name", sorted(FRAMES))
@pytest.mark.parametrize("state", STATES)
def test_alpha_floor_holds_in_every_state_and_frame(
    state: str, frame_name: str, dpr: float
) -> None:
    content, _ = content_for(state)
    for theme in (DARK, LIGHT):
        image = render(theme, content, FRAMES[frame_name], dpr=dpr)
        catching = {
            "hub": (0.0, 0.0),
            "inner gap": (0.0, (G.hub_r + G.slot_inner_r) / 2),
            "slot N": (0.0, (G.slot_inner_r + G.slot_outer_r) / 2),
            "slot gap": (22.5, 80.0),
            "ring gap": (0.0, (G.slot_outer_r + G.more_inner_r) / 2),
            "more ring": (315.0, (G.more_inner_r + G.more_outer_r) / 2),
            "halo": (0.0, G.halo_r - 2),
            "halo edge": (270.0, G.halo_r - 1),
            "shadow side": (180.0, G.slot_outer_r + 10),
        }
        for name, (angle, radius) in catching.items():
            where = f"{state}/{frame_name}: {name}"
            assert at(image, angle, radius).alpha() >= 1, f"{where} is drop-transparent"
        for angle in (0.0, 90.0, 180.0, 270.0, 315.0, 135.0):
            assert at(image, angle, G.halo_r + 2).alpha() == 0, f"{state}/{frame_name}: {angle}°"
        assert image.pixelColor(1, 1).alpha() == 0
        assert image.pixelColor(image.width() - 2, image.height() - 2).alpha() == 0


def test_the_floor_alone_is_exactly_alpha_one_and_nothing_else() -> None:
    image = blank_layer(SIZE, 1.0)
    p = QPainter(image)
    WheelRenderer().paint_floor(p, SIZE, G)
    p.end()
    assert at(image, 0, 0).alpha() == 1
    assert at(image, 45, G.halo_r - 0.5).alpha() == 1
    assert at(image, 45, G.halo_r + 1.5).alpha() == 0


# --------------------------------------------------------------------------- the look (§3, §7)


def test_hover_shows_the_accent_and_a_four_pixel_bulge() -> None:
    content, _ = content_for("hover")
    mid = (G.slot_inner_r + G.slot_outer_r) / 2
    rest = render(DARK, content, Frame())
    lit = render(DARK, content, Frame(bulge={SlotPos.N: 1.0}))
    assert near(at(rest, BESIDE, mid), DARK.palette.surface)
    assert near(at(lit, BESIDE, mid), DARK.palette.accent)
    # Proud of the ring: accent at slot_outer_r + 2, where the resting wheel shows only its shadow.
    assert near(at(lit, 0, G.slot_outer_r + BULGE_PX / 2), DARK.palette.accent)
    assert not near(at(rest, 0, G.slot_outer_r + BULGE_PX / 2), DARK.palette.accent)
    # The neighbour is untouched.
    assert near(at(lit, 45 + BESIDE, mid), DARK.palette.surface)


def test_the_hub_is_tinted_only_in_the_cancel_state() -> None:
    waiting, _ = content_for("waiting")  # the pointer sits at the center, but there is no plan
    halo, _ = content_for("halo")
    hover, _ = content_for("hover")
    assert near(at(render(DARK, waiting, Frame()), 0, 0), DARK.palette.surface, 24)
    assert near(at(render(DARK, hover, Frame()), 0, G.hub_r - 6), DARK.palette.surface, 24)
    tinted = at(render(DARK, halo, Frame()), 0, G.hub_r - 6)  # "✕ Cancel": a touch of accent
    assert not near(tinted, DARK.palette.surface, 24)


def test_the_flash_lights_the_dropped_slot_only() -> None:
    content, _ = content_for("hover")
    mid = (G.slot_inner_r + G.slot_outer_r) / 2
    image = render(DARK, content, Frame(flash={SlotPos.S: 1.0}))
    assert near(at(image, 180 + BESIDE, mid), DARK.palette.accent)
    assert near(at(image, BESIDE, mid), DARK.palette.surface)


def test_the_more_arc_grows_from_the_inner_edge() -> None:
    content, arc = content_for("more-open")
    assert arc is not None
    angle = arc.item_angle(0)
    span = G.more_outer_r - G.more_inner_r
    half = render(DARK, content, Frame(arc=arc, more_arc=0.5))
    full = render(DARK, content, Frame(arc=arc, more_arc=1.0))
    closed = render(DARK, content, Frame(arc=arc, more_arc=0.0))
    assert at(half, angle, G.more_inner_r + span * 0.25).alpha() > 100
    assert at(half, angle, G.more_outer_r - 3).alpha() == 1  # floor only, not drawn yet
    assert at(full, angle, G.more_outer_r - 3).alpha() > 100
    assert at(closed, angle, G.more_inner_r + span * 0.5).alpha() == 1


def test_labels_crossfade_from_the_skeleton() -> None:
    content, _ = content_for("armed")
    mid = (G.slot_inner_r + G.slot_outer_r) / 2

    def bright_pixels(image: QImage) -> int:
        dpr = image.devicePixelRatio()
        c = SIZE.width() / 2
        count = 0
        for dx in range(-24, 25):
            for dy in range(-10, 11):
                px = image.pixelColor(int((c + dx) * dpr), int((c - mid + dy) * dpr))
                if px.red() > 200 and px.alpha() > 200:
                    count += 1
        return count

    skeleton = render(DARK, content, Frame(labels=0.0))
    labels = render(DARK, content, Frame(labels=1.0))
    assert bright_pixels(skeleton) == 0  # the placeholder bar is faint; no label yet
    assert bright_pixels(labels) > 10  # "JPG" in white


def test_slot_and_item_labels_come_from_the_plan() -> None:
    view, _ = view_for("more-open")
    labels = slot_labels(view.plan, "More")
    assert labels[SlotPos.N] == "JPG"
    assert labels[SlotPos.NW] == "More"
    assert len(labels) == 8
    assert item_labels(view.plan) == ("P0", "P1")  # the test builder upper-cases labels
    assert slot_labels(None, "More") == {}
    assert item_labels(None) == ()


def test_disabled_and_unsupported_slots_use_the_disabled_text_color() -> None:
    disabled, _ = content_for("disabled-hover")
    unsupported, _ = content_for("not-supported")
    mid = (G.slot_inner_r + G.slot_outer_r) / 2
    for content, angle in ((disabled, 45.0), (unsupported, 0.0)):
        image = render(DARK, content, Frame())
        assert near(at(image, angle + BESIDE, mid), DARK.palette.surface, 96)  # no accent
        assert not near(at(image, angle + BESIDE, mid), DARK.palette.accent)


def test_high_contrast_is_opaque_bordered_and_has_no_shadow() -> None:
    system = QPalette()
    active = QPalette.ColorGroup.Active
    system.setColor(active, QPalette.ColorRole.Window, QColor("#000000"))
    system.setColor(active, QPalette.ColorRole.WindowText, QColor("#FFFFFF"))
    system.setColor(active, QPalette.ColorRole.Highlight, QColor("#1AEBFF"))
    system.setColor(active, QPalette.ColorRole.HighlightedText, QColor("#000000"))
    hc = Theme.build(Scheme.HIGH_CONTRAST, system=system)
    content, _ = content_for("hover")
    image = render(hc, content, Frame(bulge={SlotPos.N: 1.0}))
    dark = render(DARK, content, Frame(bulge={SlotPos.N: 1.0}))
    assert at(image, 90, (G.hub_r + G.slot_inner_r) / 2).alpha() == 255  # opaque fill
    assert at(dark, 90, (G.hub_r + G.slot_inner_r) / 2).alpha() < 255  # 92 % in Dark
    assert at(image, 180, G.slot_outer_r + 10).alpha() == 1  # floor only: no shadow
    assert at(dark, 180, G.slot_outer_r + 10).alpha() > 1  # the shadow is there in Dark
    assert near(at(image, BESIDE, (G.slot_inner_r + G.slot_outer_r) / 2), QColor("#1AEBFF"))


# --------------------------------------------------------------------------- the layer (M2 #6)


def test_the_layer_is_rebuilt_only_when_the_content_changes_and_reuses_its_buffer() -> None:
    renderer = WheelRenderer()
    content, _ = content_for("hover")
    render(DARK, content, Frame(), renderer=renderer)
    first = renderer._layer
    render(DARK, content, Frame(), renderer=renderer)
    assert renderer.layer_builds == 1
    render(DARK, content, Frame(opacity=0.5, scale=0.95), renderer=renderer)  # group values only
    assert renderer.layer_builds == 1
    render(DARK, content, Frame(bulge={SlotPos.N: 0.5}), renderer=renderer)
    assert renderer.layer_builds == 2
    assert renderer._layer is first  # the same buffer, repainted
    render(LIGHT, content, Frame(bulge={SlotPos.N: 0.5}), renderer=renderer)
    assert renderer.layer_builds == 3
    bigger = WheelGeometry.for_size("L")
    render(LIGHT, content, Frame(bulge={SlotPos.N: 0.5}), renderer=renderer, geometry=bigger)
    assert renderer.layer_builds == 4
    render(LIGHT, content, Frame(bulge={SlotPos.N: 0.5}), renderer=renderer, dpr=1.5)
    assert renderer.layer_builds == 5
    assert renderer._layer is not first  # a new ratio needs a new buffer


def test_paint_cost_at_150_percent(caplog: pytest.LogCaptureFixture) -> None:
    """A loose guard against a per-frame blur or a lost cache. The live number is the DEBUG line
    the window logs when it hides (frames, mean, max); this is the raster side only (M2 check 6)."""
    renderer = WheelRenderer()
    content, _ = content_for("hover")
    image = blank_layer(SIZE, 1.5)
    worst: list[float] = []
    group: list[float] = []
    for i in range(61):
        frame = Frame(opacity=0.5 + i / 122, scale=0.94 + 0.06 * i / 60, bulge={SlotPos.N: i / 60})
        t0 = time.perf_counter()
        p = QPainter(image)
        renderer.paint_floor(p, SIZE, G)
        renderer.paint_content(p, SIZE, 1.5, DARK, G, content, frame)
        p.end()
        worst.append((time.perf_counter() - t0) * 1000)
    steady = Frame(bulge={SlotPos.N: 1.0})
    for i in range(61):
        t0 = time.perf_counter()
        p = QPainter(image)
        renderer.paint_floor(p, SIZE, G)
        frame = Frame(opacity=i / 60, bulge=steady.bulge)
        renderer.paint_content(p, SIZE, 1.5, DARK, G, content, frame)
        p.end()
        group.append((time.perf_counter() - t0) * 1000)
    worst, group = worst[1:], group[1:]  # the first frame warms fonts and the shadow
    q = statistics.quantiles
    msg = (
        f"paint at 570 px: layer rebuilt every frame p50 {statistics.median(worst):.1f} ms, "
        f"p95 {q(worst, n=20)[18]:.1f} ms; group fade only p50 {statistics.median(group):.1f} ms, "
        f"p95 {q(group, n=20)[18]:.1f} ms"
    )
    log.warning(msg)
    assert q(worst, n=20)[18] < 33.0, msg
    assert q(group, n=20)[18] < 33.0, msg
