"""The settings window (phase-3 §6.2): a normal window bound to the ``SettingsStore``.

Rules:

- **Windows-settings style: no OK, no Cancel.** Every control shows the store's current value and
  writes a change at once through ``SettingsStore.update``; the store saves (RD-15) and tells
  every owner, this window included, through ``changed``.
- **One write per gesture, never one per step.** A slider commits through a short debounce timer
  that a release flushes, so key auto-repeat, the mouse wheel and a drag each cost one save. A
  spin box commits when editing finishes. Hiding the window flushes what is pending.
- **A refresh never fights an edit.** ``changed`` from elsewhere (the tray's Pause, a plugin
  toggle) refreshes every control except the one being edited: a slider that is held or still
  pending, a spin box that has the focus.
- **The Plugins page (S6, RD-27) shows the registry the app pushes** (``set_plugins``), as the
  HEIC row shows the engine state: the page never reads the plugins folder. A row's check box
  is the switch: unchecking writes ``plugins.enabled`` at once; checking never writes, it asks
  (``plugin_enable_requested``) and the app's trust prompt decides (§6.5). A drag, or Move up
  and Move down, writes ``plugins.order`` whole. Both writes derive from the store's value and
  the rows' ids, never from the check boxes. The push diffs the rows: the same ids keep their
  items (so a drop's own write never rebuilds the list under Qt's drop handler), a new id
  sequence rebuilds. Broken folders sit in a second, non-draggable list with a translated
  headline over the raw reason (RD-25).
- **A failed save is said once and cleared by the next success.** ``save_failed`` is kept until
  the ``changed`` that follows it draws the bar; a later successful save (the whole value is
  written each time) draws the load problems instead, or nothing.
- **The controls' user-only signals** (``activated``, ``buttonClicked``, ``clicked``,
  ``editingFinished``) drive the commits, so a refresh with ``setChecked``/``setCurrentIndex``
  never writes. A slider row refreshes under a ``QSignalBlocker`` and sets its label itself.
- **Bound methods only** as slots (see ``toasts/manager.py``): no lambda captures ``self``.
- A plain top-level ``QWidget`` (``Qt.WindowType.Window``), not a ``QDialog``: no default button
  that Enter in a spin box would click, no ``done`` loop. Esc and the close button hide it; the
  app lives in the tray. One window, reused: ``open_and_raise`` brings it back.
- This package imports no Win32 (P2): the app opens the window and passes the version and the
  repository link in. Every string goes through ``translate("Settings", …)``; the layout mirrors
  under RTL (D3a); no stylesheet, so High Contrast and the native style are Qt's.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Literal

from PySide6.QtCore import QCoreApplication, QModelIndex, QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QHideEvent, QKeyEvent, QKeySequence, QShowEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from morphwheel.core.catalog import MORE_ARC_MAX
from morphwheel.core.formats import FormatId
from morphwheel.i18n import QT_TRANSLATE_NOOP, translate
from morphwheel.plugins.discovery import BrokenKind, BrokenPlugin
from morphwheel.plugins.registry import PluginEntry, Registry
from morphwheel.settings.model import (
    LONGEST_SIDE_RANGE,
    QUALITY_RANGE,
    TRIGGER_KEYS,
    WHEEL_SIZES,
    Settings,
    WheelSize,
)
from morphwheel.settings.store import SettingsStore
from morphwheel.ui.dialogs import bring_to_front
from morphwheel.ui.text import trigger_key_label

log = logging.getLogger("morphwheel.ui.settings")

COMMIT_DELAY_MS = 300  # a slider's debounce: key repeat and the wheel become one save
PAGES = ("general", "conversion", "plugins", "about")
PLUGIN_ID_ROLE = Qt.ItemDataRole.UserRole
MAX_INPUTS_SHOWN = 3  # a row says "JPG, PNG, WebP… → TIFF", not the whole list
BROKEN_LIST_HEIGHT = 120  # a few two-line rows; the rest scroll
MIN_WIDTH = 640
MIN_HEIGHT = 420


class _SliderRow(QWidget):
    """A horizontal slider with its value beside it. ``committed`` fires once per gesture."""

    committed = Signal(int)

    def __init__(self, field: str, low: int, high: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.field = field  # the dataclass field this row writes (``Quality`` or ``Compress``)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(low, high)
        self.value_label = QLabel(str(low))
        self.value_label.setMinimumWidth(self.value_label.fontMetrics().horizontalAdvance("000"))
        self.value_label.setAlignment(
            Qt.AlignmentFlag.AlignTrailing | Qt.AlignmentFlag.AlignVCenter
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.slider, 1)
        row.addWidget(self.value_label, 0)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(COMMIT_DELAY_MS)
        self._timer.timeout.connect(self._commit)
        self.slider.valueChanged.connect(self._on_value)
        self.slider.sliderReleased.connect(self._on_released)

    @property
    def value(self) -> int:
        return self.slider.value()

    @property
    def pending(self) -> bool:
        """A commit is on its way (the debounce runs or the handle is held)."""
        return self._timer.isActive() or self.slider.isSliderDown()

    def set_value(self, value: int) -> None:
        """A refresh from the store; skipped while the user is on this slider."""
        if self.pending:
            return
        with QSignalBlocker(self.slider):  # no valueChanged: no debounce, no label
            self.slider.setValue(value)
        self.value_label.setText(str(value))

    def flush(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            self._commit()

    def _on_value(self, value: int) -> None:
        self.value_label.setText(str(value))
        self._timer.start()  # restarted on every step: one save per gesture

    def _on_released(self) -> None:
        self._timer.stop()
        self._commit()

    def _commit(self) -> None:
        self.committed.emit(self.slider.value())


HeicState = Literal["missing", "installing", "installed"]


class SettingsWindow(QWidget):
    heic_install_requested = Signal()  # the app asks for consent, then downloads (A6)
    heic_remove_requested = Signal()
    plugin_enable_requested = Signal(str)  # the plugin id; the app shows the trust prompt (§6.5)
    plugins_folder_requested = Signal()
    rescan_requested = Signal()

    def __init__(
        self,
        store: SettingsStore,
        *,
        version: str,
        repository_url: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self._store = store
        self._pending_error: str | None = None
        self._heic_state: HeicState = "missing"
        self.setWindowTitle(translate("Settings", "Morphwheel Settings"))
        self.setMinimumSize(MIN_WIDTH, MIN_HEIGHT)

        self.sidebar = QListWidget()
        self.sidebar.setMaximumWidth(160)
        self.pages = QStackedWidget()
        pages = (  # one table: the sidebar, the stack and ``PAGES`` stay in step
            ("general", translate("Settings", "General"), self._build_general()),
            ("conversion", translate("Settings", "Conversion"), self._build_conversion()),
            ("plugins", translate("Settings", "Plugins"), self._build_plugins()),
            ("about", translate("Settings", "About"), self._build_about(version, repository_url)),
        )
        assert tuple(name for name, _, _ in pages) == PAGES
        for _, label, page in pages:
            self.sidebar.addItem(label)
            self.pages.addWidget(page)
        self.sidebar.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.sidebar.setCurrentRow(0)

        self.info_bar = QLabel()
        self.info_bar.setWordWrap(True)
        self.info_bar.setTextFormat(Qt.TextFormat.PlainText)  # file paths are never markup
        self.info_bar.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.info_bar.hide()

        right = QVBoxLayout()
        right.addWidget(self.info_bar)
        right.addWidget(self.pages, 1)
        outer = QHBoxLayout(self)
        outer.addWidget(self.sidebar)
        outer.addLayout(right, 1)

        store.changed.connect(self._on_changed)
        store.save_failed.connect(self._on_save_failed)
        self._load(store.settings)
        self._draw_bar()

    # ----------------------------------------------------------------- pages
    def _build_general(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.trigger_key = QComboBox()
        self.trigger_key.addItems([trigger_key_label(k) for k in TRIGGER_KEYS])  # before connect
        self.trigger_key.activated.connect(self._on_trigger_key)  # user picks only
        form.addRow(translate("Settings", "Trigger key"), self.trigger_key)

        sizes = QWidget()
        sizes_row = QHBoxLayout(sizes)
        sizes_row.setContentsMargins(0, 0, 0, 0)
        self.wheel_size = QButtonGroup(self)
        labels = {
            "S": translate("Settings", "Small"),
            "M": translate("Settings", "Medium"),
            "L": translate("Settings", "Large"),
        }
        for index, size in enumerate(WHEEL_SIZES):
            button = QRadioButton(labels[size])
            self.wheel_size.addButton(button, index)
            sizes_row.addWidget(button)
        sizes_row.addStretch(1)
        self.wheel_size.buttonClicked.connect(self._on_wheel_size)  # one emission, user only
        form.addRow(translate("Settings", "Wheel size"), sizes)

        self.start_with_windows = QCheckBox(
            translate("Settings", "Start Morphwheel when I sign in")
        )
        self.start_with_windows.clicked.connect(self._on_start_with_windows)
        form.addRow(translate("Settings", "Start with Windows"), self.start_with_windows)

        tip = QLabel(
            translate(
                "Settings",
                "Tip: press the trigger key after you start dragging. Pressing Shift before "
                "clicking selects a range of files in File Explorer.",
            )
        )
        tip.setWordWrap(True)
        form.addRow(tip)
        return page

    def _build_conversion(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        low, high = QUALITY_RANGE
        rows = {}
        for field, label in (
            ("jpeg", translate("Settings", "JPG quality")),
            ("webp", translate("Settings", "WebP quality")),
            ("avif", translate("Settings", "AVIF quality")),
        ):
            rows[field] = _SliderRow(field, low, high)
            rows[field].committed.connect(self._on_quality)
            form.addRow(label, rows[field])
        self.jpeg_quality, self.webp_quality, self.avif_quality = rows.values()

        preset = QGroupBox(translate("Settings", "Compress preset"))
        preset_form = QFormLayout(preset)
        self.longest_side = QSpinBox()
        self.longest_side.setRange(*LONGEST_SIDE_RANGE)
        self.longest_side.setSuffix(translate("Settings", " px"))
        self.longest_side.editingFinished.connect(self._on_longest_side)
        preset_form.addRow(translate("Settings", "Longest side"), self.longest_side)
        self.compress_quality = _SliderRow("quality", low, high)
        self.compress_quality.committed.connect(self._on_compress)
        preset_form.addRow(translate("Settings", "Quality"), self.compress_quality)
        form.addRow(preset)

        heic = QWidget()  # A6: the opt-in engine; the app does the download and tells the state
        heic_row = QHBoxLayout(heic)
        heic_row.setContentsMargins(0, 0, 0, 0)
        self.heic_status = QLabel()
        self.heic_button = QPushButton()
        self.heic_button.setAutoDefault(False)
        self.heic_button.clicked.connect(self._on_heic_button)
        heic_row.addWidget(self.heic_status, 1)
        heic_row.addWidget(self.heic_button, 0)
        form.addRow(translate("Settings", "HEIC support"), heic)
        self.set_heic_state("missing")
        return page

    def _build_plugins(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        self.plugin_list = QListWidget()  # one row per third-party plugin, in arc order
        self.plugin_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.plugin_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.plugin_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.plugin_list.itemChanged.connect(self._on_plugin_item_changed)
        self.plugin_list.currentRowChanged.connect(self._update_move_buttons)
        self.plugin_list.model().rowsMoved.connect(self._on_plugin_rows_moved)
        column.addWidget(self.plugin_list, 1)
        self.plugins_empty = QLabel(
            translate(
                "Settings",
                "No plugins installed. Copy a plugin folder into the plugins folder, then click "
                "Rescan.",
            )
        )
        self.plugins_empty.setWordWrap(True)
        column.addWidget(self.plugins_empty)
        order_row = QHBoxLayout()
        self.move_up = QPushButton(translate("Settings", "Move up"))
        self.move_up.setAutoDefault(False)
        self.move_up.setShortcut(QKeySequence("Alt+Up"))
        self.move_up.clicked.connect(self._on_move_up)
        self.move_down = QPushButton(translate("Settings", "Move down"))
        self.move_down.setAutoDefault(False)
        self.move_down.setShortcut(QKeySequence("Alt+Down"))
        self.move_down.clicked.connect(self._on_move_down)
        self.arc_note = QLabel()
        self.arc_note.setWordWrap(True)
        order_row.addWidget(self.move_up, 0)
        order_row.addWidget(self.move_down, 0)
        order_row.addWidget(self.arc_note, 1)
        column.addLayout(order_row)
        hint = QLabel(
            translate(
                "Settings",
                "The order of the rows is the order of the More arc: drag a row, or use Move up "
                "and Move down. A check box enables a plugin.",
            )
        )
        hint.setWordWrap(True)
        column.addWidget(hint)
        self.broken_label = QLabel(translate("Settings", "Folders that aren't usable plugins:"))
        self.broken_list = QListWidget()  # selectable, so a reason can be read and copied
        self.broken_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.broken_list.setWordWrap(True)
        self.broken_list.setMaximumHeight(BROKEN_LIST_HEIGHT)  # the plugin rows keep the room
        column.addWidget(self.broken_label)
        column.addWidget(self.broken_list)
        self.folder_error = QLabel()  # the plugins folder itself can't be used
        self.folder_error.setWordWrap(True)
        self.folder_error.setTextFormat(Qt.TextFormat.PlainText)
        column.addWidget(self.folder_error)
        buttons = QHBoxLayout()
        self.open_plugins_folder = QPushButton(translate("Settings", "Open plugins folder"))
        self.open_plugins_folder.setAutoDefault(False)
        self.open_plugins_folder.clicked.connect(self.plugins_folder_requested)
        self.rescan = QPushButton(translate("Settings", "Rescan"))
        self.rescan.setAutoDefault(False)
        self.rescan.clicked.connect(self.rescan_requested)
        buttons.addWidget(self.open_plugins_folder, 0)
        buttons.addWidget(self.rescan, 0)
        buttons.addStretch(1)
        column.addLayout(buttons)
        warning = QLabel(
            translate(
                "Settings",
                "Plugins are Python code that runs with your permissions. Only enable plugins "
                "you trust.",
            )
        )
        warning.setWordWrap(True)
        column.addWidget(warning)
        self._show_plugin_rows((), (), None)
        return page

    def _build_about(self, version: str, repository_url: str) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        title = QLabel(translate("Settings", "Morphwheel %1").replace("%1", version))
        font = title.font()
        font.setPointSize(font.pointSize() + 4)
        font.setWeight(font.Weight.DemiBold)
        title.setFont(font)
        column.addWidget(title)
        blurb = QLabel(
            translate(
                "Settings",
                "Drag a file in File Explorer, press the trigger key, and drop it on a format. "
                "Open source under the MIT license.",
            )
        )
        blurb.setWordWrap(True)
        column.addWidget(blurb)
        self.links = QLabel(
            translate(
                "Settings", '<a href="%1">Project page</a> · <a href="%2">Report a problem</a>'
            )
            .replace("%1", repository_url)
            .replace("%2", repository_url.rstrip("/") + "/issues")
        )
        self.links.setTextFormat(Qt.TextFormat.RichText)  # our own text, never a file name
        self.links.setOpenExternalLinks(True)
        column.addWidget(self.links)
        folder = QLabel(
            translate("Settings", "Settings file: %1").replace("%1", str(self._store.path))
        )
        folder.setTextFormat(Qt.TextFormat.PlainText)
        folder.setWordWrap(True)
        folder.setLayoutDirection(Qt.LayoutDirection.LeftToRight)  # a path reads LTR under RTL
        folder.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        column.addWidget(folder)
        column.addStretch(1)
        return page

    # ----------------------------------------------------------------- navigation
    @property
    def page(self) -> str:
        return PAGES[self.pages.currentIndex()]

    def select_page(self, name: str) -> None:
        self.sidebar.setCurrentRow(PAGES.index(name))

    def open_and_raise(self) -> None:
        """Show, or bring the one window back: it may be hidden, minimized or behind others."""
        bring_to_front(self)

    # ----------------------------------------------------------------- the HEIC engine (A6)
    def set_heic_state(self, state: HeicState) -> None:
        """What the row says and offers: the app knows whether the engine is there."""
        self._heic_state = state
        texts = {
            "missing": (translate("Settings", "Not installed"), translate("Settings", "Install…")),
            "installing": (translate("Settings", "Installing…"), translate("Settings", "Install…")),
            "installed": (translate("Settings", "Installed"), translate("Settings", "Remove")),
        }
        status, button = texts[state]
        self.heic_status.setText(status)
        self.heic_button.setText(button)
        self.heic_button.setEnabled(state != "installing")

    @property
    def heic_state(self) -> HeicState:
        return self._heic_state

    # ----------------------------------------------------------------- the plugins (S6)
    def set_plugins(self, registry: Registry, folder_error: str | None = None) -> None:
        """What the rows show: the app pushes the registry at build and after every rebuild."""
        self._show_plugin_rows(registry.third_party, registry.broken, folder_error)
        overflow = registry.more_overflow
        if overflow:
            note = translate(
                "Settings", "%n enabled target(s) left out of the More arc.", None, overflow
            )
        else:
            note = translate("Settings", "The More arc shows up to %1 targets.").replace(
                "%1", str(MORE_ARC_MAX)
            )
        self.arc_note.setText(note)

    def plugin_rows(self) -> tuple[tuple[str, bool], ...]:
        """``(id, checked)`` per row, top to bottom (for the app's tests and the page itself)."""
        return tuple(
            (
                str(self.plugin_list.item(i).data(PLUGIN_ID_ROLE)),
                self.plugin_list.item(i).checkState() == Qt.CheckState.Checked,
            )
            for i in range(self.plugin_list.count())
        )

    def _show_plugin_rows(
        self,
        entries: tuple[PluginEntry, ...],
        broken: tuple[BrokenPlugin, ...],
        folder_error: str | None,
    ) -> None:
        ids = [e.id for e in entries]
        shown = [plugin_id for plugin_id, _ in self.plugin_rows()]
        with QSignalBlocker(self.plugin_list):  # a refresh never writes
            if ids != shown:  # a new sequence: rebuild, keeping the current row by id
                current = self.plugin_list.currentItem()
                current_id = current.data(PLUGIN_ID_ROLE) if current is not None else None
                self.plugin_list.clear()
                for entry in entries:
                    item = QListWidgetItem()
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setData(PLUGIN_ID_ROLE, entry.id)
                    self.plugin_list.addItem(item)
                    if entry.id == current_id:
                        self.plugin_list.setCurrentItem(item)
            for row, entry in enumerate(entries):  # the same items: texts and checks only
                item = self.plugin_list.item(row)
                item.setText(_plugin_row_text(entry))
                item.setCheckState(
                    Qt.CheckState.Checked if entry.enabled else Qt.CheckState.Unchecked
                )
        self.plugin_list.setVisible(bool(entries))
        self.plugins_empty.setVisible(not entries)
        self.broken_list.clear()
        for b in broken:
            self.broken_list.addItem(
                f"⚠ {b.directory.name}: {_broken_headline(b.kind)}\n{b.reason}"
            )
        self.broken_label.setVisible(bool(broken))
        self.broken_list.setVisible(bool(broken))
        if folder_error:
            text = translate("Settings", "The plugins folder can't be used: %1")
            self.folder_error.setText("⚠ " + text.replace("%1", folder_error))
        self.folder_error.setVisible(bool(folder_error))
        self._update_move_buttons()

    def _on_plugin_item_changed(self, item: QListWidgetItem) -> None:
        plugin_id = item.data(PLUGIN_ID_ROLE)
        if not isinstance(plugin_id, str):
            return  # a row still being built by a drop
        prefs = self._store.settings.plugins  # the truth the rows were drawn from
        checked = item.checkState() == Qt.CheckState.Checked
        if checked == (plugin_id in prefs.enabled):
            return  # a text or data change, or a drop's copy: not a switch
        if checked:
            with QSignalBlocker(self.plugin_list):
                item.setCheckState(Qt.CheckState.Unchecked)  # the trust prompt decides (§6.5)
            self.plugin_enable_requested.emit(plugin_id)
            return
        enabled = tuple(i for i in prefs.enabled if i != plugin_id)
        self._store.update(plugins=replace(prefs, enabled=enabled))

    def _on_plugin_rows_moved(self) -> None:
        # After the drop has fully landed (Qt's handler is still on the stack here).
        QTimer.singleShot(0, self._commit_plugin_order)

    def _commit_plugin_order(self) -> None:
        order = tuple(plugin_id for plugin_id, _ in self.plugin_rows())
        prefs = self._store.settings.plugins
        if order != prefs.order:
            self._store.update(plugins=replace(prefs, order=order))

    def _on_move_up(self) -> None:
        self._move_current_row(-1)

    def _on_move_down(self) -> None:
        self._move_current_row(+1)

    def _move_current_row(self, delta: int) -> None:
        row = self.plugin_list.currentRow()
        target = row + delta
        if row < 0 or not 0 <= target < self.plugin_list.count():
            return
        # moveRow's destination counts rows before the move: one past the target going down.
        destination = target if delta < 0 else target + 1
        self.plugin_list.model().moveRow(QModelIndex(), row, QModelIndex(), destination)
        self.plugin_list.setCurrentRow(target)  # Space and the arrows keep working
        self._update_move_buttons()  # the current index moved with the item: no signal

    def _update_move_buttons(self) -> None:
        row = self.plugin_list.currentRow()
        self.move_up.setEnabled(row > 0)
        self.move_down.setEnabled(0 <= row < self.plugin_list.count() - 1)

    def _on_heic_button(self) -> None:
        if self._heic_state == "installed":
            self.heic_remove_requested.emit()
        elif self._heic_state == "missing":
            self.heic_install_requested.emit()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)

    def showEvent(self, event: QShowEvent) -> None:
        self._load(self._store.settings)  # whatever changed while hidden
        self._draw_bar()
        super().showEvent(event)

    def hideEvent(self, event: QHideEvent) -> None:
        for row in self._slider_rows():
            row.flush()  # a slider still debouncing: save now
        super().hideEvent(event)

    # ----------------------------------------------------------------- the store → the controls
    def _slider_rows(self) -> tuple[_SliderRow, ...]:
        return (self.jpeg_quality, self.webp_quality, self.avif_quality, self.compress_quality)

    def _load(self, settings: Settings) -> None:
        """Every control except the one being edited; see the module docstring."""
        self.trigger_key.setCurrentIndex(TRIGGER_KEYS.index(settings.trigger_key))
        button = self.wheel_size.button(WHEEL_SIZES.index(settings.wheel_size))
        if button is not None:
            button.setChecked(True)
        self.start_with_windows.setChecked(settings.start_with_windows)
        self.jpeg_quality.set_value(settings.quality.jpeg)
        self.webp_quality.set_value(settings.quality.webp)
        self.avif_quality.set_value(settings.quality.avif)
        if not self.longest_side.hasFocus():  # typing in progress: theirs wins
            self.longest_side.setValue(settings.compress.longest_side)
        self.compress_quality.set_value(settings.compress.quality)

    def _on_changed(self, settings: Settings) -> None:
        if not self.isVisible():  # nothing to keep in step; showEvent catches up
            return
        self._load(settings)
        self._draw_bar()
        self._pending_error = None

    def _on_save_failed(self, reason: str) -> None:
        self._pending_error = reason  # drawn by the ``changed`` that follows it

    def _draw_bar(self) -> None:
        if self._pending_error is not None:
            text = "⚠ " + translate(
                "Settings",
                "Couldn't save the settings: %1. The change is in force until Morphwheel quits.",
            ).replace("%1", self._pending_error)
        elif self._store.problems:
            text = (
                translate("Settings", "Some settings fell back to their defaults:")
                + "\n"
                + "\n".join(self._store.problems)
            )
        else:
            text = ""
        self.info_bar.setText(text)
        self.info_bar.setVisible(bool(text))

    # ----------------------------------------------------------------- the controls → the store
    def _on_trigger_key(self, index: int) -> None:
        self._store.update(trigger_key=TRIGGER_KEYS[index])

    def _on_wheel_size(self, button: QAbstractButton) -> None:
        size: WheelSize = WHEEL_SIZES[self.wheel_size.id(button)]
        self._store.update(wheel_size=size)

    def _on_start_with_windows(self, checked: bool) -> None:
        self._store.update(start_with_windows=checked)

    def _on_quality(self, value: int) -> None:
        row = self.sender()
        if isinstance(row, _SliderRow):
            self._store.update(quality=replace(self._store.settings.quality, **{row.field: value}))

    def _on_compress(self, value: int) -> None:
        row = self.sender()
        if isinstance(row, _SliderRow):
            compress = replace(self._store.settings.compress, **{row.field: value})
            self._store.update(compress=compress)

    def _on_longest_side(self) -> None:
        compress = replace(self._store.settings.compress, longest_side=self.longest_side.value())
        self._store.update(compress=compress)


