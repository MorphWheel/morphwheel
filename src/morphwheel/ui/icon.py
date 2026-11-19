"""The app icon: the tray's wheel on its own disc (S7; phase-3 §7 colours).

One geometry for three outputs: ``app_icon()`` paints it at any size for the windows' title bars
and the taskbar (a ``QIconEngine``, so no image-format plugin is needed, as the tray does);
``tools/make_icon.py`` renders the same painter into ``assets/icon/morphwheel.ico`` for the
executables and the installer, and writes the SVG master from the same constants.

The mark: eight arcs (the wheel's eight slots) in white on the wheel's dark base disc, and the
accent as a dot in the hub. Fixed colours, unlike the tray: an icon can't follow the system.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QIconEngine, QPainter, QPen, QPixmap

DISC = "#202020"  # phase-3 §7: the dark base
INK = "#FFFFFF"
ACCENT = "#4CC2FF"  # phase-3 §7: the accent on this machine, fixed for the mark
ARCS = 8
ARC_GAP_DEG = 7.0  # as the tray draws them: 45° steps, 7° gaps (at large sizes)
ARC_SPAN_DEG = 45 - ARC_GAP_DEG
MIN_GAP_PX = 1.5  # at small sizes the gap grows so eight slots stay eight
FULL_BLEED_UP_TO = 32  # the disc fills the frame at taskbar sizes, as Fluent lets round marks
DISC_RADIUS = 0.48  # of the canvas size: a hair of air around the disc
RING_RADIUS = 0.31  # the arcs' centre line
STROKE = 0.115  # the arcs' width
HUB_RADIUS = 0.085


@dataclass(frozen=True)
class Arc:
    """One arc as ``(start_deg, span_deg)`` in Qt's sense: counter-clockwise from 3 o'clock."""

    start_deg: float
    span_deg: float = ARC_SPAN_DEG


def arcs(gap_deg: float = ARC_GAP_DEG) -> tuple[Arc, ...]:
    """The eight arcs, the first centred on 12 o'clock, then clockwise (the tray's order)."""
    span = 45 - gap_deg
    return tuple(Arc(90 - i * 45 - span / 2, span) for i in range(ARCS))


def gap_for(size: int) -> float:
    """The gap in degrees at ``size``: 7°, or what ``MIN_GAP_PX`` needs on a small ring."""
    ring_px = size * RING_RADIUS
    return max(ARC_GAP_DEG, math.degrees(MIN_GAP_PX / ring_px))


def disc_radius_for(size: int) -> float:
    return size / 2 if size <= FULL_BLEED_UP_TO else size * DISC_RADIUS


def paint_app_icon(painter: QPainter, rect: QRect) -> None:
    """Draw the mark into ``rect`` (device pixels). Pure: no Qt objects kept."""
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    size = min(rect.width(), rect.height())
    centre = QRectF(rect).center()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(DISC))
    disc = disc_radius_for(size)
    painter.drawEllipse(centre, disc, disc)
    ring = QRectF(
        centre.x() - size * RING_RADIUS,
        centre.y() - size * RING_RADIUS,
        2 * size * RING_RADIUS,
        2 * size * RING_RADIUS,
    )
    stroke = max(1.5, size * STROKE)
    painter.setPen(QPen(QColor(INK), stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for arc in arcs(gap_for(size)):
        painter.drawArc(ring, int(arc.start_deg * 16), int(arc.span_deg * 16))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(ACCENT))
    hub = max(1.0, size * HUB_RADIUS)
    painter.drawEllipse(QPointF(centre), hub, hub)


class _AppIconEngine(QIconEngine):
    def paint(self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State) -> None:
        paint_app_icon(painter, rect)

    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        self.paint(painter, QRect(0, 0, size.width(), size.height()), mode, state)
        painter.end()
        return pixmap

    def clone(self) -> QIconEngine:
        return _AppIconEngine()


def app_icon() -> QIcon:
    """The icon for ``QApplication.setWindowIcon``: painted at whatever size a surface asks for."""
    return QIcon(_AppIconEngine())


def render_app_icon(size: int) -> QPixmap:
    """A square pixmap of the mark at ``size`` device pixels (the tool and the tests)."""
    return _AppIconEngine().pixmap(QSize(size, size), QIcon.Mode.Normal, QIcon.State.Off)


def svg_document(size: int = 256) -> str:
    """The SVG master at the large-size geometry (7° gaps, the disc with air around it)."""
    c = size / 2
    r = size * RING_RADIUS
    paths = []
    for arc in arcs():
        # SVG's y axis points down and its angles run clockwise, Qt's counter-clockwise.
        a0 = math.radians(arc.start_deg + arc.span_deg)
        a1 = math.radians(arc.start_deg)
        x0, y0 = c + r * math.cos(a0), c - r * math.sin(a0)
        x1, y1 = c + r * math.cos(a1), c - r * math.sin(a1)
        paths.append(
            f'  <path d="M {x0:.3f} {y0:.3f} A {r:.3f} {r:.3f} 0 0 1 {x1:.3f} {y1:.3f}" '
            f'stroke="{INK}" stroke-width="{size * STROKE:.3f}" fill="none"/>'
        )
    body = "\n".join(paths)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'width="{size}" height="{size}">\n'
        f'  <circle cx="{c}" cy="{c}" r="{size * DISC_RADIUS:.3f}" fill="{DISC}"/>\n'
        f"{body}\n"
        f'  <circle cx="{c}" cy="{c}" r="{size * HUB_RADIUS:.3f}" fill="{ACCENT}"/>\n'
        f"</svg>\n"
    )
