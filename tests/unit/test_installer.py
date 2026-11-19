"""The installer script (S7 file 2) must agree with the app's own constants.

The script is text to pytest (no Inno Setup here); the compile is proven by a real ISCC run (the S7
report) and the install itself by hand (checklist C42, C43). What a test can hold:

- the mutex name, the Run key, the StartupApproved key and the value name are the app's (RD-23);
- the Run value is quoted only when the exe path has a space. ``subprocess.list2cmdline`` quotes a
  single argument iff it contains a space or a tab or is empty, and a Windows path can't contain a
  tab or a quote, so "quote iff a space" is exactly the app's rule. Don't "fix" it to always quote:
  the app would then rewrite the value at its next start;
- the privilege model (lowest, no UAC, "Launch" as the original user, skipped when silent);
- the data folders the uninstaller may delete are the app's two roots, by the app's name;
- the files the script refers to exist; pillow-heif is refused at compile time (A6); no HEIC
  checkbox (RD-30).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from morphwheel.platform import autostart, single_instance
from morphwheel.settings.paths import APP_NAME

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "packaging" / "inno" / "morphwheel.iss"


@pytest.fixture(scope="module")
def iss() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _directive(iss: str, name: str) -> str:
    match = re.search(rf"^{name}=(.*)$", iss, re.MULTILINE)
    assert match is not None, name
    return match.group(1).strip()


def _const(iss: str, name: str) -> str:
    match = re.search(rf"^\s*{name} = '([^']*)';", iss, re.MULTILINE)
    assert match is not None, name
    return match.group(1)


def test_the_mutex_is_the_apps(iss: str) -> None:
    assert _directive(iss, "AppMutex") == single_instance.MUTEX_NAME


def test_the_run_value_is_the_apps(iss: str) -> None:
    assert _const(iss, "RunKey") == autostart.RUN_KEY
    assert _const(iss, "ApprovedKey") == autostart.APPROVED_KEY
    assert _const(iss, "RunValueName") == autostart.VALUE_NAME


@pytest.mark.parametrize(
    "exe",
    [
        r"C:\Users\yuval\AppData\Local\Programs\Morphwheel\morphwheel.exe",
        r"C:\Users\Yuval Ram\AppData\Local\Programs\Morphwheel\morphwheel.exe",
        r"C:\Users\yuval\AppData\Local\Programs\Morphwheel (2)\morphwheel.exe",
        r"D:\Apps\Morph&wheel\morphwheel.exe",
        r"C:\Users\יובל\AppData\Local\Programs\Morphwheel\morphwheel.exe",
    ],
)
def test_the_quoting_rule_matches_list2cmdline(iss: str, exe: str) -> None:
    """The script quotes iff the path has a space; that is what the app writes (RD-23)."""
    body = (
        "  if Pos(' ', Exe) > 0 then\n    Result := '\"' + Exe + '\"'\n  else\n    Result := Exe;\n"
    )
    assert body in iss
    expected = subprocess.list2cmdline([exe])
    ours = f'"{exe}"' if " " in exe else exe
    assert ours == expected


def test_per_user_without_uac(iss: str) -> None:
    assert _directive(iss, "PrivilegesRequired") == "lowest"
    assert _directive(iss, "DefaultDirName") == "{autopf}\\{#AppName}"
    assert "PrivilegesRequiredOverridesAllowed" not in iss  # no "run as admin" offer
    assert "function InitializeSetup(): Boolean;" in iss
    assert "function InitializeUninstall(): Boolean;" in iss
    assert iss.count("Result := RefuseIfElevated();") == 2
    assert "TokenElevationTypeFull = 2;" in iss  # is_elevated: the full half of a split token


def test_launch_runs_as_the_original_user_and_not_when_silent(iss: str) -> None:
    run = re.search(r"^\[Run\]\n(.+)$", iss, re.MULTILINE)
    assert run is not None
    line = run.group(1)
    assert 'Filename: "{app}\\morphwheel.exe"' in line
    for flag in ("postinstall", "runasoriginaluser", "skipifsilent", "nowait"):
        assert flag in line.split("Flags:")[1], flag


def test_the_autostart_task_is_an_exact_setter(iss: str) -> None:
    assert re.search(r'^Name: "autostart";.*Flags: unchecked$', iss, re.MULTILINE)  # app default
    assert _directive(iss, "UsePreviousTasks") == "no"  # the registry is the truth, not Inno
    assert "if CurStep = ssPostInstall then" in iss
    assert "else if not WizardSilent then" in iss  # a silent run never turns autostart off
    assert "if HadRunValue and not CmdLineSetsTasks() then" in iss  # mirror once, /TASKS wins
    assert "Pos('/TASKS', Tail) > 0) or (Pos('/LOADINF', Tail) > 0" in iss
    assert '#if AppVersion == "" || FileVersion == ""' in iss  # never a nameless installer


def test_the_uninstaller_deletes_the_run_value_and_asks_about_data(iss: str) -> None:
    assert "if CurUninstallStep = usUninstall then" in iss
    assert "DeleteRunValue();" in iss
    assert "if not UninstallSilent then" in iss
    assert "MB_YESNO or MB_DEFBUTTON2" in iss  # default No
    assert "{userappdata}\\' + '{#AppName}'" in iss
    assert "{localappdata}\\' + '{#AppName}'" in iss
    name = re.search(r'^#define AppName "(.*)"$', iss, re.MULTILINE)
    assert name is not None
    assert name.group(1) == APP_NAME
    assert "plugins" in _directive(iss, "english.DeleteDataQuestion").lower()
    assert "Downloads" not in iss.split("[Code]")[1]  # converted files are never touched


def test_upgrades_clean_the_frozen_folder_and_never_relaunch(iss: str) -> None:
    assert 'Type: filesandordirs; Name: "{app}\\_internal"' in iss
    assert _directive(iss, "CloseApplications") == "yes"  # files in use: ask, don't fail
    assert _directive(iss, "RestartApplications") == "no"  # only the Launch checkbox starts the app
    assert _directive(iss, "AppMutex") == single_instance.MUTEX_NAME  # and the mutex comes first


def test_the_referenced_files_exist(iss: str) -> None:
    assert (ROOT / "LICENSE").is_file()
    assert (ROOT / "assets" / "icon" / "morphwheel.ico").is_file()
    assert _directive(iss, "LicenseFile") == "{#RepoRoot}\\LICENSE"
    assert _directive(iss, "SetupIconFile") == "{#RepoRoot}\\assets\\icon\\morphwheel.ico"


def test_the_version_comes_from_the_exe(iss: str) -> None:
    assert 'GetStringFileInfo(AppExe, "ProductVersion")' in iss
    assert "GetVersionNumbersString(AppExe)" in iss
    assert not re.search(r"^AppVersion=\d", iss, re.MULTILINE)  # never a literal


def test_the_platform_floor(iss: str) -> None:
    assert _directive(iss, "MinVersion") == "10.0.19045"  # Windows 10 22H2 (D4: best-effort floor)
    assert _directive(iss, "ArchitecturesAllowed") == "x64compatible"
    assert _directive(iss, "ArchitecturesInstallIn64BitMode") == "x64compatible"


def test_pillow_heif_is_refused_and_there_is_no_heic_checkbox(iss: str) -> None:
    guard = re.search(r"^#if .*pillow_heif.*\n\s*#error (.*)$", iss, re.MULTILINE)
    assert guard is not None
    assert "A6" in guard.group(1)
    assert "install-heic" not in iss  # RD-30: the in-app consent flow is the only HEIC path


def test_every_user_string_is_a_custom_message(iss: str) -> None:
    """Strings of ours live under a language prefix (D3a); Inno's own are {cm:...} references."""
    for key in ("ElevatedRefused", "DeleteDataQuestion"):
        assert re.search(rf"^english\.{key}=", iss, re.MULTILINE), key
        assert f"CustomMessage('{key}')" in iss, key
    assert "{cm:AutoStartProgram," in iss
    assert "{cm:LaunchProgram," in iss


def test_a_wrong_mutex_would_fail(iss: str) -> None:
    """Negative control: the agreement tests can fail."""
    broken = iss.replace("AppMutex=Local\\Morphwheel", "AppMutex=Morphwheel")
    assert _directive(broken, "AppMutex") != single_instance.MUTEX_NAME
