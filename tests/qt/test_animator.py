"""``ui.wheel.animator``: the motion table, zero durations, and the dismiss that always ends.

Traceability (phase-4 §6): "hide() at the end of every fade" (the ``finished`` half; the window's
``hide()`` is in ``test_wheel_window.py``); "animations off: duration 0" (C7); "immediate hide when
released without a drop" (the 83 ms fade starts at once).
"""

from __future__ import annotations

import time

import pytest
from pytestqt.qtbot import QtBot

from conftest import Clock
from morphwheel.core.catalog import SlotPos
from morphwheel.core.geometry import MoreArc
from morphwheel.core.gesture import HideReason
from morphwheel.ui.theme import FAST_MS, FASTER_MS
from morphwheel.ui.wheel.animator import APPEAR_SCALE, SHRINK_SCALE, Track, WheelAnimator

pytestmark = pytest.mark.usefixtures("qapp")

MS = 1_000_000
T0 = Clock.START
ARC = MoreArc(315.0, 2)


@pytest.fixture
def anim(clock: Clock) -> WheelAnimator:
    return WheelAnimator(lambda: True, clock, real_time=False)


def finished_tokens(anim: WheelAnimator) -> list[int]:
    seen: list[int] = []
    anim.finished.connect(seen.append)
    return seen


# --------------------------------------------------------------------------- tracks


def test_track_clamps_outside_its_span_and_eases_inside() -> None:
    track = Track(T0, 0.0, 1.0, 100 * MS)
    assert track.value(T0 - 1) == 0.0
    assert track.value(T0) == 0.0
    assert 0.8 < track.value(T0 + 50 * MS) < 1.0  # fast start
    assert track.value(T0 + 100 * MS) == 1.0
    assert track.value(T0 + 10_000 * MS) == 1.0
    assert not track.done(T0 + 99 * MS)
    assert track.done(T0 + 100 * MS)
    assert Track(T0, 0.3, 0.7, 0).value(T0 - 1) == 0.7  # a zero duration is its end value


# --------------------------------------------------------------------------- appear and labels


def test_appear_scales_from_94_percent_and_fades_in_over_167_ms(anim: WheelAnimator) -> None:
    anim.appear(T0)
    f0 = anim.frame(T0)
    assert (f0.opacity, f0.scale, f0.labels) == (0.0, APPEAR_SCALE, 0.0)
    mid = anim.frame(T0 + 80 * MS)
    assert 0.0 < mid.opacity < 1.0
    assert APPEAR_SCALE < mid.scale < 1.0
    end = anim.frame(T0 + FAST_MS * MS)
    assert (end.opacity, end.scale) == (1.0, 1.0)
    assert anim.active(T0 + 100 * MS)
    assert not anim.active(T0 + FAST_MS * MS)


def test_labels_crossfade_once_per_appearance(anim: WheelAnimator) -> None:
    anim.appear(T0)
    anim.plan_arrived(T0 + 20 * MS)
    assert anim.frame(T0 + 20 * MS).labels == 0.0
    assert 0.0 < anim.frame(T0 + 60 * MS).labels < 1.0
    assert anim.frame(T0 + (20 + FASTER_MS) * MS).labels == 1.0
    anim.plan_arrived(T0 + 200 * MS)  # the sniff's second plan: no second crossfade
    assert anim.frame(T0 + 201 * MS).labels == 1.0
    anim.appear(T0 + 1000 * MS)  # a new appearance starts from the skeleton again
    assert anim.frame(T0 + 1000 * MS).labels == 0.0


# --------------------------------------------------------------------------- hover, More, halo


def test_hover_bulges_in_83_ms_and_out_in_167_ms(anim: WheelAnimator) -> None:
    anim.appear(T0)
    anim.hover(SlotPos.N, None, T0)
    assert anim.frame(T0).bulge[SlotPos.N] == 0.0
    assert anim.frame(T0 + FASTER_MS * MS).bulge[SlotPos.N] == 1.0
    anim.hover(SlotPos.NE, None, T0 + 100 * MS)  # switch: N retracts, NE rises
    at_160 = anim.frame(T0 + 160 * MS)
    assert 0.0 < at_160.bulge[SlotPos.N] < 1.0
    assert at_160.bulge[SlotPos.NE] < 1.0
    assert anim.frame(T0 + (100 + FASTER_MS) * MS).bulge[SlotPos.NE] == 1.0
    assert anim.frame(T0 + (100 + FAST_MS) * MS).bulge[SlotPos.N] == 0.0
    anim.hover(None, None, T0 + 300 * MS)
    anim.hover(None, None, T0 + 600 * MS)  # finished retractions are dropped from the frame
    assert anim.frame(T0 + 600 * MS).bulge == {}
    anim.hover(SlotPos.N, None, T0 + 700 * MS)
    anim.hover(SlotPos.N, None, T0 + 710 * MS)  # the same slot again: the track is not restarted
    assert anim.frame(T0 + (700 + FASTER_MS) * MS).bulge[SlotPos.N] == 1.0


