"""The winget manifests (S7 file 4, RD-32): the templates and ``tools/release.py winget``.

The rendered set is a valid winget manifest when ``winget validate`` says so; that runs wherever
winget is on ``PATH`` (this machine, and the GitHub-hosted runner, whose winget may be older than
the manifest schema: such a client validates under the newest schema it knows and warns that the
``$schema`` header names a newer one; that single warning is tolerated, any other fails).
What runs everywhere: the templates render to YAML with the required keys per manifest type and
one schema version; the installer manifest agrees with the Inno script (the ProductCode is the
AppId plus ``_is1``, the OS floor is ``MinVersion``, the publisher is ``AppPublisher``); the locale
manifest agrees with ``pyproject.toml`` (license, description) and the app's name; the URL is the
release asset's and the digest is the file's; the output lands in winget-pkgs' folder layout; and
the tool refuses a wrongly named installer, a bad date, and a template set that uses any
placeholder set but the known one (a template that lost ``@sha256`` must not render half-filled).

YAML is loaded with ``BaseLoader`` so every scalar stays a string: ``ReleaseDate: 2026-11-19`` would
otherwise come back as a ``date`` and a future ``PackageVersion: 1.0`` as a float.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

import release  # tools/ is on pytest's pythonpath
from morphwheel.settings.paths import APP_NAME

ROOT = Path(__file__).resolve().parents[2]

ISS = (ROOT / "packaging" / "inno" / "morphwheel.iss").read_text(encoding="utf-8")
TEMPLATES = ROOT / "packaging" / "winget"
VERSION = "1.2.3"
DATE = "2027-03-04"
NAMES = {
    "version": "MorphWheel.Morphwheel.yaml",
    "installer": "MorphWheel.Morphwheel.installer.yaml",
    "defaultLocale": "MorphWheel.Morphwheel.locale.en-US.yaml",
}


def _directive(name: str) -> str:
    match = re.search(rf"^{name}=(.*)$", ISS, re.MULTILINE)
    assert match is not None, name
    return match.group(1).strip()


def _define(name: str) -> str:
    match = re.search(rf'^#define {name} "([^"]*)"$', ISS, re.MULTILINE)
    assert match is not None, name
    return match.group(1)


@pytest.fixture(scope="module")
def installer(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("installer") / release.installer_name(VERSION)
    path.write_bytes(b"MZ not really an installer\n" * 100)
    return path


@pytest.fixture(scope="module")
def rendered(installer: Path) -> dict[str, str]:
    return release.render_winget(VERSION, installer, DATE)


@pytest.fixture(scope="module")
def loaded(rendered: dict[str, str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for kind, name in NAMES.items():
        data = yaml.load(rendered[name], Loader=yaml.BaseLoader)
        assert isinstance(data, dict), name
        out[kind] = data
    return out


def test_three_manifests_one_version_one_schema(loaded: dict[str, dict[str, Any]]) -> None:
    assert set(loaded) == set(NAMES)
    schema_versions = set()
    for kind, data in loaded.items():
        assert data["ManifestType"] == kind
        assert data["PackageIdentifier"] == release.WINGET_ID == "MorphWheel.Morphwheel"
        assert data["PackageVersion"] == VERSION
        schema_versions.add(data["ManifestVersion"])
    assert len(schema_versions) == 1
    (schema_version,) = schema_versions
    assert re.fullmatch(r"\d+\.\d+\.\d+", schema_version)
    assert loaded["version"]["DefaultLocale"] == loaded["defaultLocale"]["PackageLocale"] == "en-US"


def test_the_schema_comment_names_the_same_version(rendered: dict[str, str]) -> None:
    for kind, name in NAMES.items():
        text = rendered[name]
        comment = re.search(
            r"\$schema=https://aka\.ms/winget-manifest\.(\w+)\.([\d.]+)\.schema\.json", text
        )
        assert comment is not None, name
        assert comment.group(1) == kind
        assert f"ManifestVersion: {comment.group(2)}\n" in text


@pytest.mark.parametrize(
    ("kind", "required"),
    [
        ("version", {"PackageIdentifier", "PackageVersion", "DefaultLocale"}),
        ("installer", {"PackageIdentifier", "PackageVersion", "Installers"}),
        (
            "defaultLocale",
            {"PackageIdentifier", "PackageVersion", "PackageLocale", "Publisher", "PackageName"}
            | {"License", "ShortDescription"},
        ),
    ],
)
def test_the_required_keys_of_each_type(
    loaded: dict[str, dict[str, Any]], kind: str, required: set[str]
) -> None:
    assert required | {"ManifestType", "ManifestVersion"} <= set(loaded[kind])


def test_the_installer_manifest_agrees_with_the_inno_script(
    loaded: dict[str, dict[str, Any]], installer: Path
) -> None:
    data = loaded["installer"]
    app_id = _directive("AppId")  # `{{GUID}`: Inno's doubled brace escapes the first one
    assert app_id.startswith("{{")
    product_code = app_id[1:] + "_is1"  # Inno's uninstall key name
    assert data["ProductCode"] == product_code
    assert data["MinimumOSVersion"] == _directive("MinVersion") + ".0"
    assert data["InstallerType"] == "inno"
    assert data["Scope"] == "user"  # PrivilegesRequired=lowest
    assert _directive("PrivilegesRequired") == "lowest"
    assert data["ElevationRequirement"] == "elevationProhibited"  # the script's own refusal, RD-30e
    assert data["UpgradeBehavior"] == "install"
    assert data["InstallModes"] == ["interactive", "silent", "silentWithProgress"]
    assert "InstallerSwitches" not in data  # winget's Inno defaults, RD-32
    assert data["ReleaseDate"] == DATE
    (arp,) = data["AppsAndFeaturesEntries"]
    assert arp == {
        "DisplayName": _directive("UninstallDisplayName").replace("{#AppName}", _define("AppName")),
        "Publisher": _define("AppPublisher"),
        "ProductCode": product_code,
        "InstallerType": "inno",
    }
    (one,) = data["Installers"]
    assert one["Architecture"] == "x64"
    assert one["InstallerUrl"] == (
        f"https://github.com/MorphWheel/morphwheel/releases/download/v{VERSION}/{installer.name}"
    )
    assert one["InstallerSha256"] == release._sha256(installer).upper()


def test_the_locale_manifest_agrees_with_the_project(loaded: dict[str, dict[str, Any]]) -> None:
    data = loaded["defaultLocale"]
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert data["PackageName"] == APP_NAME == _define("AppName")
    assert data["Publisher"] == _define("AppPublisher")
    assert data["PublisherUrl"] == data["PackageUrl"] == _define("AppURL")
    assert data["PublisherSupportUrl"] == _define("AppURL") + "/issues"
    assert data["License"] == project["license"]
    assert data["ShortDescription"] == project["description"]
    assert data["Moniker"] == "morphwheel"
    assert (
        data["ReleaseNotesUrl"]
        == f"https://github.com/MorphWheel/morphwheel/releases/tag/v{VERSION}"
    )
    assert data["LicenseUrl"].endswith(f"/v{VERSION}/LICENSE")
    resource = release.RESOURCE_FILE.read_text(encoding="utf-8")
    copyright_line = re.search(r"StringStruct\('LegalCopyright',\s*'([^']+)'\)", resource)
    assert copyright_line is not None
    assert data["Copyright"] == copyright_line.group(1)  # one copyright line, the exe's
    assert 1 <= len(data["Tags"]) <= 16
    assert "pillow-heif" not in data["Description"].lower()  # HEIC is an opt-in download, A6
    assert "HEIC" in data["Description"]


def test_the_output_lands_in_winget_pkgs_layout(installer: Path, tmp_path: Path) -> None:
    folder = release.write_winget(VERSION, installer, tmp_path, DATE)
    assert folder == tmp_path / "manifests" / "m" / "MorphWheel" / "Morphwheel" / VERSION
    assert sorted(p.name for p in folder.iterdir()) == sorted(NAMES.values())
    for path in folder.iterdir():
        raw = path.read_bytes()
        assert b"\r" not in raw  # LF
        assert not raw.startswith(b"\xef\xbb\xbf")  # no BOM
        assert "@" not in raw.decode("utf-8")  # nothing left unfilled
    # a second render replaces the files and touches nothing else
    (tmp_path / "manifests" / "keep.txt").write_text("x", encoding="utf-8")
    assert release.write_winget(VERSION, installer, tmp_path, DATE) == folder
    assert (tmp_path / "manifests" / "keep.txt").is_file()


def test_the_prerelease_warning(
    installer: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    release.write_winget(VERSION, installer, tmp_path, DATE)
    assert "::warning::" not in capsys.readouterr().out
    pre = installer.with_name(release.installer_name("1.2.3rc1"))
    pre.write_bytes(installer.read_bytes())
    release.write_winget("1.2.3rc1", pre, tmp_path, DATE)
    out = capsys.readouterr().out
    assert "::warning::1.2.3rc1 is a prerelease" in out
    assert "MorphWheel.Morphwheel.Preview" in out


def test_refusals(installer: Path, tmp_path: Path) -> None:
    wrong = tmp_path / "morphwheel-setup.exe"
    wrong.write_bytes(b"x")
    with pytest.raises(SystemExit, match=r"must be named morphwheel-1\.2\.3-setup\.exe"):
        release.render_winget(VERSION, wrong, DATE)
    with pytest.raises(SystemExit, match="not a file"):
        release.render_winget(VERSION, tmp_path / release.installer_name(VERSION), DATE)
    with pytest.raises(SystemExit, match="YYYY-MM-DD"):
        release.render_winget(VERSION, installer, "4 March 2027")
    with pytest.raises(SystemExit, match="YYYY-MM-DD"):
        release.render_winget(VERSION, installer, "2027-02-30")  # the shape, not a date


def test_a_template_set_with_the_wrong_placeholders_is_refused(
    installer: Path, tmp_path: Path
) -> None:
    copy = tmp_path / "templates"
    shutil.copytree(TEMPLATES, copy)
    # the control: the copy renders
    assert set(release.render_winget(VERSION, installer, DATE, templates=copy)) == set(
        NAMES.values()
    )
    # a lost placeholder: the digest line hardcoded
    path = copy / NAMES["installer"]
    path.write_text(path.read_text(encoding="utf-8").replace("@sha256", "ABC"), encoding="utf-8")
    with pytest.raises(SystemExit, match="expected exactly"):
        release.render_winget(VERSION, installer, DATE, templates=copy)
    shutil.copy(TEMPLATES / NAMES["installer"], path)
    # an unknown placeholder: refused before substitute would raise KeyError
    path = copy / NAMES["version"]
    path.write_text(path.read_text(encoding="utf-8") + "Extra: @nope\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="expected exactly"):
        release.render_winget(VERSION, installer, DATE, templates=copy)
    # a missing template
    path.unlink()
    with pytest.raises(SystemExit, match="missing template"):
        release.render_winget(VERSION, installer, DATE, templates=copy)
    shutil.copy(TEMPLATES / NAMES["version"], path)
    # a further locale (Hebrew, D3a) is rendered alongside, not refused
    hebrew = copy / "MorphWheel.Morphwheel.locale.he-IL.yaml"
    hebrew.write_text(
        (copy / NAMES["defaultLocale"]).read_text(encoding="utf-8").replace("en-US", "he-IL"),
        encoding="utf-8",
    )
    out = release.render_winget(VERSION, installer, DATE, templates=copy)
    assert set(out) == {*NAMES.values(), hebrew.name}
    assert "PackageLocale: he-IL" in out[hebrew.name]


def test_the_cli(installer: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = release.main(
        ["winget", VERSION, "--installer", str(installer), "--date", DATE, "-o", str(tmp_path)]
    )
    assert code == 0
    assert "winget manifests:" in capsys.readouterr().out
    assert (release.winget_manifest_dir(tmp_path, VERSION) / NAMES["installer"]).is_file()


@pytest.mark.skipif(shutil.which("winget") is None, reason="winget is not on PATH")
def test_winget_validate_accepts_the_rendered_set(installer: Path, tmp_path: Path) -> None:
    folder = release.write_winget(VERSION, installer, tmp_path, DATE)
    winget = shutil.which("winget")
    assert winget is not None
    result = subprocess.run(
        [winget, "validate", "--manifest", str(folder), "--disable-interactivity"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    output = result.stdout + result.stderr
    assert "Manifest validation succeeded" in output, output
    warnings = [line for line in output.splitlines() if line.startswith("Manifest Warning:")]
    # An older client than the schema checks the $schema header against the newest version it
    # knows (the GitHub runner, 2026-11); the manifest still validated. Nothing else is tolerated.
    unexpected = [w for w in warnings if "schema header URL does not match" not in w]
    assert not unexpected, unexpected
    if not warnings:
        assert result.returncode == 0, output
