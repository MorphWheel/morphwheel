"""The controller: raw input and the poller feed the gesture machine, which drives the wheel.

This is the composition root for a gesture (phase-4 §1, R4): the only place where ``platform``,
``core`` and ``ui`` meet. S2 wires monitor → ``GestureMachine`` → ``WheelWindow`` and logs the
``DropRequest``; S3 hands the request to the dispatcher, and S5 adds the tray, settings and toasts.

Rules:

- **Every event goes through the machine.** The controller never shows or hides the wheel on its
  own; it applies the machine's ``ShowWheel`` / ``HideWheel`` commands (U1, phase-2 §3.2).
- **The poller runs only while a gesture is in progress** (``wants_polling``), and the monitor
  reports motion only then (``track_moves``).
- **Ticks.** Every poller sample becomes a ``Tick`` for the machine (the release grace) and for
  the wheel session (dwell, spinner, give-up). Without ticks a still pointer would never advance
  them: Qt sends no DragMove while the pointer and keys are unchanged.
- **The window's signals are queued.** Hiding, logging and the job start happen after OLE's
  ``Drop`` call has returned, so the drop handler stays under its 5 ms budget.
- **DragLeave is classified here.** With the primary button still down it is ``WheelLeft``
  (the pointer left the halo: dismiss, U1); with the button up it is ``DropCancelled`` (OLE sends
  DragLeave, not Drop, for a release over the hub or the halo).
- **Pause (phase-2 §3.1)** hides the wheel, resets the machine and stops the poller. While
  paused, presses are ignored.
- **A press on our own window** is ignored; it can't start a gesture.
- **A source below our integrity level is not a drag source** (RD-8, S3): the window class is
  checked by the probe, and the process behind it by ``system.source_integrity_ok``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from typing import Protocol

from PySide6.QtCore import QObject, Qt, Signal

from morphwheel.core.gesture import (
    Command,
    DropCancelled,
    DropDone,
    GestureMachine,
    GiveUp,
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
from morphwheel.core.jobs import DropRequest
from morphwheel.platform import _win32, system, window_probe
from morphwheel.platform.modifier_poller import ModifierPoller, TriggerKey
from morphwheel.platform.raw_input import RawInputMonitor
from morphwheel.ui.wheel.window import WheelWindow

log = logging.getLogger("morphwheel.app.controller")

QUEUED = Qt.ConnectionType.QueuedConnection


class SourceProbe(Protocol):
    def __call__(self, x: int, y: int, *, any_source: bool = False) -> window_probe.SourceInfo: ...


class Controller(QObject):
    drop_received = Signal(object)  # DropRequest; S3 connects the dispatcher

    def __init__(
        self,
        monitor: RawInputMonitor,
        poller: ModifierPoller,
        window: WheelWindow,
        *,
        any_source: bool = False,
        source_info: SourceProbe = window_probe.source_info_at,
        threshold: Callable[[int, int, int], tuple[int, int]] = system.drag_threshold_for,
        button_down: Callable[[], bool] = system.primary_button_down,
        integrity_ok: Callable[[int], bool] = system.source_integrity_ok,
        cursor: Callable[[], tuple[int, int] | None] = _win32.cursor_pos,
        clock: Callable[[], int] = time.perf_counter_ns,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._monitor = monitor
        self._poller = poller
        self._window = window
        self._any_source = any_source
        self._source_info = source_info
        self._threshold = threshold
        self._button_down = button_down
        self._integrity_ok = integrity_ok
        self._cursor = cursor
        self._clock = clock
        self._machine = GestureMachine()
        self._paused = False
        self._connected = False

    # ----------------------------------------------------------------- lifecycle
    @property
    def machine(self) -> GestureMachine:
        return self._machine

    @property
    def paused(self) -> bool:
        return self._paused

    def start(self) -> None:
        """Connect once and register raw input. Safe to call again after ``stop``."""
        if not self._connected:
            self._connect()
        registration = self._monitor.start()
        if not registration.registered:
            log.warning("raw input is not available: %s", registration.reason)

    def _connect(self) -> None:
        self._connected = True
        self._monitor.pointer_down.connect(self._on_pointer_down)
        self._monitor.pointer_moved.connect(self._on_pointer_moved)
        self._monitor.pointer_up.connect(self._on_pointer_up)
        self._poller.changed.connect(self._on_modifier)
        self._poller.sampled.connect(self._on_sample)
        self._poller.escape.connect(self._on_escape)
        self._window.drop_requested.connect(self._on_drop_requested, QUEUED)
        self._window.cancelled.connect(self._on_cancelled, QUEUED)
        self._window.drag_left.connect(self._on_drag_left, QUEUED)
        self._window.gave_up.connect(self._on_gave_up, QUEUED)

    def stop(self) -> None:
        self._reset()
        self._monitor.stop()

    def pause(self) -> None:
        """Ignore drags until ``resume``. The current gesture, if any, ends now."""
        self._paused = True
        self._reset()
        log.info("paused")

    def resume(self) -> None:
        self._paused = False
        log.info("resumed")

    def set_trigger_key(self, key: TriggerKey) -> None:
        self._poller.set_key(key)  # takes effect at the next sample (D8)

    def _reset(self) -> None:
        self._window.hide_wheel()
        self._machine = GestureMachine()
        self._sync()

    # ----------------------------------------------------------------- inputs
    def _on_pointer_down(self, x: int, y: int) -> None:
        if self._paused:
            return
        info = self._source_info(x, y, any_source=self._any_source)
        if info.hwnd and info.hwnd == int(self._window.winId()):
            return  # a press on the wheel itself is never a drag source
        allowed = info.allowed
        if allowed and info.pid and not self._integrity_ok(info.pid):
            log.warning("press in pid %d refused: lower integrity level than ours", info.pid)
            allowed = False
        event = PointerDown(self._clock(), x, y, allowed, self._threshold(info.hwnd, x, y))
        log.debug("press at %s, allowed=%s, chain=%s", (x, y), allowed, info.chain)
        self._feed(event)
        # The poller may already be running (a press during the release grace): start from
        # "up" again, so a key held across gestures is an edge for this one too.
        self._poller.start()

    def _on_pointer_moved(self) -> None:
        if self._paused or self._machine.state is State.IDLE:
            return
        pos = self._cursor()
        if pos is not None:
            self._feed(PointerMove(self._clock(), pos[0], pos[1]))

    def _on_pointer_up(self) -> None:
        if not self._paused:
            self._feed(PointerUp(self._clock()))

    def _on_modifier(self, pressed: bool) -> None:
        self._feed(ModifierState(self._clock(), pressed))

    def _on_sample(self, t_ns: int) -> None:
        self._feed(Tick(t_ns))
        if self._machine.wheel_visible:
            self._window.tick(t_ns)

    def _on_escape(self) -> None:
        log.debug("Esc pressed in state %s", self._machine.state)

    # ----------------------------------------------------------------- wheel signals (queued)
    def _on_drop_requested(self, request: DropRequest) -> None:
        now = self._clock()
        log.info(
            "DropRequest: %d file(s) -> %s, handled %.1f ms after the drop",
            len(request.files),
            request.target_id,
            (now - request.received_at_ns) / 1e6,
        )
        self._feed(DropDone(now))
        self.drop_received.emit(request)

    def _on_cancelled(self) -> None:
        self._feed(DropCancelled(self._clock()))

    def _on_drag_left(self) -> None:
        if self._button_down():
            self._feed(WheelLeft(self._clock()))
        else:
            self._feed(DropCancelled(self._clock()))

    def _on_gave_up(self) -> None:
        self._feed(GiveUp(self._clock()))

    # ----------------------------------------------------------------- the machine
    def _feed(
        self,
        event: PointerDown
        | PointerMove
        | PointerUp
        | ModifierState
        | WheelLeft
        | DropDone
        | DropCancelled
        | GiveUp
        | Tick,
    ) -> None:
        before = self._machine.state
        self._apply(self._machine.feed(event))
        after = self._machine.state
        if after is not before:
            log.debug("state %s -> %s", before, after)
        self._sync()

    def _apply(self, commands: Sequence[Command]) -> None:
        for command in commands:
            if isinstance(command, ShowWheel):
                self._window.show_at((command.x, command.y), self._clock())
            elif isinstance(command, HideWheel):
                log.debug("hide: %s", command.reason)
                self._window.hide_wheel()

    def _sync(self) -> None:
        """Keep the poller and the motion reports in step with the machine's state."""
        wants = self._machine.wants_polling
        if wants and not self._poller.active:
            self._poller.start()
        elif not wants and self._poller.active:
            self._poller.stop()
        self._monitor.track_moves = wants
