"""``ui.settings_window``: the controls mirror the store, each gesture writes once, a refresh
never fights an edit, the bars, Esc, RTL (phase-3 §6.2, RD-15)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

import morphwheel.settings.store as store_module
from conftest import render_widget
from morphwheel.plugins.discovery import BrokenKind, BrokenPlugin, Discovery
from morphwheel.plugins.manifest import builtin_manifest, parse_manifest
from morphwheel.plugins.registry import Registry, build_registry
from morphwheel.settings.model import Compress, PluginPrefs, Quality, Settings
from morphwheel.settings.store import SettingsStore, load_settings, save_settings
from morphwheel.ui.settings_window import (
    _BROKEN_HEADLINES,
    COMMIT_DELAY_MS,
    PAGES,
    SettingsWindow,
)

pytestmark = pytest.mark.usefixtures("qapp")

URL = "https://example.invalid/morphwheel"
CHANGED = Settings(
    trigger_key="ctrl",
    wheel_size="L",
    start_with_windows=True,
    quality=Quality(jpeg=55, webp=65, avif=75),
    compress=Compress(longest_side=1600, quality=60),
)


@pytest.fixture
def store(tmp_path: Path) -> SettingsStore:
    path = tmp_path / "settings.toml"
    save_settings(path, CHANGED)
    store = SettingsStore(path)
    store.load()
    return store


@pytest.fixture
def window(store: SettingsStore, qtbot: QtBot) -> Iterator[SettingsWindow]:
    window = SettingsWindow(store, version="0.1.0", repository_url=URL)
    qtbot.addWidget(window)
    window.open_and_raise()
    yield window
    window.hide()


@pytest.fixture
def saves(monkeypatch: pytest.MonkeyPatch) -> list[Settings]:
    """Every value the store wrote (the real write still happens)."""
    written: list[Settings] = []
    real = store_module.save_settings

    def spy(path: Path, settings: Settings) -> None:
        written.append(settings)
        real(path, settings)

    monkeypatch.setattr(store_module, "save_settings", spy)
    return written


def test_the_controls_show_the_store(window: SettingsWindow) -> None:
    assert window.isVisible()
    assert window.page == "general"
    assert window.trigger_key.currentText() == "Ctrl"
    assert window.wheel_size.checkedId() == 2  # L
    assert window.start_with_windows.isChecked()
    assert window.jpeg_quality.value == 55
    assert window.jpeg_quality.value_label.text() == "55"
    assert window.webp_quality.value == 65
    assert window.avif_quality.value == 75
    assert window.longest_side.value() == 1600
    assert window.longest_side.text() == "1600 px"
    assert window.compress_quality.value == 60
    assert not window.info_bar.isVisible()
    assert URL in window.links.text()
    window.select_page("about")
    assert window.page == "about"


def test_each_control_writes_its_field_once(
    window: SettingsWindow, store: SettingsStore, saves: list[Settings]
) -> None:
    window.trigger_key.setCurrentIndex(0)
    window.trigger_key.activated.emit(0)  # the user picked Shift
    assert store.settings.trigger_key == "shift"
    window.wheel_size.button(0).click()  # Small
    assert store.settings.wheel_size == "S"
    window.start_with_windows.click()
    assert not store.settings.start_with_windows
    window.longest_side.setValue(2000)
    window.longest_side.editingFinished.emit()
    assert store.settings.compress == Compress(longest_side=2000, quality=60)
    assert len(saves) == 4
    on_disk = load_settings(store.path).settings
    assert on_disk == store.settings
    assert on_disk.quality == CHANGED.quality  # untouched fields survive


def test_a_slider_gesture_is_one_save(
    window: SettingsWindow, store: SettingsStore, saves: list[Settings], qtbot: QtBot
) -> None:
    row = window.jpeg_quality
    row.slider.setSliderDown(True)  # a drag: many steps…
    for value in (56, 60, 70, 80):
        row.slider.setValue(value)
    assert row.value_label.text() == "80"
    assert saves == []
    row.slider.setSliderDown(False)
    row.slider.sliderReleased.emit()  # …one save on release
    assert store.settings.quality.jpeg == 80
    assert len(saves) == 1

    for value in (81, 82, 83):  # key auto-repeat or the wheel: steps without a release…
        row.slider.setValue(value)
    assert len(saves) == 1
    assert row.pending
    qtbot.waitUntil(lambda: not row.pending, timeout=COMMIT_DELAY_MS * 10)  # …one save, later
    assert len(saves) == 2
    assert store.settings.quality.jpeg == 83

    window.webp_quality.slider.setValue(66)
    window.hide()  # a pending commit is flushed by the hide
    assert len(saves) == 3
    assert store.settings.quality.webp == 66
    assert load_settings(store.path).settings.quality == Quality(83, 66, 75)


def test_a_change_from_elsewhere_refreshes_without_writing(
    window: SettingsWindow, store: SettingsStore, saves: list[Settings]
) -> None:
    window.hide()
    store.update(quality=Quality(1, 2, 3))  # while hidden: nothing to keep in step…
    assert window.jpeg_quality.value == 55
    window.open_and_raise()
    assert window.jpeg_quality.value == 1  # …the show catches up
    store.update(trigger_key="ctrl+shift", wheel_size="M", quality=Quality(10, 20, 30))
    assert len(saves) == 2  # the two updates; the refreshes wrote nothing
    assert window.trigger_key.currentIndex() == 2
    assert window.wheel_size.checkedId() == 1
    assert window.jpeg_quality.value == 10
    assert window.jpeg_quality.value_label.text() == "10"  # the label follows a refresh too
    assert window.avif_quality.value == 30
    assert len(saves) == 2


def test_a_refresh_never_fights_an_edit(window: SettingsWindow, store: SettingsStore) -> None:
    window.longest_side.setFocus()
    window.longest_side.selectAll()
    QTest.keyClicks(window.longest_side, "30")  # typing "3000"…
    assert window.longest_side.hasFocus()
    row = window.jpeg_quality
    row.slider.setSliderDown(True)
    row.slider.setValue(42)
    store.update(trigger_key="shift")  # …while another owner writes
    assert window.longest_side.cleanText() == "30"  # untouched
    assert row.value == 42  # a held slider keeps the user's value
    assert window.trigger_key.currentIndex() == 0  # the rest refreshed
    row.slider.setSliderDown(False)
    row.slider.sliderReleased.emit()
    assert store.settings.quality.jpeg == 42


def test_the_bars_say_what_happened(
    qtbot: QtBot, tmp_path: Path, refused_saves: Callable[[], AbstractContextManager[None]]
) -> None:
    broken = tmp_path / "broken.toml"
    broken.write_text('trigger_key = "alt"\n', encoding="utf-8")
    problems = SettingsStore(broken)
    problems.load()
    window = SettingsWindow(problems, version="0.1.0", repository_url=URL)
    qtbot.addWidget(window)
    window.open_and_raise()
    assert window.info_bar.isVisible()
    assert window.info_bar.text().startswith("Some settings fell back to their defaults:")
    assert "trigger_key:" in window.info_bar.text()

    with refused_saves():
        problems.update(wheel_size="S")
    assert window.info_bar.text().startswith("⚠ Couldn't save the settings: ")
    assert "The process cannot access the file" in window.info_bar.text()
    assert window.wheel_size.checkedId() == 0  # the change stays in force (RD-15)
    problems.update(wheel_size="L")  # the next save works: the error is gone…
    assert window.info_bar.text().startswith("Some settings fell back")  # …the problems remain
    window.hide()


def test_the_heic_row_asks_and_shows_the_state(window: SettingsWindow) -> None:
    asked: list[str] = []
    window.heic_install_requested.connect(lambda: asked.append("install"))
    window.heic_remove_requested.connect(lambda: asked.append("remove"))
    assert window.heic_state == "missing"
    assert window.heic_status.text() == "Not installed"
    assert window.heic_button.text() == "Install…"
    assert not window.heic_button.isDefault()  # Enter in the spin box must not click it
    window.heic_button.click()
    assert asked == ["install"]
    window.set_heic_state("installing")
    assert window.heic_status.text() == "Installing…"
    assert not window.heic_button.isEnabled()
    window.set_heic_state("installed")
    assert window.heic_status.text() == "Installed"
    assert window.heic_button.text() == "Remove"
    assert window.heic_button.isEnabled()
    window.heic_button.click()
    assert asked == ["install", "remove"]


def test_esc_hides_and_the_one_window_comes_back(window: SettingsWindow) -> None:
    window.select_page("conversion")
    window.longest_side.setFocus()  # the key goes to the control first
    QTest.keyClick(window.longest_side, Qt.Key.Key_Escape)
    assert not window.isVisible()
    window.open_and_raise()
    window.select_page("general")
    window.trigger_key.setFocus()
    QTest.keyClick(window.trigger_key, Qt.Key.Key_Escape)
    assert not window.isVisible()
    window.open_and_raise()
    assert window.isVisible()
    window.close()
    assert not window.isVisible()
    window.open_and_raise()
    assert window.isVisible()


@pytest.mark.usefixtures("rtl")
def test_rtl_mirrors_the_sidebar(store: SettingsStore, qtbot: QtBot) -> None:
    window = SettingsWindow(store, version="0.1.0", repository_url=URL)
    qtbot.addWidget(window)
    window.open_and_raise()
    assert window.sidebar.geometry().left() > window.pages.geometry().left()
    image = render_widget(window)
    assert isinstance(image, QImage)
    assert image.width() >= 640
    window.hide()


# ----------------------------------------------------------------------------- the Plugins page
def _plugin(pid: str, name: str, *targets: tuple[str, str, list[str]]) -> object:
    rows = "".join(
        f'\n[[targets]]\nid = "{tid}"\nlabel = "{label}"\noutput = "{tid}"\naccepts = {accepts!r}\n'
        for tid, label, accepts in targets
    )
    head = f'[plugin]\nid = "{pid}"\nname = "{name}"\nversion = "1.2"\napi = "0.1"\n'
    head += f'entry = "{pid}:C"\n'
    return parse_manifest(head + rows, directory=Path("C:/plugins") / pid, is_builtin=False)


HEIC_PRO = _plugin("heic_pro", "HEIC Pro", ("tiff", "TIFF", ["heic", "jpeg", "png", "webp"]))
SAMPLE = _plugin("sample", "Sample plugin", ("bmp", "BMP", ["png"]), ("gif", "GIF", ["png"]))
BROKEN = BrokenPlugin(
    Path("C:/plugins/old"), BrokenKind.INVALID, "plugin.api: 0.0 is not compatible"
)


def registry(prefs: PluginPrefs | None = None, *, broken: bool = False) -> Registry:
    prefs = prefs if prefs is not None else PluginPrefs()
    discovery = Discovery(
        (builtin_manifest(), HEIC_PRO, SAMPLE),  # type: ignore[arg-type]
        (BROKEN,) if broken else (),
        Path("C:/plugins"),
    )
    return build_registry(discovery, prefs)


def test_the_plugins_page_shows_the_registry_the_app_pushes(window: SettingsWindow) -> None:
    assert "plugins" in PAGES
    window.select_page("plugins")
    assert window.plugin_rows() == ()
    assert window.plugins_empty.isVisibleTo(window)
    assert not window.plugin_list.isVisibleTo(window)
    assert not window.broken_list.isVisibleTo(window)

    window.set_plugins(registry(PluginPrefs(enabled=("sample",), order=("sample", "heic_pro"))))
    assert window.plugin_rows() == (("sample", True), ("heic_pro", False))
    assert not window.plugins_empty.isVisibleTo(window)
    texts = [window.plugin_list.item(i).text() for i in range(2)]
    assert texts[0] == "Sample plugin 1.2  ·  PNG → BMP, GIF"
    assert texts[1] == "HEIC Pro 1.2  ·  JPG, PNG, WebP, … → TIFF"  # the inputs are capped
    assert window.arc_note.text() == "The More arc shows up to 6 targets."

    window.set_plugins(
        registry(broken=True), "the plugins folder is a link; it must be a real folder"
    )
    assert window.plugin_rows() == (("heic_pro", False), ("sample", False))  # a new order: rebuilt
    assert window.broken_list.isVisibleTo(window)
    assert window.broken_list.item(0).text() == (
        "⚠ old: The manifest is invalid\nplugin.api: 0.0 is not compatible"
    )
    assert (
        window.broken_list.item(0).flags() & Qt.ItemFlag.ItemIsSelectable
    )  # the reason is reachable
    assert window.folder_error.isVisibleTo(window)
    assert "it must be a real folder" in window.folder_error.text()


def test_the_arc_note_counts_the_overflow(window: SettingsWindow) -> None:
    many = _plugin(
        "many",
        "Many",
        *[(f, f.upper(), ["png"]) for f in ("bmp", "gif", "ico", "pdf", "tiff", "webp", "avif")],
    )
    discovery = Discovery((builtin_manifest(), many), (), Path("C:/plugins"))  # type: ignore[arg-type]
    window.set_plugins(build_registry(discovery, PluginPrefs(enabled=("many",))))
    assert window.arc_note.text() == "1 enabled target left out of the More arc."
    discovery = Discovery((builtin_manifest(), many, SAMPLE), (), Path("C:/plugins"))  # type: ignore[arg-type]
    window.set_plugins(build_registry(discovery, PluginPrefs(enabled=("many", "sample"))))
    assert window.arc_note.text() == "3 enabled targets left out of the More arc."


def test_checking_a_row_asks_and_unchecking_writes(
    window: SettingsWindow, store: SettingsStore, saves: list[Settings]
) -> None:
    asked: list[str] = []
    window.plugin_enable_requested.connect(asked.append)
    window.select_page("plugins")
    window.set_plugins(registry(PluginPrefs(enabled=("sample",))))
    heic, sample = window.plugin_list.item(0), window.plugin_list.item(1)
    assert (heic.data(Qt.ItemDataRole.UserRole), sample.data(Qt.ItemDataRole.UserRole)) == (
        "heic_pro",
        "sample",
    )
    # Checking never writes: the row reverts, the app's prompt decides (§6.5).
    window.plugin_list.setCurrentItem(heic)
    QTest.keyClick(window.plugin_list, Qt.Key.Key_Space)
    assert asked == ["heic_pro"]
    assert heic.checkState() == Qt.CheckState.Unchecked
    assert saves == []
    # A push with the same ids keeps the items and only moves the checks.
    window.set_plugins(registry(PluginPrefs(enabled=("sample", "heic_pro"))))
    assert window.plugin_list.item(0) is heic
    assert heic.checkState() == Qt.CheckState.Checked
    # Unchecking writes ``enabled`` without the id, from the store's value, and nothing else.
    store.update(plugins=PluginPrefs(enabled=("sample", "heic_pro"), order=("heic_pro",)))
    saves.clear()
    sample.setCheckState(Qt.CheckState.Unchecked)
    assert [s.plugins for s in saves] == [PluginPrefs(enabled=("heic_pro",), order=("heic_pro",))]
    assert asked == ["heic_pro"]
    # A refresh that repeats the state writes nothing.
    window.set_plugins(registry(PluginPrefs(enabled=("heic_pro",), order=("heic_pro",))))
    assert len(saves) == 1


def test_move_buttons_and_a_model_move_write_the_order_whole(
    window: SettingsWindow, store: SettingsStore, saves: list[Settings], qtbot: QtBot
) -> None:
    window.select_page("plugins")
    store.update(plugins=PluginPrefs(enabled=("heic_pro",)))  # the writes derive from the store
    saves.clear()
    window.set_plugins(registry(PluginPrefs(enabled=("heic_pro",))))
    assert [pid for pid, _ in window.plugin_rows()] == ["heic_pro", "sample"]
    assert not window.move_up.isEnabled()  # no current row yet
    assert not window.move_down.isEnabled()
    window.plugin_list.setCurrentRow(0)
    assert not window.move_up.isEnabled()
    assert window.move_down.isEnabled()
    window.move_down.click()
    assert [pid for pid, _ in window.plugin_rows()] == ["sample", "heic_pro"]
    assert window.plugin_list.currentRow() == 1  # the moved row stays current
    assert not window.move_down.isEnabled()
    qtbot.waitUntil(lambda: len(saves) == 1, timeout=2000)  # the write is deferred past the drop
    assert saves[0].plugins == PluginPrefs(enabled=("heic_pro",), order=("sample", "heic_pro"))
    assert window.plugin_list.item(1).checkState() == Qt.CheckState.Checked  # the check moved too
    window.move_up.click()
    qtbot.waitUntil(lambda: len(saves) == 2, timeout=2000)
    assert saves[1].plugins.order == ("heic_pro", "sample")
    window.move_up.click()  # already first: nothing
    qtbot.wait(50)
    assert len(saves) == 2


def test_the_folder_and_rescan_buttons_ask_the_app(window: SettingsWindow) -> None:
    asked: list[str] = []
    window.plugins_folder_requested.connect(lambda: asked.append("folder"))
    window.rescan_requested.connect(lambda: asked.append("rescan"))
    window.open_plugins_folder.click()
    window.rescan.click()
    assert asked == ["folder", "rescan"]
    assert not window.open_plugins_folder.isDefault()
    assert not window.rescan.isDefault()


def test_every_broken_kind_has_a_headline() -> None:
    assert set(_BROKEN_HEADLINES) == set(BrokenKind)
