"""``platform.system``: the pure parts are exact; the Win32 parts prove shape and fallbacks.

The real restart is never exercised here (it would spawn a process). Its pieces are: the command
line (exact), the shell-token acquisition (shape), and the elevation gate (a non-elevated process
returns False at once). Running the app as administrator and clicking "Restart normally" is a
checklist row.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest

if sys.platform != "win32":  # pragma: no cover
    pytest.skip("Win32 only", allow_module_level=True)

from morphwheel.platform import _win32 as w
from morphwheel.platform import system


@pytest.mark.parametrize(
    ("frozen", "exe", "extra", "expected"),
    [
        (False, r"C:\py\python.exe", (), r"C:\py\python.exe -m morphwheel"),
        (
            True,
            r"C:\Program Files\Morphwheel\morphwheel.exe",
            (),
            r'"C:\Program Files\Morphwheel\morphwheel.exe"',
        ),
        (
            False,
            r"C:\my venv\python.exe",
            ("--debug",),
            r'"C:\my venv\python.exe" -m morphwheel --debug',
        ),
        (True, r"C:\mw\morphwheel.exe", ("--log", "a b"), r'C:\mw\morphwheel.exe --log "a b"'),
    ],
)
def test_restart_command_line(
    monkeypatch: pytest.MonkeyPatch, frozen: bool, exe: str, extra: tuple[str, ...], expected: str
) -> None:
    monkeypatch.setattr(sys, "executable", exe)
    if frozen:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
    else:
        monkeypatch.delattr(sys, "frozen", raising=False)
    assert system.restart_command_line(extra) == expected


def test_elevation_is_the_token_type() -> None:
    kind = system.elevation_type()
    assert kind in (
        w.TOKEN_ELEVATION_TYPE_DEFAULT,
        w.TOKEN_ELEVATION_TYPE_FULL,
        w.TOKEN_ELEVATION_TYPE_LIMITED,
    )
    assert system.is_elevated() is (kind == w.TOKEN_ELEVATION_TYPE_FULL)


def test_restart_refuses_when_not_elevated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system, "is_elevated", lambda: False)
    calls: list[str] = []
    monkeypatch.setattr(system, "_shell_primary_token", lambda: calls.append("token"))
    assert system.restart_unelevated() is False
    assert calls == []  # it never went looking for the shell


def test_restart_reports_failure_when_windows_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CreateProcessWithTokenW failure path closes the token and returns False."""
    closed: list[int] = []
    monkeypatch.setattr(system, "is_elevated", lambda: True)
    monkeypatch.setattr(system, "_shell_primary_token", lambda: 0x1234)
    monkeypatch.setattr(w.advapi32, "CreateProcessWithTokenW", lambda *a: 0)
    monkeypatch.setattr(w.kernel32, "CloseHandle", lambda h: closed.append(int(h)) or 1)
    assert system.restart_unelevated() is False
    assert closed == [0x1234]


def test_restart_closes_handles_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[int] = []
    seen: dict[str, Any] = {}

    def fake_create(token: Any, flags: Any, app: Any, cmd: Any, *rest: Any) -> int:
        seen["token"], seen["cmd"] = token, cmd.value
        info = rest[-1]._obj  # byref(PROCESS_INFORMATION)
        info.hProcess, info.hThread, info.dwProcessId = 0x10, 0x11, 4242
        return 1

    monkeypatch.setattr(system, "is_elevated", lambda: True)
    monkeypatch.setattr(system, "_shell_primary_token", lambda: 0x1234)
    monkeypatch.setattr(w.advapi32, "CreateProcessWithTokenW", fake_create)
    monkeypatch.setattr(w.kernel32, "CloseHandle", lambda h: closed.append(int(h)) or 1)
    assert system.restart_unelevated(("--x",)) is True
    assert seen["token"] == 0x1234
    assert seen["cmd"].endswith(" --x")
    assert sorted(closed) == [0x10, 0x11, 0x1234]


def test_shell_token_has_a_handle_or_a_reason() -> None:
    """On a desktop with Explorer this yields a primary token; on a bare runner, None."""
    token = system._shell_primary_token()
    if token is not None:
        assert w.kernel32.CloseHandle(token)


def test_drag_threshold_is_per_dpi_and_never_zero() -> None:
    for dpi in (96, 120, 144, 192):
        cx, cy = system.drag_threshold(dpi)
        assert cx >= 1
        assert cy >= 1
    assert system.drag_threshold(0) >= (1, 1)  # the floor, whatever Windows says for DPI 0


def test_drag_threshold_at_uses_a_real_dpi(monkeypatch: pytest.MonkeyPatch) -> None:
    assert system.dpi_at(0, 0) >= w.USER_DEFAULT_SCREEN_DPI
    assert system.drag_threshold_at(0, 0) >= (1, 1)
    desktop = int(w.user32.GetDesktopWindow())
    assert system.drag_threshold_for(desktop, 0, 0) == system.drag_threshold_at(0, 0)
    assert system.dpi_for(0, 0, 0) >= w.USER_DEFAULT_SCREEN_DPI  # no window: monitor or system

    # Fallback chain: no window and no monitor → the system DPI, never 0.
    monkeypatch.setattr(w, "window_at", lambda x, y: 0)
    monkeypatch.setattr(w.user32, "MonitorFromPoint", lambda pt, flags: 0)
    assert system.dpi_at(-1, -1) >= w.USER_DEFAULT_SCREEN_DPI
    monkeypatch.setattr(w.user32, "GetDpiForSystem", lambda: 0)
    assert system.dpi_at(-1, -1) == w.USER_DEFAULT_SCREEN_DPI


def test_primary_button_honors_swapped_buttons(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[int] = []
    monkeypatch.setattr(w, "key_down", lambda vk: asked.append(vk) or False)
    monkeypatch.setattr(system, "buttons_swapped", lambda: False)
    system.primary_button_down()
    monkeypatch.setattr(system, "buttons_swapped", lambda: True)
    system.primary_button_down()
    assert asked == [w.VK_LBUTTON, w.VK_RBUTTON]
    assert isinstance(system.buttons_swapped(), bool)


def test_accessibility_switches_are_bools_with_safe_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert isinstance(system.animations_enabled(), bool)
    assert isinstance(system.high_contrast(), bool)

    monkeypatch.setattr(w.user32, "SystemParametersInfoW", lambda *a: 0)  # the query fails
    assert system.animations_enabled() is True
    assert system.high_contrast() is False
