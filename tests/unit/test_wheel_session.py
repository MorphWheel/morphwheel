"""Tests for ``core.wheel_session``: arming (U7), the More arc (U3), waiting, hub data (C5), drops.

Traceability (phase-4 §6): "arming after 12 px"; "waiting state: spinner at 150 ms, give up at
1.5 s"; "the hub repeats the target under the cursor"; "8 fixed slots, More, plugins only in the
More arc".
"""

from __future__ import annotations

import pytest
from builtin_targets import BUILTINS, file, plugin

from morphwheel.core.catalog import Catalog, Reason, SlotPos
from morphwheel.core.formats import FormatId
from morphwheel.core.geometry import MoreArc, Point, Region, RegionKind, WheelGeometry, polar
from morphwheel.core.wheel_session import (
    ARMING_DISTANCE,
    GIVE_UP_AFTER_NS,
    MORE_DWELL_NS,
    SPINNER_AFTER_NS,
    Accept,
    Cancel,
    CancelReason,
    HubKind,
    WheelSession,
)

G = WheelGeometry()
MS = 1_000_000
PLUGINS = [plugin("p0", {FormatId.PNG}), plugin("p1", {FormatId.PNG})]
WITH_PLUGINS = Catalog.of([*BUILTINS, *PLUGINS])
BUILTIN_ONLY = Catalog.of(BUILTINS)


def armed_session(
    catalog: Catalog = WITH_PLUGINS, files: tuple[str, ...] = ("a.png",)
) -> WheelSession:
    session = WheelSession(G, appear_at=Point(0, 0), t0_ns=0)
    session.set_plan(catalog.plan([file(n) for n in files]))
    session.on_pointer(Point(0, -ARMING_DISTANCE - 1), 10 * MS)  # leave the center: armed
    return session


# --------------------------------------------------------------------------- waiting


def test_waiting_spinner_and_give_up() -> None:
    session = WheelSession(G, appear_at=Point(0, 0), t0_ns=0)
    assert session.tick(SPINNER_AFTER_NS - 1).hub.kind is HubKind.WAITING
    assert session.tick(SPINNER_AFTER_NS).hub.kind is HubKind.SPINNER
    assert session.tick(GIVE_UP_AFTER_NS).hub.kind is HubKind.GAVE_UP
    assert session.decide_drop(polar(0, 80), GIVE_UP_AFTER_NS) == Cancel(CancelReason.NOT_READY)
    view = session.set_plan(WITH_PLUGINS.plan([file("a.png")]))
    # The pointer was left armed on JPG by decide_drop: the plan's arrival lights it up at once.
    assert (view.hub.kind, view.hub.target) == (HubKind.TARGET, BUILTINS[0])


# --------------------------------------------------------------------------- arming (U7)


def test_edge_clamped_start_on_a_slot_needs_movement() -> None:
    start = polar(0, 80)  # the wheel was shifted at a screen edge: the cursor starts on JPG
    session = WheelSession(G, appear_at=start, t0_ns=0)
    session.set_plan(WITH_PLUGINS.plan([file("a.png")]))

    view = session.on_pointer(start, MS)
    assert not view.armed
    assert not view.accepts_drop
    assert view.hub.kind is HubKind.FILES  # no target preview before arming
    assert session.decide_drop(start, MS) == Cancel(CancelReason.NOT_ARMED)

    moved = polar(10, 80)  # ~14 px along the same slot
    assert session.decide_drop(moved, 2 * MS) == Accept(BUILTINS[0], 0)


def test_arming_is_sticky() -> None:
    session = armed_session()
    view = session.on_pointer(Point(0, 0), 20 * MS)  # back to where it appeared
    assert view.armed


# --------------------------------------------------------------------------- never accept


@pytest.mark.parametrize(
    ("point", "files", "catalog", "reason"),
    [
        (Point(0, 0), ("a.png",), WITH_PLUGINS, CancelReason.HUB),
        (polar(22.5, 80), ("a.png",), WITH_PLUGINS, CancelReason.GAP),
        (polar(0, 38), ("a.png",), WITH_PLUGINS, CancelReason.GAP),
        (polar(0, 150), ("a.png",), WITH_PLUGINS, CancelReason.HALO),
        (polar(0, 300), ("a.png",), WITH_PLUGINS, CancelReason.OUTSIDE),
        (polar(315, 80), ("a.png",), WITH_PLUGINS, CancelReason.MORE_SLOT),
        (polar(45, 80), ("a.png",), WITH_PLUGINS, CancelReason.DISABLED),  # PNG is the source
        (polar(180, 80), ("a.heic",), WITH_PLUGINS, CancelReason.DISABLED),  # Compress on HEIC
        (polar(0, 80), ("a.txt",), WITH_PLUGINS, CancelReason.NOT_SUPPORTED),
        (polar(0, 80), ("a.gif",), Catalog.of(BUILTINS[1:]), CancelReason.DISABLED),  # empty slot
    ],
)
def test_decide_drop_never_accepts_unsafe_positions(
    point: Point, files: tuple[str, ...], catalog: Catalog, reason: CancelReason
) -> None:
    session = armed_session(catalog, files)
    assert session.decide_drop(point, 50 * MS) == Cancel(reason)
    assert not session.on_pointer(point, 51 * MS).accepts_drop


