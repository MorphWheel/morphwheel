"""The release documents (S7 file 5) are held to the code and the build.

Prose cannot be executed, but its facts can be pinned to the places they come from, so a change
there fails here first:

- ``THIRD_PARTY_NOTICES.md`` names every runtime distribution the bundle's license collector
  ships, at the installed version; every ``===== name-version =====`` section of Pillow's shipped
  license file; the extra texts under ``packaging/licenses/`` (Qt, aom); Python's major.minor and
  the OpenSSL it links; PyInstaller at the pinned version; and pillow-heif only as the opt-in
  download at the version the ``heic`` extra pins.
- ``CHANGELOG.md`` has a section the release tool finds for the version being prepared (the
  ``__version__`` with its dev or pre segment removed).
- ``README.md`` names the winget identifier, the installer file name, and links the other four.
- ``PRIVACY.md`` quotes the consent dialog's sentence, names the download host the engine module
  uses, the app's folders, the Downloads fallback and the Run key.
- ``SECURITY.md`` names the private reporting route and the worker time limit.
"""

from __future__ import annotations

import re
import ssl
import sys
import tomllib
from importlib import metadata
from pathlib import Path
from urllib.parse import urlsplit

import morphwheel
import release  # tools/ is on pytest's pythonpath
from morphwheel.engine import engines
from morphwheel.engine.worker_pool import DEFAULT_TASK_TIMEOUT_S
from morphwheel.platform import autostart
from morphwheel.settings.paths import APP_NAME, app_paths

ROOT = Path(__file__).resolve().parents[2]
PACKAGING = ROOT / "packaging" / "pyinstaller"
sys.path.insert(0, str(PACKAGING))
from bundle_licenses import (  # noqa: E402
    EXTRA_TEXTS,
    QT_DISTRIBUTIONS,
    RUNTIME_DISTRIBUTIONS,
    _normalised,
    license_files,
)

sys.path.remove(str(PACKAGING))

NOTICES = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")
PRIVACY = (ROOT / "PRIVACY.md").read_text(encoding="utf-8")
SECURITY = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
_PILLOW_SECTION = re.compile(r"^===== ([a-z0-9-]+?)-(\d[\w.]*) =====$", re.MULTILINE)


def _row(text: str, first_cell: str) -> str:
    """The markdown table row whose first cell is ``first_cell`` (case-insensitive)."""
    rows = [
        line
        for line in text.splitlines()
        if line.startswith("|") and line.split("|")[1].strip().lower() == first_cell.lower()
    ]
    assert len(rows) == 1, (first_cell, rows)
    return rows[0]


def _row_starting(text: str, prefix: str) -> str:
    rows = [
        line
        for line in text.splitlines()
        if line.startswith("|") and line.split("|")[1].strip().lower().startswith(prefix.lower())
    ]
    assert len(rows) == 1, (prefix, rows)
    return rows[0]


def test_the_notices_name_every_runtime_distribution_at_its_version() -> None:
    for name in RUNTIME_DISTRIBUTIONS:
        version = metadata.version(name)
        if name in QT_DISTRIBUTIONS:
            row = _row_starting(NOTICES, "PySide6-Essentials, shiboken6")
            assert version in row, name
            assert version in _row_starting(NOTICES, "Qt (via PySide6")
            continue
        row = _row(NOTICES, _normalised(metadata.metadata(name)["Name"]))
        assert f"| {version} |" in row, name
        assert f"licenses\\{_normalised(metadata.metadata(name)['Name'])}-{version}\\" in row


def test_the_notices_list_every_library_in_pillows_license_file() -> None:
    pillow = next(src for src, folder in license_files() if folder.startswith("pillow-"))
    sections = _PILLOW_SECTION.findall(pillow.read_text(encoding="utf-8"))
    assert len(sections) >= 10  # brotli, freetype, ..., zlib-ng: the control that the regex reads
    for name, version in sections:
        assert f"| {version} |" in _row(NOTICES, name), (name, version)
    # the two AV1 codecs libavif was compiled with (test_packaging pins them in the wheel)
    assert "aom" in [n for n, _ in sections] or "Alliance for Open Media" in NOTICES
    _row(NOTICES, "dav1d")


