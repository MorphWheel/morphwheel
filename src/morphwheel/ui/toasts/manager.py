"""``ToastManager``: shows ``ToastModel``s as small frameless windows (phase-3 §5, U6). S3 minimum.

Rules (phase-3 §5):

- Bottom-right of the screen where the drop happened, above the taskbar (the screen's *available*
  geometry), stacked upward, at most ``MAX_VISIBLE`` at a time; the oldest non-sticky toast makes
  room.
- No focus, no activation: a toast never steals the keyboard. A click dismisses it (S5 adds the
  real ✕ and the buttons).
- Hover pauses the countdown; leaving resumes it with the time that was left.
- A toast shown with a ``key`` replaces the toast that carries the same key: the working toast of a
  job gives way to its result.
- Layout direction follows the application (RTL-ready, D3a): the labels use leading alignment.
- The labels are plain text: a file name that looks like markup is shown as is, never rendered.
- Nothing here runs during a drag: the wheel is the only window shown then (phase-3 C1). Toasts
  appear when a job finishes, after the wheel has hidden.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QEnterEvent, QFont, QGuiApplication, QMouseEvent, QScreen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from morphwheel.ui.toasts.model import ToastKind, ToastModel

log = logging.getLogger("morphwheel.ui.toasts")

MAX_VISIBLE = 3
MARGIN = 16  # logical px from the work-area edge
GAP = 8
WIDTH = 360

_FLAGS = (
    Qt.WindowType.Tool
    | Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.WindowStaysOnTopHint
    | Qt.WindowType.WindowDoesNotAcceptFocus
)
_ACCENT = {
    ToastKind.WORKING: "#5a8dee",
    ToastKind.SUCCESS: "#3fae5a",
    ToastKind.INFO: "#6c7a89",
    ToastKind.WARNING: "#e0a526",
    ToastKind.ERROR: "#d9534f",
    ToastKind.CRITICAL: "#b3261e",
}
_GLYPH = {
    ToastKind.WORKING: "◌",
    ToastKind.SUCCESS: "✓",
    ToastKind.INFO: "✓",
    ToastKind.WARNING: "!",
    ToastKind.ERROR: "✕",
    ToastKind.CRITICAL: "⚠",
}


class ToastWidget(QWidget):
    dismissed = Signal(object)  # self

    def __init__(self, model: ToastModel) -> None:
        super().__init__(None, _FLAGS)
        self.model = model
        self.key: str | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setFixedWidth(WIDTH)
        self.setStyleSheet(
            "QWidget { background: #202024; border: 1px solid #3a3a40; border-left: 4px solid "
            f"{_ACCENT[model.kind]}; border-radius: 6px; }}"
            " QLabel { color: #ececec; background: transparent; border: none; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)
        self._title = QLabel(f"{_GLYPH[model.kind]}  {model.title}")
        self._title.setTextFormat(Qt.TextFormat.PlainText)  # file names are never markup
        self._title.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        self._title.setWordWrap(True)
        self._title.setAlignment(Qt.AlignmentFlag.AlignLeading | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._title)
        self._body = QLabel(model.body)
        self._body.setTextFormat(Qt.TextFormat.PlainText)
        self._body.setFont(QFont("Segoe UI", 9))
        self._body.setWordWrap(True)
        self._body.setAlignment(Qt.AlignmentFlag.AlignLeading | Qt.AlignmentFlag.AlignVCenter)
        self._body.setVisible(bool(model.body))
        self._body.setStyleSheet("color: #c4c4c8;")
        layout.addWidget(self._body)
        self.adjustSize()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self._remaining_ms = model.duration_ms

    # ----------------------------------------------------------------- content
    def update_model(self, model: ToastModel) -> None:
        """Replace the text in place (a working toast's progress). The manager re-lays out."""
        self.model = model
        self._title.setText(f"{_GLYPH[model.kind]}  {model.title}")
        self._body.setText(model.body)
        self._body.setVisible(bool(model.body))

    # ----------------------------------------------------------------- timing
    def start_countdown(self) -> None:
        if self._remaining_ms > 0:
            self._timer.start(self._remaining_ms)

    @property
    def counting_down(self) -> bool:
        return self._timer.isActive()

    def enterEvent(self, event: QEnterEvent) -> None:  # hover pauses
        if self._timer.isActive():
            self._remaining_ms = max(1000, self._timer.remainingTime())
            self._timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self.start_countdown()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self.dismiss()

    def dismiss(self) -> None:
        self._timer.stop()
        self.hide()
        self.dismissed.emit(self)


class ToastManager(QObject):
    def __init__(
        self,
        parent: QObject | None = None,
        *,
        screen_for: Callable[[], QScreen | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._visible: list[ToastWidget] = []
        self._screen_for = screen_for or QGuiApplication.primaryScreen

    @property
    def visible(self) -> tuple[ToastWidget, ...]:
        return tuple(self._visible)

    def show(
        self, model: ToastModel, *, screen: QScreen | None = None, key: str | None = None
    ) -> ToastWidget:
        """Show a toast. With ``key``, replace the toast that has the same key."""
        existing = next((t for t in self._visible if key is not None and t.key == key), None)
        if existing is not None and existing.model.kind is model.kind is ToastKind.WORKING:
            existing.update_model(model)
            self._relayout(screen)
            return existing
        if existing is not None:
            self._remove(existing)
        while len(self._visible) >= MAX_VISIBLE:
            victim = next((t for t in self._visible if not t.model.sticky), self._visible[0])
            self._remove(victim)
        toast = ToastWidget(model)
        toast.key = key
        toast.dismissed.connect(self._on_dismissed)
        self._visible.append(toast)
        self._relayout(screen)
        toast.show()
        toast.start_countdown()
        log.debug("toast: %s %r", model.kind.value, model.title)
        return toast

    def dismiss_all(self) -> None:
        for toast in list(self._visible):
            toast.dismiss()

    # ----------------------------------------------------------------- internals
    def _on_dismissed(self, toast: object) -> None:
        if isinstance(toast, ToastWidget) and toast in self._visible:
            self._visible.remove(toast)
            toast.deleteLater()
            self._relayout(None)

    def _remove(self, toast: ToastWidget) -> None:
        toast.dismissed.disconnect(self._on_dismissed)
        self._visible.remove(toast)
        toast.hide()
        toast.deleteLater()

    def _relayout(self, screen: QScreen | None) -> None:
        screen = screen or self._screen_for()
        if screen is None:
            return
        area = screen.availableGeometry()
        bottom = area.bottom() - MARGIN
        right = area.right() - MARGIN
        for toast in reversed(self._visible):  # newest at the bottom
            toast.adjustSize()
            toast.move(QPoint(right - toast.width(), bottom - toast.height()))
            bottom -= toast.height() + GAP
