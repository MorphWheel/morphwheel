"""ctypes bindings for the Win32 calls Morphwheel makes (phase-4 §2, §4.3).

This module holds only signatures, structs, constants and marshalling helpers. The behavior lives
in the sibling modules: ``raw_input`` (WM_INPUT), ``modifier_poller`` (key state), ``window_probe``
(the source window), ``system`` (elevation, DPI, accessibility, integrity levels) and ``shell``
(the Recycle Bin).

Rules:

- **No Qt.** The worker executable (A5a) must be able to import ``platform.shell`` without loading
  Qt (R2), so nothing in this module or its imports touches PySide6. Enforced by contract P1.
- **Every DLL is our own ``WinDLL`` with ``use_last_error=True``.** ``ctypes.windll`` is shared
  across packages and their ``argtypes`` would collide. Errors are read with
  :func:`ctypes.get_last_error`, never ``GetLastError``.
- **Nothing here prints or logs.** The frozen app runs without a console, so ``sys.stdout`` is
  ``None`` there.
- **Struct layouts are asserted in ``tests/unit/test_win32.py``** against the SDK sizes, so a
  hand-written layout can't drift.

Calls that take screen coordinates (``GetCursorPos``, ``WindowFromPoint``, ``GetDpiForWindow``)
see virtualized values until a ``QGuiApplication`` exists, because Qt is what switches the process
to per-monitor DPI awareness. The callers run after the application is built.
"""

from __future__ import annotations

import ctypes
from ctypes import POINTER, byref
from ctypes import wintypes as wt
from typing import Any

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
shcore = ctypes.WinDLL("shcore", use_last_error=True)
userenv = ctypes.WinDLL("userenv", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

# --------------------------------------------------------------------------- constants
# Window messages and raw input (winuser.h)
WM_INPUT = 0x00FF
RID_INPUT = 0x10000003
RIM_TYPEMOUSE = 0
RIDEV_REMOVE = 0x00000001
RIDEV_INPUTSINK = 0x00000100
HID_USAGE_PAGE_GENERIC = 0x01
HID_USAGE_GENERIC_MOUSE = 0x02
RI_MOUSE_LEFT_BUTTON_DOWN = 0x0001
RI_MOUSE_LEFT_BUTTON_UP = 0x0002
RI_MOUSE_RIGHT_BUTTON_DOWN = 0x0004
RI_MOUSE_RIGHT_BUTTON_UP = 0x0008
RI_MOUSE_WHEEL = 0x0400
MOUSE_MOVE_ABSOLUTE = 0x0001

# Virtual keys. Raw input flags and GetAsyncKeyState report the *physical* buttons, whatever
# "Switch primary and secondary buttons" says, so callers check SM_SWAPBUTTON.
VK_LBUTTON = 0x01
VK_RBUTTON = 0x02
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_ESCAPE = 0x1B
KEY_DOWN_BIT = 0x8000  # GetAsyncKeyState: only this bit is reliable; the low bit is shared state

# System metrics
SM_SWAPBUTTON = 23
SM_CXDRAG = 68
SM_CYDRAG = 69

# Window relationships
GA_PARENT = 1

# Monitors and DPI
MONITOR_DEFAULTTONEAREST = 0x00000002
MDT_EFFECTIVE_DPI = 0
USER_DEFAULT_SCREEN_DPI = 96

# SystemParametersInfo
SPI_GETHIGHCONTRAST = 0x0042
SPI_GETCLIENTAREAANIMATION = 0x1042
HCF_HIGHCONTRASTON = 0x00000001

# Processes and tokens
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_ASSIGN_PRIMARY = 0x0001
TOKEN_DUPLICATE = 0x0002
TOKEN_QUERY = 0x0008
TOKEN_ADJUST_DEFAULT = 0x0080
TOKEN_ADJUST_SESSIONID = 0x0100
TOKEN_ELEVATION_TYPE = 18  # TOKEN_INFORMATION_CLASS
TOKEN_ELEVATION = 20
TOKEN_ELEVATION_TYPE_DEFAULT = 1  # no linked token: UAC off, or not an administrator
TOKEN_ELEVATION_TYPE_FULL = 2  # the elevated half of a split token
TOKEN_ELEVATION_TYPE_LIMITED = 3  # the normal half of a split token
SECURITY_IMPERSONATION = 2  # SECURITY_IMPERSONATION_LEVEL
LOGON_WITH_PROFILE = 0x00000001  # CreateProcessWithTokenW dwLogonFlags
CREATE_UNICODE_ENVIRONMENT = 0x00000400
TOKEN_PRIMARY = 1  # TOKEN_TYPE
TOKEN_INTEGRITY_LEVEL = 25  # TOKEN_INFORMATION_CLASS: a TOKEN_MANDATORY_LABEL
SECURITY_MANDATORY_UNTRUSTED_RID = 0x0000
SECURITY_MANDATORY_LOW_RID = 0x1000
SECURITY_MANDATORY_MEDIUM_RID = 0x2000
SECURITY_MANDATORY_HIGH_RID = 0x3000
SECURITY_MANDATORY_SYSTEM_RID = 0x4000

# Shell (shellapi.h, shlobj.h)
FO_DELETE = 0x0003
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400
DRIVE_FIXED = 3
INVALID_HANDLE_VALUE = wt.HANDLE(-1).value

# Error codes
ERROR_INSUFFICIENT_BUFFER = 122
ERROR_INVALID_WINDOW_HANDLE = 1400
ERROR_SERVICE_DISABLED = 1058


# --------------------------------------------------------------------------- structs
class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", wt.DWORD),
        ("dwSize", wt.DWORD),
        ("hDevice", wt.HANDLE),
        ("wParam", wt.WPARAM),
    ]


