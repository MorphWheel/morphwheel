"""``WheelWindow``: the one window shown during a drag, and the only drop target (phase-4 §4.6).

It is pre-created (``winId()`` at construction registers the OLE drop target), sized for the largest
wheel (phase-3 C1), translucent, and never takes focus. It owns a ``WheelSession`` per appearance
and turns OLE's events into the session's inputs. The look comes from ``renderer.py`` (the theme's
tokens, a cached content layer) and the motion from ``animator.py`` (S4).

Safety rules, all of them tested offscreen:

- **DragEnter always goes through ``force_copy``,** even before arming, even without a session
  (carry-over from S1): a window that ignores DragEnter gets no DragMove from Qt.
- **DragMove and Drop are accepted only when ``SessionView.accepts_drop`` says so,** through
  ``force_copy``; everything else is ``reject``. Without a session (the wheel is fading, or an
  event already in flight arrives after it hid) both are rejected.
- **No drop is ever accepted as Move.** ``assert_safe`` runs before a ``DropRequest`` leaves.
- **The drop handler does only the decision and the emit** (under 5 ms, phase-2 §4). The
  controller connects the signals queued, so hiding, logging and the job start happen after
  ``IDropTarget::Drop`` has returned.
- **DragEnter does no I/O:** it reads ``urls()`` only, and plans by extension. The header sniff
  runs on the ``Sniffer`` thread (S3) and lands as a second ``set_plan`` through a queued signal,
  unless the wheel hid or a newer DragEnter came in the meantime (a generation number). The second
  plan keeps arming, hover and the More state (the session does), and the animator keeps the bulge.
- **Alpha floor (C2, C3).** ``paintEvent`` paints the floor first, before anything else is even
  computed: every pixel inside the halo has alpha ≥ 1 in every frame, whatever the animation does
  and even if the content painter fails. The window's own opacity is never touched.
- **Every fade ends in ``hide()``** (C3): the animator's ``finished`` hides the window, and a
  real-time backstop fires if frames stop coming. While fading, the session is already gone
  (events are rejected) but the last view stays frozen, so the fade shows the wheel as it was.
- **Hide clears the session.** Each ``show_at`` starts a new session (new arming, new timers), cuts
  any fade short and appears from the current opacity, and re-reads the theme and the motion switch.

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

from PySide6.QtCore import QPoint, QPointF, Qt, Signal
from PySide6.QtGui import (
    QCursor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QGuiApplication,
    QPainter,
    QPaintEvent,
)
from PySide6.QtWidgets import QWidget

from morphwheel.core.catalog import MORE_ARC_MAX, Catalog, Reason, SlotPos
from morphwheel.core.formats import FileInfo
from morphwheel.core.geometry import Point, Rect, RegionKind, WheelGeometry
from morphwheel.core.gesture import HideReason
from morphwheel.core.jobs import DropRequest
from morphwheel.core.wheel_session import Accept, HubInfo, HubKind, SessionView, WheelSession
from morphwheel.logs import timed
from morphwheel.ui.theme import Scheme, Theme, detect_scheme, system_accent
from morphwheel.ui.wheel.animator import WheelAnimator
from morphwheel.ui.wheel.drop_guard import assert_safe, force_copy, reject
from morphwheel.ui.wheel.renderer import (
    Content,
    Frame,
    HubText,
    WheelRenderer,
    item_labels,
    slot_labels,
)
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
        motion_enabled: Callable[[], bool] = lambda: True,
        high_contrast: Callable[[], bool] = lambda: False,
        scheme: Scheme | None = None,
        real_time: bool = True,
    ) -> None:
        """``motion_enabled`` and ``high_contrast`` are the Windows switches, read at each show
        (``app`` passes ``platform.system``'s; this package imports no Win32). ``scheme`` pins Light
        or Dark (tests); ``None`` follows the platform; High Contrast wins over both. ``real_time=
        False`` turns off the frame timer and the fade backstop, so tests drive ``animate()``."""
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
        self._dropped_slot: SlotPos | None = None  # for the flash, between the drop and the hide
        self._high_contrast = high_contrast
        self._fixed_scheme = scheme
        self._theme = self._build_theme()
        self._renderer = WheelRenderer()
        self._animator = WheelAnimator(motion_enabled, clock, real_time=real_time, parent=self)
        self._animator.frame_ready.connect(self.update)
        self._animator.finished.connect(self._on_fade_finished)
        self._paint_failed = False
        self._paint_ms: list[float] = []  # per appearance, summarized at hide (M2 check 6)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAcceptDrops(True)
        edge = WheelGeometry.for_size("L").window_size  # sized for the largest state (C1)
        self.setFixedSize(edge, edge)
        self.winId()  # create the native window now: RegisterDragDrop happens here
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_scheme_changed)

    # ----------------------------------------------------------------- state
    @property
    def session(self) -> WheelSession | None:
        return self._session

    @property
    def view(self) -> SessionView | None:
        """The last view; it stays while the wheel fades, so the fade shows the wheel as it was."""
        return self._view

    @property
    def generation(self) -> int:
        """Counts appearances and DragEnters; a sniff result for an older generation is ignored."""
        return self._generation

    @property
    def theme(self) -> Theme:
        return self._theme

    @property
    def frame(self) -> Frame:
        """The animation state right now (the animator is the one source of truth)."""
        return self._animator.frame(self._clock())

    @property
    def fading(self) -> bool:
        return self._animator.dismissing

    def content(self) -> Content:
        """What the renderer is given, strings included."""
        view = self._view
        plan = view.plan if view is not None else None
        hub = self._hub_text(view.hub) if view is not None else HubText()
        return Content(view, hub, slot_labels(plan, self.tr("More")), item_labels(plan))

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
        self._theme = self._build_theme()  # the accent can change without a scheme signal
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
        self._generation += 1  # a sniff from the previous drag can't land on this session
        self._view = None
        self._files = ()
        self._gave_up_sent = False
        self._dropped_slot = None
        self._paint_ms = []
        self._animator.appear(t_ns)  # cuts a running fade short, without hiding
        self._set_view(self._session.tick(t_ns), t_ns)
        self.show()
        self.update()
        log.debug(
            "wheel shown: press at %s, cursor %s, center %s, screen %s, motion %s, theme %s",
            physical_xy,
            (cursor.x(), cursor.y()),
            (round(center.x), round(center.y)),
            screen.name(),
            "on" if self._animator.motion.enabled else "off",
            self._theme.scheme.value,
        )

    def hide_wheel(self, reason: HideReason | None = None) -> None:
        """End the session now and fade out; the fade ends in ``hide()`` (C3).

        After a drop the slot flashes first, then the wheel shrinks and fades (phase-3 §8). With
        animations off everything happens at once. A second call while fading changes nothing.
        """
        if self._session is None:
            return  # hidden, or already fading
        self._session = None  # from here on DragMove and Drop are rejected; the view stays
        slot = self._dropped_slot if reason is HideReason.DROPPED else None
        self._animator.dismiss(reason, self._clock(), slot)  # may finish synchronously
        self.update()

    def tick(self, t_ns: int) -> None:
        """Time passes: dwell, spinner and give-up. Driven by the poller's samples."""
        if self._session is None:
            return
        self._set_view(self._session.tick(t_ns), t_ns)

    def animate(self) -> None:
        """One animation step at the clock's time: what the frame timer does (tests call it)."""
        self._animator.step()

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
        self._set_view(self._session.set_plan(plan), self._clock())
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
        self._set_view(self._session.set_plan(plan), self._clock())
        log.debug("sniff landed: plan %s", plan.status)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._session is None:
            reject(event)
            return
        now = self._clock()
        view = self._session.on_pointer(self._relative(event.position()), now)
        self._set_view(view, now)
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
            self._dropped_slot = decision.slot  # flashes when the controller hides (phase-3 §8)
            self.drop_requested.emit(DropRequest(self._files, decision.target.id, now))
            return
        reject(event)
        self.cancelled.emit()

    # ----------------------------------------------------------------- helpers
    def _relative(self, pos: QPointF) -> Point:
        half = self.width() / 2
        return Point(pos.x() - half, pos.y() - half)

    def _set_view(self, view: SessionView, t_ns: int) -> None:
        prev = self._view
        if view != prev:
            if prev is None or (view.region, view.hub.kind, view.hub.target) != (
                prev.region,
                prev.hub.kind,
                prev.hub.target,
            ):
                region = view.region.kind.value
                if view.region.slot is not None:
                    region += ":" + view.region.slot.value
                elif view.region.item is not None:
                    region += f":{view.region.item}"
                target = view.hub.target.id if view.hub.target is not None else "-"
                log.debug("hover: %s hub=%s %s", region, view.hub.kind.value, target)
            self._view = view
            self._feed_animator(view, t_ns)
            self.update()
        if view.hub.kind is HubKind.GAVE_UP and not self._gave_up_sent:
            self._gave_up_sent = True
            self.gave_up.emit()

    def _feed_animator(self, view: SessionView, t_ns: int) -> None:
        if view.plan is not None:
            self._animator.plan_arrived(t_ns)  # a no-op after the first plan
        slot: SlotPos | None = None
        item: int | None = None
        if view.highlight_slot:  # not the region alone: arming and a disabled flip matter
            if view.region.kind is RegionKind.SLOT:
                slot = view.region.slot
            elif view.region.kind is RegionKind.MORE_ITEM:
                item = view.region.item
        self._animator.hover(slot, item, t_ns)
        self._animator.more(view.more_arc, t_ns)
        self._animator.halo_edge(view.halo_edge_visible, t_ns)

    def _on_fade_finished(self, token: int) -> None:
        if self._session is not None:
            return  # defensive: appear() cancels a dismiss, so a live session never sees this
        self.hide()
        self._view = None
        self._files = ()
        if self._paint_ms:
            log.debug(
                "wheel hidden (fade %d): %d frames painted, mean %.1f ms, max %.1f ms",
                token,
                len(self._paint_ms),
                sum(self._paint_ms) / len(self._paint_ms),
                max(self._paint_ms),
            )
        else:
            log.debug("wheel hidden (fade %d)", token)

    # ----------------------------------------------------------------- theme
    def _build_theme(self) -> Theme:
        if self._high_contrast():
            scheme = Scheme.HIGH_CONTRAST
        elif self._fixed_scheme is not None:
            scheme = self._fixed_scheme
        else:
            scheme = detect_scheme(QGuiApplication.styleHints())
        palette = QGuiApplication.palette()
        return Theme.build(scheme, accent=system_accent(palette), system=palette)

    def _on_scheme_changed(self) -> None:
        self._theme = self._build_theme()
        self.update()

    # ----------------------------------------------------------------- painting
    def paintEvent(self, event: QPaintEvent) -> None:
        started = time.perf_counter()
        p = QPainter(self)
        # The floor first and alone, before anything that could fail: this is what catches (C2).
        self._renderer.paint_floor(p, self.size(), self._geometry)
        try:
            self._renderer.paint_content(
                p,
                self.size(),
                self.devicePixelRatioF(),
                self._theme,
                self._geometry,
                self.content(),
                self.frame,
            )
        except Exception:  # a painting bug must never leave the window transparent (C3)
            if not self._paint_failed:
                self._paint_failed = True
                log.exception("wheel content failed to paint; the floor still catches")
        p.end()
        self._paint_ms.append((time.perf_counter() - started) * 1000)

    def _hub_text(self, hub: HubInfo) -> HubText:
        """Hub content as two lines. Keys only in core; the strings live here (D3, translatable)."""
        kind = hub.kind
        if kind is HubKind.WAITING:
            return HubText()
        if kind is HubKind.SPINNER:
            return HubText("…")
        if kind is HubKind.GAVE_UP:
            return HubText(self.tr("Can't read this drag"))
        if kind is HubKind.FILES:
            if hub.file_count == 1 and self._files:
                return HubText(self._files[0].path.name, self._files_text(1))
            return HubText(self._files_text(hub.file_count))
        if kind is HubKind.TARGET and hub.target is not None:
            bottom = self._files_text(hub.file_count)
            if hub.skip_count:
                bottom += ", " + self._skipped_text(hub.skip_count)
            return HubText("→ " + hub.target.label, bottom)
        if kind is HubKind.DISABLED:
            if hub.reason is Reason.IS_SOURCE and hub.target is not None:
                return HubText(self.tr("{format} is the source").format(format=hub.target.label))
            return HubText(self._reason_text(hub.reason))
        if kind is HubKind.MORE:
            return HubText(self.tr("More"))
        if kind is HubKind.CANCEL:
            return HubText(self.tr("✕ Cancel"))
        if kind is HubKind.NOT_SUPPORTED:
            return HubText(self.tr("⊘ Not supported"), self._reason_text(hub.reason))
        return HubText()

    def _files_text(self, count: int) -> str:
        """Correct English without a translator; ``%n`` keeps the plural forms for translations."""
        return self.tr("1 file") if count == 1 else self.tr("%n files", "", count)

    def _skipped_text(self, count: int) -> str:
        return self.tr("1 skipped") if count == 1 else self.tr("%n skipped", "", count)

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
            Reason.NO_PLUGINS: self.tr("No plugins enabled"),
        }
        return texts.get(reason, "") if reason is not None else ""
