"""``platform.window_probe``: the allow/deny table, and the chain walk over real windows.

The chains in the table are the ones the spike and the S0 checklist logged (C4, C6). The walk is
checked against two windows this test creates itself, so no Explorer is needed.
"""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Iterator
from ctypes import wintypes as wt

import pytest

if sys.platform != "win32":  # pragma: no cover
    pytest.skip("Win32 only", allow_module_level=True)

from morphwheel.platform import _win32 as w
from morphwheel.platform.window_probe import (
    MAX_CHAIN,
    SourceInfo,
    class_chain,
    is_allowed_chain,
    source_info_at,
)

EXPLORER_ITEMS = (
    "DirectUIHWND",
    "SHELLDLL_DefView",
    "ShellTabWindowClass",
    "CabinetWClass",
)
DESKTOP_ICONS = ("SysListView32", "SHELLDLL_DefView", "Progman")
DESKTOP_ICONS_WORKERW = ("SysListView32", "SHELLDLL_DefView", "WorkerW")
NAV_PANE = ("NamespaceTreeControl", "ShellTabWindowClass", "CabinetWClass")
TITLE_BAR = ("TITLE_BAR_SCAFFOLDING_WINDOW_CLASS", "CabinetWClass")
COMMAND_BAR = (
    "Microsoft.UI.Content.DesktopChildSiteBridge",
    "ShellTabWindowClass",
    "CabinetWClass",
)
NOTEPAD = ("Edit", "Notepad")


@pytest.mark.parametrize(
    ("chain", "allowed"),
    [
        (EXPLORER_ITEMS, True),
        (DESKTOP_ICONS, True),
        (DESKTOP_ICONS_WORKERW, True),
        (NAV_PANE, True),
        (TITLE_BAR, False),
        (COMMAND_BAR, False),
        (NOTEPAD, False),
        ((), False),
        # A rejected class anywhere wins, even under an allowed one.
        (("TITLE_BAR_SCAFFOLDING_WINDOW_CLASS", "SHELLDLL_DefView", "Progman"), False),
        # Case matters: Windows class names are compared exactly.
        (("shelldll_defview", "Progman"), False),
    ],
)
def test_allow_deny_table(chain: tuple[str, ...], allowed: bool) -> None:
    assert is_allowed_chain(chain) is allowed


@pytest.fixture
def static_windows() -> Iterator[tuple[int, int]]:
    """A parent STATIC window with a STATIC child, destroyed after the test."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.CreateWindowExW.restype = wt.HWND
    user32.CreateWindowExW.argtypes = [
        wt.DWORD,
        wt.LPCWSTR,
        wt.LPCWSTR,
        wt.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wt.HWND,
        wt.HMENU,
        wt.HINSTANCE,
        wt.LPVOID,
    ]
    user32.DestroyWindow.restype = wt.BOOL
    user32.DestroyWindow.argtypes = [wt.HWND]
    ws_child = 0x40000000
    parent = user32.CreateWindowExW(0, "STATIC", "mw", 0, 0, 0, 10, 10, None, None, None, None)
    if not parent:
        pytest.skip("no window station to create windows in")
    child = user32.CreateWindowExW(
        0, "STATIC", "mw", ws_child, 0, 0, 5, 5, parent, None, None, None
    )
    assert child
    try:
        yield int(parent), int(child)
    finally:
        user32.DestroyWindow(parent)  # destroys the child too


def test_class_chain_walks_up_to_the_desktop(static_windows: tuple[int, int]) -> None:
    parent, child = static_windows
    assert class_chain(child) == ("Static", "Static")
    assert class_chain(parent) == ("Static",)
    assert class_chain(int(w.user32.GetDesktopWindow())) == ()
    assert class_chain(0) == ()
    assert MAX_CHAIN >= 8  # deep enough for Explorer, bounded against a loop


def test_source_info_shape_and_any_source() -> None:
    info = source_info_at(-32000, -32000)
    assert isinstance(info, SourceInfo)
    assert isinstance(info.chain, tuple)
    assert info.allowed is is_allowed_chain(info.chain)
    assert source_info_at(-32000, -32000, any_source=True).allowed is True


def test_source_info_for_a_known_window(
    monkeypatch: pytest.MonkeyPatch, static_windows: tuple[int, int]
) -> None:
    _, child = static_windows
    monkeypatch.setattr(w, "window_at", lambda x, y: child)
    info = source_info_at(1, 1)
    assert info.hwnd == child
    assert info.pid == w.window_pid(child) > 0
    assert info.chain == ("Static", "Static")
    assert info.allowed is False

    monkeypatch.setattr(w, "window_at", lambda x, y: 0)  # nothing under the point
    assert source_info_at(1, 1) == SourceInfo(hwnd=0, pid=0, chain=(), allowed=False)
