"""``ModifierPoller``: samples the trigger key every 8 ms while a gesture is in progress (SP-1, D8).

Raw Input reports no key presses here (no keyboard is registered, by design), and a pressed Shift
produces no WM_INPUT while the mouse is still. So the trigger key is polled with
``GetAsyncKeyState``, which the spike measured at 1 to 9 ms behind Raw Input. The poller runs only
while the gesture machine wants it (``GestureMachine.wants_polling``): between a press and the end
of the gesture.

Signals:

- ``changed(bool)``: the trigger key went down or up (edges only);
- ``sampled(int)``: every sample, with ``t_ns``. The controller turns it into ``Tick`` for the
  gesture machine and the wheel session, whose dwell, spinner, give-up and release-grace timers
  only advance on ticks;
- ``escape()``: Esc went down (C8; logged, the OLE drag loop does the cancelling itself).

Rules:

- **Start from "up".** ``start()`` forgets the last state, so a key that is already held is seen
  as an edge on the first sample. This matches ``GestureMachine``'s own reset on ``PointerDown``.
- **``set_key`` takes effect at the next sample** (phase-4 §6, D8 row).
- **Inclusive keys.** ``"shift"`` means "Shift is down", so Ctrl+Shift also counts; ``"ctrl+shift"``
  needs both. Explorer then proposes Link, and ``force_copy`` still picks Copy.
- **Only the high bit** of ``GetAsyncKeyState`` is read. On the secure desktop, or when the
  foreground window belongs to a higher-integrity process (UIPI), it reads "up" (C9).
- The ``QTimer`` is a ``PreciseTimer``: a coarse one may be coalesced and drift.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Literal, get_args

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from morphwheel.platform import _win32 as w

TriggerKey = Literal["shift", "ctrl", "ctrl+shift"]
TRIGGER_KEYS: tuple[TriggerKey, ...] = get_args(TriggerKey)
POLL_INTERVAL_MS = 8

_VKS: dict[TriggerKey, tuple[int, ...]] = {
    "shift": (w.VK_SHIFT,),
    "ctrl": (w.VK_CONTROL,),
    "ctrl+shift": (w.VK_CONTROL, w.VK_SHIFT),
}

KeyReader = Callable[[int], bool]  # vk -> physically down


def key_state(reader: KeyReader, key: TriggerKey) -> bool:
    """Whether every key of the trigger combination is down."""
    return all(reader(vk) for vk in _VKS[key])


class ModifierPoller(QObject):
    changed = Signal(bool)
    sampled = Signal(object)  # t_ns: a Python int, because Signal(int) is a 32-bit C int
    escape = Signal()

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        reader: KeyReader = w.key_down,
        clock: Callable[[], int] = time.perf_counter_ns,
    ) -> None:
        super().__init__(parent)
        self._reader = reader
        self._clock = clock
        self._key: TriggerKey = "shift"
        self._pressed = False
        self._escape = False
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._sample)

    @property
    def key(self) -> TriggerKey:
        return self._key

    @property
    def active(self) -> bool:
        return self._timer.isActive()

    def set_key(self, key: TriggerKey) -> None:
        if key not in _VKS:
            raise ValueError(f"unknown trigger key {key!r}")
        self._key = key

    def start(self) -> None:
        """Begin sampling, from a clean "up" state. Idempotent."""
        self._pressed = False
        self._escape = False
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _sample(self) -> None:
        now = self._clock()
        pressed = key_state(self._reader, self._key)
        if pressed != self._pressed:
            self._pressed = pressed
            self.changed.emit(pressed)
        esc = self._reader(w.VK_ESCAPE)
        if esc and not self._escape:
            self.escape.emit()
        self._escape = esc
        self.sampled.emit(now)
