"""``engine.engines`` (A6): a pinned hash gates the install; nothing lands on a mismatch."""

from __future__ import annotations

from pathlib import Path

import pytest
from fake_heic import fake_wheel, pin

from morphwheel.core.formats import FormatId
from morphwheel.engine import engines
from morphwheel.engine.engines import (
    HEIC_WHEEL,
    EngineInstallError,
    heic_installed,
    install_heic,
    missing_engines,
    remove_heic,
)


def test_install_verifies_then_lays_the_files_out_flat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = fake_wheel()
    pin(monkeypatch, data)
    urls: list[str] = []

    def fetch(url: str) -> bytes:
        urls.append(url)
        return data

    assert missing_engines(tmp_path) == (
        {FormatId.HEIC} if not engines.heic_available(tmp_path) else set()
    )
    folder = install_heic(tmp_path, fetch=fetch)
    assert urls == [HEIC_WHEEL.url]
    assert folder == tmp_path / "heic"
    assert sorted(p.name for p in folder.iterdir()) == [
        "_pillow_heif.cp312-win_amd64.pyd",
        "libheif-abc.dll",
        "pillow_heif",
    ]
    assert not (folder / "pillow_heif-1.8.1.dist-info").exists()
    assert heic_installed(tmp_path)
    assert missing_engines(tmp_path) == frozenset()
    assert not (tmp_path / "heic.installing").exists()
    remove_heic(tmp_path)
    assert not heic_installed(tmp_path)


def test_wrong_hash_installs_nothing(tmp_path: Path) -> None:
    with pytest.raises(EngineInstallError, match="pinned hash"):
        install_heic(tmp_path, fetch=lambda url: fake_wheel())  # the real pin doesn't match a fake
    assert list(tmp_path.iterdir()) == []


def test_zip_slip_and_incomplete_wheels_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evil = fake_wheel(extra={"pillow_heif/../../evil.py": b"x"})
    pin(monkeypatch, evil)
    with pytest.raises(EngineInstallError, match="outside the engine dir"):
        install_heic(tmp_path, fetch=lambda url: evil)
    assert list(tmp_path.iterdir()) == []
    assert not (tmp_path.parent / "evil.py").exists()

    incomplete = fake_wheel(pyd=False)
    pin(monkeypatch, incomplete)
    with pytest.raises(EngineInstallError, match="expected files"):
        install_heic(tmp_path, fetch=lambda url: incomplete)
    assert list(tmp_path.iterdir()) == []

    garbage = b"not a zip"
    pin(monkeypatch, garbage)
    with pytest.raises(EngineInstallError, match="not a wheel"):
        install_heic(tmp_path, fetch=lambda url: garbage)


def test_an_unwritable_folder_is_a_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = fake_wheel()
    pin(monkeypatch, data)
    blocked = tmp_path / "engines"
    blocked.write_bytes(b"not a folder")  # the engines "folder" is a file: mkdir fails
    with pytest.raises(EngineInstallError) as raised:
        install_heic(blocked, fetch=lambda url: data)
    assert raised.value.kind == "write"
    assert not (blocked.parent / "heic.installing").exists()
    assert install_heic(tmp_path / "ok", fetch=lambda url: data).is_dir()
    assert remove_heic(tmp_path / "ok") is True
    assert remove_heic(tmp_path / "never") is True  # nothing there: nothing left


def test_reinstall_replaces_the_old_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = fake_wheel()
    pin(monkeypatch, data)
    install_heic(tmp_path, fetch=lambda url: data)
    (tmp_path / "heic" / "stale.txt").write_bytes(b"old")
    install_heic(tmp_path, fetch=lambda url: data)
    assert not (tmp_path / "heic" / "stale.txt").exists()
    assert heic_installed(tmp_path)


def test_download_errors_become_install_errors(tmp_path: Path) -> None:
    def fetch(url: str) -> bytes:
        raise EngineInstallError("download failed: offline")

    with pytest.raises(EngineInstallError, match="offline"):
        install_heic(tmp_path, fetch=fetch)


def test_the_pin_matches_pypi_metadata() -> None:
    """The recorded facts about the wheel are self-consistent (the URL names the file)."""
    assert HEIC_WHEEL.url.endswith("/" + HEIC_WHEEL.name)
    assert HEIC_WHEEL.url.startswith("https://files.pythonhosted.org/")
    assert len(HEIC_WHEEL.sha256) == 64
    assert "cp312" in HEIC_WHEEL.name
    assert "win_amd64" in HEIC_WHEEL.name
