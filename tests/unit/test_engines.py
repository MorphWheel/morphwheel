"""``engine.engines`` (A6): a pinned hash gates the install; nothing lands on a mismatch."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest

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


def fake_wheel(*, extra: dict[str, bytes] | None = None, pyd: bool = True) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("pillow_heif/__init__.py", b"# fake\n")
        z.writestr("pillow_heif/heif.py", b"\n")
        if pyd:
            z.writestr("_pillow_heif.cp312-win_amd64.pyd", b"MZ fake")
        z.writestr("pillow_heif-1.8.1.data/platlib/libheif-abc.dll", b"MZ dll")
        z.writestr("pillow_heif-1.8.1.dist-info/METADATA", b"Name: pillow-heif\n")
        z.writestr("pillow_heif-1.8.1.dist-info/licenses/LICENSE.txt", b"GPL\n")
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


def pin(monkeypatch: pytest.MonkeyPatch, data: bytes) -> None:
    """Point the pinned spec's hash at ``data``, so a fake wheel passes verification."""
    spec = engines.WheelSpec(
        HEIC_WHEEL.name, HEIC_WHEEL.url, hashlib.sha256(data).hexdigest(), len(data), "pillow_heif"
    )
    monkeypatch.setattr(engines, "HEIC_WHEEL", spec)


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
