"""``RawInputMonitor``: primary-button presses, releases and motion from WM_INPUT (SP-1).

Raw Input is the detection mechanism the spike chose: no low-level hook, no keyboard hook. A
hidden sink window registers the mouse with ``RIDEV_INPUTSINK``, so WM_INPUT arrives while
Explorer owns the drag. A native event filter decodes each packet on the GUI thread and emits:

- ``pointer_down(x, y)``: the primary button went down, with the cursor in physical px;
- ``pointer_moved()``: any other packet, while :attr:`track_moves` is set (the gesture machine only
  needs motion between a press and a release);
- ``pointer_up()``: the primary button came up.

Rules:

- **Physical buttons.** ``usButtonFlags`` names the physical button, so with "Switch primary and
  secondary buttons" on, the primary button is the *right* one. ``start()`` reads
  ``SM_SWAPBUTTON`` once per registration.
- **Position comes from ``GetCursorPos``,** never from ``lLastX`` / ``lLastY``: over RDP and in VMs
  those are absolute values from 0 to 65535, and we only need where the cursor is.
- **The filter never raises into Qt's loop.** A bug is logged once, and the filter keeps returning
  ``(False, 0)`` so the message still reaches ``DefWindowProc``, which WM_INPUT requires.
- **A fixed 48-byte buffer is enough:** only the mouse is registered, and ``RAWMOUSE`` is fixed
  size. A larger packet is dropped and logged once rather than designed for.
- **``start()`` never raises.** Without a native window (Qt's ``offscreen`` platform in tests) it
  reports ``registered=False``; the GUI runs, drags are simply not seen.
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import byref
from ctypes import wintypes as wt
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

from morphwheel.platform import _win32 as w

log = logging.getLogger("morphwheel.platform.raw_input")


class RawMouse(StrEnum):
    DOWN = "down"  # the primary button went down
    UP = "up"
    MOVE = "move"  # anything else: motion, the other buttons, the wheel


def parse_raw_mouse(packet: w.RAWINPUTMOUSE, *, swapped: bool) -> list[RawMouse]:
    """Classify one mouse packet. Both edges can share a packet, in which case down comes first."""
    if packet.header.dwType != w.RIM_TYPEMOUSE:
        return []
    flags = packet.mouse.usButtonFlags
    if swapped:
        down, up = w.RI_MOUSE_RIGHT_BUTTON_DOWN, w.RI_MOUSE_RIGHT_BUTTON_UP
    else:
        down, up = w.RI_MOUSE_LEFT_BUTTON_DOWN, w.RI_MOUSE_LEFT_BUTTON_UP
    events: list[RawMouse] = []
    if flags & down:
        events.append(RawMouse.DOWN)
    if flags & up:
        events.append(RawMouse.UP)
    return events or [RawMouse.MOVE]


@dataclass(frozen=True)
class Registration:
    registered: bool
    error: int = 0
    reason: str = ""


class _Filter(QAbstractNativeEventFilter):
    """Decodes WM_INPUT. Kept alive by the monitor: Qt calls it until it is removed."""

    def __init__(self, monitor: RawInputMonitor) -> None:
        super().__init__()
        self._monitor = monitor
        self._buffer = w.RAWINPUTMOUSE()
        self._size = wt.UINT()
        self._failed = False

    def nativeEventFilter(self, event_type: Any, message: Any) -> Any:
        try:
            msg = wt.MSG.from_address(int(message))
            if msg.message == w.WM_INPUT:
                self._monitor._on_input(self._read(msg.lParam))
        except Exception:
            if not self._failed:
                self._failed = True
                log.exception("raw input filter failed; further failures are not logged")
        return False, 0

    def _read(self, handle: int) -> w.RAWINPUTMOUSE | None:
        self._size.value = ctypes.sizeof(self._buffer)
        got = w.user32.GetRawInputData(
            handle,
            w.RID_INPUT,
            byref(self._buffer),
            byref(self._size),
            ctypes.sizeof(w.RAWINPUTHEADER),
        )
        if got == 0xFFFFFFFF:
            if not self._failed:
                self._failed = True
                log.error("GetRawInputData failed: error %d (logged once)", w.last_error())
            return None
        return self._buffer


class RawInputMonitor(QObject):
    pointer_down = Signal(int, int)  # physical px
    pointer_moved = Signal()
    pointer_up = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.track_moves = False  # the controller sets it while a gesture is in progress
        self._swapped = False
        self._sink: QWidget | None = None
        self._filter: _Filter | None = None
        self._registration = Registration(registered=False, reason="not started")

    @property
    def registration(self) -> Registration:
        return self._registration

    def start(self) -> Registration:
        """Register for mouse raw input. Idempotent; never raises."""
        if self._registration.registered:
            return self._registration
        self._swapped = bool(w.user32.GetSystemMetrics(w.SM_SWAPBUTTON))
        app = QCoreApplication.instance()
        if app is None or QGuiApplication.platformName() != "windows":
            self._registration = Registration(False, reason="not the windows platform")
            return self._registration
        if self._sink is None:
            self._sink = QWidget()  # never shown; it exists for its HWND
        hwnd = int(self._sink.winId())
        if not w.user32.IsWindow(hwnd):
            self._registration = Registration(False, w.ERROR_INVALID_WINDOW_HANDLE, "no HWND")
            return self._registration
        device = w.RAWINPUTDEVICE(
            w.HID_USAGE_PAGE_GENERIC, w.HID_USAGE_GENERIC_MOUSE, w.RIDEV_INPUTSINK, hwnd
        )
        if not w.user32.RegisterRawInputDevices(byref(device), 1, ctypes.sizeof(device)):
            error = w.last_error()
            log.error("RegisterRawInputDevices failed: error %d", error)
            self._registration = Registration(False, error, "RegisterRawInputDevices failed")
            return self._registration
        if self._filter is None:
            self._filter = _Filter(self)
            app.installNativeEventFilter(self._filter)
        self._registration = Registration(True)
        log.info("raw input registered (swapped buttons: %s)", self._swapped)
        return self._registration

    def stop(self) -> None:
        """Unregister and remove the filter. Idempotent."""
        app = QCoreApplication.instance()
        if self._filter is not None and app is not None:
            app.removeNativeEventFilter(self._filter)
        self._filter = None
        if self._registration.registered:
            device = w.RAWINPUTDEVICE(
                w.HID_USAGE_PAGE_GENERIC, w.HID_USAGE_GENERIC_MOUSE, w.RIDEV_REMOVE, None
            )
            if not w.user32.RegisterRawInputDevices(byref(device), 1, ctypes.sizeof(device)):
                log.warning("RIDEV_REMOVE failed: error %d", w.last_error())
        self._registration = Registration(registered=False, reason="stopped")

    # ------------------------------------------------------------------ packet handling
    def _on_input(self, packet: w.RAWINPUTMOUSE | None) -> None:
        if packet is None:
            return
        for event in parse_raw_mouse(packet, swapped=self._swapped):
            if event is RawMouse.DOWN:
                pos = w.cursor_pos()
                if pos is not None:  # None on the secure desktop: no gesture can start there
                    self.pointer_down.emit(pos[0], pos[1])
            elif event is RawMouse.UP:
                self.pointer_up.emit()
            elif self.track_moves:
                self.pointer_moved.emit()
