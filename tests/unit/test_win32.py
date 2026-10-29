"""``platform._win32``: struct layouts match the SDK, and the signatures call through.

The layout checks are the point of this file: a ctypes struct that is one field off still "works"
until the wrong bytes are read. The sizes and offsets are the x64 SDK values. The smoke checks
prove each signature marshals (a wrong ``argtypes`` raises or returns garbage) without needing a
desktop session; nothing here depends on the cursor or on a window of ours.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import byref
from ctypes import wintypes as wt

import pytest

if sys.platform != "win32":  # pragma: no cover
    pytest.skip("Win32 only", allow_module_level=True)

from morphwheel.platform import _win32 as w


@pytest.mark.parametrize(
    ("struct", "size", "alignment"),
    [
        (w.RAWINPUTHEADER, 24, 8),
        (w.RAWMOUSE, 24, 4),
        (w.RAWINPUTMOUSE, 48, 8),
        (w.RAWINPUTDEVICE, 16, 8),
        (w.HIGHCONTRASTW, 16, 8),
        (w.STARTUPINFOW, 104, 8),
        (w.PROCESS_INFORMATION, 24, 8),
        (w.SHFILEOPSTRUCTW, 56, 8),
        (w.SID_AND_ATTRIBUTES, 16, 8),
        (w.TOKEN_MANDATORY_LABEL, 16, 8),
        (wt.MSG, 48, 8),
        (wt.POINT, 8, 4),
    ],
)
def test_struct_sizes_match_the_sdk(
    struct: type[ctypes.Structure], size: int, alignment: int
) -> None:
    assert ctypes.sizeof(struct) == size
    assert ctypes.alignment(struct) == alignment


def test_rawmouse_layout() -> None:
    assert w.RAWMOUSE.usFlags.offset == 0
    assert w.RAWMOUSE.ulButtons.offset == 4
    assert w.RAWMOUSE.usButtonFlags.offset == 4
    assert w.RAWMOUSE.usButtonData.offset == 6
    assert w.RAWMOUSE.ulRawButtons.offset == 8
    assert w.RAWMOUSE.lLastX.offset == 12
    assert w.RAWMOUSE.lLastY.offset == 16
    assert w.RAWMOUSE.ulExtraInformation.offset == 20
    assert w.RAWINPUTMOUSE.mouse.offset == 24

    # The union really aliases: the low word of ulButtons is the flags, the high word the data.
    packet = w.RAWINPUTMOUSE()
    packet.mouse.ulButtons = 0x00780001
    assert packet.mouse.usButtonFlags == w.RI_MOUSE_LEFT_BUTTON_DOWN
    assert packet.mouse.usButtonData == 0x0078


def test_rawinputdevice_layout() -> None:
    assert w.RAWINPUTDEVICE.usUsage.offset == 2
    assert w.RAWINPUTDEVICE.dwFlags.offset == 4
    assert w.RAWINPUTDEVICE.hwndTarget.offset == 8


def test_startupinfo_layout() -> None:
    assert w.STARTUPINFOW.dwFlags.offset == 60
    assert w.STARTUPINFOW.wShowWindow.offset == 64
    assert w.STARTUPINFOW.lpReserved2.offset == 72
    assert w.STARTUPINFOW.hStdError.offset == 96
    assert w.PROCESS_INFORMATION.dwProcessId.offset == 16


def test_raw_input_header_size_is_what_getrawinputdata_wants() -> None:
    """``GetRawInputData`` rejects any header size other than the real one."""
    assert ctypes.sizeof(w.RAWINPUTHEADER) == 24


def test_get_raw_input_data_rejects_a_bad_handle() -> None:
    """Negative control: the signature marshals, and a bad handle yields the documented -1."""
    buf = w.RAWINPUTMOUSE()
    size = wt.UINT(ctypes.sizeof(buf))
    result = w.user32.GetRawInputData(
        None, w.RID_INPUT, byref(buf), byref(size), ctypes.sizeof(w.RAWINPUTHEADER)
    )
    assert result == 0xFFFFFFFF


def test_metrics_and_dpi_calls_marshal() -> None:
    for dpi in (96, 144, 192):
        assert w.user32.GetSystemMetricsForDpi(w.SM_CXDRAG, dpi) != 0
        assert w.user32.GetSystemMetricsForDpi(w.SM_CYDRAG, dpi) != 0
    assert w.user32.GetSystemMetrics(w.SM_SWAPBUTTON) in (0, 1)
    assert w.user32.GetDpiForSystem() >= w.USER_DEFAULT_SCREEN_DPI

    monitor = w.user32.MonitorFromPoint(wt.POINT(0, 0), w.MONITOR_DEFAULTTONEAREST)
    if monitor:  # a headless runner may have no display at all
        x, y = wt.UINT(), wt.UINT()
        assert w.shcore.GetDpiForMonitor(monitor, w.MDT_EFFECTIVE_DPI, byref(x), byref(y)) == 0
        assert x.value >= w.USER_DEFAULT_SCREEN_DPI


def test_window_calls_marshal() -> None:
    desktop = w.user32.GetDesktopWindow()
    assert desktop
    assert w.user32.IsWindow(desktop)
    assert not w.user32.IsWindow(None)
    assert w.class_name(desktop) == "#32769"  # the desktop window's class, by the SDK
    assert w.class_name(0) == ""
    assert w.user32.GetAncestor(desktop, w.GA_PARENT) in (None, 0)
    assert w.window_pid(desktop) > 0
    assert w.user32.GetDpiForWindow(desktop) >= w.USER_DEFAULT_SCREEN_DPI
    assert w.user32.GetDpiForWindow(None) == 0
    assert w.user32.FindWindowW("no-such-class-morphwheel", None) in (None, 0)
    assert w.window_at(-32000, -32000) in (0, desktop)


def test_key_and_cursor_calls_marshal() -> None:
    assert isinstance(w.key_down(w.VK_SHIFT), bool)
    assert isinstance(w.key_down(w.VK_LBUTTON), bool)
    pos = w.cursor_pos()
    assert pos is None or (isinstance(pos[0], int) and isinstance(pos[1], int))


def test_system_parameters_info_marshals() -> None:
    animation = wt.BOOL()
    assert w.user32.SystemParametersInfoW(w.SPI_GETCLIENTAREAANIMATION, 0, byref(animation), 0)
    assert animation.value in (0, 1)

    hc = w.HIGHCONTRASTW()
    hc.cbSize = ctypes.sizeof(hc)
    assert w.user32.SystemParametersInfoW(w.SPI_GETHIGHCONTRAST, hc.cbSize, byref(hc), 0)
    assert hc.cbSize == 16
    assert isinstance(hc.dwFlags, int)

    # Negative control: a wrong cbSize is rejected.
    bad = w.HIGHCONTRASTW()
    bad.cbSize = 4
    assert not w.user32.SystemParametersInfoW(w.SPI_GETHIGHCONTRAST, bad.cbSize, byref(bad), 0)


def test_token_queries_marshal() -> None:
    """CI runners are elevated, so only the shape is asserted, never a particular value."""
    token = wt.HANDLE()
    assert w.advapi32.OpenProcessToken(w.kernel32.GetCurrentProcess(), w.TOKEN_QUERY, byref(token))
    try:
        elevation_type = w.token_information_dword(token.value, w.TOKEN_ELEVATION_TYPE)
        assert elevation_type in (
            w.TOKEN_ELEVATION_TYPE_DEFAULT,
            w.TOKEN_ELEVATION_TYPE_FULL,
            w.TOKEN_ELEVATION_TYPE_LIMITED,
        )
        assert w.token_information_dword(token.value, w.TOKEN_ELEVATION) in (0, 1)
        assert w.token_information_dword(token.value, 9999) is None  # negative control
        rid = w.token_integrity_rid(token.value)
        assert rid in (w.SECURITY_MANDATORY_MEDIUM_RID, w.SECURITY_MANDATORY_HIGH_RID)
    finally:
        assert w.kernel32.CloseHandle(token)
    assert w.token_integrity_rid(0) is None  # negative control: no token
    assert not w.kernel32.OpenProcess(w.PROCESS_QUERY_LIMITED_INFORMATION, False, 0)