class _RAWMOUSE_BUTTONS(ctypes.Structure):
    _fields_ = [("usButtonFlags", wt.USHORT), ("usButtonData", wt.USHORT)]


class _RAWMOUSE_UNION(ctypes.Union):
    _anonymous_ = ("buttons",)
    _fields_ = [("ulButtons", wt.ULONG), ("buttons", _RAWMOUSE_BUTTONS)]


class RAWMOUSE(ctypes.Structure):
    """The SDK puts the button union at a 4-byte boundary after ``usFlags``; the union does that."""

    _anonymous_ = ("u",)
    _fields_ = [
        ("usFlags", wt.USHORT),
        ("u", _RAWMOUSE_UNION),
        ("ulRawButtons", wt.ULONG),
        ("lLastX", wt.LONG),
        ("lLastY", wt.LONG),
        ("ulExtraInformation", wt.ULONG),
    ]


class RAWINPUTMOUSE(ctypes.Structure):
    """``RAWINPUT`` for the mouse case. Only mice are registered, so HID packets never arrive."""

    _fields_ = [("header", RAWINPUTHEADER), ("mouse", RAWMOUSE)]


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", wt.USHORT),
        ("usUsage", wt.USHORT),
        ("dwFlags", wt.DWORD),
        ("hwndTarget", wt.HWND),
    ]


class HIGHCONTRASTW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.UINT),
        ("dwFlags", wt.DWORD),
        ("lpszDefaultScheme", wt.LPWSTR),
    ]


class SHFILEOPSTRUCTW(ctypes.Structure):
    """Natural alignment on x64 (shellapi.h packs it only for 32-bit builds)."""

    _fields_ = [
        ("hwnd", wt.HWND),
        ("wFunc", wt.UINT),
        ("pFrom", wt.LPCWSTR),  # double-NUL-terminated list
        ("pTo", wt.LPCWSTR),
        ("fFlags", wt.WORD),  # FILEOP_FLAGS
        ("fAnyOperationsAborted", wt.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wt.LPCWSTR),
    ]


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wt.DWORD)]


