"""``WheelRenderer``: paints the wheel from a ``SessionView`` and a ``Frame`` (phase-3 §2, §3, §7).

Two calls per paint, in this order:

1. ``paint_floor``: a circle of radius ``halo_r`` filled with alpha 1, antialiasing off. **Every
   catching pixel comes from this call**, so the window paints it first, before anything that could
   fail (C2, C3). It never scales, fades or clips.
2. ``paint_content``: everything visible. The content is rendered once into a cached layer (a
   premultiplied ``QImage`` at physical resolution) and the layer is drawn as **one group** under
   the frame's opacity and scale. Fading one image avoids the double blending of per-primitive
   opacity and costs well under a millisecond per frame (M2 check 6). Everything is clipped to the
   floor's circle, so no shadow, bulge or antialiased edge can put a pixel with alpha > 0 outside
   the halo.

Rules:

- No window opacity, ever (C3). The floor is independent of ``Frame``.
- The renderer holds no theme and no geometry: both are arguments, so a size or scheme change can
  never leave it stale. The layer is regenerated whenever any input differs (compared by value),
  into the same buffer while the size and the pixel ratio hold.
- Strings arrive ready-made in ``Content`` (labels, the hub's two lines). The renderer translates
  nothing (D3); ``slot_labels`` and ``item_labels`` are the one place that maps a plan to labels.
- High Contrast (C7): opaque fills, 2 px borders in the system's text color, no shadow.
- Hover is shown three ways (phase-3 §7, color blindness): the accent fill, the 4 px bulge, and the
  hub's text (the window supplies the latter).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QImage, QPainter, QPainterPath, QPen

from morphwheel.core.catalog import MORE_SLOT, SLOT_ORDER, SlotPos, SlotState, SlotStatus, WheelPlan
from morphwheel.core.geometry import (
    MORE_ITEM_SPAN_DEG,
    SLOT_GAP_DEG,
    SLOT_SPAN_DEG,
    MoreArc,
    WheelGeometry,
    polar,
)
from morphwheel.core.wheel_session import HubKind, SessionView
from morphwheel.ui.theme import Theme

FLOOR = QColor(0, 0, 0, 1)  # the alpha floor: invisible, catches drops (C2)
BULGE_PX = 4.0  # the hovered slot stands this much proud (phase-3 §3)
SHADOW_SPREAD_PX = 18.0
SHADOW_OFFSET_PX = 4.0
SHADOW_RINGS = 24
SKELETON_BAR = (30.0, 6.0)  # the label placeholder while the plan is unknown
HUB_PADDING = 6.0


@dataclass(frozen=True)
class HubText:
    top: str = ""
    bottom: str = ""


@dataclass(frozen=True)
class Content:
    """What to draw, apart from time: the view and its ready-made strings."""

    view: SessionView | None
    hub: HubText = HubText()
    labels: Mapping[SlotPos, str] = field(default_factory=dict)
    item_labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class Frame:
    """The animator's output. ``opacity`` and ``scale`` apply to the layer; the rest is content."""

    opacity: float = 1.0
    scale: float = 1.0
    labels: float = 1.0  # 0 = skeleton, 1 = labels (the DragEnter crossfade)
    bulge: Mapping[SlotPos, float] = field(default_factory=dict)  # per slot, 0..1
    item_bulge: Mapping[int, float] = field(default_factory=dict)  # per arc item, 0..1
    arc: MoreArc | None = None  # the More arc as last open; drawn while it grows or shrinks
    more_arc: float = 0.0  # the arc's growth, 0..1
    halo_edge: float = 0.0  # the halo edge line (U1), 0..1
    flash: Mapping[SlotPos, float] = field(default_factory=dict)  # the dropped slot's flash

    def content_key(self) -> tuple[object, ...]:
        return (
            round(self.labels, 3),
            tuple(sorted((s.value, round(v, 3)) for s, v in self.bulge.items() if v > 0)),
            tuple(sorted((i, round(v, 3)) for i, v in self.item_bulge.items() if v > 0)),
            self.arc,
            round(self.more_arc, 3),
            round(self.halo_edge, 3),
            tuple(sorted((s.value, round(v, 3)) for s, v in self.flash.items() if v > 0)),
        )


def slot_labels(plan: WheelPlan | None, more_label: str) -> dict[SlotPos, str]:
    """The eight slot labels: the target's label, ``more_label`` for More, "" for an empty slot."""
    if plan is None:
        return {}
    out: dict[SlotPos, str] = {}
    for slot in SLOT_ORDER:
        state = plan.slots[slot]
        if slot is MORE_SLOT:
            out[slot] = more_label
        else:
            out[slot] = state.target.label if state.target is not None else ""
    return out