# --------------------------------------------------------------------------- plugin rows
def _plugin_row_text(entry: PluginEntry) -> str:
    """``Name 1.2  ·  JPG, PNG → TIFF``: the labels the wheel uses, the inputs capped."""
    targets = entry.manifest.targets
    accepted = {f for t in targets for f in t.accepts}
    inputs = [f.label for f in FormatId if f in accepted]
    if len(inputs) > MAX_INPUTS_SHOWN:
        inputs = [*inputs[:MAX_INPUTS_SHOWN], "…"]
    outputs = ", ".join(t.label for t in targets)
    plugin = entry.manifest.plugin
    return f"{plugin.name} {plugin.version}  ·  {', '.join(inputs)} → {outputs}"


_BROKEN_HEADLINES: dict[BrokenKind, str] = {  # one per kind: a test holds it complete
    BrokenKind.LINK: QT_TRANSLATE_NOOP("Settings", "Links aren't followed; copy the folder here"),
    BrokenKind.NO_MANIFEST: QT_TRANSLATE_NOOP("Settings", "No plugin.toml"),
    BrokenKind.MISPLACED: QT_TRANSLATE_NOOP(
        "Settings", "plugin.toml must be inside a plugin folder"
    ),
    BrokenKind.INVALID: QT_TRANSLATE_NOOP("Settings", "The manifest is invalid"),
    BrokenKind.NAME_MISMATCH: QT_TRANSLATE_NOOP(
        "Settings", "The folder name doesn't match the plugin id"
    ),
    BrokenKind.ID_TAKEN: QT_TRANSLATE_NOOP("Settings", "Another plugin has this id"),
    BrokenKind.MODULE_CLASH: QT_TRANSLATE_NOOP(
        "Settings", "The plugin's module name is used by another plugin"
    ),
    BrokenKind.ERROR: QT_TRANSLATE_NOOP("Settings", "Can't read this plugin"),
}


def _broken_headline(kind: BrokenKind) -> str:
    """The translated line over a broken folder's raw reason (RD-25)."""
    return QCoreApplication.translate("Settings", _BROKEN_HEADLINES[kind])
