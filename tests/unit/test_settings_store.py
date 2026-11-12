"""``settings.store``'s pure functions: read tolerantly, written atomically, never lost."""

from __future__ import annotations

import logging
import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest

from morphwheel.settings.model import DEFAULTS, Compress, Quality, Settings
from morphwheel.settings.store import INVALID_SUFFIX, load_settings, save_settings

CHANGED = Settings(trigger_key="ctrl", wheel_size="L", quality=Quality(jpeg=50, webp=85, avif=70))


def _document(path: Path) -> dict[str, object]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_a_missing_file_is_the_first_run(tmp_path: Path) -> None:
    path = tmp_path / "Morphwheel" / "settings.toml"
    loaded = load_settings(path)
    assert loaded.settings == DEFAULTS
    assert loaded.problems == ()
    assert not path.parent.exists()  # loading creates nothing


def test_save_creates_the_folder_and_the_file_reads_back(
    tmp_path: Path, temp_files: Callable[[Path], list[Path]]
) -> None:
    path = tmp_path / "Morphwheel" / "settings.toml"
    save_settings(path, CHANGED)
    assert load_settings(path).settings == CHANGED
    assert temp_files(path.parent) == []
    text = path.read_text(encoding="utf-8")
    assert 'trigger_key = "ctrl"' in text
    assert "[quality]" in text


def test_save_replaces_an_existing_file(
    tmp_path: Path, temp_files: Callable[[Path], list[Path]]
) -> None:
    path = tmp_path / "settings.toml"
    save_settings(path, CHANGED)
    save_settings(path, DEFAULTS)
    assert load_settings(path).settings == DEFAULTS
    assert temp_files(tmp_path) == []


def test_unknown_keys_survive_a_save(tmp_path: Path) -> None:
    path = tmp_path / "settings.toml"
    path.write_text(
        'future = "yes"\nwheel_size = "S"\n[quality]\njxl = 95\njpeg = 10\n[plugins.pins]\na = 1\n',
        encoding="utf-8",
    )
    loaded = load_settings(path)
    assert loaded.settings.wheel_size == "S"
    assert loaded.settings.quality.jpeg == 10
    save_settings(path, Settings(wheel_size="L"))
    document = _document(path)
    assert document["future"] == "yes"
    assert document["wheel_size"] == "L"
    assert document["quality"] == {"jxl": 95, "jpeg": 90, "webp": 85, "avif": 70}
    assert document["plugins"] == {"enabled": [], "order": [], "pins": {"a": 1}}


def test_a_table_given_as_a_scalar_is_replaced_not_merged(tmp_path: Path) -> None:
    path = tmp_path / "settings.toml"
    path.write_text("quality = 5\n[[compress]]\nquality = 1\n", encoding="utf-8")
    loaded = load_settings(path)
    assert loaded.settings == DEFAULTS
    assert [p.split(":")[0] for p in loaded.problems] == ["quality", "compress"]
    save_settings(path, Settings(compress=Compress(longest_side=1000, quality=50)))
    document = _document(path)
    assert document["quality"] == {"jpeg": 90, "webp": 85, "avif": 70}
    assert document["compress"] == {"longest_side": 1000, "quality": 50}


def test_a_newer_schema_is_never_downgraded(tmp_path: Path) -> None:
    path = tmp_path / "settings.toml"
    path.write_text("schema = 3\nnew_key = 1\n", encoding="utf-8")
    loaded = load_settings(path)
    assert loaded.settings.schema == 3
    assert len(loaded.problems) == 1
    save_settings(path, Settings(wheel_size="S"))  # schema 1 in the value: the file keeps 3
    document = _document(path)
    assert document["schema"] == 3
    assert document["new_key"] == 1
    assert document["wheel_size"] == "S"


