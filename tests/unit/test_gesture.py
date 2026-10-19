"""Transition-table tests for ``core.gesture`` (U1 sticky/dismiss/reopen, release ordering).

Traceability (phase-4 §6): "sticky wheel, halo cancel, leaving the halo closes, a new Shift
reopens"; "hide immediately on release without a drop" (read as: as soon as we know).
"""

from __future__ import annotations

import pytest

from morphwheel.core.gesture import (
    RELEASE_GRACE_NS,
    DropCancelled,
    DropDone,
    Event,
    GestureMachine,
    GiveUp,
    HideReason,
    HideWheel,
    ModifierState,
    PointerDown,
    PointerMove,
    PointerUp,
    ShowWheel,
    State,
    Tick,
    WheelLeft,
)

MS = 1_000_000


def down(allowed: bool = True) -> PointerDown:
    return PointerDown(0, 0, 0, allowed, (4, 4))


def move(x: int, y: int = 0) -> PointerMove:
    return PointerMove(1, x, y)


def mod(pressed: bool) -> ModifierState:
    return ModifierState(2, pressed)


OPEN = [down(), move(10), mod(True)]  # a typical opening: drag, then press Shift


def run(events: list[Event]) -> tuple[list[object], State]:
    machine = GestureMachine()
    commands: list[object] = []
    for event in events:
        commands.extend(machine.feed(event))
    return commands, machine.state


@pytest.mark.parametrize(
    ("events", "commands", "state"),
    [
        pytest.param([down(), move(10), PointerUp(5)], [], State.IDLE, id="no-modifier"),
        pytest.param(OPEN, [ShowWheel(10, 0)], State.WHEEL_OPEN, id="shift-after-threshold"),
        pytest.param(  # held before the click: the first poll sample after PointerDown sees it
            [down(), mod(True), move(10)], [ShowWheel(10, 0)], State.WHEEL_OPEN, id="shift-held"
        ),
        pytest.param(  # a sample taken before the click is discarded (stale-state guard)
            [mod(True), down(), move(10)], [], State.DRAGGING, id="pre-click-sample-ignored"
        ),
        pytest.param(
            [down(allowed=False), move(10), mod(True)], [], State.DRAGGING, id="source-not-allowed"
        ),
        pytest.param([down(), move(3, 3), mod(True)], [], State.PRESSED, id="below-threshold"),
        pytest.param(
            [down(), move(3, 3), mod(True), move(9)],
            [ShowWheel(9, 0)],
            State.WHEEL_OPEN,
            id="threshold-crossed-while-held",
        ),
        pytest.param([*OPEN, mod(False)], [ShowWheel(10, 0)], State.WHEEL_OPEN, id="sticky"),
        pytest.param(
            [*OPEN, WheelLeft(3)],
            [ShowWheel(10, 0), HideWheel(HideReason.LEFT_HALO)],
            State.DISMISSED,
            id="leave-halo-dismisses",
        ),
        pytest.param(
            [*OPEN, WheelLeft(3), mod(True)],
            [ShowWheel(10, 0), HideWheel(HideReason.LEFT_HALO)],
            State.DISMISSED,
            id="still-held-is-not-a-new-press",
        ),
        pytest.param(
            [*OPEN, WheelLeft(3), mod(False), move(50, 20), mod(True)],
            [ShowWheel(10, 0), HideWheel(HideReason.LEFT_HALO), ShowWheel(50, 20)],
            State.WHEEL_OPEN,
            id="new-press-reopens",
        ),
        pytest.param(
            [*OPEN, WheelLeft(3), PointerUp(4)],
            [ShowWheel(10, 0), HideWheel(HideReason.LEFT_HALO)],
            State.IDLE,
            id="dismissed-then-released",
        ),
        pytest.param(
            [*OPEN, PointerUp(4)], [ShowWheel(10, 0)], State.RELEASING, id="up-waits-for-drop"
        ),
        pytest.param(
            [*OPEN, PointerUp(4), DropDone(5)],
            [ShowWheel(10, 0), HideWheel(HideReason.DROPPED)],
            State.IDLE,
            id="up-before-drop",
        ),
        pytest.param(
            [*OPEN, DropDone(4), PointerUp(5), mod(False), mod(True)],
            [ShowWheel(10, 0), HideWheel(HideReason.DROPPED)],
            State.IDLE,
            id="drop-before-up-then-no-reopen",
        ),
        pytest.param(
            [*OPEN, PointerUp(4), DropCancelled(5)],
            [ShowWheel(10, 0), HideWheel(HideReason.CANCELLED)],
            State.IDLE,
            id="released-over-hub",
        ),
        pytest.param(
            [*OPEN, down()],
            [ShowWheel(10, 0), HideWheel(HideReason.RESET)],
            State.PRESSED,
            id="new-press-resets",
        ),
        pytest.param(
            [DropDone(1), DropCancelled(2), WheelLeft(3), Tick(4), PointerUp(5)],
            [],
            State.IDLE,
            id="late-events-in-idle-are-no-ops",
        ),
    ],
)
def test_transitions(events: list[Event], commands: list[object], state: State) -> None:
    assert run(events) == (commands, state)


def test_stale_modifier_does_not_open_the_next_gesture() -> None:
    """Shift released while IDLE (poller stopped) must not open a later plain drag."""
    events = [*OPEN, DropDone(4), PointerUp(5), down(), move(10)]
    assert run(events) == ([ShowWheel(10, 0), HideWheel(HideReason.DROPPED)], State.DRAGGING)


def test_modifier_held_across_gestures_opens_after_the_first_poll() -> None:
    events = [*OPEN, DropDone(4), PointerUp(5), down(), mod(True), move(10)]
    commands, state = run(events)
    assert commands[-1] == ShowWheel(10, 0)
    assert state is State.WHEEL_OPEN


def test_give_up_dismisses_and_a_new_press_reopens() -> None:
    events = [*OPEN, GiveUp(3), mod(False), mod(True)]
    commands, state = run(events)
    assert commands == [ShowWheel(10, 0), HideWheel(HideReason.GAVE_UP), ShowWheel(10, 0)]
    assert state is State.WHEEL_OPEN


def test_release_grace_timeout() -> None:
    machine = GestureMachine()
    for event in OPEN:
        machine.feed(event)
    released_at = 1_000 * MS
    assert machine.feed(PointerUp(released_at)) == []
    assert machine.feed(Tick(released_at + RELEASE_GRACE_NS - MS)) == []
    assert machine.wheel_visible
    assert machine.feed(Tick(released_at + RELEASE_GRACE_NS)) == [HideWheel(HideReason.CANCELLED)]
    assert machine.state is State.IDLE
    assert not machine.wheel_visible


def test_polling_only_during_a_gesture() -> None:
    machine = GestureMachine()
    assert not machine.wants_polling
    machine.feed(down())
    assert machine.wants_polling
    machine.feed(PointerUp(1))
    assert not machine.wants_polling