def test_more_arc_grows_shrinks_keeps_its_shape_and_retracts_its_items(
    anim: WheelAnimator,
) -> None:
    anim.appear(T0)
    assert anim.frame(T0).arc is None
    anim.more(ARC, T0)
    assert anim.frame(T0).more_arc == 0.0
    assert anim.frame(T0).arc == ARC
    assert anim.frame(T0 + FAST_MS * MS).more_arc == 1.0
    anim.hover(None, 1, T0 + 200 * MS)
    assert anim.frame(T0 + 300 * MS).item_bulge[1] == 1.0
    anim.more(None, T0 + 300 * MS)
    at_350 = anim.frame(T0 + 350 * MS)
    assert 0.0 < at_350.more_arc < 1.0
    assert at_350.arc == ARC  # the shrinking arc is still drawn where it was
    assert 0.0 < at_350.item_bulge[1] < 1.0
    end = anim.frame(T0 + (300 + FAST_MS) * MS)
    assert (end.more_arc, end.item_bulge[1]) == (0.0, 0.0)
    anim.appear(T0 + 1000 * MS)
    assert anim.frame(T0 + 1000 * MS).arc is None


def test_halo_edge_fades_in_83_ms(anim: WheelAnimator) -> None:
    anim.appear(T0)
    anim.halo_edge(True, T0)
    assert 0.0 < anim.frame(T0 + 40 * MS).halo_edge < 1.0
    assert anim.frame(T0 + FASTER_MS * MS).halo_edge == 1.0
    anim.halo_edge(False, T0 + 100 * MS)
    assert anim.frame(T0 + (100 + FASTER_MS) * MS).halo_edge == 0.0


# --------------------------------------------------------------------------- dismiss (C3)


def test_a_cancel_fades_in_83_ms_and_finishes_once(anim: WheelAnimator, clock: Clock) -> None:
    seen = finished_tokens(anim)
    anim.appear(T0 - 1000 * MS)
    token = anim.dismiss(HideReason.CANCELLED, T0)
    assert anim.dismissing
    assert anim.frame(T0).opacity == 1.0
    assert 0.0 < anim.frame(T0 + 40 * MS).opacity < 1.0
    assert anim.frame(T0 + FASTER_MS * MS).opacity == 0.0
    clock.now = T0 + 40 * MS
    anim.step()
    assert seen == []  # not yet
    clock.now = T0 + FASTER_MS * MS
    anim.step()
    assert seen == [token]
    assert not anim.dismissing
    clock.now += 100 * MS
    anim.step()
    assert seen == [token]  # once


def test_a_drop_flashes_the_slot_then_shrinks_and_fades(anim: WheelAnimator, clock: Clock) -> None:
    seen = finished_tokens(anim)
    anim.appear(T0 - 1000 * MS)
    token = anim.dismiss(HideReason.DROPPED, T0, SlotPos.S)
    flash0 = anim.frame(T0)
    assert (flash0.flash[SlotPos.S], flash0.opacity, flash0.scale) == (1.0, 1.0, 1.0)
    mid_flash = anim.frame(T0 + 40 * MS)
    assert 0.0 < mid_flash.flash[SlotPos.S] < 1.0
    assert (mid_flash.opacity, mid_flash.scale) == (1.0, 1.0)  # the fade waits for the flash
    after_flash = anim.frame(T0 + (FASTER_MS + 80) * MS)
    assert after_flash.flash[SlotPos.S] == 0.0
    assert 0.0 < after_flash.opacity < 1.0
    assert SHRINK_SCALE < after_flash.scale < 1.0
    end = anim.frame(T0 + (FASTER_MS + FAST_MS) * MS)
    assert (end.opacity, end.scale) == (0.0, SHRINK_SCALE)
    clock.now = T0 + (FASTER_MS + FAST_MS) * MS
    anim.step()
    assert seen == [token]


def test_a_drop_on_an_arc_item_has_no_slot_to_flash(anim: WheelAnimator) -> None:
    anim.appear(T0 - 1000 * MS)
    anim.dismiss(HideReason.DROPPED, T0, None)
    assert anim.frame(T0 + 10 * MS).flash == {}
    assert anim.frame(T0 + (FASTER_MS + FAST_MS) * MS).opacity == 0.0


def test_a_second_dismiss_while_fading_keeps_the_first(anim: WheelAnimator, clock: Clock) -> None:
    seen = finished_tokens(anim)
    anim.appear(T0 - 1000 * MS)
    token = anim.dismiss(HideReason.CANCELLED, T0)
    again = anim.dismiss(HideReason.DROPPED, T0 + 10 * MS, SlotPos.N)
    assert again == token
    assert anim.frame(T0 + 20 * MS).flash == {}  # no flash was started
    clock.now = T0 + FASTER_MS * MS
    anim.step()
    assert seen == [token]


