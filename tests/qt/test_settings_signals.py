"""``SettingsStore``: set, save, then signal; and ``TriggerKey`` pinned to the poller."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import get_args

import pytest
from pytestqt.qtbot import QtBot

from morphwheel.platform.modifier_poller import TriggerKey as PollerKey
from morphwheel.settings import model
from morphwheel.settings.model import DEFAULTS, Quality, Settings
from morphwheel.settings.store import SettingsStore, load_settings, save_settings

pytestmark = pytest.mark.usefixtures("qapp")


def test_the_trigger_keys_match_the_pollers() -> None:
    assert get_args(model.TriggerKey) == get_args(PollerKey)


def test_update_sets_saves_then_signals(
    tmp_path: Path, temp_files: Callable[[Path], list[Path]]
) -> None:
    path = tmp_path / "settings.toml"
    store = SettingsStore(path)
    assert store.load() == DEFAULTS
    seen: list[Settings] = []
    on_disk_at_signal: list[Settings] = []

    def on_changed(new: Settings) -> None:
        seen.append(new)
        on_disk_at_signal.append(load_settings(path).settings)  # saved before the signal

    store.changed.connect(on_changed)
    new = store.update(trigger_key="ctrl", quality=Quality(jpeg=60, webp=85, avif=70))
    assert new == store.settings
    assert new.trigger_key == "ctrl"
    assert new.quality.jpeg == 60
    assert seen == [new]
    assert on_disk_at_signal == [new]
    assert temp_files(tmp_path) == []


def test_a_no_op_update_neither_signals_nor_writes(
    tmp_path: Path, temp_files: Callable[[Path], list[Path]]
) -> None:
    path = tmp_path / "settings.toml"
    store = SettingsStore(path)
    store.load()
    store.update(wheel_size="L")
    before = path.read_bytes()
    emitted: list[object] = []
    store.changed.connect(emitted.append)
    assert store.update(wheel_size="L") == store.settings
    assert store.update() == store.settings
    assert emitted == []
    assert path.read_bytes() == before
    assert temp_files(tmp_path) == []


def test_an_unread_file_is_read_again_before_the_first_write(
    tmp_path: Path, unreadable: Callable[[Path], AbstractContextManager[None]], qtbot: QtBot
) -> None:
    """The store held the defaults as a stand-in; merging them into a file that became readable
    would replace the user's values (the S5 file 5 review). ``update`` loads again first."""
    path = tmp_path / "settings.toml"
    save_settings(path, Settings(trigger_key="ctrl", wheel_size="L", onboarding_done=True))
    store = SettingsStore(path)
    with unreadable(path):
        assert store.load() == DEFAULTS
        assert store.unread
        assert store.problems[0].startswith("settings.toml: can't be read")
    with qtbot.waitSignal(store.changed, timeout=1000) as told:
        store.update(paused=True)  # readable by now
    expected = Settings(trigger_key="ctrl", wheel_size="L", onboarding_done=True, paused=True)
    assert told.args == [expected]
    assert store.settings == expected
    assert not store.unread
    assert load_settings(path).settings == expected  # nothing of theirs was replaced

    fresh = SettingsStore(tmp_path / "none.toml")
    fresh.load()
    assert not fresh.unread  # a missing file is a first run, not an unread one


def test_changes_made_while_the_file_is_unreadable_all_survive(
    tmp_path: Path, unreadable: Callable[[Path], AbstractContextManager[None]]
) -> None:
    path = tmp_path / "settings.toml"
    save_settings(path, Settings(wheel_size="L", onboarding_done=True))
    store = SettingsStore(path)
    failures: list[str] = []
    store.save_failed.connect(failures.append)
    with unreadable(path):
        store.load()
        store.update(trigger_key="ctrl")  # refused, in force
        store.update(paused=True)  # refused too: the first change is still there
        assert store.settings == Settings(trigger_key="ctrl", paused=True)
        assert len(failures) == 2
        assert store.unread
    store.update(start_with_windows=True)  # readable now: theirs, plus all three changes
    expected = Settings(
        wheel_size="L",
        onboarding_done=True,
        trigger_key="ctrl",
        paused=True,
        start_with_windows=True,
    )
    assert store.settings == expected
    assert load_settings(path).settings == expected
    assert len(failures) == 2
    assert not store.unread


def test_a_no_op_change_after_the_re_read_still_lands(
    tmp_path: Path, unreadable: Callable[[Path], AbstractContextManager[None]], qtbot: QtBot
) -> None:
    """The file holds a value the stand-in doesn't; a change equal to the stand-in must not take
    the no-op shortcut, or the store, the owners and the file part ways (the security review)."""
    path = tmp_path / "settings.toml"
    save_settings(path, Settings(wheel_size="L"))
    store = SettingsStore(path)
    with unreadable(path):
        store.load()
    assert store.settings.wheel_size == "M"  # the stand-in
    with qtbot.waitSignal(store.changed, timeout=1000) as told:
        returned = store.update(wheel_size="M")  # a no-op against the stand-in, not the file
    assert returned == store.settings == load_settings(path).settings == Settings(wheel_size="M")
    assert told.args == [returned]


def test_an_unknown_field_is_a_programming_error(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.toml")
    with pytest.raises(TypeError):
        store.update(colour="red")
    assert store.settings == DEFAULTS


def test_a_failed_save_is_reported_and_the_value_stays(
    tmp_path: Path,
    lock_directory: Callable[[Path], None],
    temp_files: Callable[[Path], list[Path]],
) -> None:
    folder = tmp_path / "locked"
    folder.mkdir()
    path = folder / "settings.toml"
    store = SettingsStore(path)
    store.load()
    store.update(paused=True)
    before = path.read_bytes()
    lock_directory(folder)
    failures: list[str] = []
    changes: list[Settings] = []
    store.save_failed.connect(failures.append)
    store.changed.connect(changes.append)
    new = store.update(paused=False, wheel_size="S")
    assert new.paused is False
    assert store.settings == new  # the running app uses what the user chose
    assert len(failures) == 1
    assert changes == [new]
    assert path.read_bytes() == before  # the file is untouched
    assert temp_files(folder) == []
