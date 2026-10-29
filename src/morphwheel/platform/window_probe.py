"""Which window a press landed on, and whether it is a drag source we serve (phase-2 §3.1). No Qt.

The sources in the MVP are File Explorer and the Desktop. Both draw their items in a
``SHELLDLL_DefView`` child (the Desktop's sits under ``Progman`` or a ``WorkerW``), and Explorer's
navigation pane is a ``NamespaceTreeControl``. A press on Explorer's title bar or tabs lands on the
WinUI scaffolding instead (spike test 6, checklist C6): those classes are rejected even when an
allowed class sits above them in the chain.

The decision is a pure function of the class chain, :func:`is_allowed_chain`, so it is unit-tested
as a table. The walk itself, :func:`class_chain`, is proven by the checklist rows C4 and C6.

This module never looks at our own windows: the controller compares ``SourceInfo.hwnd`` with the
wheel's handle, because the wheel is the one window of ours a press could land on during a drag.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from morphwheel.platform import _win32 as w

ALLOWED_CLASSES = frozenset({"SHELLDLL_DefView", "NamespaceTreeControl"})
REJECTED_CLASSES = frozenset(
    {
        "TITLE_BAR_SCAFFOLDING_WINDOW_CLASS",  # Explorer's title bar and tab strip
        "Microsoft.UI.Content.DesktopChildSiteBridge",  # Explorer's WinUI command bar
    }
)
MAX_CHAIN = 24  # a window nested deeper than this is not Explorer; stop rather than loop


@dataclass(frozen=True)
class SourceInfo:
    hwnd: int
    pid: int
    chain: tuple[str, ...]  # classes from the pressed window up to, not including, the desktop
    allowed: bool


def is_allowed_chain(chain: Iterable[str]) -> bool:
    """The allow/deny rule over a class chain, innermost first. Rejected classes win."""
    classes = set(chain)
    if classes & REJECTED_CLASSES:
        return False
    return bool(classes & ALLOWED_CLASSES)


def class_chain(hwnd: int) -> tuple[str, ...]:
    """Window classes from ``hwnd`` up through its parents, stopping at the desktop."""
    desktop = int(w.user32.GetDesktopWindow() or 0)
    chain: list[str] = []
    current = hwnd
    while current and current != desktop and len(chain) < MAX_CHAIN:
        chain.append(w.class_name(current))
        current = int(w.user32.GetAncestor(current, w.GA_PARENT) or 0)
    return tuple(chain)


def source_info_at(x: int, y: int, *, any_source: bool = False) -> SourceInfo:
    """Describe the window under a physical point. ``any_source`` allows every window."""
    hwnd = w.window_at(x, y)
    chain = class_chain(hwnd) if hwnd else ()
    return SourceInfo(
        hwnd=hwnd,
        pid=w.window_pid(hwnd) if hwnd else 0,
        chain=chain,
        allowed=any_source or is_allowed_chain(chain),
    )