class TOKEN_MANDATORY_LABEL(ctypes.Structure):
    _fields_ = [("Label", SID_AND_ATTRIBUTES)]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD),
        ("lpReserved", wt.LPWSTR),
        ("lpDesktop", wt.LPWSTR),
        ("lpTitle", wt.LPWSTR),
        ("dwX", wt.DWORD),
        ("dwY", wt.DWORD),
        ("dwXSize", wt.DWORD),
        ("dwYSize", wt.DWORD),
        ("dwXCountChars", wt.DWORD),
        ("dwYCountChars", wt.DWORD),
        ("dwFillAttribute", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("wShowWindow", wt.WORD),
        ("cbReserved2", wt.WORD),
        ("lpReserved2", POINTER(ctypes.c_ubyte)),
        ("hStdInput", wt.HANDLE),
        ("hStdOutput", wt.HANDLE),
        ("hStdError", wt.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wt.HANDLE),
        ("hThread", wt.HANDLE),
        ("dwProcessId", wt.DWORD),
        ("dwThreadId", wt.DWORD),
    ]


# --------------------------------------------------------------------------- signatures
def _sig(fn: Any, restype: Any, *argtypes: Any) -> None:
    fn.restype = restype
    fn.argtypes = list(argtypes)


# Windows and the cursor
_sig(user32.GetCursorPos, wt.BOOL, POINTER(wt.POINT))
_sig(user32.WindowFromPoint, wt.HWND, wt.POINT)
_sig(user32.GetAncestor, wt.HWND, wt.HWND, wt.UINT)
_sig(user32.GetDesktopWindow, wt.HWND)
_sig(user32.GetShellWindow, wt.HWND)
_sig(user32.GetForegroundWindow, wt.HWND)
_sig(user32.FindWindowW, wt.HWND, wt.LPCWSTR, wt.LPCWSTR)
_sig(user32.IsWindow, wt.BOOL, wt.HWND)
_sig(user32.GetClassNameW, ctypes.c_int, wt.HWND, wt.LPWSTR, ctypes.c_int)
_sig(user32.GetWindowThreadProcessId, wt.DWORD, wt.HWND, POINTER(wt.DWORD))

# Keys and metrics
_sig(user32.GetAsyncKeyState, ctypes.c_short, ctypes.c_int)
_sig(user32.GetSystemMetrics, ctypes.c_int, ctypes.c_int)
_sig(user32.GetSystemMetricsForDpi, ctypes.c_int, ctypes.c_int, wt.UINT)
_sig(user32.SystemParametersInfoW, wt.BOOL, wt.UINT, wt.UINT, ctypes.c_void_p, wt.UINT)

# DPI
_sig(user32.GetDpiForWindow, wt.UINT, wt.HWND)
_sig(user32.GetDpiForSystem, wt.UINT)
_sig(user32.MonitorFromPoint, wt.HMONITOR, wt.POINT, wt.DWORD)
_sig(
    shcore.GetDpiForMonitor,
    ctypes.HRESULT,
    wt.HMONITOR,
    ctypes.c_int,
    POINTER(wt.UINT),
    POINTER(wt.UINT),
)

# Raw input
_sig(user32.RegisterRawInputDevices, wt.BOOL, POINTER(RAWINPUTDEVICE), wt.UINT, wt.UINT)
_sig(
    user32.GetRawInputData,
    wt.UINT,
    wt.HANDLE,  # HRAWINPUT, the lParam of WM_INPUT
    wt.UINT,
    ctypes.c_void_p,
    POINTER(wt.UINT),
    wt.UINT,
)

