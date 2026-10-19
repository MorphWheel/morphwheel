"""Safety matrix for ``force_copy``: no combination of offered actions and modifiers may yield Move.

Traceability: phase-4 §6, row "force_copy, never Move".
"""

from __future__ import annotations

import itertools
from collections.abc import Callable

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent

from morphwheel.ui.wheel.drop_guard import (
    SAFE_ACTIONS,
    UnsafeDropError,
    assert_safe,
    force_copy,
    reject,
)

pytestmark = pytest.mark.usefixtures("qapp")

A = Qt.DropAction
M = Qt.KeyboardModifier

OFFERS: dict[str, Qt.DropAction] = {
    "copy|move|link": A.CopyAction | A.MoveAction | A.LinkAction,  # File Explorer
    "copy|move": A.CopyAction | A.MoveAction,
    "copy|link": A.CopyAction | A.LinkAction,
    "move|link": A.MoveAction | A.LinkAction,
    "copy": A.CopyAction,
    "move": A.MoveAction,
    "link": A.LinkAction,
}
MODIFIERS: dict[str, Qt.KeyboardModifier] = {
    "none": M.NoModifier,
    "shift": M.ShiftModifier,
    "ctrl": M.ControlModifier,
    "ctrl+shift": M.ControlModifier | M.ShiftModifier,
    "alt": M.AltModifier,
    "shift+alt": M.ShiftModifier | M.AltModifier,
}

EventFactory = Callable[[Qt.DropAction, Qt.KeyboardModifier, QMimeData], QDropEvent]


def _drop(offer: Qt.DropAction, mods: Qt.KeyboardModifier, mime: QMimeData) -> QDropEvent:
    return QDropEvent(QPointF(10, 10), offer, mime, Qt.MouseButton.LeftButton, mods)


def _enter(offer: Qt.DropAction, mods: Qt.KeyboardModifier, mime: QMimeData) -> QDropEvent:
    return QDragEnterEvent(QPointF(10, 10), offer, mime, Qt.MouseButton.LeftButton, mods)


def _move(offer: Qt.DropAction, mods: Qt.KeyboardModifier, mime: QMimeData) -> QDropEvent:
    return QDragMoveEvent(QPointF(10, 10), offer, mime, Qt.MouseButton.LeftButton, mods)


FACTORIES: dict[str, EventFactory] = {"enter": _enter, "move": _move, "drop": _drop}


@pytest.fixture
def mime() -> QMimeData:
    data = QMimeData()
    data.setUrls([QUrl.fromLocalFile(r"C:\fixtures\photo.png")])
    return data


def _expected(offer: Qt.DropAction) -> Qt.DropAction | None:
    for action in SAFE_ACTIONS:
        if offer & action:
            return action
    return None


@pytest.mark.parametrize(
    ("kind", "offer_name", "mods_name"),
    list(itertools.product(FACTORIES, OFFERS, MODIFIERS)),
)
def test_force_copy_never_accepts_move(
    kind: str, offer_name: str, mods_name: str, mime: QMimeData
) -> None:
    event = FACTORIES[kind](OFFERS[offer_name], MODIFIERS[mods_name], mime)

    result = force_copy(event)

    expected = _expected(OFFERS[offer_name])
    assert result == expected
    if expected is None:
        assert not event.isAccepted()
    else:
        assert event.isAccepted()
        assert event.dropAction() == expected
    assert event.dropAction() != A.MoveAction or not event.isAccepted()
    assert_safe(event)  # must not raise


def test_hazard_qt_proposes_move_under_shift(mime: QMimeData) -> None:
    """Documents why the guard exists.

    If Qt ever stops proposing Move here, revisit phase-1 §3.3.
    """
    event = _drop(OFFERS["copy|move|link"], M.ShiftModifier, mime)

    assert event.proposedAction() == A.MoveAction
    event.accept()  # what a naive drop handler does
    assert event.dropAction() == A.MoveAction  # this would make Explorer delete the source


def test_assert_safe_rejects_an_accepted_move(mime: QMimeData) -> None:
    event = _drop(OFFERS["copy|move|link"], M.ShiftModifier, mime)
    event.accept()

    with pytest.raises(UnsafeDropError):
        assert_safe(event)


def test_reject_ignores_the_event(mime: QMimeData) -> None:
    event = _drop(OFFERS["copy|move|link"], M.ShiftModifier, mime)
    event.accept()

    reject(event)

    assert not event.isAccepted()
    assert event.dropAction() == A.IgnoreAction
    assert_safe(event)  # an ignored event is safe
