"""The tray icon (phase-3 §6.1): four states, their tooltips, and the menu.

Rules:

- **States, by precedence:** an alert (a critical result the user hasn't looked at) over working
  over paused over normal. An alert must be seen; a paused app can still finish a job.
- **The icon is painted, not loaded:** a ``QIconEngine`` draws the wheel (a ring of eight arcs) at
  exactly the size the shell asks for, at any DPI, so no image-format plugin is needed. It is
  white on a dark taskbar and near-black on a light one; the taskbar's mode arrives as a callable
  (``platform.system.light_taskbar``: this package imports no Win32, P2) and is re-read on every
  refresh and on a colour-scheme change.
- **Working:** one bright arc walks around the ring, eight frames a second (phase-3 §8). With
  Windows' animations off (C7) there is no timer at all: a solid dot in the centre instead. The
  timer runs only while the effective state is working and the icon is shown.
- **Pause is a setting.** The menu's "Pause Morphwheel" asks (``pause_toggled``); the settings
  store answers through ``set_paused``, which checks the action without firing it again. The
  action's check state is the only pause state kept here.
- **Signals out, nothing done here:** settings, the log folder, about, quit and the alert's
  details are the app's to act on. ``Trigger`` (a left click, or Enter on a focused icon) shows
  the alerts if there are any, else asks for the settings. ``DoubleClick`` is ignored: on Windows
  it follows a ``Trigger`` that already acted.
- Every slot connected to a child object is a bound method or a signal, never a lambda that
  captures ``self`` (see ``toasts/manager.py``).
- ``show()`` is always called: Qt's Windows backend adds the icon again by itself when Explorer
  (re)starts, but only for an icon that was shown.
- Every string goes through ``translate("Tray", …)`` (D3a). The menu mirrors under RTL by itself.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from enum import StrEnum

from PySide6.QtCore import QObject, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QGuiApplication,
    QIcon,
    QIconEngine,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from morphwheel.i18n import translate
from morphwheel.settings.model import TriggerKey
from morphwheel.ui.text import trigger_key_label

log = logging.getLogger("morphwheel.ui.tray")

FRAMES = 8  # one bright arc per slot position (phase-3 §8)
FRAME_MS = 125
ALERT_COLOR = QColor("#C42B1C")  # phase-3 §7 critical, readable on both taskbars
INK_ON_DARK = QColor("#FFFFFF")
INK_ON_LIGHT = QColor("#1B1B1B")
DIM_ALPHA = 0.45


class TrayState(StrEnum):
    NORMAL = "normal"
    PAUSED = "paused"
    WORKING = "working"
    ALERT = "alert"


# --------------------------------------------------------------------------- the icon
def paint_wheel(
    painter: QPainter, rect: QRect, state: TrayState, *, frame: int, light: bool, motion: bool
) -> None:
    """Draw one state of the icon into ``rect`` (device pixels). Pure: no Qt objects kept."""
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    ink = INK_ON_LIGHT if light else INK_ON_DARK
    dim = QColor(ink)
    dim.setAlphaF(DIM_ALPHA)
    size = min(rect.width(), rect.height())
    stroke = max(1.5, size / 8)
    inset = stroke / 2 + size * 0.06
    ring = QRectF(rect).adjusted(inset, inset, -inset, -inset)
    busy = state is TrayState.WORKING
    base = dim if state in (TrayState.PAUSED, TrayState.WORKING) else ink
    painter.setPen(QPen(base, stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
    for i in range(FRAMES):  # eight arcs with small gaps: the wheel
        painter.drawArc(ring, int((90 - i * 45 - 19) * 16), 38 * 16)
    if busy and motion:
        painter.setPen(QPen(ink, stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        i = frame % FRAMES
        painter.drawArc(ring, int((90 - i * 45 - 19) * 16), 38 * 16)
    centre = QRectF(rect).center()
    if busy and not motion:  # a fixed dot (C7)
        r = size * 0.14
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ink)
        painter.drawEllipse(centre, r, r)
    if state is TrayState.PAUSED:  # ‖
        bar_w = max(1.0, size / 10)
        bar_h = size * 0.28
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ink)
        for dx in (-bar_w, bar_w * 0.5):
            painter.drawRect(
                QRectF(centre.x() + dx - bar_w * 0.25, centre.y() - bar_h / 2, bar_w, bar_h)
            )
    if state is TrayState.ALERT:  # a red badge in the bottom-right quarter
        r = size * 0.2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ALERT_COLOR)
        painter.drawEllipse(QRectF(rect.right() - 2 * r, rect.bottom() - 2 * r, 2 * r, 2 * r))


class _WheelIconEngine(QIconEngine):
    """Paints at whatever size the shell asks for (16, 20, 24, 32 px at any DPI)."""

    def __init__(self, state: TrayState, frame: int, light: bool, motion: bool) -> None:
        super().__init__()
        self._args = (state, frame, light, motion)

    def paint(self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State) -> None:
        kind, frame, light, motion = self._args
        paint_wheel(painter, rect, kind, frame=frame, light=light, motion=motion)

    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        self.paint(painter, QRect(0, 0, size.width(), size.height()), mode, state)
        painter.end()
        return pixmap

    def clone(self) -> QIconEngine:
        return _WheelIconEngine(*self._args)


def tray_icon(
    state: TrayState, *, frame: int = 0, light: bool = False, motion: bool = True
) -> QIcon:
    return QIcon(_WheelIconEngine(state, frame, light, motion))


# --------------------------------------------------------------------------- the tray
class TrayIcon(QObject):
    pause_toggled = Signal(bool)  # the user asked; the settings store answers via set_paused
    settings_requested = Signal()
    log_folder_requested = Signal()
    about_requested = Signal()
    quit_requested = Signal()
    alert_clicked = Signal(str)  # the alerts' details, joined; the alerts are cleared

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        motion_enabled: Callable[[], bool] = lambda: True,
        light_taskbar: Callable[[], bool] = lambda: False,
    ) -> None:
        super().__init__(parent)
        self._motion_enabled = motion_enabled
        self._light_taskbar = light_taskbar
        self._trigger_key: TriggerKey = "shift"
        self._working: tuple[int, int] | None = None
        self._alerts: list[str] = []
        self._frame = 0
        self._light = False  # the Windows switches, read at each refresh and scheme change
        self._motion = True
        self._painted: tuple[TrayState, int, bool, bool] | None = None  # what the icon shows

        self._menu = QMenu()  # kept: setContextMenu doesn't own it
        self._pause_action = QAction(translate("Tray", "Pause Morphwheel"), self._menu)
        self._pause_action.setCheckable(True)
        self._pause_action.triggered.connect(self.pause_toggled)  # user clicks only
        self._settings_action = QAction(translate("Tray", "Settings…"), self._menu)
        self._settings_action.triggered.connect(self.settings_requested)
        self._log_action = QAction(translate("Tray", "Open log folder"), self._menu)
        self._log_action.triggered.connect(self.log_folder_requested)
        self._about_action = QAction(translate("Tray", "About Morphwheel"), self._menu)
        self._about_action.triggered.connect(self.about_requested)
        self._quit_action = QAction(translate("Tray", "Quit"), self._menu)
        self._quit_action.triggered.connect(self.quit_requested)
        self._menu.addAction(self._pause_action)
        self._menu.addAction(self._settings_action)
        self._menu.addAction(self._log_action)
        self._menu.addSeparator()
        self._menu.addAction(self._about_action)
        self._menu.addAction(self._quit_action)

        self._icon = QSystemTrayIcon(self)
        self._icon.setContextMenu(self._menu)
        self._icon.activated.connect(self._on_activated)
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._refresh)
        self._refresh()

    # ----------------------------------------------------------------- read-backs
    @property
    def state(self) -> TrayState:
        if self._alerts:
            return TrayState.ALERT
        if self._working is not None:
            return TrayState.WORKING
        if self._pause_action.isChecked():
            return TrayState.PAUSED
        return TrayState.NORMAL

    @property
    def paused(self) -> bool:
        return self._pause_action.isChecked()

    @property
    def alerts(self) -> tuple[str, ...]:
        return tuple(self._alerts)

    @property
    def frame(self) -> int:
        return self._frame

    @property
    def animating(self) -> bool:
        return self._timer.isActive()

    @property
    def tooltip(self) -> str:
        return self._icon.toolTip()

    @property
    def visible(self) -> bool:
        return self._icon.isVisible()

    @property
    def menu(self) -> QMenu:
        return self._menu

    @property
    def actions(self) -> tuple[QAction, ...]:
        """Pause, Settings, Open log folder, About, Quit (the separator left out)."""
        return (
            self._pause_action,
            self._settings_action,
            self._log_action,
            self._about_action,
            self._quit_action,
        )

    # ----------------------------------------------------------------- lifecycle
    def show(self) -> None:
        self._icon.show()
        self._refresh()

    def hide(self) -> None:
        self._menu.hide()
        self._icon.hide()
        self._refresh()

    # ----------------------------------------------------------------- the owners' inputs
    def set_trigger_key(self, key: TriggerKey) -> None:
        self._trigger_key = key
        self._refresh()

    def set_paused(self, paused: bool) -> None:
        self._pause_action.setChecked(paused)  # setChecked never fires ``triggered``: no loop
        self._refresh()

    def set_working(self, done: int, total: int) -> None:
        self._working = (done, total)
        self._refresh()

    def clear_working(self) -> None:
        self._working = None
        self._refresh()

    def add_alert(self, text: str) -> None:
        self._alerts.append(text)
        self._refresh()

    def clear_alerts(self) -> None:
        self._alerts.clear()
        self._refresh()

    # ----------------------------------------------------------------- internals
    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason != QSystemTrayIcon.ActivationReason.Trigger:
            return  # Context: Qt shows the menu; DoubleClick: the Trigger before it acted
        if self._alerts:
            text = "\n\n".join(self._alerts)
            self.clear_alerts()
            self.alert_clicked.emit(text)
        else:
            self.settings_requested.emit()

    def _tick(self) -> None:
        self._frame = (self._frame + 1) % FRAMES
        self._repaint()

    def _refresh(self) -> None:
        """The one place that derives everything from the inputs: tooltip, timer, icon."""
        self._light = self._light_taskbar()  # a registry read: here, not on every tick
        self._motion = self._motion_enabled()
        state = self.state
        animate = state is TrayState.WORKING and self.visible and self._motion
        if animate and not self._timer.isActive():
            self._frame = 0
            self._timer.start()  # never restarted on a progress tick: the arc keeps walking
        elif not animate and self._timer.isActive():
            self._timer.stop()
        tip = self._tooltip_for(state)
        if tip != self._icon.toolTip():  # each set is a shell call
            self._icon.setToolTip(tip)
        self._repaint()

    def _repaint(self) -> None:
        """Hand the shell a new icon only when the picture changed (a progress tick changes the
        tooltip, not the picture)."""
        wanted = (self.state, self._frame, self._light, self._motion)
        if wanted == self._painted:
            return
        self._painted = wanted
        state, frame, light, motion = wanted
        self._icon.setIcon(tray_icon(state, frame=frame, light=light, motion=motion))

    def _tooltip_for(self, state: TrayState) -> str:
        if state is TrayState.ALERT:
            return translate("Tray", "%n problem(s) — click for details", None, len(self._alerts))
        if state is TrayState.WORKING:
            done, total = self._working or (0, 0)
            return (
                translate("Tray", "Converting %1 / %2…")
                .replace("%1", str(done))
                .replace("%2", str(total))
            )
        if state is TrayState.PAUSED:
            return translate("Tray", "Morphwheel — paused")
        key = trigger_key_label(self._trigger_key)
        return translate("Tray", "Morphwheel — %1-drag to convert").replace("%1", key)