def test_motion_off_completes_everything_at_once_and_finishes_synchronously(clock: Clock) -> None:
    anim = WheelAnimator(lambda: False, clock, real_time=False)
    seen = finished_tokens(anim)
    anim.appear(T0)
    anim.plan_arrived(T0)
    anim.hover(SlotPos.N, None, T0)
    anim.more(ARC, T0)
    anim.halo_edge(True, T0)
    f = anim.frame(T0)
    assert (f.opacity, f.scale, f.labels, f.more_arc, f.halo_edge) == (1.0, 1.0, 1.0, 1.0, 1.0)
    assert f.bulge[SlotPos.N] == 1.0
    assert not anim.active(T0)
    token = anim.dismiss(HideReason.DROPPED, T0, SlotPos.N)
    assert seen == [token]  # emitted inside dismiss()
    assert not anim.dismissing
    assert anim.frame(T0).opacity == 0.0


def test_the_motion_switch_is_read_at_each_appearance(clock: Clock) -> None:
    enabled = True
    anim = WheelAnimator(lambda: enabled, clock, real_time=False)
    anim.appear(T0)
    assert anim.motion.enabled
    assert anim.frame(T0).opacity == 0.0
    enabled = False
    anim.appear(T0 + 1000 * MS)
    assert not anim.motion.enabled
    assert anim.frame(T0 + 1000 * MS).opacity == 1.0


def test_appear_during_a_dismiss_cancels_it_and_continues_from_there(
    anim: WheelAnimator, clock: Clock
) -> None:
    seen = finished_tokens(anim)
    anim.appear(T0 - 1000 * MS)
    anim.dismiss(HideReason.LEFT_HALO, T0)
    mid = anim.frame(T0 + 40 * MS).opacity
    assert 0.0 < mid < 1.0
    anim.appear(T0 + 40 * MS)
    assert not anim.dismissing
    assert anim.frame(T0 + 40 * MS).opacity == pytest.approx(mid)  # no jump to 0
    assert anim.frame(T0 + 40 * MS).scale == 1.0  # a plain fade kept the scale
    assert anim.frame(T0 + (40 + FAST_MS) * MS).opacity == 1.0
    for t in (T0 + FASTER_MS * MS, T0 + 1000 * MS):
        clock.now = t
        anim.step()
    assert seen == []  # the cancelled dismiss never finishes


def test_appear_after_a_shrink_continues_from_the_current_scale(anim: WheelAnimator) -> None:
    anim.appear(T0 - 1000 * MS)
    anim.dismiss(HideReason.DROPPED, T0, SlotPos.N)
    t = T0 + (FASTER_MS + 60) * MS
    current = anim.frame(t)
    assert SHRINK_SCALE < current.scale < 1.0
    anim.appear(t)
    assert anim.frame(t).scale == pytest.approx(current.scale)
    assert anim.frame(t).flash == {}  # the flash is cleared for the new appearance


def test_dismiss_before_any_appearance_is_harmless(anim: WheelAnimator) -> None:
    seen = finished_tokens(anim)
    token = anim.dismiss(HideReason.RESET, T0)
    assert anim.frame(T0).opacity == 0.0
    assert seen == [token]  # nothing to fade: finished at once


# --------------------------------------------------------------------------- real time


def test_without_real_time_no_timer_ever_runs(anim: WheelAnimator) -> None:
    anim.appear(T0)
    anim.hover(SlotPos.N, None, T0)
    anim.dismiss(HideReason.CANCELLED, T0)
    assert not anim.timer_active


def test_the_frame_timer_drives_a_real_fade_to_its_end(qtbot: QtBot) -> None:
    anim = WheelAnimator(lambda: True, time.perf_counter_ns, real_time=True)
    seen = finished_tokens(anim)
    frames: list[int] = []
    anim.frame_ready.connect(lambda: frames.append(1))
    now = time.perf_counter_ns()
    anim.appear(now - 1000 * MS)
    token = anim.dismiss(HideReason.CANCELLED, now)
    assert anim.timer_active
    qtbot.waitUntil(lambda: seen == [token], timeout=2000)
    assert len(frames) >= 2
    assert not anim.timer_active
    assert not anim.dismissing


def test_the_backstop_hides_when_frames_stop_advancing(qtbot: QtBot, clock: Clock) -> None:
    """A clock that never moves: the fade can't end by itself, so the backstop ends it."""
    anim = WheelAnimator(lambda: True, clock, real_time=True)
    seen = finished_tokens(anim)
    anim.appear(T0 - 1000 * MS)
    token = anim.dismiss(HideReason.CANCELLED, T0)
    assert anim.frame(T0 + 1).opacity > 0.99  # with a stuck clock the frame never changes
    qtbot.waitUntil(lambda: seen == [token], timeout=2000)
    assert not anim.dismissing
    assert not anim.timer_active
    anim.dismiss(HideReason.CANCELLED, T0)
    anim.reset()  # cancelled: the backstop must not fire for it
    qtbot.wait(FASTER_MS + 150)
    assert seen == [token]
