"""Elevation, the per-DPI drag threshold and the accessibility switches (phase-4 §4.3). No Qt.

Rules:

- **Elevation is the token's elevation *type*, not its elevation bit** (phase-2 §3.7, phase-3 §6.4).
  With UAC off, every process of an administrator reports "elevated", Explorer included, and
  drags work. Only the *full* half of a split token is the case that breaks drag and drop between
  Explorer and us, and it is the only case "Restart normally" can fix.
- **"Restart normally"** (phase-3 §6.4, 🔶 S2) relaunches the app with the shell's token: Explorer
  runs as the unelevated user, so a primary token duplicated from it starts a normal process.
  ``CreateProcessWithTokenW`` needs ``SeImpersonatePrivilege``, which the full administrator token
  holds, and it goes through the Secondary Logon service. Any failure returns ``False``, and the
  dialog then offers Quit only.
- **The drag threshold** is what Explorer's own ``DragDetect`` uses: ``SM_CXDRAG`` / ``SM_CYDRAG``
  for the DPI of the window under the point, which is per-side ("the pointer can move this far
  before a drag begins"), so callers compare with ``>``.
- **Physical buttons.** Raw input and ``GetAsyncKeyState`` report the physical buttons whatever
  "Switch primary and secondary buttons" says, so :func:`primary_button_down` checks
  ``SM_SWAPBUTTON`` (phase-4 §4.3 review).

Calls that take screen coordinates see virtualized values until a ``QGuiApplication`` exists, so
:func:`drag_threshold_at` runs only after the application is built.
"""

from __future__ import annotations

import ctypes
import logging
import subprocess
import sys
from collections.abc import Sequence
from ctypes import byref
from ctypes import wintypes as wt

from morphwheel.platform import _win32 as w

log = logging.getLogger("morphwheel.platform.system")

SHELL_TRAY_CLASS = "Shell_TrayWnd"


# --------------------------------------------------------------------------- elevation
def elevation_type() -> int | None:
    """``TOKEN_ELEVATION_TYPE_*`` of this process, or ``None`` if the token can't be read."""
    token = wt.HANDLE()
    if not w.advapi32.OpenProcessToken(w.kernel32.GetCurrentProcess(), w.TOKEN_QUERY, byref(token)):
        return None
    try:
        return w.token_information_dword(int(token.value or 0), w.TOKEN_ELEVATION_TYPE)
    finally:
        w.kernel32.CloseHandle(token)


def is_elevated() -> bool:
    """True only for the full half of a split token: the case the startup warning is about."""
    return elevation_type() == w.TOKEN_ELEVATION_TYPE_FULL


def restart_command_line(extra_args: Sequence[str] = ()) -> str:
    """The command line that starts this app again: the frozen exe, or ``python -m morphwheel``."""
    frozen = bool(getattr(sys, "frozen", False))
    parts = [sys.executable] if frozen else [sys.executable, "-m", "morphwheel"]
    return subprocess.list2cmdline([*parts, *extra_args])


def _shell_window() -> int:
    hwnd = w.user32.GetShellWindow()
    if not hwnd:
        hwnd = w.user32.FindWindowW(SHELL_TRAY_CLASS, None)
    return int(hwnd or 0)


