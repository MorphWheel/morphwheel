"""Wheel geometry: radii, hit-test regions, clamping to the screen, and the More arc.

Sources: phase-3 §2.1 (layout), U2 (8 slots), U3 (More arc), U4 (size M = disc Ø 236).

- Coordinates are logical pixels relative to the wheel center. y grows downward, as on screen.
- Angles are compass degrees: 0° is north, increasing clockwise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from morphwheel.core.catalog import MORE_SLOT, SLOT_ORDER, SlotPos

# Size M (scale 1.0), logical px.
HUB_R = 36.0
SLOT_INNER_R = 40.0
SLOT_OUTER_R = 118.0
MORE_INNER_R = 124.0
MORE_OUTER_R = 170.0
HALO_R = 190.0  # invisible catch ring (U1), alpha floor ≥ 1
SLOT_SPAN_DEG = 360.0 / len(SLOT_ORDER)  # 45°
SLOT_GAP_DEG = 3.0
MORE_ITEM_SPAN_DEG = 30.0

SIZE_SCALES = {"S": 0.85, "M": 1.0, "L": 1.2}


@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True)
class Rect:
    left: float
    top: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.left + self.width

    @property
    def bottom(self) -> float:
        return self.top + self.height

    @property
    def center(self) -> Point:
        return Point(self.left + self.width / 2, self.top + self.height / 2)

    def contains(self, p: Point) -> bool:
        return self.left <= p.x <= self.right and self.top <= p.y <= self.bottom


class RegionKind(StrEnum):
    HUB = "hub"  # cancel
    SLOT = "slot"
    GAP = "gap"  # between slots or rings: no-op, but still catches (alpha floor)
    MORE_ITEM = "more_item"
    HALO = "halo"  # catch ring: cancel; leaving it dismisses the wheel (U1)
    OUTSIDE = "outside"  # alpha 0: drops pass through to the window below


@dataclass(frozen=True)
class Region:
    kind: RegionKind
    slot: SlotPos | None = None
    item: int | None = None


def compass_angle(p: Point) -> float:
    return (math.degrees(math.atan2(p.x, -p.y)) + 360.0) % 360.0


def angle_delta(a: float, b: float) -> float:
    """Signed smallest difference ``a - b``, in (-180, 180]."""
    d = (a - b) % 360.0
    return d - 360.0 if d > 180.0 else d


def polar(angle_deg: float, radius: float) -> Point:
    rad = math.radians(angle_deg)
    return Point(radius * math.sin(rad), -radius * math.cos(rad))


@dataclass(frozen=True)
class MoreArc:
    """The open More arc: ``count`` items of 30°, clockwise around ``center_deg``."""

    center_deg: float
    count: int

    @property
    def span_deg(self) -> float:
        return self.count * MORE_ITEM_SPAN_DEG

    def item_at(self, angle: float) -> int | None:
        offset = angle_delta(angle, self.center_deg) + self.span_deg / 2
        if 0.0 <= offset < self.span_deg:
            return int(offset // MORE_ITEM_SPAN_DEG)
        return None

    def item_angle(self, index: int) -> float:
        start = self.center_deg - self.span_deg / 2
        return (start + (index + 0.5) * MORE_ITEM_SPAN_DEG) % 360.0


@dataclass(frozen=True)
class WheelGeometry:
    scale: float = 1.0

    @classmethod
    def for_size(cls, size: str) -> WheelGeometry:
        return cls(SIZE_SCALES[size])

    @property
    def hub_r(self) -> float:
        return HUB_R * self.scale

    @property
    def slot_inner_r(self) -> float:
        return SLOT_INNER_R * self.scale

    @property
    def slot_outer_r(self) -> float:
        return SLOT_OUTER_R * self.scale

    @property
    def more_inner_r(self) -> float:
        return MORE_INNER_R * self.scale

    @property
    def more_outer_r(self) -> float:
        return MORE_OUTER_R * self.scale

    @property
    def halo_r(self) -> float:
        return HALO_R * self.scale

    @property
    def window_size(self) -> int:
        """The fixed window edge, sized for the largest state: the halo (phase-3 C1)."""
        return math.ceil(2 * self.halo_r)

    @staticmethod
    def slot_angle(slot: SlotPos) -> float:
        return SLOT_ORDER.index(slot) * SLOT_SPAN_DEG

    def region(self, p: Point, more: MoreArc | None = None) -> Region:
        r = math.hypot(p.x, p.y)
        if r <= self.hub_r:
            return Region(RegionKind.HUB)
        if r < self.slot_inner_r:
            return Region(RegionKind.GAP)
        angle = compass_angle(p)
        if r <= self.slot_outer_r:
            shifted = (angle + SLOT_SPAN_DEG / 2) % 360.0
            offset = shifted % SLOT_SPAN_DEG
            if offset < SLOT_GAP_DEG / 2 or offset > SLOT_SPAN_DEG - SLOT_GAP_DEG / 2:
                return Region(RegionKind.GAP)
            return Region(RegionKind.SLOT, slot=SLOT_ORDER[int(shifted // SLOT_SPAN_DEG)])
        if more is not None and r <= self.more_outer_r and more.item_at(angle) is not None:
            if r < self.more_inner_r:
                return Region(RegionKind.GAP)
            return Region(RegionKind.MORE_ITEM, item=more.item_at(angle))
        if r <= self.halo_r:
            return Region(RegionKind.HALO)
        return Region(RegionKind.OUTSIDE)

    def is_outward_of_more_slot(self, p: Point) -> bool:
        """Beyond the More slot's outer edge, within its angular span ("push through" in U3)."""
        within = abs(angle_delta(compass_angle(p), self.slot_angle(MORE_SLOT))) <= SLOT_SPAN_DEG / 2
        return within and math.hypot(p.x, p.y) > self.slot_outer_r

    def clamp_center(self, cursor: Point, screen: Rect) -> Point:
        """Where to center the wheel so the DISC stays on screen. The halo may spill over."""
        r = self.slot_outer_r

        def clamp(value: float, low: float, high: float) -> float:
            return (low + high) / 2 if low > high else min(max(value, low), high)

        return Point(
            clamp(cursor.x, screen.left + r, screen.right - r),
            clamp(cursor.y, screen.top + r, screen.bottom - r),
        )

    def more_arc(self, center: Point, screen: Rect, count: int) -> MoreArc | None:
        """The arc for ``count`` plugin items: NW by default, rotated inward near screen edges."""
        if count <= 0:
            return None
        preferred = MoreArc(self.slot_angle(MORE_SLOT), count)
        if self._arc_fits(preferred, center, screen):
            return preferred
        toward_screen = compass_angle(Point(screen.center.x - center.x, screen.center.y - center.y))
        return MoreArc(toward_screen, count)

    def _arc_fits(self, arc: MoreArc, center: Point, screen: Rect) -> bool:
        start = arc.center_deg - arc.span_deg / 2
        steps = arc.count * 2
        for i in range(steps + 1):
            p = polar(start + arc.span_deg * i / steps, self.more_outer_r)
            if not screen.contains(Point(center.x + p.x, center.y + p.y)):
                return False
        return True
