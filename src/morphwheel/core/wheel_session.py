"""One wheel appearance, from show to drop: hover, arming, the More arc, and what the hub says.

The wheel window (S2/S4) feeds it pointer positions relative to the wheel center, in logical px,
together with timestamps. It answers with a ``SessionView``, which tells the window what to paint
and whether to accept or reject DragMove. ``decide_drop`` makes the final call.

Rules:

- **U7, arming.** Nothing can be selected until the pointer has moved ``ARMING_DISTANCE`` from
  where it was when the wheel appeared. That position is not necessarily the center: near a screen
  edge the wheel is shifted, and the cursor may start on a slot.
- **U3, More arc.** It opens after a ``MORE_DWELL_NS`` hover on the More slot, or immediately when
  the pointer pushes outward through it. It closes when the pointer returns to the hub or to
  another slot.
- **Waiting.** Until DragEnter supplies a plan, the hub shows a spinner after
  ``SPINNER_AFTER_NS`` and gives up after ``GIVE_UP_AFTER_NS`` (phase-3 §4).
- **C5.** The hub repeats the hovered target, because Explorer's drag thumbnail covers the slot
  label.
- ``set_plan`` can be called twice: once by extension at DragEnter, and again after the async
  sniff. The second call keeps arming, hover and the More state.

The hub content is data (``HubInfo``), never text. The UI renders and translates it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from morphwheel.core.catalog import MORE_SLOT, Reason, SlotState, Target, WheelPlan
from morphwheel.core.geometry import MoreArc, Point, Region, RegionKind, WheelGeometry

ARMING_DISTANCE = 12.0  # logical px (U7)
MORE_DWELL_NS = 250_000_000
SPINNER_AFTER_NS = 150_000_000
GIVE_UP_AFTER_NS = 1_500_000_000


class HubKind(StrEnum):
    WAITING = "waiting"  # no plan yet (usually hidden by the 167 ms appear animation)
    SPINNER = "spinner"
    GAVE_UP = "gave_up"  # "Can't read this drag"
    FILES = "files"  # "photo.png" / "3 files"
    TARGET = "target"  # "→ JPG", with skip count
    DISABLED = "disabled"  # hovered slot can't be used: reason
    MORE = "more"  # hovering the More slot
    CANCEL = "cancel"  # hub or halo
    NOT_SUPPORTED = "not_supported"  # whole drag: plan reason


@dataclass(frozen=True)
class HubInfo:
    kind: HubKind
    target: Target | None = None
    reason: Reason | None = None
    file_count: int = 0
    skip_count: int = 0


@dataclass(frozen=True)
class SessionView:
    plan: WheelPlan | None
    armed: bool
    region: Region
    hover: SlotState | None  # the slot / arc item under the pointer, if any
    highlight_slot: bool  # paint the hovered slot or item as selected
    more_arc: MoreArc | None  # set while the arc is open
    halo_edge_visible: bool  # faint ring at the halo edge while the pointer is in it
    hub: HubInfo
    accepts_drop: bool  # DragMove: force_copy when True, reject when False


class CancelReason(StrEnum):
    NOT_READY = "not_ready"
    NOT_SUPPORTED = "not_supported"
    NOT_ARMED = "not_armed"
    HUB = "hub"
    GAP = "gap"
    HALO = "halo"
    OUTSIDE = "outside"
    MORE_SLOT = "more_slot"
    DISABLED = "disabled"


@dataclass(frozen=True)
class Accept:
    target: Target
    skip_count: int


@dataclass(frozen=True)
class Cancel:
    reason: CancelReason


_REGION_CANCEL = {
    RegionKind.HUB: CancelReason.HUB,
    RegionKind.GAP: CancelReason.GAP,
    RegionKind.HALO: CancelReason.HALO,
    RegionKind.OUTSIDE: CancelReason.OUTSIDE,
}


class WheelSession:
    def __init__(
        self,
        geometry: WheelGeometry,
        *,
        appear_at: Point,
        t0_ns: int,
        more_center_deg: float = 315.0,
    ) -> None:
        self.geometry = geometry
        self.plan: WheelPlan | None = None
        self._appear_at = appear_at
        self._t0 = t0_ns
        self._more_center = more_center_deg
        self._pointer = appear_at
        self._now = t0_ns
        self._armed = False
        self._more_open = False
        self._dwell_since: int | None = None
        self._prev_region = geometry.region(appear_at)

    # ----------------------------------------------------------------- inputs
    def set_plan(self, plan: WheelPlan) -> SessionView:
        self.plan = plan
        if not self._more_available():
            self._more_open = False
        return self._view()

    def on_pointer(self, p: Point, t_ns: int) -> SessionView:
        self._pointer, self._now = p, t_ns
        if (
            not self._armed
            and math.dist((p.x, p.y), (self._appear_at.x, self._appear_at.y)) >= ARMING_DISTANCE
        ):
            self._armed = True
        self._update_more()
        view = self._view()
        self._prev_region = view.region
        return view

    def tick(self, t_ns: int) -> SessionView:
        """Time passes without pointer movement: dwell, spinner and give-up."""
        self._now = t_ns
        self._update_more()
        return self._view()

    def decide_drop(self, p: Point, t_ns: int) -> Accept | Cancel:
        view = self.on_pointer(p, t_ns)
        if view.accepts_drop and view.hover is not None and view.hover.target is not None:
            return Accept(view.hover.target, view.hover.skip_count)
        if self.plan is None:
            return Cancel(CancelReason.NOT_READY)
        if not self.plan.ok:
            return Cancel(CancelReason.NOT_SUPPORTED)
        if view.region.kind in _REGION_CANCEL:
            return Cancel(_REGION_CANCEL[view.region.kind])
        if not self._armed:
            return Cancel(CancelReason.NOT_ARMED)
        if view.region.slot is MORE_SLOT:
            return Cancel(CancelReason.MORE_SLOT)
        return Cancel(CancelReason.DISABLED)

    # ----------------------------------------------------------------- internals
    def _more_available(self) -> bool:
        return self.plan is not None and self.plan.ok and self.plan.slots[MORE_SLOT].enabled

    def _arc(self) -> MoreArc | None:
        if not self._more_open or self.plan is None:
            return None
        return MoreArc(self._more_center, len(self.plan.more))

    def _update_more(self) -> None:
        if not (self._more_available() and self._armed):
            self._more_open = False
            self._dwell_since = None
            return
        region = self.geometry.region(self._pointer, self._arc())
        if self._more_open:
            back_inside = region.kind is RegionKind.HUB or (
                region.kind is RegionKind.SLOT and region.slot is not MORE_SLOT
            )
            if back_inside:
                self._more_open = False
            return
        on_more = region.kind is RegionKind.SLOT and region.slot is MORE_SLOT
        pushed_out = (
            self._prev_region.kind is RegionKind.SLOT
            and self._prev_region.slot is MORE_SLOT
            and self.geometry.is_outward_of_more_slot(self._pointer)
        )
        if pushed_out:
            self._more_open = True
        elif on_more:
            if self._dwell_since is None:
                self._dwell_since = self._now
            elif self._now - self._dwell_since >= MORE_DWELL_NS:
                self._more_open = True
        else:
            self._dwell_since = None

    def _view(self) -> SessionView:
        arc = self._arc()
        region = self.geometry.region(self._pointer, arc)
        plan = self.plan
        hover: SlotState | None = None
        if plan is not None:
            if region.kind is RegionKind.SLOT and region.slot is not None:
                hover = plan.slots[region.slot]
            elif region.kind is RegionKind.MORE_ITEM and region.item is not None:
                hover = plan.more[region.item]
        is_more_slot = region.kind is RegionKind.SLOT and region.slot is MORE_SLOT
        selectable = (
            plan is not None
            and plan.ok
            and self._armed
            and hover is not None
            and hover.enabled
            and not is_more_slot
        )
        return SessionView(
            plan=plan,
            armed=self._armed,
            region=region,
            hover=hover,
            highlight_slot=selectable or (is_more_slot and self._armed and self._more_available()),
            more_arc=arc,
            halo_edge_visible=region.kind is RegionKind.HALO,
            hub=self._hub(region, hover, selectable, is_more_slot),
            accepts_drop=selectable,
        )

    def _hub(
        self, region: Region, hover: SlotState | None, selectable: bool, is_more_slot: bool
    ) -> HubInfo:
        plan = self.plan
        if plan is None:
            waited = self._now - self._t0
            if waited >= GIVE_UP_AFTER_NS:
                return HubInfo(HubKind.GAVE_UP)
            return HubInfo(HubKind.SPINNER if waited >= SPINNER_AFTER_NS else HubKind.WAITING)
        if not plan.ok:
            return HubInfo(HubKind.NOT_SUPPORTED, reason=plan.reason, file_count=plan.file_count)
        if region.kind in (RegionKind.HUB, RegionKind.HALO):
            return HubInfo(HubKind.CANCEL, file_count=plan.file_count)
        if self._armed and hover is not None:
            if is_more_slot:
                if hover.enabled:
                    return HubInfo(HubKind.MORE, file_count=plan.file_count)
                return HubInfo(HubKind.DISABLED, reason=hover.reason, file_count=plan.file_count)
            if selectable:
                return HubInfo(
                    HubKind.TARGET,
                    target=hover.target,
                    file_count=plan.file_count,
                    skip_count=hover.skip_count,
                )
            return HubInfo(
                HubKind.DISABLED,
                target=hover.target,
                reason=hover.reason,
                file_count=plan.file_count,
            )
        return HubInfo(HubKind.FILES, file_count=plan.file_count)
