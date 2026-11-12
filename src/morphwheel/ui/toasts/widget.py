"""``ToastWidget``: one toast, drawn with the theme's tokens (phase-3 §5, §7, §8; U6).

Rules:

- **Never a focus change.** The window has ``WindowDoesNotAcceptFocus`` (``WS_EX_NOACTIVATE``: a
  click never activates it) and ``WA_ShowWithoutActivating``; every button has ``NoFocus``. The
  user keeps typing in Explorer while the buttons stay clickable (M2 check 7).
- **Our own surface.** The window is frameless and translucent, and ``paintEvent`` draws the
  rounded surface, its border and a 4 px stripe on the leading edge in the kind's color. In High
  Contrast (C7) the surface is the system ``Window`` color with a 2 px border, no transparency.
  ``WA_TranslucentBackground`` is set before the first ``show``, which is why a toast is built
  from a fresh theme and never re-themed.
- **Motion (§8):** it appears rising 12 px while fading in over 250 ms and leaves fading out over
  167 ms; with animations off both take 0 ms. The fade uses ``windowOpacity``: a toast is not a
  drop target, so the wheel's alpha-floor rule (C3) doesn't apply here. The animations are
  attributes with the widget as parent, so a fade can't be garbage-collected halfway and leave a
  ghost toast. ``hide()`` runs at the end of every dismiss.
- **The manager owns the position.** ``place`` sets the final spot; the rise is a scalar offset
  applied on each frame, so a relayout during the rise lands where the manager said.
- **Plain text only.** A file name that looks like markup is shown as is.
- **No tooltips.** Toasts never show a second window (C1 spirit); the ✕ has an accessible name.
- Leading alignment and ``QLayout``s throughout, so the layout mirrors under RTL (D3a).
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QEvent, QPoint, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QEnterEvent, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from morphwheel.ui.theme import EASING, FAST_MS, NORMAL_MS, Motion, Palette, Theme
from morphwheel.ui.toasts.model import ToastAction, ToastKind, ToastModel

log = logging.getLogger("morphwheel.ui.toasts")

WIDTH = 360  # logical px
RADIUS = 8.0
STRIPE = 4  # the accent stripe on the leading edge
RISE_PX = 12
PADDING = (14, 10, 14, 10)  # inside the stripe
BAR_HEIGHT = 4
MIN_PAUSE_MS = 1_000  # the time left after a hover never drops under this

_RUNNING = QVariantAnimation.State.Running
_FLAGS = (
    Qt.WindowType.Tool
    | Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.WindowStaysOnTopHint
    | Qt.WindowType.WindowDoesNotAcceptFocus
)
_GLYPH = {
    ToastKind.WORKING: "◌",
    ToastKind.SUCCESS: "✓",
    ToastKind.INFO: "✓",
    ToastKind.WARNING: "!",
    ToastKind.ERROR: "✕",
    ToastKind.CRITICAL: "⚠",
    ToastKind.HINT: "◎",  # the wheel itself is speaking
}


def _hex(color: QColor) -> str:
    return color.name(QColor.NameFormat.HexArgb)


_STRIPE_ROLE = {  # phase-3 §7: success, caution, critical; the accent while working
    ToastKind.WORKING: "accent",
    ToastKind.SUCCESS: "success",
    ToastKind.INFO: "text_secondary",
    ToastKind.WARNING: "caution",
    ToastKind.ERROR: "critical",
    ToastKind.CRITICAL: "critical",
    ToastKind.HINT: "accent",
}


def stripe_color(kind: ToastKind, palette: Palette) -> QColor:
    """The kind's color role, from the palette."""
    color: QColor = getattr(palette, _STRIPE_ROLE[kind])
    return color


