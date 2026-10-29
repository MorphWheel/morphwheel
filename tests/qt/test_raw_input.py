"""``platform.raw_input``: packet classification as a table, and the monitor's behavior offscreen.

Real WM_INPUT can't be produced under ``QT_QPA_PLATFORM=offscreen``, so the filter is driven with
hand-built packets. The registration path is checked for the one thing that matters in tests:
``start()`` reports instead of raising when there is no native window.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes as wt
from typing import Any

import pytest

if sys.platform != "win32":  # pragma: no cover
    pytest.skip("Win32 only", allow_module_level=True)

from morphwheel.platform import _win32 as w
from morphwheel.platform.raw_input import RawInputMonitor, RawMouse, parse_raw_mouse

pytestmark = pytest.mark.usefixtures("qapp")


def packet(flags: int = 0, *, dx: int = 0, dy: int = 0, kind: int = w.RIM_TYPEMOUSE) -> Any:
    p = w.RAWINPUTMOUSE()
    p.header.dwType = kind
    p.header.dwSize = ctypes.sizeof(p)
    p.mouse.usButtonFlags = flags
    p.mouse.lLastX, p.mouse.lLastY = dx, dy
    return p


L_DOWN, L_UP = w.RI_MOUSE_LEFT_BUTTON_DOWN, w.RI_MOUSE_LEFT_BUTTON_UP
R_DOWN, R_UP = w.RI_MOUSE_RIGHT_BUTTON_DOWN, w.RI_MOUSE_RIGHT_BUTTON_UP


@pytest.mark.parametrize(
    ("flags", "swapped", "expected"),
    [
        (L_DOWN, False, [RawMouse.DOWN]),
        (L_UP, False, [RawMouse.UP]),
        (L_DOWN | L_UP, False, [RawMouse.DOWN, RawMouse.UP]),  # coalesced click: down first
        (0, False, [RawMouse.MOVE]),  # motion only
        (w.RI_MOUSE_WHEEL, False, [RawMouse.MOVE]),  # wheel only: harmless as a move
        (R_DOWN, False, [RawMouse.MOVE]),  # the secondary button is not a gesture
        (R_DOWN, True, [RawMouse.DOWN]),  # swapped: the right button is primary
        (R_UP, True, [RawMouse.UP]),
        (L_DOWN, True, [RawMouse.MOVE]),  # swapped: the left button is secondary
        (L_DOWN | R_UP, True, [RawMouse.UP]),
    ],
)
def test_parse_table(flags: int, swapped: bool, expected: list[RawMouse]) -> None:
    assert parse_raw_mouse(packet(flags, dx=3, dy=0), swapped=swapped) == expected


def test_non_mouse_packets_are_ignored() -> None:
    assert parse_raw_mouse(packet(L_DOWN, kind=1), swapped=False) == []  # RIM_TYPEKEYBOARD


def test_start_reports_instead_of_raising_offscreen() -> None:
    monitor = RawInputMonitor()
    result = monitor.start()
    assert result.registered is False
    assert result.reason
    assert monitor.registration == result
    monitor.stop()
    monitor.stop()  # idempotent
    assert monitor.registration.registered is False


@pytest.fixture
def wired() -> tuple[RawInputMonitor, list[Any]]:
    monitor = RawInputMonitor()
    seen: list[Any] = []
    monitor.pointer_down.connect(lambda x, y: seen.append(("down", x, y)))
    monitor.pointer_moved.connect(lambda: seen.append("move"))
    monitor.pointer_up.connect(lambda: seen.append("up"))
    return monitor, seen


def test_packets_become_signals(
    monkeypatch: pytest.MonkeyPatch, wired: tuple[RawInputMonitor, list[Any]]
) -> None:
    monitor, seen = wired
    monkeypatch.setattr(w, "cursor_pos", lambda: (640, 480))

    monitor._on_input(packet(L_DOWN))
    monitor._on_input(packet(0, dx=5))  # ignored: not tracking moves yet
    monitor.track_moves = True
    monitor._on_input(packet(0, dx=5))
    monitor._on_input(packet(L_UP))
    monitor._on_input(None)  # a failed read
    assert seen == [("down", 640, 480), "move", "up"]


def test_no_press_without_a_cursor_position(
    monkeypatch: pytest.MonkeyPatch, wired: tuple[RawInputMonitor, list[Any]]
) -> None:
    monitor, seen = wired
    monkeypatch.setattr(w, "cursor_pos", lambda: None)  # the secure desktop
    monitor._on_input(packet(L_DOWN | L_UP))
    assert seen == ["up"]


def test_swapped_buttons_are_read_at_start(
    monkeypatch: pytest.MonkeyPatch, wired: tuple[RawInputMonitor, list[Any]]
) -> None:
    monitor, seen = wired
    monkeypatch.setattr(w, "cursor_pos", lambda: (1, 2))
    monkeypatch.setattr(w.user32, "GetSystemMetrics", lambda index: 1 if index == 23 else 0)
    monitor.start()  # fails to register offscreen, but has read SM_SWAPBUTTON
    monitor._on_input(packet(R_DOWN))
    monitor._on_input(packet(L_DOWN))  # now the secondary button
    assert seen == [("down", 1, 2)]


def test_filter_logs_a_failure_once_and_never_raises(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    wired: tuple[RawInputMonitor, list[Any]],
) -> None:
    from morphwheel.platform.raw_input import _Filter

    monitor, seen = wired
    filt = _Filter(monitor)
    msg = wt.MSG()
    msg.message = w.WM_INPUT
    msg.lParam = 0  # not a raw input handle: GetRawInputData returns -1
    with caplog.at_level(logging.ERROR, logger="morphwheel.platform.raw_input"):
        for _ in range(3):
            assert filt.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(msg)) == (
                False,
                0,
            )
    assert len([r for r in caplog.records if "GetRawInputData" in r.message]) == 1
    assert seen == []

    # A bug inside the handler is also logged once, not raised.
    monkeypatch.setattr(monitor, "_on_input", lambda p: 1 / 0)
    monkeypatch.setattr(filt, "_read", lambda handle: packet(L_DOWN))
    filt._failed = False
    with caplog.at_level(logging.ERROR, logger="morphwheel.platform.raw_input"):
        for _ in range(2):
            assert filt.nativeEventFilter(b"", ctypes.addressof(msg)) == (False, 0)
    assert len([r for r in caplog.records if "filter failed" in r.message]) == 1


def test_a_decoded_packet_flows_through_the_filter(
    monkeypatch: pytest.MonkeyPatch, wired: tuple[RawInputMonitor, list[Any]]
) -> None:
    """GetRawInputData is replaced by a fake that fills the monitor's reused buffer."""
    from morphwheel.platform.raw_input import _Filter

    monitor, seen = wired
    monkeypatch.setattr(w, "cursor_pos", lambda: (7, 8))

    def fake_get(handle: Any, cmd: Any, buf: Any, size: Any, header: Any) -> int:
        assert cmd == w.RID_INPUT
        assert header == 24
        target = buf._obj
        target.header.dwType = w.RIM_TYPEMOUSE
        target.mouse.usButtonFlags = L_DOWN
        return ctypes.sizeof(target)

    monkeypatch.setattr(w.user32, "GetRawInputData", fake_get)
    filt = _Filter(monitor)
    msg = wt.MSG()
    msg.message = w.WM_INPUT
    msg.lParam = 0x1234
    filt.nativeEventFilter(b"", ctypes.addressof(msg))
    msg.message = 0x0200  # WM_MOUSEMOVE: not ours
    filt.nativeEventFilter(b"", ctypes.addressof(msg))
    assert seen == [("down", 7, 8)]
