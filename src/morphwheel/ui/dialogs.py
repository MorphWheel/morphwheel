"""The dialogs (phase-3 §6.4; RD-22): the elevated warning, the Details window, the download
consent, and the one "bring a window back" helper.

Rules:

- **Modal only before the controller starts.** The elevated warning runs from ``startup_checks``,
  before any drag can reach the app, so it may block. Everything else here is a non-modal window
  with signals: a modal box would block every toast's buttons and make the wheel refuse drags.
- **A consent before any network use (A6).** The download box names the file, its size, the
  source (PyPI) and the licence (GPLv2) and answers through a signal; its keyboard default is
  Cancel, as phase-3 §6.5 sets for the plugin trust prompt (S6), so Return never starts a download
  the user hasn't read about.
- **One window, reused.** ``DetailsWindow`` and the consent box are built once and brought back.
- Slots are bound methods or signals (see ``toasts/manager.py``); no lambda captures ``self``.
- Plain text wherever a file name can appear. Every string goes through ``translate("Dialogs", …)``.
  This package imports no Win32 (P2): the app owns the restart and the download themselves.
"""

from __future__ import annotations

from typing import Literal

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QHBoxLayout,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from morphwheel.i18n import translate
from morphwheel.ui.toasts.model import human_size

ElevatedChoice = Literal["restart", "quit"]


# --------------------------------------------------------------------------- windows
def bring_to_front(window: QWidget) -> None:
    """Show a window, or bring the one that exists back: hidden, minimized or behind others."""
    if window.isMinimized():
        window.showNormal()
    else:
        window.show()
    window.raise_()
    window.activateWindow()


# --------------------------------------------------------------------------- elevated (§6.4)
def elevated_box() -> QMessageBox:
    """⚠ "Morphwheel is running as administrator": Restart normally (accept) or Quit (reject)."""
    box = QMessageBox(QMessageBox.Icon.Warning, "Morphwheel", "")
    box.setText(translate("Dialogs", "Morphwheel is running as administrator"))
    box.setInformativeText(
        translate("Dialogs", "Dragging from File Explorer won't work in this mode.")
    )
    restart = box.addButton(
        translate("Dialogs", "Restart normally"), QMessageBox.ButtonRole.AcceptRole
    )
    box.addButton(translate("Dialogs", "Quit"), QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(restart)
    return box


def ask_elevated() -> ElevatedChoice:
    """Modal, on purpose: it runs before the controller starts (``startup_checks``)."""
    box = elevated_box()
    box.exec()
    accepted = box.buttonRole(box.clickedButton()) == QMessageBox.ButtonRole.AcceptRole
    return "restart" if accepted else "quit"


def explain_failed_restart() -> None:
    """Only Quit remains (phase-3 §6.4): say why, modally, still before the controller starts."""
    QMessageBox.critical(
        None,
        "Morphwheel",
        translate(
            "Dialogs",
            "Couldn't start a normal instance. Please quit and start Morphwheel from the Start "
            "menu.",
        ),
    )


# --------------------------------------------------------------------------- details
class DetailsWindow(QWidget):
    """The full failure list behind a toast's Details button, or a tray alert: a plain window
    with a read-only, selectable text, Copy and Close. Esc hides it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle(translate("Dialogs", "Details"))
        self.setMinimumSize(520, 320)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)  # paths read better whole
        self.copy_button = QPushButton(translate("Dialogs", "Copy"))
        self.copy_button.clicked.connect(self._copy)
        self.close_button = QPushButton(translate("Dialogs", "Close"))
        self.close_button.clicked.connect(self.hide)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.close_button)
        column = QVBoxLayout(self)
        column.addWidget(self.text, 1)
        column.addLayout(buttons)

    def show_text(self, text: str) -> None:
        self.text.setPlainText(text)
        bring_to_front(self)

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.text.toPlainText())

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)


# --------------------------------------------------------------------------- the download consent
class HeicConsent(QObject):
    """ "Install HEIC support?": the file, the size, the source and the licence (A6), answered
    through ``confirmed``. Non-modal; Cancel is the keyboard default."""

    confirmed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.box: QMessageBox | None = None  # built at the first ask, then reused
        self.install_button: QAbstractButton | None = None

    @property
    def is_open(self) -> bool:
        return self.box is not None and self.box.isVisible()

    def ask(self, wheel_name: str, size: int) -> None:
        if self.box is None:
            box = QMessageBox(QMessageBox.Icon.Question, "Morphwheel", "")
            box.setWindowModality(Qt.WindowModality.NonModal)
            box.setText(translate("Dialogs", "Install HEIC support?"))
            box.setTextFormat(Qt.TextFormat.PlainText)
            cancel = box.addButton(
                translate("Dialogs", "Cancel"), QMessageBox.ButtonRole.RejectRole
            )
            self.install_button = box.addButton(
                translate("Dialogs", "Install"), QMessageBox.ButtonRole.AcceptRole
            )
            box.setDefaultButton(cancel)  # Return never starts a download unread (§6.5)
            box.setEscapeButton(cancel)
            box.buttonClicked.connect(self._on_clicked)
            self.box = box
        self.box.setInformativeText(
            translate(
                "Dialogs",
                "Morphwheel downloads %1 (%2) from PyPI and keeps it in your profile, for you "
                "only. pillow-heif is open source under the GPLv2; Morphwheel itself stays MIT.",
            )
            .replace("%1", wheel_name)
            .replace("%2", human_size(size))
        )
        bring_to_front(self.box)

    def _on_clicked(self, button: QAbstractButton) -> None:
        if button is self.install_button:
            self.confirmed.emit()
