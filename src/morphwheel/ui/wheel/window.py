"""``WheelWindow``: the one window shown during a drag, and the only drop target (phase-4 §4.6).

It is pre-created (``winId()`` at construction registers the OLE drop target), sized for the largest
wheel (phase-3 C1), translucent, and never takes focus. It owns a ``WheelSession`` per appearance
and turns OLE's events into the session's inputs. The S2 renderer is plain: a floor, a disc, slot
labels and the hub text. The final look and the per-element fade come in S4 (``renderer.py``,
``animator.py``).

Safety rules, all of them tested offscreen:

- **DragEnter always goes through ``force_copy``,** even before arming, even without a session
  (carry-over from S1): a window that ignores DragEnter gets no DragMove from Qt.
- **DragMove and Drop are accepted only when ``SessionView.accepts_drop`` says so,** through
  ``force_copy``; everything else is ``reject``. Without a session (the window is hidden, and an
  event already in flight still arrives) both are rejected.
- **No drop is ever accepted as Move.** ``assert_safe`` runs before a ``DropRequest`` leaves.
- **The drop handler does only the decision and the emit** (under 5 ms, phase-2 §4). The
  controller connects the signals queued, so hiding, logging and the job start happen after
  ``IDropTarget::Drop`` has returned.
- **DragEnter does no I/O:** it reads ``urls()`` only, and plans by extension. The header sniff
  runs on the ``Sniffer`` thread (S3) and lands as a second ``set_plan`` through a queued signal,
  unless the wheel hid or a newer DragEnter came in the meantime (a generation number).
- **Alpha floor.** Every catching pixel (hub, gaps, slots, the halo) is painted with alpha ≥ 1,
  without antialiasing, so the edge pixels are no exception. Outside the halo nothing is painted.
- **Hide clears the session.** Each ``show_at`` starts a new session (new arming, new timers).

Signals:

- ``drop_requested(DropRequest)``: an accepted drop;
- ``cancelled()``: a drop that landed where nothing can be selected (OLE sends Drop, not
  DragLeave, when the last DragMove was accepted);
- ``drag_left()``: DragLeave. The controller decides between "pointer left the halo" and
  "released over the hub" by the button state;
- ``gave_up()``: no plan arrived within the give-up time (phase-3 §4), once per session.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import QWidget

from morphwheel.core.catalog import MORE_ARC_MAX, MORE_SLOT, SLOT_ORDER, Catalog, Reason
from morphwheel.core.formats import FileInfo
from morphwheel.core.geometry import Point, Rect, RegionKind, WheelGeometry, polar
from morphwheel.core.jobs import DropRequest
from morphwheel.core.wheel_session import Accept, HubInfo, HubKind, SessionView, WheelSession
from morphwheel.logs import timed
from morphwheel.ui.wheel.drop_guard import assert_safe, force_copy, reject
from morphwheel.ui.wheel.sniffer import Sniffer

log = logging.getLogger("morphwheel.ui.wheel")

WheelSize = Literal["S", "M", "L"]
DROP_BUDGET_MS = 5.0

_WINDOW_FLAGS = (
    Qt.WindowType.Tool
    | Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.WindowStaysOnTopHint
    | Qt.WindowType.WindowDoesNotAcceptFocus
)

# S2 palette. The theme (S4) replaces it.
_FLOOR = QColor(0, 0, 0, 1)
_DISC = QColor(32, 32, 36, 235)  # U5: 92 % opaque
_HUB = QColor(60, 60, 66, 245)
_SLOT_TEXT = QColor(230, 230, 230)
_SLOT_DIM = QColor(120, 120, 124)
_ACCENT = QColor(255, 140, 30)
_HALO_EDGE = QColor(255, 255, 255, 40)


class WheelWindow(QWidget):
    drop_requested = Signal(object)
    cancelled = Signal()
    drag_left = Signal()
    gave_up = Signal()

    def __init__(
        self,
        catalog: Catalog,
        *,
        size: WheelSize = "M",
        clock: Callable[[], int] = time.perf_counter_ns,
        cursor: Callable[[], QPoint] = QCursor.pos,
        sniffer: Sniffer | None = None,
    ) -> None:
        super().__init__(None, _WINDOW_FLAGS)
        self._catalog = catalog
        self._clock = clock
        self._cursor = cursor
        self._sniffer = sniffer if sniffer is not None else Sniffer(self)
        self._sniffer.finished.connect(self.on_sniffed, Qt.ConnectionType.QueuedConnection)
        self._generation = 0
        self._geometry = WheelGeometry.for_size(size)
        self._session: WheelSession | None = None
        self._view: SessionView | None = None
        self._files: tuple[FileInfo, ...] = ()  # local files only, as planned
        self._gave_up_sent = False

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAcceptDrops(True)
        edge = WheelGeometry.for_size("L").window_size  # sized for the largest state (C1)
        self.setFixedSize(edge, edge)
        self.winId()  # create the native window now: RegisterDragDrop happens here

    # ----------------------------------------------------------------- state
    @property
    def session(self) -> WheelSession | None:
        return self._session

    @property
    def view(self) -> SessionView | None:
        return self._view

    @property
    def generation(self) -> int:
        """Counts DragEnters; a sniff result for an older generation is ignored."""
        return self._generation

    def drop_files(self) -> tuple[FileInfo, ...]:
        """The local files of the current drag, as last planned (sniffed when the sniff landed)."""
        return self._files

    @property
    def wheel_size(self) -> WheelSize:
        return next(s for s in ("S", "M", "L") if WheelGeometry.for_size(s) == self._geometry)

    def apply_size(self, size: WheelSize) -> None:
        """Change the wheel size. Only while hidden (U4): a visible wheel keeps its hit regions."""
        if self.isVisible():
            raise RuntimeError("the wheel size can only change while the wheel is hidden")
        self._geometry = WheelGeometry.for_size(size)

    def show_at(self, physical_xy: tuple[int, int], t_ns: int) -> None:
        """Show the wheel around the cursor, clamped so the disc stays on screen (phase-3 §2.1).

        ``physical_xy`` is where raw input saw the press; it is logged. Placement uses the logical
        cursor position, because Qt's windows are placed in logical, per-screen coordinates.
        """
        cursor = self._cursor()
        screen = QGuiApplication.screenAt(cursor) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        screen_rect = Rect(area.x(), area.y(), area.width(), area.height())
        center = self._geometry.clamp_center(Point(cursor.x(), cursor.y()), screen_rect)
        half = self.width() / 2
        self.move(round(center.x - half), round(center.y - half))
        arc = self._geometry.more_arc(center, screen_rect, MORE_ARC_MAX)
        self._session = WheelSession(
            self._geometry,
            appear_at=Point(cursor.x() - center.x, cursor.y() - center.y),
            t0_ns=t_ns,
            more_center_deg=arc.center_deg if arc is not None else 315.0,
        )
        self._view = self._session.tick(t_ns)
        self._files = ()
        self._gave_up_sent = False
        self.show()
        log.debug(
            "wheel shown: press at %s, cursor %s, center %s, screen %s",
            physical_xy,
            (cursor.x(), cursor.y()),
            (round(center.x), round(center.y)),
            screen.name(),
        )

    def hide_wheel(self) -> None:
        """Hide now and forget the session. S4 fades first; the fade still ends in ``hide()``."""
        self.hide()
        self._session = None
        self._view = None
        self._files = ()

    def tick(self, t_ns: int) -> None:
        """Time passes: dwell, spinner and give-up. Driven by the poller's samples."""
        if self._session is None:
            return
        self._set_view(self._session.tick(t_ns))

    # ----------------------------------------------------------------- drag events
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        force_copy(event)  # always: an ignored DragEnter gets no DragMove
        if self._session is None:
            return
        infos: list[FileInfo] = []
        for url in event.mimeData().urls():
            if url.isLocalFile():
                infos.append(FileInfo.from_path(Path(url.toLocalFile())))
            else:
                infos.append(FileInfo.from_path(Path(url.toString()), is_local=False))
        self._files = tuple(i for i in infos if i.is_local)
        plan = self._catalog.plan(infos)
        self._set_view(self._session.set_plan(plan))
        log.debug("DragEnter: %d url(s), plan %s", len(infos), plan.status)
        self._generation += 1
        self._sniffer.sniff(self._generation, infos)

    def on_sniffed(self, generation: int, infos: object) -> None:
        """The sniffer's result: re-plan with the real formats, unless it is stale."""
        if self._session is None or generation != self._generation:
            return
        if not isinstance(infos, tuple):
            return
        refined: tuple[FileInfo, ...] = infos
        self._files = tuple(i for i in refined if i.is_local)
        plan = self._catalog.plan(refined)
        self._set_view(self._session.set_plan(plan))
        log.debug("sniff landed: plan %s", plan.status)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._session is None:
            reject(event)
            return
        view = self._session.on_pointer(self._relative(event.position()), self._clock())
        self._set_view(view)
        if view.accepts_drop:
            force_copy(event)
        else:
            reject(event)

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        event.accept()
        self.drag_left.emit()

    def dropEvent(self, event: QDropEvent) -> None:
        with timed(log, "drop handler", DROP_BUDGET_MS):
            self._handle_drop(event)

    def _handle_drop(self, event: QDropEvent) -> None:
        if self._session is None:
            reject(event)
            return
        now = self._clock()
        decision = self._session.decide_drop(self._relative(event.position()), now)
        if isinstance(decision, Accept) and force_copy(event) is not None:
            assert_safe(event)
            self.drop_requested.emit(DropRequest(self._files, decision.target.id, now))
            return
        reject(event)
        self.cancelled.emit()

    # ----------------------------------------------------------------- helpers
    def _relative(self, pos: QPointF) -> Point:
        half = self.width() / 2
        return Point(pos.x() - half, pos.y() - half)

    def _set_view(self, view: SessionView) -> None:
        if view != self._view:
            if self._view is None or (view.region, view.hub.kind, view.hub.target) != (
                self._view.region,
                self._view.hub.kind,
                self._view.hub.target,
            ):
                region = view.region.kind.value
                if view.region.slot is not None:
                    region += ":" + view.region.slot.value
                elif view.region.item is not None:
                    region += f":{view.region.item}"
                target = view.hub.target.id if view.hub.target is not None else "-"
                log.debug("hover: %s hub=%s %s", region, view.hub.kind.value, target)
            self._view = view
            self.update()
        if view.hub.kind is HubKind.GAVE_UP and not self._gave_up_sent:
            self._gave_up_sent = True
            self.gave_up.emit()

    # ----------------------------------------------------------------- painting (S2 renderer)
    def paintEvent(self, event: QPaintEvent) -> None:
        g = self._geometry
        view = self._view
        c = QPointF(self.width() / 2, self.height() / 2)
        p = QPainter(self)

        # The floor first, without antialiasing: every pixel inside the halo has alpha ≥ 1.
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        self._fill_circle(p, c, g.halo_r, _FLOOR)

        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if view is not None and view.halo_edge_visible:
            p.setPen(QPen(_HALO_EDGE, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, g.halo_r - 1, g.halo_r - 1)
        self._fill_circle(p, c, g.slot_outer_r, _DISC)
        self._paint_slots(p, c, view)
        self._paint_more(p, c, view)
        self._fill_circle(p, c, g.hub_r, _HUB)
        self._paint_hub(p, c, view)
        p.end()

    @staticmethod
    def _fill_circle(p: QPainter, c: QPointF, r: float, color: QColor) -> None:
        path = QPainterPath()
        path.addEllipse(c, r, r)
        p.fillPath(path, color)

    def _paint_slots(self, p: QPainter, c: QPointF, view: SessionView | None) -> None:
        g = self._geometry
        plan = view.plan if view is not None else None
        p.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        for slot in SLOT_ORDER:
            angle = WheelGeometry.slot_angle(slot)
            mid = polar(angle, (g.slot_inner_r + g.slot_outer_r) / 2)
            hovered = (
                view is not None
                and view.highlight_slot
                and view.region.kind is RegionKind.SLOT
                and view.region.slot is slot
            )
            if hovered:
                wedge = QPainterPath()
                wedge.moveTo(c)
                r = g.slot_outer_r + 4  # the hovered slot stands 4 px proud (phase-3 §3)
                wedge.arcTo(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), 90 - angle - 21, 42)
                wedge.closeSubpath()
                p.fillPath(wedge, QColor(_ACCENT.red(), _ACCENT.green(), _ACCENT.blue(), 90))
            label = ""
            color = _SLOT_TEXT
            if plan is not None:
                state = plan.slots[slot]
                label = (
                    self.tr("More")
                    if slot is MORE_SLOT
                    else (state.target.label if state.target is not None else "")
                )
                if not state.enabled or not plan.ok:
                    color = _SLOT_DIM
            p.setPen(_ACCENT if hovered else color)
            p.drawText(
                QRectF(c.x() + mid.x - 40, c.y() + mid.y - 10, 80, 20),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )

    def _paint_more(self, p: QPainter, c: QPointF, view: SessionView | None) -> None:
        if view is None or view.more_arc is None or view.plan is None:
            return
        g = self._geometry
        arc = view.more_arc
        ring = QPainterPath()
        ring.addEllipse(c, g.more_outer_r, g.more_outer_r)
        ring.addEllipse(c, g.more_inner_r, g.more_inner_r)
        p.fillPath(ring, _DISC)
        for index, item in enumerate(view.plan.more):
            mid = polar(arc.item_angle(index), (g.more_inner_r + g.more_outer_r) / 2)
            hovered = view.region.kind is RegionKind.MORE_ITEM and view.region.item == index
            p.setPen(_ACCENT if hovered else (_SLOT_TEXT if item.enabled else _SLOT_DIM))
            p.drawText(
                QRectF(c.x() + mid.x - 30, c.y() + mid.y - 10, 60, 20),
                Qt.AlignmentFlag.AlignCenter,
                item.target.label if item.target is not None else "",
            )

    def _paint_hub(self, p: QPainter, c: QPointF, view: SessionView | None) -> None:
        r = self._geometry.hub_r
        p.setPen(QColor(255, 255, 255))
        p.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        text = self._hub_text(view.hub) if view is not None else ""
        p.drawText(
            QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r),
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
            text,
        )

    def _hub_text(self, hub: HubInfo) -> str:
        """Hub content as text. Keys only in core; the strings live here (D3, translatable)."""
        kind = hub.kind
        if kind is HubKind.WAITING:
            return ""
        if kind is HubKind.SPINNER:
            return "…"
        if kind is HubKind.GAVE_UP:
            return self.tr("Can't read this drag")
        if kind is HubKind.FILES:
            return self._files_text(hub.file_count)
        if kind is HubKind.TARGET and hub.target is not None:
            line = "→ " + hub.target.label
            if hub.skip_count:
                line += "\n" + self.tr("%n skipped", "", hub.skip_count)
            return line
        if kind is HubKind.DISABLED:
            return self._reason_text(hub.reason)
        if kind is HubKind.MORE:
            return self.tr("More")
        if kind is HubKind.CANCEL:
            return self.tr("✕ Cancel")
        if kind is HubKind.NOT_SUPPORTED:
            return self.tr("⊘ Not supported") + "\n" + self._reason_text(hub.reason)
        return ""

    def _files_text(self, count: int) -> str:
        if count == 1 and self._files:
            return self._files[0].path.name
        return self.tr("%n files", "", count)

    def _reason_text(self, reason: Reason | None) -> str:
        texts: dict[Reason, str] = {
            Reason.NO_FILES: self.tr("Nothing to convert"),
            Reason.FOLDER: self.tr("Folders aren't supported"),
            Reason.NOT_LOCAL: self.tr("Only local files"),
            Reason.ENGINE_MISSING: self.tr("Needs the HEIC engine"),
            Reason.ANIMATED: self.tr("Animated images aren't supported"),
            Reason.UNKNOWN_FORMAT: self.tr("Unknown format"),
            Reason.UNSUPPORTED_FORMAT: self.tr("Not a supported format"),
            Reason.NO_COMMON_FORMAT: self.tr("No common format"),
            Reason.IS_SOURCE: self.tr("Already this format"),
            Reason.CONVERT_FIRST: self.tr("Convert first"),
            Reason.NOT_FOR_THESE_FILES: self.tr("Not for these files"),
            Reason.NO_PLUGINS: self.tr("No plugins"),
        }
        return texts.get(reason, "") if reason is not None else ""