class ToastWidget(QWidget):
    dismissed = Signal(object)  # self, after hide()
    action_clicked = Signal(object)  # ToastAction; once per toast, then the toast is dismissed

    def __init__(self, model: ToastModel, theme: Theme, motion: Motion) -> None:
        super().__init__(None, _FLAGS)
        self.model = model
        self.key: str | None = None
        self.theme = theme
        self._motion = motion
        self._final = QPoint()
        self._dismissing = False
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        if not theme.high_contrast:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(WIDTH)
        self._build(theme)
        self.update_model(model)
        self.adjustSize()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self._remaining_ms = model.duration_ms

        self._rise = QVariantAnimation(self)  # 1 → 0: the fraction of the rise still to go
        self._rise.setStartValue(1.0)
        self._rise.setEndValue(0.0)
        self._rise.setEasingCurve(EASING)
        self._rise.valueChanged.connect(self._on_rise)
        self._fade = QVariantAnimation(self)  # 1 → 0: the opacity while leaving
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.setEasingCurve(EASING)
        self._fade.valueChanged.connect(self._on_fade)
        self._fade.finished.connect(self._finish)

    # ----------------------------------------------------------------- building
    def _build(self, theme: Theme) -> None:
        p = theme.palette
        fonts = theme.fonts
        self._stripe = stripe_color(self.model.kind, p)
        self._surface = p.critical_bg if self.model.kind is ToastKind.CRITICAL else p.surface
        border_px = int(theme.border_width)
        text, secondary = _hex(p.text), _hex(p.text_secondary)
        accent, on_accent, outline = _hex(p.accent), _hex(p.text_on_accent), _hex(p.outline_surface)
        self.setStyleSheet(
            f"QLabel {{ color: {text}; background: transparent; }}"
            f" QLabel#body {{ color: {secondary}; }}"
            " QToolButton { background: transparent; border: none; padding: 0;"
            f" color: {secondary}; }}"
            f" QToolButton:hover {{ color: {text}; }}"
            f" QPushButton {{ color: {text}; background: transparent;"
            f" border: {border_px}px solid {outline}; border-radius: 4px; padding: 3px 10px; }}"
            f" QPushButton:hover {{ background: {accent}; color: {on_accent};"
            f" border-color: {accent}; }}"
        )
        left, top, right, bottom = PADDING
        outer = QVBoxLayout(self)
        outer.setContentsMargins(left + STRIPE, top, right, bottom)
        outer.setSpacing(4)

        # A QLabel aligns "leading" by its own text's script, so a Latin file name would sit
        # left under a right-to-left title (D3a): the edge is the layout's, absolutely.
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        lead = (
            (Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft)
            | Qt.AlignmentFlag.AlignAbsolute
            | Qt.AlignmentFlag.AlignTop
        )
        header = QHBoxLayout()
        header.setSpacing(8)
        self._glyph = QLabel(_GLYPH[self.model.kind])
        self._glyph.setFont(fonts.toast_title)
        self._glyph.setAlignment(lead)
        self._glyph.setStyleSheet(f"color: {_hex(self._stripe)};")
        header.addWidget(self._glyph, 0)
        self._title = QLabel()
        self._title.setTextFormat(Qt.TextFormat.PlainText)  # file names are never markup
        self._title.setFont(fonts.toast_title)
        self._title.setWordWrap(True)
        self._title.setAlignment(lead)
        header.addWidget(self._title, 1)
        self.close_button = QToolButton()
        self.close_button.setText("✕")
        self.close_button.setAccessibleName(self.tr("Dismiss"))
        self.close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_button.setAutoRaise(True)
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.clicked.connect(self.dismiss)
        header.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(header)
        indent = self._glyph.sizeHint().width() + header.spacing()  # body under the title

        self._body = QLabel()
        self._body.setObjectName("body")
        self._body.setTextFormat(Qt.TextFormat.PlainText)
        self._body.setFont(fonts.toast_body)
        self._body.setWordWrap(True)
        self._body.setAlignment(lead)
        self._body.setContentsMargins(0 if rtl else indent, 0, indent if rtl else 0, 0)
        outer.addWidget(self._body)

        self.bar = _Bar(self._stripe, p.outline, p.text if theme.high_contrast else None)
        self.bar.setContentsMargins(0 if rtl else indent, 2, indent if rtl else 0, 2)
        outer.addWidget(self.bar)

        self.buttons: list[_ActionButton] = []
        if self.model.actions:
            row = QHBoxLayout()
            row.setSpacing(8)
            row.setContentsMargins(indent, 4, 0, 0)
            for action in self.model.actions:
                button = _ActionButton(action)
                button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.setFont(fonts.toast_body)
                button.clicked.connect(self._on_button)  # bound, no lambda: see ``manager.py``
                row.addWidget(button, 0)
                self.buttons.append(button)
            row.addStretch(1)
            outer.addLayout(row)

    # ----------------------------------------------------------------- content
    def update_model(self, model: ToastModel) -> None:
        """Replace the text in place (a working toast's progress). The manager re-lays out."""
        self.model = model
        self._title.setText(model.title)
        self._body.setText(model.body)
        self._body.setVisible(bool(model.body))
        progress = model.progress
        self.bar.setVisible(progress is not None and self._motion.enabled)  # §8: text when off
        if progress is not None:
            self.bar.set_progress(progress.done, progress.total)

    def _on_button(self) -> None:
        button = self.sender()
        if not isinstance(button, _ActionButton) or self._dismissing:
            return  # a second click during the fade would act twice (Undo: "Not undone")
        log.debug("toast action: %s", button.action.kind.value)
        self.action_clicked.emit(button.action)
        self.dismiss()

    # ----------------------------------------------------------------- placing and motion
    def place(self, final: QPoint) -> None:
        """The manager's spot for this toast. During the rise the offset is still applied."""
        self._final = QPoint(final)
        self._apply_rise(self._rise.currentValue() if self._rise.state() == _RUNNING else 0.0)

    def appear(self) -> None:
        """Show at the final spot, rising and fading in (0 ms when animations are off)."""
        ms = self._motion.ms(NORMAL_MS)
        self._apply_rise(1.0 if ms else 0.0)
        self.show()
        if ms:
            self._rise.setDuration(ms)
            self._rise.start()

    def _on_rise(self, value: object) -> None:
        self._apply_rise(float(value))  # type: ignore[arg-type]

    def _apply_rise(self, fraction: float) -> None:
        self.move(self._final + QPoint(0, round(RISE_PX * fraction)))
        if not self._dismissing:
            self.setWindowOpacity(1.0 - fraction)

    @property
    def settled(self) -> bool:
        return self._rise.state() != _RUNNING and self._fade.state() != _RUNNING

    def settle(self) -> None:
        """Jump to the end of any running animation (for tests; ``place`` needs no settling)."""
        for animation in (self._rise, self._fade):
            if animation.state() == _RUNNING:
                animation.setCurrentTime(animation.duration())  # emits the end value

    # ----------------------------------------------------------------- timing
    def start_countdown(self) -> None:
        if self._remaining_ms > 0 and not self._dismissing:
            self._timer.start(self._remaining_ms)

    @property
    def counting_down(self) -> bool:
        return self._timer.isActive()

    def enterEvent(self, event: QEnterEvent) -> None:  # hover pauses
        if self._timer.isActive():
            self._remaining_ms = max(MIN_PAUSE_MS, self._timer.remainingTime())
            self._timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self.start_countdown()
        super().leaveEvent(event)

    # ----------------------------------------------------------------- leaving
    @property
    def dismissing(self) -> bool:
        return self._dismissing

    def dismiss(self) -> None:
        """Fade out, then ``hide()`` and ``dismissed``. A second call is a no-op."""
        if self._dismissing:
            return
        self._stop_motion()
        for button in self.buttons:
            button.setEnabled(False)
        ms = self._motion.ms(FAST_MS)
        if ms == 0:
            self._finish()
            return
        self._fade.setDuration(ms)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.start()

    def drop(self) -> None:
        """Hide at once, with no fade and no signal (the manager removes it itself)."""
        self._stop_motion()
        self._fade.stop()
        self.hide()

    def _stop_motion(self) -> None:
        self._dismissing = True
        self._timer.stop()
        self._rise.stop()

    def _on_fade(self, value: object) -> None:
        self.setWindowOpacity(float(value))  # type: ignore[arg-type]

    def _finish(self) -> None:
        self.hide()
        self.dismissed.emit(self)

    # ----------------------------------------------------------------- painting
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self.theme.border_width
        inset = width / 2
        rect = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        path = QPainterPath()
        if self.theme.high_contrast:
            path.addRect(rect)  # opaque window: no transparent corners to show
        else:
            path.addRoundedRect(rect, RADIUS, RADIUS)
        painter.fillPath(path, self._surface)
        painter.save()
        painter.setClipPath(path)
        stripe = QRectF(self.rect())
        if self.layoutDirection() == Qt.LayoutDirection.RightToLeft:
            stripe.setLeft(stripe.right() - STRIPE)
        else:
            stripe.setRight(STRIPE)
        painter.fillRect(stripe, self._stripe)
        painter.restore()
        painter.setPen(QPen(self.theme.palette.outline_surface, width))
        painter.drawPath(path)
        painter.end()


