"""``ToastManager``: shows ``ToastModel``s as ``ToastWidget``s (phase-3 §5, U6).

Rules (phase-3 §5, and the S5 review):

- Bottom-right of the screen where the drop happened, above the taskbar (the screen's *available*
  geometry), stacked upward, at most ``MAX_VISIBLE`` at a time; the oldest non-sticky toast makes
  room. The manager owns every toast's final position; the widgets only animate towards it.
- No focus, no activation (see ``widget.py``). ✕ dismisses; a button acts once and dismisses.
- A toast shown with a ``key`` replaces the toast that carries the same key: the working toast of
  a job gives way to its result. A working toast the user dismissed stays dismissed: later
  progress for that key shows nothing until the result arrives.
- ``show_later`` delays a toast (the single-file working toast, phase-3 §3); showing or cancelling
  the same key first drops it, so a quick job never flashes "working".
- **Never during a drag (C1).** While ``hold()`` is true (the app passes "the wheel is visible")
  nothing is shown: a new toast would be a topmost window over the wheel, and OLE would route
  the drag to it. Models queue until ``release()`` (the app wires the wheel's ``hidden`` to it).
- Layout direction follows the application (RTL-ready, D3a).
- The three action signals carry data only; the app does the work (``platform.shell`` for Show in
  folder, ``UndoRegistry`` for Undo, a dialog for Details): this package imports neither (P2).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QPoint, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QScreen

from morphwheel.ui.theme import Motion, Scheme, current_theme
from morphwheel.ui.toasts.model import ActionKind, ToastAction, ToastKind, ToastModel
from morphwheel.ui.toasts.widget import ToastWidget

log = logging.getLogger("morphwheel.ui.toasts")

MAX_VISIBLE = 3
MARGIN = 16  # logical px from the work-area edge
GAP = 8


@dataclass(frozen=True)
class _Pending:
    model: ToastModel
    screen: QScreen | None
    key: str | None


class ToastManager(QObject):
    undo_clicked = Signal(str)  # job_id (D5: the registry decides)
    show_in_folder_clicked = Signal(object)  # Path
    details_clicked = Signal(str)  # the full text
    settings_clicked = Signal(str)  # the settings page to open
    closed = Signal(str)  # the key of a toast the user closed (✕, a button, ``dismiss``, time)
    install_heic_clicked = Signal()  # the offer's Install (A6): the app asks for consent

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        screen_for: Callable[[], QScreen | None] | None = None,
        motion_enabled: Callable[[], bool] = lambda: True,
        high_contrast: Callable[[], bool] = lambda: False,
        scheme: Scheme | None = None,
        hold: Callable[[], bool] = lambda: False,
    ) -> None:
        """``motion_enabled`` and ``high_contrast`` are the Windows switches, read at each show;
        ``scheme`` pins Light or Dark (tests); ``hold`` says whether showing must wait (C1),
        and ``release`` is the slot to call when it may go on."""
        super().__init__(parent)
        self._visible: list[ToastWidget] = []
        self._screen_for = screen_for or QGuiApplication.primaryScreen
        self._motion_enabled = motion_enabled
        self._high_contrast = high_contrast
        self._scheme = scheme
        self._hold = hold
        self._later: dict[str, tuple[QTimer, _Pending]] = {}
        self._held: list[_Pending] = []
        self._suppressed: set[str] = set()  # keys whose working toast the user dismissed
        self._screen: QScreen | None = None  # where the stack is: the last drop's screen

    @property
    def visible(self) -> tuple[ToastWidget, ...]:
        return tuple(self._visible)

    @property
    def pending(self) -> tuple[str, ...]:
        """Keys with a delayed toast still waiting."""
        return tuple(self._later)

    @property
    def held(self) -> int:
        """Toasts waiting for the hold to end."""
        return len(self._held)

    # ----------------------------------------------------------------- showing
    def show(
        self, model: ToastModel, *, screen: QScreen | None = None, key: str | None = None
    ) -> ToastWidget | None:
        """Show a toast. With ``key``, replace the toast that has the same key.

        Returns the widget, or ``None`` when nothing shows yet (held, or a dismissed working
        toast's key).
        """
        self.cancel(key)
        if key is not None and model.kind is not ToastKind.WORKING:
            self._suppressed.discard(key)
        if key in self._suppressed:
            return None
        pending = _Pending(model, screen, key)
        if self._hold():
            self._held.append(pending)
            return None
        return self._show_now(pending)

    def release(self) -> None:
        """The hold ended (the wheel hid): show what waited, unless it is on again."""
        if self._hold():
            return
        held, self._held = self._held, []
        for pending in held:
            self.show(pending.model, screen=pending.screen, key=pending.key)

    def show_later(
        self,
        model: ToastModel,
        delay_ms: int,
        *,
        screen: QScreen | None = None,
        key: str,
    ) -> None:
        """Show ``model`` after ``delay_ms`` unless ``show`` or ``cancel`` names ``key`` first."""
        self.cancel(key)
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(self._fire_due)  # a bound method, never a lambda (see below)
        self._later[key] = (timer, _Pending(model, screen, key))
        timer.start(delay_ms)

    def cancel(self, key: str | None) -> None:
        """Drop the delayed toast for ``key``, if any."""
        if key is None:
            return
        entry = self._later.pop(key, None)
        if entry is not None:
            entry[0].stop()
            entry[0].deleteLater()

    def dismiss(self, key: str) -> None:
        """Take the toast with ``key`` away wherever it is: delayed, held, or on screen (it
        fades, then ``closed`` fires). A replacement by key and ``dismiss_all`` don't use this:
        they are not the user closing anything."""
        self.cancel(key)
        self._held = [p for p in self._held if p.key != key]
        toast = next((t for t in self._visible if t.key == key), None)  # at most one per key
        if toast is not None:
            toast.dismiss()  # idempotent while it fades

    def dismiss_all(self) -> None:
        """Hide everything at once (shutdown): no fades, no delayed or held toasts left."""
        for key in list(self._later):
            self.cancel(key)
        self._held.clear()
        for toast in list(self._visible):
            self._remove(toast)

    # ----------------------------------------------------------------- internals
    def _fire_due(self) -> None:
        """Show every delayed toast whose single-shot timer has gone off.

        The timers are children of the manager and are deleted later; a lambda slot capturing
        ``self`` would hold the manager's last reference from inside its own child, and the
        deferred delete of the child would then free the parent mid-destruction (a crash seen in
        the test suite). A bound method keeps no such reference.
        """
        due = [key for key, (timer, _) in self._later.items() if not timer.isActive()]
        for key in due:
            entry = self._later.pop(key)
            entry[0].deleteLater()
            pending = entry[1]
            self.show(pending.model, screen=pending.screen, key=pending.key)

    def _show_now(self, pending: _Pending) -> ToastWidget:
        model, screen, key = pending.model, pending.screen, pending.key
        existing = next((t for t in self._visible if key is not None and t.key == key), None)
        if existing is not None and existing.model.kind is model.kind is ToastKind.WORKING:
            before = existing.size()
            existing.update_model(model)
            existing.adjustSize()
            if existing.size() != before:  # progress text alone moves nothing
                self._relayout(screen)
            return existing
        if existing is not None:  # the undo toast lands where the stack is: its job's screen
            self._remove(existing)
        while len(self._visible) >= MAX_VISIBLE:
            victim = next((t for t in self._visible if not t.model.sticky), self._visible[0])
            self._remove(victim)
        theme = current_theme(self._high_contrast(), self._scheme)
        toast = ToastWidget(model, theme, Motion(self._motion_enabled()))
        toast.key = key
        toast.dismissed.connect(self._on_dismissed)
        toast.action_clicked.connect(self._on_action)
        self._visible.append(toast)
        self._relayout(screen)
        toast.appear()
        toast.start_countdown()
        log.debug("toast: %s %r", model.kind.value, model.title)
        return toast

    def _on_action(self, action: object) -> None:
        if not isinstance(action, ToastAction):
            return
        if action.kind is ActionKind.UNDO:
            self.undo_clicked.emit(str(action.payload))
        elif action.kind is ActionKind.SHOW_IN_FOLDER:
            self.show_in_folder_clicked.emit(action.payload)
        elif action.kind is ActionKind.DETAILS:
            self.details_clicked.emit(str(action.payload))
        elif action.kind is ActionKind.SETTINGS:
            self.settings_clicked.emit(str(action.payload))
        elif action.kind is ActionKind.INSTALL_HEIC:
            self.install_heic_clicked.emit()
        # DISMISS: nothing to route; the widget dismisses itself after any action

    def _on_dismissed(self, toast: object) -> None:
        if isinstance(toast, ToastWidget) and toast in self._visible:
            if toast.key is not None and toast.model.kind is ToastKind.WORKING:
                self._suppressed.add(toast.key)  # the user said no; progress stays quiet
            self._visible.remove(toast)
            toast.deleteLater()
            self._relayout(None)
            if toast.key is not None:
                self.closed.emit(toast.key)  # last: a slot may show or dismiss toasts itself

    def _remove(self, toast: ToastWidget) -> None:
        toast.dismissed.disconnect(self._on_dismissed)
        toast.action_clicked.disconnect(self._on_action)
        self._visible.remove(toast)
        toast.drop()
        toast.deleteLater()

    def _relayout(self, screen: QScreen | None) -> None:
        """Place the stack on ``screen``, or where it already is (a dismissal passes ``None``)."""
        self._screen = screen or self._screen or self._screen_for()
        screen = self._screen
        if screen is None:
            return
        area = screen.availableGeometry()
        bottom = area.bottom() - MARGIN
        right = area.right() - MARGIN
        for toast in reversed(self._visible):  # newest at the bottom
            toast.adjustSize()
            toast.place(QPoint(right - toast.width(), bottom - toast.height()))
            bottom -= toast.height() + GAP