# Processes and tokens
_sig(kernel32.GetCurrentProcess, wt.HANDLE)
_sig(kernel32.OpenProcess, wt.HANDLE, wt.DWORD, wt.BOOL, wt.DWORD)
_sig(kernel32.CloseHandle, wt.BOOL, wt.HANDLE)
_sig(advapi32.OpenProcessToken, wt.BOOL, wt.HANDLE, wt.DWORD, POINTER(wt.HANDLE))
_sig(
    advapi32.GetTokenInformation,
    wt.BOOL,
    wt.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wt.DWORD,
    POINTER(wt.DWORD),
)
_sig(
    advapi32.DuplicateTokenEx,
    wt.BOOL,
    wt.HANDLE,
    wt.DWORD,
    ctypes.c_void_p,  # LPSECURITY_ATTRIBUTES
    ctypes.c_int,  # SECURITY_IMPERSONATION_LEVEL
    ctypes.c_int,  # TOKEN_TYPE
    POINTER(wt.HANDLE),
)
_sig(
    advapi32.CreateProcessWithTokenW,
    wt.BOOL,
    wt.HANDLE,
    wt.DWORD,  # dwLogonFlags
    wt.LPCWSTR,  # lpApplicationName
    wt.LPWSTR,  # lpCommandLine: a writable buffer
    wt.DWORD,  # dwCreationFlags
    ctypes.c_void_p,  # lpEnvironment
    wt.LPCWSTR,  # lpCurrentDirectory
    POINTER(STARTUPINFOW),
    POINTER(PROCESS_INFORMATION),
)
_sig(userenv.CreateEnvironmentBlock, wt.BOOL, POINTER(ctypes.c_void_p), wt.HANDLE, wt.BOOL)
_sig(userenv.DestroyEnvironmentBlock, wt.BOOL, ctypes.c_void_p)
_sig(advapi32.GetSidSubAuthorityCount, POINTER(ctypes.c_ubyte), ctypes.c_void_p)
_sig(advapi32.GetSidSubAuthority, POINTER(wt.DWORD), ctypes.c_void_p, wt.DWORD)

# Shell
_sig(shell32.SHFileOperationW, ctypes.c_int, POINTER(SHFILEOPSTRUCTW))
_sig(kernel32.GetDriveTypeW, wt.UINT, wt.LPCWSTR)


# --------------------------------------------------------------------------- marshalling helpers
def last_error() -> int:
    """The thread's last Win32 error, as captured by ``use_last_error``."""
    return ctypes.get_last_error()


def cursor_pos() -> tuple[int, int] | None:
    """The cursor in physical screen px, or ``None`` when it can't be read (secure desktop)."""
    pt = wt.POINT()
    if not user32.GetCursorPos(byref(pt)):
        return None
    return pt.x, pt.y


def window_at(x: int, y: int) -> int:
    """The HWND under a physical point, or 0."""
    return int(user32.WindowFromPoint(wt.POINT(x, y)) or 0)


def class_name(hwnd: int) -> str:
    """The window class of ``hwnd``; empty when the handle is gone."""
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def key_down(vk: int) -> bool:
    """Whether the key is physically down right now (``GetAsyncKeyState`` high bit only)."""
    return bool(user32.GetAsyncKeyState(vk) & KEY_DOWN_BIT)


def window_pid(hwnd: int) -> int:
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, byref(pid))
    return pid.value


def token_information_dword(token: int, info_class: int) -> int | None:
    """A DWORD-sized token query, such as ``TOKEN_ELEVATION_TYPE``. ``None`` if the query fails."""
    value, size = wt.DWORD(), wt.DWORD()
    if not advapi32.GetTokenInformation(token, info_class, byref(value), 4, byref(size)):
        return None
    return int(value.value)


def token_integrity_rid(token: int) -> int | None:
    """The token's integrity level (a ``SECURITY_MANDATORY_*_RID``), or ``None`` if unreadable."""
    size = wt.DWORD()
    advapi32.GetTokenInformation(token, TOKEN_INTEGRITY_LEVEL, None, 0, byref(size))
    if last_error() != ERROR_INSUFFICIENT_BUFFER or not size.value:
        return None
    buf = ctypes.create_string_buffer(size.value)
    if not advapi32.GetTokenInformation(token, TOKEN_INTEGRITY_LEVEL, buf, size.value, byref(size)):
        return None
    label = ctypes.cast(buf, POINTER(TOKEN_MANDATORY_LABEL)).contents
    sid = label.Label.Sid
    if not sid:
        return None
    count = advapi32.GetSidSubAuthorityCount(sid).contents.value
    if not count:
        return None
    return int(advapi32.GetSidSubAuthority(sid, count - 1).contents.value)