def _shell_primary_token() -> int | None:
    """A primary token duplicated from the shell (Explorer), or ``None``. The caller closes it."""
    hwnd = _shell_window()
    if not hwnd:
        log.warning("restart: no shell window")
        return None
    pid = w.window_pid(hwnd)
    process = w.kernel32.OpenProcess(w.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not process:
        log.warning("restart: OpenProcess(shell pid %d) failed: %d", pid, w.last_error())
        return None
    token, primary = wt.HANDLE(), wt.HANDLE()
    try:
        if not w.advapi32.OpenProcessToken(
            process, w.TOKEN_QUERY | w.TOKEN_DUPLICATE, byref(token)
        ):
            log.warning("restart: OpenProcessToken failed: %d", w.last_error())
            return None
        access = (
            w.TOKEN_QUERY
            | w.TOKEN_DUPLICATE
            | w.TOKEN_ASSIGN_PRIMARY
            | w.TOKEN_ADJUST_DEFAULT
            | w.TOKEN_ADJUST_SESSIONID
        )
        if not w.advapi32.DuplicateTokenEx(
            token, access, None, w.SECURITY_IMPERSONATION, w.TOKEN_PRIMARY, byref(primary)
        ):
            log.warning("restart: DuplicateTokenEx failed: %d", w.last_error())
            return None
        return int(primary.value or 0) or None
    finally:
        if token.value:
            w.kernel32.CloseHandle(token)
        w.kernel32.CloseHandle(process)


def restart_unelevated(extra_args: Sequence[str] = ()) -> bool:
    """Start a normal (unelevated) instance of the app. True if the new process was created.

    The caller quits this instance afterwards. Returns ``False`` when not elevated (there is
    nothing to restart into), when the shell is missing, or when Windows refuses, for example
    because the Secondary Logon service is disabled.
    """
    if not is_elevated():
        return False
    token = _shell_primary_token()
    if token is None:
        return False
    command = ctypes.create_unicode_buffer(restart_command_line(extra_args))
    startup = w.STARTUPINFOW()
    startup.cb = ctypes.sizeof(startup)
    info = w.PROCESS_INFORMATION()
    # The new process gets the token's own environment (its profile paths), not ours: after an
    # over-the-shoulder elevation ours would point at the administrator's profile.
    environment = ctypes.c_void_p()
    if not w.userenv.CreateEnvironmentBlock(byref(environment), token, False):
        # With no block, Windows builds one from the token's profile itself: still not ours.
        log.warning("restart: CreateEnvironmentBlock failed: %d", w.last_error())
        environment = ctypes.c_void_p()
    try:
        ok = bool(
            w.advapi32.CreateProcessWithTokenW(
                token,
                w.LOGON_WITH_PROFILE,
                None,
                command,
                w.CREATE_UNICODE_ENVIRONMENT if environment.value else 0,
                environment,
                None,
                byref(startup),
                byref(info),
            )
        )
        if ok:
            w.kernel32.CloseHandle(info.hThread)
            w.kernel32.CloseHandle(info.hProcess)
            log.info("restart: started pid %d without elevation", info.dwProcessId)
        else:
            log.warning("restart: CreateProcessWithTokenW failed: %d", w.last_error())
        return ok
    finally:
        if environment.value:
            w.userenv.DestroyEnvironmentBlock(environment)
        w.kernel32.CloseHandle(token)


# --------------------------------------------------------------------------- DPI and threshold
def dpi_for(hwnd: int, x: int, y: int) -> int:
    """The effective DPI of ``hwnd`` (0 for none), else of the monitor at the point, else system."""
    dpi = int(w.user32.GetDpiForWindow(hwnd)) if hwnd else 0
    if not dpi:
        monitor = w.user32.MonitorFromPoint(wt.POINT(x, y), w.MONITOR_DEFAULTTONEAREST)
        if monitor:
            dx, dy = wt.UINT(), wt.UINT()
            if w.shcore.GetDpiForMonitor(monitor, w.MDT_EFFECTIVE_DPI, byref(dx), byref(dy)) == 0:
                dpi = dx.value
    return dpi or int(w.user32.GetDpiForSystem()) or w.USER_DEFAULT_SCREEN_DPI


def dpi_at(x: int, y: int) -> int:
    """The effective DPI at a physical point: its window, else its monitor, else the system."""
    return dpi_for(w.window_at(x, y), x, y)


def drag_threshold(dpi: int) -> tuple[int, int]:
    """``SM_CXDRAG`` / ``SM_CYDRAG`` for ``dpi``, per side, never below 1."""
    cx = abs(int(w.user32.GetSystemMetricsForDpi(w.SM_CXDRAG, dpi)))
    cy = abs(int(w.user32.GetSystemMetricsForDpi(w.SM_CYDRAG, dpi)))
    return max(cx, 1), max(cy, 1)


def drag_threshold_for(hwnd: int, x: int, y: int) -> tuple[int, int]:
    """The drag threshold for a press on ``hwnd`` at a physical point (``PointerDown``).

    The window probe already found ``hwnd``; passing it avoids a second ``WindowFromPoint``.
    """
    return drag_threshold(dpi_for(hwnd, x, y))


def drag_threshold_at(x: int, y: int) -> tuple[int, int]:
    return drag_threshold(dpi_at(x, y))


# --------------------------------------------------------------------------- input facts
def buttons_swapped() -> bool:
    return bool(w.user32.GetSystemMetrics(w.SM_SWAPBUTTON))


def primary_button_down() -> bool:
    """Whether the *primary* mouse button is held, honoring swapped buttons."""
    return w.key_down(w.VK_RBUTTON if buttons_swapped() else w.VK_LBUTTON)


# --------------------------------------------------------------------------- accessibility (C7)
def animations_enabled() -> bool:
    """Windows' "Animation effects" switch; False over RDP with animations off. Unknown → True."""
    value = wt.BOOL()
    if not w.user32.SystemParametersInfoW(w.SPI_GETCLIENTAREAANIMATION, 0, byref(value), 0):
        return True
    return bool(value.value)


def high_contrast() -> bool:
    """Whether a High Contrast theme is active. Unknown → False."""
    hc = w.HIGHCONTRASTW()
    hc.cbSize = ctypes.sizeof(hc)
    if not w.user32.SystemParametersInfoW(w.SPI_GETHIGHCONTRAST, hc.cbSize, byref(hc), 0):
        return False
    return bool(hc.dwFlags & w.HCF_HIGHCONTRASTON)