class _ActionButton(QPushButton):
    def __init__(self, action: ToastAction) -> None:
        super().__init__(action.label)
        self.action = action


class _Bar(QWidget):
    """The batch progress bar (phase-3 §8): a track with a fill, no shimmer, no animation."""

    def __init__(self, fill: QColor, track: QColor, outline: QColor | None) -> None:
        super().__init__()
        self._fill = fill
        self._track = track
        self._outline = outline  # High Contrast: a visible edge instead of a faint track
        self._done = 0
        self._total = 1
        self.setFixedHeight(BAR_HEIGHT + 4)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    @property
    def progress(self) -> tuple[int, int]:
        return self._done, self._total

    def set_progress(self, done: int, total: int) -> None:
        self._done, self._total = done, max(total, 1)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = self.contentsRect()
        track = QRectF(area.x(), area.center().y() - BAR_HEIGHT / 2, area.width(), BAR_HEIGHT)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._track)
        painter.drawRoundedRect(track, BAR_HEIGHT / 2, BAR_HEIGHT / 2)
        fill = QRectF(track)
        if self.layoutDirection() == Qt.LayoutDirection.RightToLeft:
            fill.setLeft(track.right() - track.width() * self._done / self._total)
        else:
            fill.setWidth(track.width() * self._done / self._total)
        painter.setBrush(self._fill)
        painter.drawRoundedRect(fill, BAR_HEIGHT / 2, BAR_HEIGHT / 2)
        if self._outline is not None:
            painter.setPen(QPen(self._outline, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(track, BAR_HEIGHT / 2, BAR_HEIGHT / 2)
        painter.end()
