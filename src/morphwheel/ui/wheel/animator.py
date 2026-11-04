"""``WheelAnimator``: turns the wheel's events into a ``Frame`` over time (phase-3 §8, C3, C7).

The animator owns no pixels. It keeps one ``Track`` per animated value (a start time, two values
and a duration, eased with the WinUI curve) and answers ``frame(t_ns)``. Time always comes in: the
window's clock is injected, so tests step it and ask for frames deterministically. A 16 ms
``QTimer`` asks the window to repaint while any track is live, and stops when none is. The window
paints the floor on every frame regardless of what the animator says (C2), so the animator can
only ever change how the wheel *looks*, never what it catches.

Motion table (phase-3 §8):

- appear: scale 0.94 → 1 and opacity → 1 in 167 ms, from the current values when a fade is cut
  short;
- the plan arrives: labels replace the skeleton in 83 ms, once per appearance;
- hover: 83 ms in, 167 ms out, one track per slot or arc item;
- the More arc: grows 167 ms, shrinks 167 ms (items retract with it); the arc as last open is
  kept here, so the shrink can still draw it;
- the halo edge: 83 ms;
- dismiss after a drop: the dropped slot flashes 83 ms, then the wheel shrinks to 0.9 and fades
  in 167 ms;
- any other dismiss: fade in 83 ms.

Windows' animation switch (C7) is a callable read at every ``appear``: when it is off every
duration is 0, so each call completes at once and a dismiss finishes synchronously, inside
``dismiss()``. Callers set their own state **before** calling it.

Dismiss safety (C3): ``finished(token)`` is emitted exactly once per dismiss, from ``step()`` when
the fade's end time has passed, or from a real-time backstop timer shortly after the fade should
have ended, in case frames stop coming (a stalled loop, a clock that doesn't advance). ``appear()``
and ``reset()`` cancel the current dismiss without emitting: a stale fade can never hide a newer
appearance.
"""

from __future__ import annotations

import itertools
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from morphwheel.core.catalog import SlotPos
from morphwheel.core.geometry import MoreArc
from morphwheel.core.gesture import HideReason
from morphwheel.ui.theme import Motion, ease
from morphwheel.ui.wheel.renderer import Frame

log = logging.getLogger("morphwheel.ui.wheel")

FRAME_INTERVAL_MS = 16
BACKSTOP_SLACK_MS = 50
APPEAR_SCALE = 0.94
SHRINK_SCALE = 0.9

K = TypeVar("K")


@dataclass(frozen=True)
class Track:
    """One eased value over time. Outside its span it holds an end value (progress is clamped)."""

    start_ns: int
    from_v: float
    to_v: float
    duration_ns: int

    @staticmethod
    def still(value: float) -> Track:
        return Track(0, value, value, 0)

    @property
    def end_ns(self) -> int:
        return self.start_ns + self.duration_ns

    def value(self, t_ns: int) -> float:
        if self.duration_ns <= 0 or t_ns >= self.end_ns:
            return self.to_v
        if t_ns <= self.start_ns:
            return self.from_v
        progress = (t_ns - self.start_ns) / self.duration_ns
        return self.from_v + (self.to_v - self.from_v) * ease(progress)

    def done(self, t_ns: int) -> bool:
        return t_ns >= self.end_ns