def item_labels(plan: WheelPlan | None) -> tuple[str, ...]:
    if plan is None:
        return ()
    return tuple(s.target.label if s.target is not None else "" for s in plan.more)


def blank_layer(size: QSize, dpr: float) -> QImage:
    """A transparent, premultiplied image at physical resolution, in logical coordinates."""
    image = QImage(
        math.ceil(size.width() * dpr),
        math.ceil(size.height() * dpr),
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    image.setDevicePixelRatio(dpr)
    image.fill(Qt.GlobalColor.transparent)
    return image


class WheelRenderer:
    def __init__(self) -> None:
        self._layer: QImage | None = None
        self._layer_key: tuple[object, ...] | None = None
        self._shadow: QImage | None = None
        self._shadow_key: tuple[object, ...] | None = None
        self._floor: tuple[tuple[object, ...], QPainterPath] | None = None
        self.layer_builds = 0  # for tests: how often the layer was regenerated

    # ----------------------------------------------------------------- the floor (C2)
    def floor_path(self, size: QSize, geometry: WheelGeometry) -> QPainterPath:
        key: tuple[object, ...] = (size.width(), size.height(), geometry.scale)
        if self._floor is None or self._floor[0] != key:
            path = QPainterPath()
            path.addEllipse(_center(size), geometry.halo_r, geometry.halo_r)
            self._floor = (key, path)
        return self._floor[1]

    def paint_floor(self, painter: QPainter, size: QSize, geometry: WheelGeometry) -> None:
        """Alpha 1 over the whole halo, no antialiasing: the edge pixels are no exception."""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillPath(self.floor_path(size, geometry), FLOOR)
        painter.restore()

    # ----------------------------------------------------------------- the content
    def paint_content(
        self,
        painter: QPainter,
        size: QSize,
        dpr: float,
        theme: Theme,
        geometry: WheelGeometry,
        content: Content,
        frame: Frame,
    ) -> None:
        if frame.opacity <= 0.0:
            return
        layer = self._layer_for(size, dpr, theme, geometry, content, frame)
        c = _center(size)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setClipPath(self.floor_path(size, geometry))
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setOpacity(min(1.0, frame.opacity))
        painter.translate(c)
        painter.scale(frame.scale, frame.scale)
        painter.translate(-c)
        painter.drawImage(QPointF(0.0, 0.0), layer)
        painter.restore()

    # ----------------------------------------------------------------- the layer
    def _layer_for(
        self,
        size: QSize,
        dpr: float,
        theme: Theme,
        geometry: WheelGeometry,
        content: Content,
        frame: Frame,
    ) -> QImage:
        key: tuple[object, ...] = (
            (size.width(), size.height()),
            dpr,
            theme,
            geometry,
            content,
            frame.content_key(),
        )
        if self._layer is not None and key == self._layer_key:
            return self._layer
        same_buffer = (
            self._layer is not None
            and self._layer_key is not None
            and key[:2] == self._layer_key[:2]
        )
        if same_buffer and self._layer is not None:
            self._layer.fill(Qt.GlobalColor.transparent)  # same size and ratio: reuse the buffer
        else:
            self._layer = blank_layer(size, dpr)
        self._build_layer(self._layer, size, dpr, theme, geometry, content, frame)
        self._layer_key = key
        self.layer_builds += 1
        return self._layer

    def _build_layer(
        self,
        image: QImage,
        size: QSize,
        dpr: float,
        theme: Theme,
        geometry: WheelGeometry,
        content: Content,
        frame: Frame,
    ) -> None:
        p = QPainter(image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        c = _center(size)
        g = geometry
        pal = theme.palette
        view = content.view
        plan = view.plan if view is not None else None
        dimmed = plan is not None and not plan.ok

        if theme.has_shadow:
            p.drawImage(QPointF(0.0, 0.0), self._shadow_for(size, dpr, theme, geometry))
        _fill_circle(p, c, g.slot_outer_r, pal.disc)
        self._paint_slots(p, c, theme, g, content, frame, dimmed)
        self._paint_more(p, c, theme, g, content, frame)
        # The disc's own outline, over the wedges so the bulge reads as "proud of the ring".
        p.setPen(QPen(pal.outline_surface, theme.border_width))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(c, g.slot_outer_r, g.slot_outer_r)
        if frame.halo_edge > 0.0:
            edge = QColor(pal.outline_surface)
            edge.setAlphaF(edge.alphaF() * frame.halo_edge)
            p.setPen(QPen(edge, 1.5))
            p.drawEllipse(c, g.halo_r - 1.5, g.halo_r - 1.5)
        self._paint_hub(p, c, theme, g, content, dimmed)
        p.end()

    # ----------------------------------------------------------------- slots
    def _paint_slots(
        self,
        p: QPainter,
        c: QPointF,
        theme: Theme,
        g: WheelGeometry,
        content: Content,
        frame: Frame,
        dimmed: bool,
    ) -> None:
        pal = theme.palette
        view = content.view
        plan = view.plan if view is not None else None
        p.setFont(theme.fonts.slot_label)
        metrics = QFontMetricsF(theme.fonts.slot_label)
        for slot in SLOT_ORDER:
            angle = WheelGeometry.slot_angle(slot)
            state: SlotState | None = plan.slots[slot] if plan is not None else None
            bulge = frame.bulge.get(slot, 0.0)
            lit = max(bulge, frame.flash.get(slot, 0.0))
            outer = g.slot_outer_r + BULGE_PX * bulge
            wedge = _sector(c, g.slot_inner_r, outer, angle, SLOT_SPAN_DEG - SLOT_GAP_DEG)
            fill = QColor(pal.surface)
            if state is not None and (state.status is SlotStatus.EMPTY or dimmed):
                fill.setAlphaF(fill.alphaF() * 0.5)
            fill = _mix(fill, pal.accent, lit)
            p.setPen(QPen(pal.outline if lit < 0.5 else pal.accent, theme.border_width))
            p.setBrush(fill)
            p.drawPath(wedge)

            mid = polar(angle, (g.slot_inner_r + outer) / 2)
            at = QPointF(c.x() + mid.x, c.y() + mid.y)
            if frame.labels < 1.0:
                bar = QColor(pal.skeleton)
                bar.setAlphaF(bar.alphaF() * (1.0 - frame.labels))
                w, h = SKELETON_BAR
                skeleton = QPainterPath()
                skeleton.addRoundedRect(QRectF(at.x() - w / 2, at.y() - h / 2, w, h), h / 2, h / 2)
                p.fillPath(skeleton, bar)
            label = content.labels.get(slot, "")
            if frame.labels > 0.0 and label:
                color = pal.text
                if state is not None and (not state.enabled or dimmed):
                    color = pal.text_disabled
                color = _mix(color, pal.text_on_accent, lit)
                color.setAlphaF(color.alphaF() * frame.labels)
                p.setPen(color)
                width = max(metrics.horizontalAdvance(label), 1.0) + 8
                p.drawText(
                    QRectF(at.x() - width / 2, at.y() - 10, width, 20),
                    Qt.AlignmentFlag.AlignCenter,
                    label,
                )

    # ----------------------------------------------------------------- the More arc (U3)
    def _paint_more(
        self,
        p: QPainter,
        c: QPointF,
        theme: Theme,
        g: WheelGeometry,
        content: Content,
        frame: Frame,
    ) -> None:
        arc = frame.arc
        if arc is None or frame.more_arc <= 0.0 or arc.count == 0:
            return
        pal = theme.palette
        outer = g.more_inner_r + (g.more_outer_r - g.more_inner_r) * frame.more_arc
        ring = _sector(c, g.more_inner_r, outer, arc.center_deg, arc.span_deg)
        p.setPen(QPen(pal.outline_surface, theme.border_width))
        p.setBrush(pal.disc)
        p.drawPath(ring)
        p.setFont(theme.fonts.slot_label)
        metrics = QFontMetricsF(theme.fonts.slot_label)
        view = content.view
        for index in range(arc.count):
            angle = arc.item_angle(index)
            lit = frame.item_bulge.get(index, 0.0)
            item = _sector(c, g.more_inner_r, outer, angle, MORE_ITEM_SPAN_DEG - SLOT_GAP_DEG)
            p.setPen(QPen(pal.outline if lit < 0.5 else pal.accent, theme.border_width))
            p.setBrush(_mix(QColor(pal.surface), pal.accent, lit))
            p.drawPath(item)
            label = content.item_labels[index] if index < len(content.item_labels) else ""
            if not label or frame.more_arc < 0.5:
                continue
            enabled = True
            if view is not None and view.plan is not None and index < len(view.plan.more):
                enabled = view.plan.more[index].enabled
            color = _mix(pal.text if enabled else pal.text_disabled, pal.text_on_accent, lit)
            color.setAlphaF(color.alphaF() * (frame.more_arc - 0.5) * 2.0)
            mid = polar(angle, (g.more_inner_r + outer) / 2)
            width = max(metrics.horizontalAdvance(label), 1.0) + 8
            p.setPen(color)
            p.drawText(
                QRectF(c.x() + mid.x - width / 2, c.y() + mid.y - 10, width, 20),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )

    # ----------------------------------------------------------------- the hub (C5)
    def _paint_hub(
        self,
        p: QPainter,
        c: QPointF,
        theme: Theme,
        g: WheelGeometry,
        content: Content,
        dimmed: bool,
    ) -> None:
        pal = theme.palette
        view = content.view
        fill = pal.surface
        if view is not None and view.hub.kind is HubKind.CANCEL:  # the hub or the halo (U1)
            fill = _mix(QColor(pal.surface), pal.accent, 0.35)
        p.setPen(QPen(pal.outline_surface, theme.border_width))
        p.setBrush(fill)
        p.drawEllipse(c, g.hub_r, g.hub_r)
        if not content.hub.top:
            return
        width = 2 * g.hub_r - 2 * HUB_PADDING
        top_font, bottom_font = theme.fonts.hub_top, theme.fonts.hub_bottom
        top_metrics, bottom_metrics = QFontMetricsF(top_font), QFontMetricsF(bottom_font)
        top = top_metrics.elidedText(content.hub.top, Qt.TextElideMode.ElideMiddle, width)
        bottom = bottom_metrics.elidedText(content.hub.bottom, Qt.TextElideMode.ElideMiddle, width)
        top_h = top_metrics.height()
        bottom_h = bottom_metrics.height() if bottom else 0.0
        y = c.y() - (top_h + bottom_h) / 2
        p.setFont(top_font)
        p.setPen(pal.text_disabled if dimmed else pal.text)
        p.drawText(QRectF(c.x() - width / 2, y, width, top_h), Qt.AlignmentFlag.AlignCenter, top)
        if bottom:
            p.setFont(bottom_font)
            p.setPen(pal.text_secondary)
            p.drawText(
                QRectF(c.x() - width / 2, y + top_h, width, bottom_h),
                Qt.AlignmentFlag.AlignCenter,
                bottom,
            )

    # ----------------------------------------------------------------- the shadow
    def _shadow_for(self, size: QSize, dpr: float, theme: Theme, geometry: WheelGeometry) -> QImage:
        """A soft shadow under the disc, from concentric rings; cached per size, dpr and theme."""
        key: tuple[object, ...] = (
            (size.width(), size.height()),
            dpr,
            geometry.scale,
            theme.palette.shadow.rgba(),
        )
        if self._shadow is not None and key == self._shadow_key:
            return self._shadow
        image = blank_layer(size, dpr)
        p = QPainter(image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        c = _center(size)
        shadow_center = QPointF(c.x(), c.y() + SHADOW_OFFSET_PX)
        ring = QColor(theme.palette.shadow)
        ring.setAlphaF(theme.palette.shadow.alphaF() / SHADOW_RINGS)
        for k in range(SHADOW_RINGS):
            r = geometry.slot_outer_r + SHADOW_SPREAD_PX * (1.0 - k / SHADOW_RINGS)
            _fill_circle(p, shadow_center, r, ring)
        p.end()
        self._shadow, self._shadow_key = image, key
        return image


# --------------------------------------------------------------------------- helpers


def _center(size: QSize) -> QPointF:
    return QPointF(size.width() / 2, size.height() / 2)


def _fill_circle(p: QPainter, c: QPointF, r: float, color: QColor) -> None:
    path = QPainterPath()
    path.addEllipse(c, r, r)
    p.fillPath(path, color)


def _sector(
    c: QPointF, inner: float, outer: float, center_deg: float, span_deg: float
) -> QPainterPath:
    """An annular sector around the compass angle ``center_deg`` (0 = N, clockwise)."""
    # QPainterPath.arcTo counts degrees counter-clockwise from 3 o'clock.
    start = 90.0 - (center_deg + span_deg / 2)
    path = QPainterPath()
    outer_rect = QRectF(c.x() - outer, c.y() - outer, 2 * outer, 2 * outer)
    inner_rect = QRectF(c.x() - inner, c.y() - inner, 2 * inner, 2 * inner)
    path.arcMoveTo(outer_rect, start)
    path.arcTo(outer_rect, start, span_deg)
    path.arcTo(inner_rect, start + span_deg, -span_deg)
    path.closeSubpath()
    return path


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    """Linear blend from ``a`` (t = 0) to ``b`` (t = 1), alpha included."""
    if t <= 0.0:
        return QColor(a)
    if t >= 1.0:
        return QColor(b)
    return QColor.fromRgbF(
        a.redF() + (b.redF() - a.redF()) * t,
        a.greenF() + (b.greenF() - a.greenF()) * t,
        a.blueF() + (b.blueF() - a.blueF()) * t,
        a.alphaF() + (b.alphaF() - a.alphaF()) * t,
    )
