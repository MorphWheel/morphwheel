"""``ui.dialogs``: the elevated box (phase-3 §6.4), the Details window, the download consent (A6)
and the one bring-back helper."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from morphwheel.ui.dialogs import DetailsWindow, HeicConsent, bring_to_front, elevated_box

pytestmark = pytest.mark.usefixtures("qapp")


def test_the_elevated_box_offers_a_restart_and_a_quit(qtbot: QtBot) -> None:
    box = elevated_box()
    qtbot.addWidget(box)
    assert box.text() == "Morphwheel is running as administrator"
    assert box.informativeText() == "Dragging from File Explorer won't work in this mode."
    assert box.icon() == QMessageBox.Icon.Warning
    buttons = box.buttons()
    assert [b.text() for b in buttons] == ["Restart normally", "Quit"]
    assert box.buttonRole(buttons[0]) == QMessageBox.ButtonRole.AcceptRole
    assert box.buttonRole(buttons[1]) == QMessageBox.ButtonRole.RejectRole
    assert box.defaultButton() is buttons[0]  # Return restarts: the way out that keeps working
    assert box.isModal()  # on purpose: it runs before the controller starts


def test_the_details_window_shows_copies_and_hides(qtbot: QtBot) -> None:
    window = DetailsWindow()
    qtbot.addWidget(window)
    window.show_text("C:\\x\\scan.tiff — The file couldn't be read.\nC:\\x\\b.png — x")
    assert window.isVisible()
    assert window.windowTitle() == "Details"
    assert window.text.isReadOnly()
    assert window.text.toPlainText().startswith("C:\\x\\scan.tiff")
    assert not window.isModal()
    assert not (window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
    window.copy_button.click()
    assert QGuiApplication.clipboard().text().startswith("C:\\x\\scan.tiff")
    window.text.setFocus()
    QTest.keyClick(window.text, Qt.Key.Key_Escape)  # from inside the text too
    assert not window.isVisible()
    window.show_text("second")  # reused, with the new text
    assert window.isVisible()
    assert window.text.toPlainText() == "second"
    window.close_button.click()
    assert not window.isVisible()


def test_the_consent_names_the_download_and_defaults_to_cancel(qtbot: QtBot) -> None:
    consent = HeicConsent()
    confirmed: list[bool] = []
    consent.confirmed.connect(lambda: confirmed.append(True))
    assert not consent.is_open
    consent.ask("pillow_heif-1.8.1-cp312-cp312-win_amd64.whl", 6_604_108)
    assert consent.is_open
    box = consent.box
    assert box is not None
    qtbot.addWidget(box)
    assert box.text() == "Install HEIC support?"
    info = box.informativeText()
    assert "pillow_heif-1.8.1-cp312-cp312-win_amd64.whl" in info
    assert "6.3 MB" in info
    assert "PyPI" in info
    assert "GPLv2" in info
    assert not box.isModal()  # a modal box would block the toasts and the wheel
    assert box.windowModality() == Qt.WindowModality.NonModal
    by_text = {b.text(): b for b in box.buttons()}  # Qt orders buttons by role, not by call
    assert set(by_text) == {"Cancel", "Install"}
    assert box.defaultButton() is by_text["Cancel"]  # Return never starts a download unread
    assert box.escapeButton() is by_text["Cancel"]
    by_text["Cancel"].click()  # nothing
    assert confirmed == []
    assert not consent.is_open
    consent.ask("pillow_heif-1.8.1-cp312-cp312-win_amd64.whl", 6_604_108)  # the same box again
    assert consent.box is box
    assert consent.is_open
    by_text["Install"].click()
    assert confirmed == [True]
    assert not consent.is_open


def test_bring_to_front_shows_or_restores(qtbot: QtBot) -> None:
    window = DetailsWindow()
    qtbot.addWidget(window)
    bring_to_front(window)
    assert window.isVisible()
    window.hide()
    bring_to_front(window)
    assert window.isVisible()
    window.showMinimized()
    bring_to_front(window)
    assert window.isVisible()
    assert not window.isMinimized()
    window.hide()
