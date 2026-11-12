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

from PySide6.QtCore import QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QHideEvent, QKeyEvent, QShowEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from morphwheel.i18n import translate
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
PAGES = ("general", "conversion", "about")
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
