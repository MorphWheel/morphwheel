"""The rule that keeps source files safe: never accept a drop as Move.

In File Explorer, Shift+drag means Move. Qt follows that and proposes ``MoveAction`` whenever
Shift is held and the source allows Move. If a drop target accepts that, Qt reports
DROPEFFECT_MOVE back to Explorer, and Explorer then **deletes the source file** (an "unoptimized
move").

- Rationale: phase-1 §3.3.
- Spike result: a plain ``accept()`` under Shift returned MoveAction.
- Prior incident: Avidemux commit ac6f21c.

Every drag event the wheel handles (DragEnter, DragMove and Drop) goes through :func:`force_copy` or
:func:`reject`. ``acceptProposedAction()`` and a bare ``accept()`` are never used.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QDropEvent

# In order of preference. Move is deliberately absent.
SAFE_ACTIONS: tuple[Qt.DropAction, ...] = (Qt.DropAction.CopyAction, Qt.DropAction.LinkAction)


class UnsafeDropError(RuntimeError):
    """A drop was about to be accepted with an action that could delete the source."""


def force_copy(event: QDropEvent) -> Qt.DropAction | None:
    """Accept ``event`` as Copy, or as Link if the source offers no Copy. Otherwise ignore it.

    Works for QDragEnterEvent, QDragMoveEvent and QDropEvent, because all three are QDropEvents.
    Returns the accepted action, or ``None`` if the event was ignored.
    """
    possible = event.possibleActions()
    for action in SAFE_ACTIONS:
        if possible & action:
            event.setDropAction(action)
            event.accept()
            return action
    reject(event)
    return None


def reject(event: QDropEvent) -> None:
    """Refuse the event. Used for the hub, gaps, the halo, and unsupported drags.

    Over a rejected area, the drag shows "no drop", and releasing the button cancels: Explorer does
    nothing.
    """
    event.setDropAction(Qt.DropAction.IgnoreAction)
    event.ignore()


def assert_safe(event: QDropEvent) -> None:
    """Final check before an accepted drop is handed to the engine.

    Raises :class:`UnsafeDropError` if the event is accepted with an action other than Copy or Link.
    """
    if event.isAccepted() and event.dropAction() not in SAFE_ACTIONS:
        raise UnsafeDropError(
            f"drop accepted as {event.dropAction()!r}; only Copy/Link are allowed"
        )
