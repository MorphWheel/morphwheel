"""The CI workflow (``.github/workflows/ci.yml``), parsed: its crash-dump capture.

A native crash in the tests should leave a dump, without changing what CI checks. What a test can
hold: the dump setup comes before the tests and can never fail the job; the tests run through
``tools/wer_launch.py`` (its own tests: ``test_wer_launch.py``); the dumps are uploaded only when
the job fails, each attempt under its own name, and nothing else goes into that artifact.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / ".github" / "workflows" / "ci.yml"


@pytest.fixture(scope="module")
def steps() -> list[dict[str, Any]]:
    loaded = yaml.safe_load(CI.read_text(encoding="utf-8"))
    (job,) = loaded["jobs"].values()
    return list(job["steps"])


def _index(steps: list[dict[str, Any]], name: str) -> int:
    found = [i for i, s in enumerate(steps) if s.get("name") == name]
    assert len(found) == 1, name
    return found[0]


def test_the_dumps_are_set_up_before_the_tests_and_never_fail_the_job(
    steps: list[dict[str, Any]],
) -> None:
    dumps = _index(steps, "Turn on crash dumps (this runner only)")
    assert dumps < _index(steps, "Tests")
    step = steps[dumps]
    assert step["continue-on-error"] is True
    assert step["timeout-minutes"] <= 5  # nor can a stalled one hold the job
    run = step["run"]
    assert r'$key = "$wer\LocalDumps\python.exe"' in run
    assert '$dumps = Join-Path $env:RUNNER_TEMP "ci-dumps"' in run
    assert "python -X faulthandler tools/wer_launch.py --crash" in run  # the canary, as pytest runs
    assert "Get-Process -Name WerFault" in run  # its dump is complete before it is removed
    assert "Remove-Item -LiteralPath $f.FullName" in run  # only real crashes reach the artifact
    assert run.rstrip().endswith("exit 0")
    assert "${{" not in run


def test_the_tests_run_through_the_launcher(steps: list[dict[str, Any]]) -> None:
    run = steps[_index(steps, "Tests")]["run"]
    assert run.split("#")[0].strip() == "python tools/wer_launch.py pytest"
    assert (ROOT / "tools" / "wer_launch.py").is_file()


def test_the_dumps_are_uploaded_only_on_failure(steps: list[dict[str, Any]]) -> None:
    tests = _index(steps, "Tests")
    wait = _index(steps, "Wait for crash dumps to be written")
    upload = _index(steps, "Upload crash dumps")
    assert tests < wait < upload == len(steps) - 1
    assert steps[wait]["if"] == "failure()"
    assert "Get-Process -Name WerFault" in steps[wait]["run"]
    assert "1..180" in steps[wait]["run"]  # time for a full dump of a pytest process
    step = steps[upload]
    assert step["if"] == "failure()"
    assert str(step["uses"]).startswith("actions/upload-artifact@")
    assert step["with"]["path"] == "${{ runner.temp }}/ci-dumps"  # the dumps folder only
    assert step["with"]["name"] == "ci-dumps-${{ github.run_id }}-${{ github.run_attempt }}"
    assert step["with"]["if-no-files-found"] == "ignore"
    assert step["with"]["retention-days"] <= 14