def test_the_notices_name_the_extra_texts_and_their_bundle_folders() -> None:
    folders = {folder for _, folder in license_files() if folder in ("Qt", "aom")} | {
        p.name for p in EXTRA_TEXTS.iterdir() if p.is_dir()
    }
    for folder in folders:
        assert f"licenses\\{folder}\\" in NOTICES, folder
    for src, folder in license_files():
        if folder in ("Qt", "aom"):
            assert src.name in NOTICES, src.name


def test_the_notices_name_python_openssl_and_pyinstaller() -> None:
    major_minor = f"{sys.version_info.major}.{sys.version_info.minor}"
    assert f"| Python | {major_minor} |" in NOTICES
    assert f"licenses\\Python-{major_minor}\\LICENSE.txt" in NOTICES
    openssl = re.match(r"OpenSSL (\d+\.\d+\.\d+)", ssl.OPENSSL_VERSION)
    assert openssl is not None
    assert f"| OpenSSL | {openssl.group(1)} |" in NOTICES
    assert f"| {metadata.version('pyinstaller')} |" in _row_starting(NOTICES, "PyInstaller")


def test_the_notices_keep_pillow_heif_as_the_opt_in_download() -> None:
    (heic_pin,) = PYPROJECT["optional-dependencies"]["heic"]
    version = heic_pin.split("==")[1]
    assert f"pillow-heif {version}" in NOTICES
    before, after = NOTICES.split("## Not shipped: the opt-in HEIC engine")
    assert "pillow-heif" not in before.replace("pillow-heif` wheel is", "")  # named only as opt-in
    assert "GPL" in after
    assert "never part of the installer" in after
    assert engines.HEIC_WHEEL.name.startswith(f"pillow_heif-{version}-")


def test_the_changelog_has_the_section_the_release_tool_will_publish() -> None:
    base = re.match(r"\d+(\.\d+)*", morphwheel.__version__)
    assert base is not None
    body = release.notes_section(base.group(0))
    assert body is not None, "the release notes would be the fallback line"
    assert len(body) > 500
    assert "### Added" in body


def test_the_readme_names_the_install_facts_and_links_the_policies() -> None:
    assert f"winget install {release.WINGET_ID}" in README
    assert release.installer_name("<version>") in README
    for link in (
        "PRIVACY.md",
        "SECURITY.md",
        "THIRD_PARTY_NOTICES.md",
        "CHANGELOG.md",
        "docs/plugins.md",
    ):
        assert f"]({link})" in README, link
    assert APP_NAME in README


def test_the_privacy_policy_matches_the_engine_download_and_the_paths(tmp_path: Path) -> None:
    host = urlsplit(engines.HEIC_WHEEL.url).netloc
    assert f"`{host}`" in PRIVACY
    dialogs = (ROOT / "src" / "morphwheel" / "ui" / "dialogs.py").read_text(encoding="utf-8")
    sentence = "pillow-heif is open source under the GPLv2; Morphwheel itself stays MIT."
    assert sentence in dialogs
    assert sentence in PRIVACY
    paths = app_paths(
        roaming_base=tmp_path / "R", local_base=tmp_path / "L", downloads=tmp_path / "D"
    )
    for path, token in (
        (paths.settings_file, "%APPDATA%\\Morphwheel\\settings.toml"),
        (paths.plugins_dir, "%APPDATA%\\Morphwheel\\plugins\\"),
        (paths.logs_dir, "%LOCALAPPDATA%\\Morphwheel\\logs\\"),
        (paths.engines_dir, "%LOCALAPPDATA%\\Morphwheel\\engines\\"),
        (paths.fallback_output_dir, "Downloads\\Morphwheel"),
    ):
        assert path.name == token.rstrip("\\").split("\\")[-1], token
        assert token in PRIVACY, token
    assert f"HKCU\\{autostart.RUN_KEY}\\{autostart.VALUE_NAME}" in PRIVACY
    assert "GetAsyncKeyState" in PRIVACY
    assert "Raw Input" in PRIVACY


def test_the_security_policy_names_the_route_and_the_limit() -> None:
    assert "Report a vulnerability" in SECURITY
    assert f"{int(DEFAULT_TASK_TIMEOUT_S)}-second limit" in SECURITY
    assert "RD-28" in SECURITY
    assert "RD-8" in SECURITY