class WheelAnimator(QObject):
    frame_ready = Signal()  # repaint now
    finished = Signal(int)  # the dismiss with this token is complete: hide the window

    def __init__(
        self,
        motion_enabled: Callable[[], bool],
        clock: Callable[[], int],
        *,
        real_time: bool = True,
        parent: QObject | None = None,
    ) -> None:
        """``real_time=False`` disables the frame timer and the backstop: tests call ``step()``."""
        super().__init__(parent)
        self._motion_enabled = motion_enabled
        self.motion = Motion(motion_enabled())
        self._clock = clock
        self._real_time = real_time
        self._opacity = Track.still(0.0)
        self._scale = Track.still(APPEAR_SCALE)
        self._labels = Track.still(0.0)
        self._bulge: dict[SlotPos, Track] = {}
        self._item_bulge: dict[int, Track] = {}
        self._arc_shown: MoreArc | None = None
        self._arc = Track.still(0.0)
        self._halo_edge = Track.still(0.0)
        self._flash: dict[SlotPos, Track] = {}
        self._dismiss_token = 0
        self._dismiss_end_ns: int | None = None  # set while a dismiss is running
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(FRAME_INTERVAL_MS)
        self._timer.timeout.connect(self.step)
        self._backstop = QTimer(self)
        self._backstop.setSingleShot(True)
        self._backstop.timeout.connect(self._on_backstop)

    # ----------------------------------------------------------------- state
    @property
    def dismissing(self) -> bool:
        return self._dismiss_end_ns is not None

    @property
    def dismiss_token(self) -> int:
        return self._dismiss_token

    @property
    def timer_active(self) -> bool:
        return self._timer.isActive()

    def active(self, t_ns: int) -> bool:
        """True while any track is still moving at ``t_ns``."""
        tracks = itertools.chain(
            (self._opacity, self._scale, self._labels, self._arc, self._halo_edge),
            self._bulge.values(),
            self._item_bulge.values(),
            self._flash.values(),
        )
        return any(not track.done(t_ns) for track in tracks)

    def frame(self, t_ns: int) -> Frame:
        return Frame(
            opacity=self._opacity.value(t_ns),
            scale=self._scale.value(t_ns),
            labels=self._labels.value(t_ns),
            bulge={slot: tr.value(t_ns) for slot, tr in self._bulge.items()},
            item_bulge={index: tr.value(t_ns) for index, tr in self._item_bulge.items()},
            arc=self._arc_shown,
            more_arc=self._arc.value(t_ns),
            halo_edge=self._halo_edge.value(t_ns),
            flash={slot: tr.value(t_ns) for slot, tr in self._flash.items()},
        )

    # ----------------------------------------------------------------- inputs
    def appear(self, t_ns: int) -> None:
        """A new appearance, from the current opacity and scale: a cut-short fade doesn't jump."""
        current = self.frame(t_ns)
        self._cancel_dismiss()
        self.motion = Motion(self._motion_enabled())  # Windows' switch, re-read at each show (C7)
        opacity = current.opacity
        scale = current.scale if opacity > 0.0 else APPEAR_SCALE
        fast = self.motion.fast_ns
        self._opacity = Track(t_ns, opacity, 1.0, fast)
        self._scale = Track(t_ns, scale, 1.0, fast)
        self._labels = Track.still(0.0)
        self._bulge.clear()
        self._item_bulge.clear()
        self._arc_shown = None
        self._arc = Track.still(0.0)
        self._halo_edge = Track.still(0.0)
        self._flash.clear()
        self._wake()

    def plan_arrived(self, t_ns: int) -> None:
        """The first plan: labels replace the skeleton. A later plan (the sniff) changes nothing."""
        if self._labels.to_v >= 1.0:
            return
        self._labels = Track(t_ns, self._labels.value(t_ns), 1.0, self.motion.faster_ns)
        self._wake()

    def hover(self, slot: SlotPos | None, item: int | None, t_ns: int) -> None:
        """The highlighted slot or arc item (or neither): it bulges in, everything else retracts."""
        changed = False
        for key, track in list(self._bulge.items()):
            if key is not slot:
                changed |= self._retract(self._bulge, key, track, t_ns)
        for index, track in list(self._item_bulge.items()):
            if index != item:
                changed |= self._retract(self._item_bulge, index, track, t_ns)
        if slot is not None:
            changed |= self._raise(self._bulge, slot, t_ns)
        if item is not None:
            changed |= self._raise(self._item_bulge, item, t_ns)
        if changed:
            self._wake()

    def more(self, arc: MoreArc | None, t_ns: int) -> None:
        """The More arc as the session shows it: ``None`` closes it (the last arc is kept to draw
        the shrink)."""
        changed = False
        if arc is not None and arc != self._arc_shown:
            self._arc_shown = arc
            changed = True
        target = 1.0 if arc is not None else 0.0
        if self._arc.to_v != target:
            self._arc = Track(t_ns, self._arc.value(t_ns), target, self.motion.fast_ns)
            changed = True
        if arc is None:
            for index, track in list(self._item_bulge.items()):
                changed |= self._retract(self._item_bulge, index, track, t_ns)
        if changed:
            self._wake()

    def halo_edge(self, visible: bool, t_ns: int) -> None:
        target = 1.0 if visible else 0.0
        if self._halo_edge.to_v != target:
            self._halo_edge = Track(
                t_ns, self._halo_edge.value(t_ns), target, self.motion.faster_ns
            )
            self._wake()

    def dismiss(self, reason: HideReason | None, t_ns: int, slot: SlotPos | None = None) -> int:
        """Start the fade-out and return its token. A second call while fading keeps the first.

        After a drop (``slot`` is the dropped slot) the slot flashes first. ``finished(token)``
        follows: synchronously when nothing is visible or every duration is 0, else from ``step()``
        or the backstop.
        """
        if self.dismissing:
            return self._dismiss_token
        self._dismiss_token += 1
        token = self._dismiss_token
        faster, fast = self.motion.faster_ns, self.motion.fast_ns
        current = self.frame(t_ns)
        if current.opacity <= 0.0:  # nothing visible to fade
            self._opacity = Track.still(0.0)
            self._finish(token)
            return token
        if reason is HideReason.DROPPED:
            if slot is not None:
                self._flash[slot] = Track(t_ns, 1.0, 0.0, faster)
            self._opacity = Track(t_ns + faster, current.opacity, 0.0, fast)
            self._scale = Track(t_ns + faster, current.scale, SHRINK_SCALE, fast)
        else:
            self._opacity = Track(t_ns, current.opacity, 0.0, faster)
        self._dismiss_end_ns = self._opacity.end_ns
        if self._dismiss_end_ns <= t_ns:
            self._finish(token)
            return token
        self._wake()
        if self._real_time:
            total_ms = (self._dismiss_end_ns - t_ns) // 1_000_000
            self._backstop.start(int(total_ms) + BACKSTOP_SLACK_MS)
        return token

    def reset(self) -> None:
        """Stop everything, emit nothing. The next ``appear`` starts from the current values."""
        self._cancel_dismiss()
        self._timer.stop()

    # ----------------------------------------------------------------- the frame clock
    def step(self) -> None:
        """One frame: repaint; finish the dismiss once its time has passed; stop when idle."""
        t_ns = self._clock()
        self.frame_ready.emit()
        end = self._dismiss_end_ns
        if end is not None and t_ns >= end:
            self._finish(self._dismiss_token)
        elif not self.active(t_ns):
            self._timer.stop()

    # ----------------------------------------------------------------- internals
    def _wake(self) -> None:
        if self._real_time and not self._timer.isActive():
            self._timer.start()

    def _cancel_dismiss(self) -> None:
        self._dismiss_end_ns = None
        self._backstop.stop()

    def _finish(self, token: int) -> None:
        self.reset()
        self.finished.emit(token)

    def _on_backstop(self) -> None:
        if self.dismissing:
            log.warning("wheel fade-out did not finish on its own; hiding by the backstop timer")
            self._finish(self._dismiss_token)

    def _raise(self, tracks: dict[K, Track], key: K, t_ns: int) -> bool:
        """Start the key's track toward 1; False when it is already heading there."""
        current = tracks.get(key)
        if current is not None and current.to_v >= 1.0:
            return False
        start = current.value(t_ns) if current is not None else 0.0
        tracks[key] = Track(t_ns, start, 1.0, self.motion.faster_ns)
        return True

    def _retract(self, tracks: dict[K, Track], key: K, track: Track, t_ns: int) -> bool:
        """Start the key's track toward 0 (a finished retraction is dropped). False if unchanged."""
        if track.to_v <= 0.0:
            if track.done(t_ns):
                del tracks[key]
            return False
        tracks[key] = Track(t_ns, track.value(t_ns), 0.0, self.motion.fast_ns)
        return True
