"""The packaging inputs that a test can hold (S7): the version resource and the license texts.

The build itself is proven by a real PyInstaller run (the S7 report), not here.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

import morphwheel

ROOT = Path(__file__).resolve().parents[2]
PACKAGING = ROOT / "packaging" / "pyinstaller"
sys.path.insert(0, str(PACKAGING))
from bundle_licenses import (  # noqa: E402
    QT_DISTRIBUTIONS,
    RUNTIME_DISTRIBUTIONS,
    datas,
    license_files,
)

sys.path.pop(0)


def test_the_version_resource_matches_the_package_version() -> None:
    """``file_version_info.txt`` is committed; it must not drift from ``__version__``."""
    text = (PACKAGING / "file_version_info.txt").read_text(encoding="utf-8")
    match = re.match(r"(\d+)\.(\d+)\.(\d+)", morphwheel.__version__)
    assert match is not None
    numbers = tuple(int(n) for n in match.groups())
    assert f"filevers=({numbers[0]}, {numbers[1]}, {numbers[2]}, 0)" in text
    assert f"prodvers=({numbers[0]}, {numbers[1]}, {numbers[2]}, 0)" in text
    assert f"StringStruct('ProductVersion', '{morphwheel.__version__}')" in text
    assert f"StringStruct('FileVersion', '{numbers[0]}.{numbers[1]}.{numbers[2]}.0')" in text


def test_every_runtime_dependency_ships_a_license_text() -> None:
    pairs = license_files()
    folders = {folder.lower().replace("-", "_") for _, folder in pairs}
    for name in RUNTIME_DISTRIBUTIONS:
        if name in QT_DISTRIBUTIONS:
            continue  # LGPL-3.0: no grant text in the wheels; packaging/licenses/ (next test)
        assert any(f.startswith(name.lower().replace("-", "_")) for f in folders), name
    assert any(f.startswith("python_3.") for f in folders)
    for src, _ in pairs:
        assert src.is_file()
        assert src.stat().st_size > 100  # a text, not an empty file (Qt ships a 470-byte reference)


def test_qt_license_texts_are_bundled() -> None:
    """PySide6's wheels carry only the commercial reference; the LGPL-3.0 and GPL-3.0 texts live
    under packaging/licenses/ (from gnu.org, verbatim) and must both reach the bundle."""
    qt_texts = {src.name: src for src, folder in license_files() if folder == "Qt"}
    assert sorted(qt_texts) == ["GPL-3.0.txt", "LGPL-3.0.txt"]
    lgpl = qt_texts["LGPL-3.0.txt"].read_text(encoding="utf-8")
    gpl = qt_texts["GPL-3.0.txt"].read_text(encoding="utf-8")
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in lgpl
    assert "GNU GENERAL PUBLIC LICENSE" in gpl
    assert lgpl.count("Version 3, 29 June 2007") == gpl.count("Version 3, 29 June 2007") == 1
    assert "END OF TERMS AND CONDITIONS" in gpl  # the whole text, not a stub


def test_the_extra_texts_are_bundled_per_folder() -> None:
    """``packaging/licenses/<folder>/*.txt`` reaches ``licenses/<folder>/``: today aom's LICENSE and
    PATENTS (the AV1 encoder compiled into Pillow's libavif; Pillow's license file omits them)."""
    aom = {src.name: src for src, folder in license_files() if folder == "aom"}
    assert sorted(aom) == ["LICENSE.txt", "PATENTS.txt"]
    assert "Alliance for Open Media" in aom["LICENSE.txt"].read_text(encoding="utf-8")
    assert "Patent License 1.0" in aom["PATENTS.txt"].read_text(encoding="utf-8")


def test_pillow_carries_no_gpl_or_lgpl_codec() -> None:
    """Pillow's SBOM lists libimagequant (GPL-3.0) and FriBiDi (LGPL-2.1) among the libraries its
    wheels *may* link; the Windows wheel links neither, and THIRD_PARTY_NOTICES.md says so. A
    Pillow upgrade that brings one in is the A6 class of problem and must fail here first. The aom
    encoder and dav1d decoder are what the notices name for AVIF."""
    from PIL import _avif, features

    assert features.check("libimagequant") is False
    assert features.check("raqm") is False  # raqm is what pulls FriBiDi in
    assert _avif.encoder_codec_available("aom") is True
    assert _avif.decoder_codec_available("dav1d") is True
    for codec in ("rav1e", "svt"):
        assert _avif.encoder_codec_available(codec) is False, codec  # not in the notices


def test_the_datas_land_under_licenses() -> None:
    for src, dest in datas():
        assert Path(src).is_file()
        assert dest.startswith("licenses/")
        assert "\\" not in dest


def test_the_runtime_distribution_list_matches_pyproject() -> None:
    """Every runtime dependency ships a text, and nothing is listed that pyproject doesn't pin."""
    with (ROOT / "pyproject.toml").open("rb") as f:
        pinned = {
            re.split(r"[=<>!~ ]", dep, maxsplit=1)[0].lower().replace("-", "_")
            for dep in tomllib.load(f)["project"]["dependencies"]
        }
    listed = {name.lower() for name in RUNTIME_DISTRIBUTIONS}
    assert listed == pinned | {"shiboken6"}  # PySide6's own dependency, pulled in by it