def test_accept_reports_skips_in_a_mixed_drag() -> None:
    session = armed_session(files=("a.png", "b.jpg"))
    view = session.on_pointer(polar(0, 80), 20 * MS)
    assert view.highlight_slot
    assert (view.hub.kind, view.hub.skip_count, view.hub.file_count) == (HubKind.TARGET, 1, 2)
    assert view.hub.target is BUILTINS[0]  # C5: the hub repeats the target
    assert session.decide_drop(polar(0, 80), 21 * MS) == Accept(BUILTINS[0], 1)


# --------------------------------------------------------------------------- hub data


def test_hub_shows_cancel_disabled_and_not_supported() -> None:
    session = armed_session()
    assert session.on_pointer(Point(0, 0), 20 * MS).hub.kind is HubKind.CANCEL
    halo = session.on_pointer(polar(90, 160), 21 * MS)
    assert (halo.hub.kind, halo.halo_edge_visible) == (HubKind.CANCEL, True)
    source = session.on_pointer(polar(45, 80), 22 * MS).hub
    assert (source.kind, source.reason) == (HubKind.DISABLED, Reason.IS_SOURCE)

    blocked = armed_session(files=("a.gif",))
    blocked.set_plan(WITH_PLUGINS.plan([file("a.gif", animated=True)]))
    hub = blocked.on_pointer(polar(0, 80), 30 * MS).hub
    assert (hub.kind, hub.reason) == (HubKind.NOT_SUPPORTED, Reason.ANIMATED)


# --------------------------------------------------------------------------- More arc (U3)


def test_more_opens_after_dwell_and_accepts_a_plugin_target() -> None:
    session = armed_session()
    nw = polar(315, 80)
    view = session.on_pointer(nw, 1_000 * MS)
    assert (view.hub.kind, view.more_arc) == (HubKind.MORE, None)
    assert session.tick(1_000 * MS + MORE_DWELL_NS - 1).more_arc is None
    arc = session.tick(1_000 * MS + MORE_DWELL_NS).more_arc
    assert arc is not None
    assert arc.count == len(PLUGINS)

    item0 = polar(arc.item_angle(0), 150)
    view = session.on_pointer(item0, 1_400 * MS)
    assert view.accepts_drop
    assert view.hub.target is PLUGINS[0]
    assert session.decide_drop(item0, 1_401 * MS) == Accept(PLUGINS[0], 0)

    assert session.on_pointer(polar(0, 80), 1_500 * MS).more_arc is None  # back to a slot: close


def test_more_opens_when_pushed_outward() -> None:
    session = armed_session()
    session.on_pointer(polar(315, 80), 20 * MS)
    assert session.on_pointer(polar(315, 130), 21 * MS).more_arc is not None


def test_drop_decides_on_the_more_state_the_user_saw() -> None:
    """RF-2: a drop that would push through the More slot must not open the arc and pick an item."""
    session = armed_session()
    session.on_pointer(polar(315, 80), 20 * MS)  # on More, the arc still closed
    arc = MoreArc(315.0, len(PLUGINS))
    item0 = polar(arc.item_angle(0), 150)
    assert G.is_outward_of_more_slot(item0)  # a pointer event here would open the arc,
    assert G.region(item0, arc) == Region(RegionKind.MORE_ITEM, item=0)  # landing on PLUGINS[0]
    assert session.decide_drop(item0, 21 * MS) == Cancel(CancelReason.HALO)


def test_more_without_plugins_never_opens() -> None:
    session = armed_session(BUILTIN_ONLY)
    view = session.on_pointer(polar(315, 80), 20 * MS)
    assert (view.hub.kind, view.hub.reason) == (HubKind.DISABLED, Reason.NO_PLUGINS)
    assert session.tick(20 * MS + 10 * MORE_DWELL_NS).more_arc is None
    assert session.on_pointer(polar(315, 130), 30 * MS).more_arc is None


def test_second_plan_keeps_arming_and_more_state() -> None:
    session = armed_session()
    session.on_pointer(polar(315, 80), 20 * MS)
    session.on_pointer(polar(315, 130), 21 * MS)  # open the arc
    view = session.set_plan(WITH_PLUGINS.plan([file("a.png", animated=False)]))  # sniff result
    assert view.armed
    assert view.more_arc is not None
    assert view.plan is not None
    assert view.plan.slots[SlotPos.N].enabled
