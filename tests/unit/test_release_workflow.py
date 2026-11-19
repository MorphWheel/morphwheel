"""The release workflow (S7 file 3, RD-31), parsed, not pattern-matched.

The run itself is proven on GitHub (a tag push, or a manual rehearsal); what a test can hold is the
shape that keeps it safe: minimal permissions per job, every third-party action pinned to a commit,
the signing and publishing steps gated on a tag push of this repository, the build chain in the
order the spec needs, pwsh idioms that actually fail (no ``$GITHUB_*`` in pwsh, Start-Process for
the windowed exe, no redirections into release files), and the SignPath inputs spelled as the
action expects (GitHub only warns about an unknown input). ``ci.yml`` is held to the same pin
rule.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
PIN = re.compile(r"^(?P<action>[\w.-]+/[\w.-]+)@(?P<sha>[0-9a-f]{40}) # v\d+(\.\d+)*$")
TAG_PUSH = "github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')"
THIS_REPO = "github.repository == 'MorphWheel/morphwheel'"
SIGNPATH_INPUTS = {
    "api-token",
    "organization-id",
    "project-slug",
    "signing-policy-slug",
    "artifact-configuration-slug",
    "github-artifact-id",
    "wait-for-completion",
    "wait-for-completion-timeout-in-seconds",
    "output-artifact-directory",
    "github-token",
    "parameters",
    "skip-decompress",
    "connector-url",
}


@pytest.fixture(scope="module")
def workflow() -> dict[Any, Any]:
    loaded = yaml.safe_load((WORKFLOWS / "release.yml").read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


@pytest.fixture(scope="module")
def steps(workflow: dict[Any, Any]) -> dict[str, list[dict[str, Any]]]:
    return {name: job["steps"] for name, job in workflow["jobs"].items()}


def _run_steps(steps: list[dict[str, Any]]) -> list[str]:
    return [s["run"] for s in steps if "run" in s]


def _step(steps: list[dict[str, Any]], name_part: str) -> dict[str, Any]:
    found = [s for s in steps if name_part.lower() in str(s.get("name", "")).lower()]
    assert len(found) == 1, (name_part, [s.get("name") for s in found])
    return found[0]


def _index(steps: list[dict[str, Any]], name_part: str) -> int:
    return steps.index(_step(steps, name_part))


def test_triggers_are_version_tags_and_a_manual_rehearsal(workflow: dict[Any, Any]) -> None:
    on = workflow[True]  # PyYAML reads the bare key `on` as a boolean
    assert on == {"push": {"tags": ["v*"]}, "workflow_dispatch": None}
    assert workflow["concurrency"] == {
        "group": "release-${{ github.ref }}",
        "cancel-in-progress": False,
    }


def test_permissions_are_minimal_per_job(workflow: dict[Any, Any]) -> None:
    assert workflow["permissions"] == {"contents": "read"}
    jobs = workflow["jobs"]
    assert set(jobs) == {"build", "publish"}
    assert jobs["build"]["permissions"] == {"contents": "read", "actions": "read"}
    assert jobs["publish"]["permissions"] == {"contents": "write"}
    assert jobs["publish"]["needs"] == "build"
    assert jobs["publish"]["if"] == f"{TAG_PUSH} && {THIS_REPO}"
    for job in jobs.values():
        assert job["runs-on"] == "windows-latest"
        assert "timeout-minutes" in job


@pytest.mark.parametrize("name", ["release.yml", "ci.yml"])
def test_every_action_is_pinned_to_a_commit(name: str) -> None:
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    uses = re.findall(r"^\s*-?\s*uses:\s*(.+)$", text, re.MULTILINE)
    assert uses, name
    for ref in uses:
        assert PIN.match(ref.strip()), f"{name}: unpinned or uncommented action {ref!r}"


def test_checkout_never_keeps_credentials(steps: dict[str, list[dict[str, Any]]]) -> None:
    for job_steps in steps.values():
        for step in job_steps:
            if str(step.get("uses", "")).startswith("actions/checkout@"):
                assert step["with"] == {"persist-credentials": False}


def test_the_build_chain_is_in_the_specs_order(steps: dict[str, list[dict[str, Any]]]) -> None:
    build = steps["build"]
    order = [
        _index(build, "Version"),
        _index(build, "Install the dev extra"),
        _index(build, "No pillow-heif"),
        _index(build, "Translations"),
        _index(build, "PyInstaller"),
        _index(build, "Worker check"),
        _index(build, "Sign the executables"),
        _index(build, "Use the signed executables"),
        _index(build, "Inno Setup"),
        _index(build, "Installer name and size"),
        _index(build, "Sign the installer"),
        _index(build, "Use the signed installer"),
        _index(build, "Checksums and release notes"),
        _index(build, "winget manifests"),
        _index(build, "Upload the release files"),
    ]
    assert order == sorted(order)
    winget = _step(build, "winget manifests")  # after the signed installer and its checksum
    assert "if" not in winget  # the rehearsal renders it too
    assert "winget $env:VERSION" in winget["run"]
    assert winget["run"].rstrip().endswith(r"-o packaging\output\installer\winget")
    assert (
        _step(build, "Install the dev extra")["run"] == 'python -m pip install -e ".[dev]"'
    )  # never [heic] (A6)
    assert "pillow_heif" in _step(build, "No pillow-heif")["run"]
    assert _step(build, "Translations")["run"] == "python tools/translations.py release"
    assert "--max-mb 45" in _step(build, "Installer name and size")["run"]  # T6
    assert "check-tag $env:TAG" in _step(build, "Version")["run"]


def test_the_worker_check_waits_for_the_windowed_exe(
    steps: dict[str, list[dict[str, Any]]],
) -> None:
    run = _step(steps["build"], "Worker check")["run"]
    assert "Start-Process" in run
    assert "-Wait -PassThru" in run
    assert "--worker-check" in run
    assert run.rstrip().endswith("exit $p.ExitCode")


def test_pwsh_idioms(steps: dict[str, list[dict[str, Any]]]) -> None:
    for job_steps in steps.values():
        for run in _run_steps(job_steps):
            assert "$GITHUB_" not in run, run  # pwsh: $env:NAME, or an env: block
            assert not re.search(r">\s*\S", run.replace("2>$null", "")), run  # no redirections
            commands = [
                ln for ln in run.splitlines() if ln.strip() and not ln.strip().startswith("#")
            ]
            native = re.compile(r"(\s*|.*=\s*)&?\s*(python|pyinstaller|gh)\b")
            natives = [ln for ln in commands if native.match(ln)]
            if len(natives) > 1:
                assert "$PSNativeCommandUseErrorActionPreference = $true" in run, run


def test_signing_is_optional_and_gated(
    steps: dict[str, list[dict[str, Any]]], workflow: dict[Any, Any]
) -> None:
    gate = workflow["env"]["SIGNING"]
    assert TAG_PUSH in gate
    assert THIS_REPO in gate
    assert "vars.SIGNPATH_ORGANIZATION_ID != ''" in gate
    assert "secrets." not in gate  # secrets cannot be read in an expression that gates
    build = steps["build"]
    signing = [
        s for s in build if "signpath/github-action-submit-signing-request@" in str(s.get("uses"))
    ]
    assert len(signing) == 2
    for step in signing:
        assert step["if"] == "env.SIGNING == 'true'"
        assert set(step["with"]) <= SIGNPATH_INPUTS, set(step["with"]) - SIGNPATH_INPUTS
        assert step["with"]["wait-for-completion-timeout-in-seconds"] == 3600
        assert step["with"]["api-token"] == "${{ secrets.SIGNPATH_API_TOKEN }}"
    configs = {s["with"]["artifact-configuration-slug"] for s in signing}
    assert configs == {"${{ vars.SIGNPATH_CONFIG_EXES }}", "${{ vars.SIGNPATH_CONFIG_INSTALLER }}"}
    gated = [s for s in build if s.get("if") == "env.SIGNING == 'true'"]
    assert len(gated) == 6  # upload, sign, use: twice
    for step in gated:
        if "run" in step:
            assert (
                "Get-AuthenticodeSignature" in step["run"]
            )  # a signed file is verified before use
    for step in build:
        if str(step.get("uses", "")).startswith("actions/upload-artifact@"):
            assert step["with"]["overwrite"] is True  # a re-run must not collide
            assert step["with"]["if-no-files-found"] == "error"
    assert workflow["jobs"]["build"]["timeout-minutes"] >= 60  # a manual approval may take a while


def test_publish_verifies_and_never_overwrites_a_published_release(
    steps: dict[str, list[dict[str, Any]]], workflow: dict[Any, Any]
) -> None:
    publish = steps["publish"]
    env = workflow["jobs"]["publish"]["env"]
    assert env["GH_TOKEN"] == "${{ github.token }}"
    assert env["GH_REPO"] == "${{ github.repository }}"  # no git remote to infer it from
    assert _index(publish, "Verify the checksums") < _index(publish, "Draft release")
    assert (
        _step(publish, "Verify the checksums")["run"]
        == "python tools/release.py verify release/SHA256SUMS.txt"
    )
    draft = _step(publish, "Draft release")["run"]
    assert "--draft" in draft
    assert "--verify-tag" in draft
    assert "isDraft" in draft
    assert "2>" not in draft  # no swallowed stderr: the existence check is a list
    assert "already published" in draft
    assert "--latest=false" in draft
    assert "GH_TOKEN" not in str(
        workflow["jobs"]["build"]
    )  # the build job never holds a write token


def test_a_broken_pin_is_caught() -> None:
    """Negative control for the pin rule."""
    assert PIN.match("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1")
    assert not PIN.match("actions/checkout@v7")
    assert not PIN.match("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1")
    assert not PIN.match("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b # v7.0.1")
