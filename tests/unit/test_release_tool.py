"""``tools/release.py`` (S7 file 3): the version, the tag check, the notes, the checksums, T6."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import morphwheel
import release  # tools/ is on pytest's pythonpath

ROOT = Path(__file__).resolve().parents[2]

CHANGELOG = """# Changelog

## [Unreleased]

- Something cooking.

## [0.2.0] - 2027-01-01

- Second.
- Lines.

## [0.1.0] - 2026-12-01

- First release.

[Unreleased]: https://example.invalid/compare/v0.2.0...HEAD
[0.2.0]: https://example.invalid/compare/v0.1.0...v0.2.0
[0.1.0]: https://example.invalid/releases/tag/v0.1.0
"""


def test_the_version_is_read_as_text_and_matches_the_package_and_the_resource() -> None:
    assert release.read_version() == morphwheel.__version__  # the resource agrees, or this raises


def test_version_drift_is_refused(tmp_path: Path) -> None:
    init = tmp_path / "__init__.py"
    init.write_text('__version__ = "0.2.0"\n', encoding="utf-8")
    resource = tmp_path / "file_version_info.txt"
    resource.write_text("StringStruct('ProductVersion', '0.1.0')", encoding="utf-8")
    with pytest.raises(SystemExit, match="update the resource"):
        release.read_version(init, resource)
    init.write_text('__version__ = "0.2"\n', encoding="utf-8")
    assert release.read_version(init, None) == "0.2"
    init.write_text('__version__ = "0.2.0-beta"\n', encoding="utf-8")
    with pytest.raises(SystemExit, match="canonical"):
        release.read_version(init, None)


@pytest.mark.parametrize(
    ("version", "pre"),
    [
        ("0.1.0.dev0", True),
        ("0.1.0", False),
        ("1.0.0rc1", True),
        ("1.0.0a1", True),
        ("1.0.0b2", True),
        ("1.0.0.post1", False),
        ("1.0.0rc1.dev2", True),
        ("10.0.0", False),
    ],
)
def test_prerelease_follows_pep_440(version: str, pre: bool) -> None:
    assert release.is_prerelease(version) is pre


def test_check_tag_accepts_the_matching_tag_and_refuses_others(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert release.main(["check-tag", f"v{morphwheel.__version__}"]) == 0
    assert f"version={morphwheel.__version__}" in capsys.readouterr().out
    assert out.read_text(encoding="utf-8").splitlines() == [
        f"version={morphwheel.__version__}",
        f"prerelease={'true' if release.is_prerelease(morphwheel.__version__) else 'false'}",
    ]
    assert release.main(["version"]) == 0
    assert f"version={morphwheel.__version__}" in capsys.readouterr().out
    assert release.main(["check-tag", "v9.9.9"]) == 1
    assert "is not v" in capsys.readouterr().out
    assert release.main(["check-tag", morphwheel.__version__]) == 1  # no "v": refused too


def test_notes_take_the_versions_section_without_heading_or_link_block(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(CHANGELOG, encoding="utf-8")
    assert release.notes_section("0.2.0", changelog) == "- Second.\n- Lines.\n"
    assert release.notes_section("0.1.0", changelog) == "- First release.\n"  # the last section
    assert release.notes_section("0.3.0", changelog) is None
    assert release.notes_section("0.1.0", tmp_path / "missing.md") is None
    plain = tmp_path / "plain.md"
    plain.write_text("﻿## v0.1.0\n\ntext\n\n## 0.1.0.dev0\n\nold\n", encoding="utf-8")
    assert release.notes_section("0.1.0", plain) == "text\n"  # a BOM and a "v" are tolerated
    assert release.notes_section("0.1", plain) is None  # a prefix is not a match
    assert release.notes_section("0.1.0.dev0", plain) == "old\n"


def test_notes_command_writes_utf8_lf_without_bom_and_falls_back(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_bytes("## [0.1.0]\r\n\r\n- Hebrew: עברית\r\n- Two\r\n".encode())  # CRLF
    out = tmp_path / "notes.md"
    assert release.main(["notes", "0.1.0", "--changelog", str(changelog), "-o", str(out)]) == 0
    assert out.read_bytes() == "- Hebrew: עברית\n- Two\n".encode()
    assert release.main(["notes", "0.9.0", "--changelog", str(changelog), "-o", str(out)]) == 0
    fallback = out.read_text(encoding="utf-8")
    assert fallback.startswith("Morphwheel 0.9.0.")
    assert "sign" not in fallback.lower()  # never a claim about signing
    assert "::warning::" in capsys.readouterr().out


def test_checksums_are_sha256sum_lines_sorted_by_name_and_verify(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    b = tmp_path / "b.exe"
    a = tmp_path / "a.txt"
    b.write_bytes(b"installer")
    a.write_bytes(b"sums")
    out = tmp_path / "SHA256SUMS.txt"
    assert release.main(["checksums", str(b), str(a), "-o", str(out)]) == 0
    assert (
        out.read_bytes()
        == (
            f"{hashlib.sha256(b'sums').hexdigest()}  a.txt\n"
            f"{hashlib.sha256(b'installer').hexdigest()}  b.exe\n"
        ).encode()
    )
    assert release.main(["verify", str(out)]) == 0
    assert "b.exe: OK" in capsys.readouterr().out
    b.write_bytes(b"tampered")
    with pytest.raises(SystemExit, match="does not match"):
        release.main(["verify", str(out)])
    b.unlink()
    with pytest.raises(SystemExit, match="missing"):
        release.main(["verify", str(out)])
    out.write_text("\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="lists no files"):
        release.main(["verify", str(out)])


def test_check_installer_wants_exactly_one_file_under_the_limit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit, match="expected exactly"):
        release.check_installer(tmp_path, "0.1.0", 45)
    exe = tmp_path / "morphwheel-0.1.0-setup.exe"
    exe.write_bytes(b"x" * 2048)
    assert release.check_installer(tmp_path, "0.1.0", 45) == exe
    assert "0.0 MB (limit 45 MB)" in capsys.readouterr().out
    with pytest.raises(SystemExit, match=r"over the 0\.001 MB limit"):
        release.check_installer(tmp_path, "0.1.0", 0.001)
    (tmp_path / "morphwheel-0.1.0.dev0-setup.exe").write_bytes(b"y")
    with pytest.raises(SystemExit, match="expected exactly"):
        release.check_installer(tmp_path, "0.1.0", 45)  # two installers: ambiguous
    exe.unlink()
    assert release.main(["check-installer", str(tmp_path), "--version", "0.1.0.dev0"]) == 0