def test_a_corrupt_file_is_moved_aside_and_the_defaults_load(tmp_path: Path) -> None:
    path = tmp_path / "settings.toml"
    path.write_bytes(b"wheel_size = \n")
    loaded = load_settings(path)
    assert loaded.settings == DEFAULTS
    assert len(loaded.problems) == 1
    assert loaded.problems[0].startswith("settings.toml: not valid TOML")
    aside = tmp_path / ("settings.toml" + INVALID_SUFFIX)
    assert not path.exists()
    assert aside.read_bytes() == b"wheel_size = \n"
    # A second corrupt file replaces the older copy aside; nothing is lost that was readable.
    path.write_bytes(b"\xff\xfe")
    assert load_settings(path).settings == DEFAULTS
    assert aside.read_bytes() == b"\xff\xfe"
    # The next save starts a fresh file.
    save_settings(path, CHANGED)
    assert load_settings(path).settings == CHANGED
    # A hand edit that broke the file while the app runs: the save's own re-read moves it aside.
    broken = b"[quality\n"
    path.write_bytes(broken)
    save_settings(path, DEFAULTS)
    assert aside.read_bytes() == broken
    assert load_settings(path).settings == DEFAULTS


def test_a_utf8_bom_is_not_corruption(tmp_path: Path) -> None:
    path = tmp_path / "settings.toml"
    bom = b"\xef\xbb\xbf"
    path.write_bytes(bom + b'wheel_size = "S"\n')
    loaded = load_settings(path)
    assert loaded.settings.wheel_size == "S"
    assert loaded.problems == ()
    assert path.exists()


def test_a_locked_folder_refuses_the_save_and_leaves_the_old_file(
    tmp_path: Path,
    lock_directory: Callable[[Path], None],
    temp_files: Callable[[Path], list[Path]],
) -> None:
    folder = tmp_path / "locked"
    folder.mkdir()
    path = folder / "settings.toml"
    save_settings(path, DEFAULTS)
    before = path.read_bytes()
    lock_directory(folder)
    with pytest.raises(PermissionError):
        save_settings(path, CHANGED)
    assert path.read_bytes() == before
    assert temp_files(folder) == []


def test_an_unreadable_file_loads_the_defaults_and_refuses_a_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "settings.toml"
    save_settings(path, CHANGED)
    original = Path.read_bytes

    def locked(self: Path) -> bytes:
        if self == path:
            raise PermissionError(32, "The process cannot access the file")
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", locked)
    loaded = load_settings(path)
    assert loaded.settings == DEFAULTS
    assert loaded.problems[0].startswith("settings.toml: can't be read")
    with pytest.raises(PermissionError):
        save_settings(path, DEFAULTS)  # the blocking review finding: never write over the unread
    monkeypatch.undo()
    assert load_settings(path).settings == CHANGED


def test_a_replace_blocked_for_a_moment_is_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, temp_files: Callable[[Path], list[Path]]
) -> None:
    import morphwheel.settings.store as store

    path = tmp_path / "settings.toml"
    real_replace = Path.replace
    failures = {"left": 3}

    def flaky(self: Path, target: Path) -> Path:
        if failures["left"] and target == path:
            failures["left"] -= 1
            raise PermissionError(32, "sharing violation")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky)
    monkeypatch.setattr(store, "_REPLACE_RETRY_S", 0.0)
    save_settings(path, CHANGED)
    assert failures["left"] == 0
    assert load_settings(path).settings == CHANGED
    assert temp_files(tmp_path) == []


def test_load_logs_each_problem_once(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    from morphwheel.settings.store import SettingsStore

    path = tmp_path / "settings.toml"
    path.write_text('trigger_key = "alt"\nwheel_size = "XL"\n', encoding="utf-8")
    logger = logging.getLogger("morphwheel")
    monkey_propagate = logger.propagate
    logger.propagate = True  # ``setup_logging`` turns it off in other tests
    try:
        with caplog.at_level(logging.WARNING, logger="morphwheel.settings.store"):
            store = SettingsStore(path)
            assert store.load() == DEFAULTS
    finally:
        logger.propagate = monkey_propagate
    # Deduplicated: depending on the order, caplog may hold a second capture handler.
    warnings = sorted({r.getMessage() for r in caplog.records if r.levelno == logging.WARNING})
    assert warnings == sorted("settings: " + problem for problem in store.problems)
    assert [p.split(":")[0] for p in store.problems] == ["trigger_key", "wheel_size"]
