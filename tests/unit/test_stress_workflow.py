"""The stress workflow (``.github/workflows/stress.yml``), parsed: the by-hand loop that hunts the
intermittent access violation with a native dump.

The run itself is proven on GitHub. What a test can hold: it only runs by hand, with read-only
permissions; the inputs reach the scripts through ``env`` and are never spliced into them; the dump
settings, the error-mode launcher and the three canaries come before the loop, which runs pytest
through the launcher; failures are judged by exit code; a run over its time limit is killed with
its tree; the artifact is uploaded even when the loop fails; and the default test list names files
that exist.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
STRESS = ROOT / ".github" / "workflows" / "stress.yml"


@pytest.fixture(scope="module")
def workflow() -> dict[Any, Any]:
    loaded = yaml.safe_load(STRESS.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


@pytest.fixture(scope="module")
def steps(workflow: dict[Any, Any]) -> list[dict[str, Any]]:
    (job,) = workflow["jobs"].values()
    return list(job["steps"])


def _index(steps: list[dict[str, Any]], name_part: str) -> int:
    found = [i for i, s in enumerate(steps) if name_part.lower() in str(s.get("name", "")).lower()]
    assert len(found) == 1, name_part
    return found[0]


def test_it_runs_by_hand_only_with_read_permissions(workflow: dict[Any, Any]) -> None:
    triggers = workflow[True]  # PyYAML reads the bare key `on` as True
    assert set(triggers) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    (job,) = workflow["jobs"].values()
    assert "permissions" not in job  # nothing wider than the workflow's


def test_the_inputs_are_never_spliced_into_a_script(steps: list[dict[str, Any]]) -> None:
    for step in steps:
        run = step.get("run", "")
        assert "${{" not in run, step.get("name")  # inputs arrive through env only
    loop = steps[_index(steps, "loop")]
    assert loop["env"] == {
        "STRESS_ITERATIONS": "${{ inputs.iterations }}",
        "STRESS_RUN_MINUTES": "${{ inputs.run_minutes }}",
        "STRESS_TESTS": "${{ inputs.tests }}",
    }


def test_the_dumps_are_set_up_and_proven_before_the_loop(steps: list[dict[str, Any]]) -> None:
    dumps, canary, loop = (_index(steps, n) for n in ("crash dumps", "canary", "loop"))
    assert dumps < canary < loop
    setup = steps[dumps]["run"]
    assert r'$wer = "HKLM:\SOFTWARE\Microsoft\Windows\Windows Error Reporting"' in setup
    assert r'$key = "$wer\LocalDumps\python.exe"' in setup
    assert "-Name DumpFolder" in setup
    assert "SetErrorMode(0)" in setup  # the launcher: an inherited SEM_NOGPFAULTERRORBOX skips WER
    assert "sys.path[0] = os.getcwd()" in setup  # imports as under `python -m pytest`
    assert "ctypes.cast(1, ctypes.POINTER(ctypes.c_int))[0]" in setup  # a real fault
    run = steps[canary]["run"]
    assert "ctypes.cast(1, ctypes.POINTER(ctypes.c_int))[0]" in run  # the inherited-mode canary
    assert 'string_at(0)"' not in run + setup  # ctypes turns that fault into an OSError on Windows
    assert '@($launcher, "--crash")' in run
    assert '@("-X", "faulthandler", $launcher, "--crash")' in run  # the way pytest runs
    assert "Get-Process -Name WerFault" in run  # the dump is complete before it is removed
    assert "exit 0" in run  # a missing dump warns; the loop still runs


def test_failures_are_counted_by_exit_code(steps: list[dict[str, Any]]) -> None:
    run = steps[_index(steps, "loop")]["run"]
    assert "$p.ExitCode -eq 0" in run
    assert '$pytest = @($launcher, "pytest",' in run  # every run resets its error mode
    assert "access violation" not in run.lower()  # faulthandler prints handled ones too
    assert "PSNativeCommandUseErrorActionPreference" not in run  # one failed run must not stop it
    assert "$env:GITHUB_STEP_SUMMARY" in run
    assert "$GITHUB_" not in run.replace("$env:GITHUB_", "")  # pwsh reads env as $env:NAME


def test_the_artifact_is_uploaded_whatever_the_loop_did(steps: list[dict[str, Any]]) -> None:
    upload = steps[_index(steps, "upload")]
    assert upload["if"] == "always()"
    assert str(upload["uses"]).startswith("actions/upload-artifact@")
    assert upload["with"]["path"] == "${{ runner.temp }}/stress"
    assert upload["with"]["if-no-files-found"] == "ignore"


def test_the_default_test_list_names_files_that_exist(workflow: dict[Any, Any]) -> None:
    default = workflow[True]["workflow_dispatch"]["inputs"]["tests"]["default"]
    paths = default.split()
    assert paths[-1] == "tests/qt/test_plugin_failures.py"  # the file the crash happened in
    for path in paths:
        assert (ROOT / path).exists(), path


def test_bad_numbers_are_refused(steps: list[dict[str, Any]]) -> None:
    run = steps[_index(steps, "loop")]["run"]
    assert re.search(
        r"TryParse\(\$env:STRESS_ITERATIONS, \[ref\]\$n\) -or \$n -lt 1 -or \$n -gt 100", run
    )
    assert re.search(r"TryParse\(\$env:STRESS_RUN_MINUTES, .* -gt 60", run)


def test_a_hung_run_is_killed_with_its_workers(
    workflow: dict[Any, Any], steps: list[dict[str, Any]]
) -> None:
    run = steps[_index(steps, "loop")]["run"]
    assert "$p.WaitForExit($minutes * 60000)" in run
    assert "try { $p.Kill($true) } catch" in run  # the tree; it may have exited just now
    assert "try { Remove-Item -LiteralPath $out, $err } catch" in run  # a worker may hold the log
    assert "$null = $p.Handle" in run  # else ExitCode reads as null after the exit
    (job,) = workflow["jobs"].values()
    assert job["timeout-minutes"] >= 300  # the iteration cap fits before the job is cancelled
