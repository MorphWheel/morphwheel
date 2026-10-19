"""The gesture state machine: when the wheel opens, stays open, and closes (U1, SP-1).

It is fed with input events from the OS-hooks layer (raw input and modifier polling) and with drop
outcomes from the wheel window. It returns ``ShowWheel`` / ``HideWheel`` commands. Time comes in
on the events (``t_ns``), so tests are deterministic.

Rules:

- **Open.** The drag crosses the system threshold from an allowed source while the trigger key is
  down, or the trigger key is pressed later during the drag. Holding the key before the click
  still opens the wheel at the threshold; Explorer will have range-selected files, which is
  Explorer's own behavior.
- **Sticky (U1).** Releasing the trigger key does not close the wheel.
- **Dismiss (U1).** Leaving the catch halo with the button still down (``WheelLeft``) closes the
  wheel for the rest of the drag, which goes back to being a normal Explorer drag. A *new* press of
  the trigger key reopens it.
  A wheel that never got a plan (``GiveUp``, phase-3 §4) is dismissed the same way.
- **No stale key state.** Each ``PointerDown`` starts with the key "up", because the poller doesn't
  run while idle. If the key really is held, the first poll sample is an edge.
- **Release.** The raw mouse-up arrives 1-4 ms *before* OLE delivers the drop (spike log). So a
  release first enters ``RELEASING``, which ends on ``DropDone``, on ``DropCancelled`` (OLE sends
  DragLeave, not Drop, after a release over the hub, a gap or the halo), or after
  ``RELEASE_GRACE_NS``. This is how phase-2's "hide immediately when nothing was dropped" is
  implemented: hide as soon as we *know*.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

RELEASE_GRACE_NS = 150_000_000  # 150 ms


@dataclass(frozen=True)
class PointerDown:
    t_ns: int
    x: int
    y: int
    source_allowed: bool  # Explorer / Desktop (window probe), or "any source" mode
    threshold: tuple[int, int]  # SM_CXDRAG / SM_CYDRAG for the monitor's DPI


@dataclass(frozen=True)
class PointerMove:
    t_ns: int
    x: int
    y: int


@dataclass(frozen=True)
class PointerUp:
    t_ns: int


@dataclass(frozen=True)
class ModifierState:
    t_ns: int
    pressed: bool  # the configured trigger key (D8)


@dataclass(frozen=True)
class WheelLeft:
    """DragLeave from the wheel while the button is still down: the pointer left the halo."""

    t_ns: int


@dataclass(frozen=True)
class DropDone:
    t_ns: int


@dataclass(frozen=True)
class DropCancelled:
    """DragLeave with the button up: released over hub / gap / halo, so OLE sent no Drop."""

    t_ns: int


@dataclass(frozen=True)
class GiveUp:
    """The wheel never received a plan (no DragEnter within the give-up time, phase-3 §4)."""

    t_ns: int


@dataclass(frozen=True)
class Tick:
    t_ns: int


Event = (
    PointerDown
    | PointerMove
    | PointerUp
    | ModifierState
    | WheelLeft
    | DropDone
    | DropCancelled
    | GiveUp
    | Tick
)


class HideReason(StrEnum):
    DROPPED = "dropped"
    CANCELLED = "cancelled"  # released without a drop
    LEFT_HALO = "left_halo"
    GAVE_UP = "gave_up"  # behaves like a dismiss: a new press of the trigger key reopens
    RESET = "reset"  # a new press arrived before the previous gesture finished


@dataclass(frozen=True)
class ShowWheel:
    x: int
    y: int


@dataclass(frozen=True)
class HideWheel:
    reason: HideReason


Command = ShowWheel | HideWheel


class State(StrEnum):
    IDLE = "idle"
    PRESSED = "pressed"
    DRAGGING = "dragging"
    WHEEL_OPEN = "wheel_open"
    RELEASING = "releasing"
    DISMISSED = "dismissed"


class GestureMachine:
    def __init__(self) -> None:
        self.state = State.IDLE
        self._modifier = False
        self._allowed = False
        self._origin = (0, 0)
        self._pos = (0, 0)
        self._threshold = (4, 4)
        self._released_at = 0

    @property
    def wants_polling(self) -> bool:
        """The modifier poller only needs to run while a gesture is in progress (phase-4 §4.3)."""
        return self.state is not State.IDLE

    @property
    def wheel_visible(self) -> bool:
        return self.state in (State.WHEEL_OPEN, State.RELEASING)

    def feed(self, event: Event) -> list[Command]:
        if isinstance(event, ModifierState):
            edge = event.pressed and not self._modifier
            self._modifier = event.pressed
            if edge and self.state in (State.DRAGGING, State.DISMISSED) and self._allowed:
                return self._open()
            return []
        if isinstance(event, PointerDown):
            commands: list[Command] = []
            if self.wheel_visible:
                commands.append(HideWheel(HideReason.RESET))
            self.state = State.PRESSED
            # The poller stops while IDLE, so a key released between gestures was never seen.
            # Start from "up"; if the key is really held, the first poll sample is an edge.
            self._modifier = False
            self._allowed = event.source_allowed
            self._origin = self._pos = (event.x, event.y)
            self._threshold = event.threshold
            return commands
        if isinstance(event, PointerMove):
            self._pos = (event.x, event.y)
            if self.state is State.PRESSED and self._beyond_threshold():
                self.state = State.DRAGGING
                if self._modifier and self._allowed:
                    return self._open()
            return []
        if isinstance(event, PointerUp):
            if self.state is State.WHEEL_OPEN:
                self.state = State.RELEASING
                self._released_at = event.t_ns
            elif self.state is not State.RELEASING:
                self.state = State.IDLE
            return []
        if isinstance(event, WheelLeft | GiveUp):
            if self.state is State.WHEEL_OPEN:
                self.state = State.DISMISSED
                reason = (
                    HideReason.LEFT_HALO if isinstance(event, WheelLeft) else HideReason.GAVE_UP
                )
                return [HideWheel(reason)]
            return []
        if isinstance(event, DropDone):
            return self._finish(HideReason.DROPPED)
        if isinstance(event, DropCancelled):
            return self._finish(HideReason.CANCELLED)
        # Tick
        if self.state is State.RELEASING and event.t_ns - self._released_at >= RELEASE_GRACE_NS:
            return self._finish(HideReason.CANCELLED)
        return []

    def _open(self) -> list[Command]:
        self.state = State.WHEEL_OPEN
        return [ShowWheel(*self._pos)]

    def _finish(self, reason: HideReason) -> list[Command]:
        if self.state in (State.WHEEL_OPEN, State.RELEASING):
            # From WHEEL_OPEN: the drop beat our raw mouse-up; that up will find us IDLE.
            self.state = State.IDLE
            return [HideWheel(reason)]
        return []  # late or foreign drop events are no-ops

    def _beyond_threshold(self) -> bool:
        dx = abs(self._pos[0] - self._origin[0])
        dy = abs(self._pos[1] - self._origin[1])
        return dx > self._threshold[0] or dy > self._threshold[1]
