"""``tools/wer_launch.py``: runs a module as ``python -m`` would, with crashes allowed to reach WER.

The CI and stress workflows run pytest through it. What a test can hold here: it clears only the
``SEM_NOGPFAULTERRORBOX`` bit and keeps the rest of the mode; importing it changes nothing; the
module runs with the arguments, the import path and the exit code of ``python -m``; and the
child processes inherit the cleared bit. ``--crash`` is not run here: it is a real access violation,
and on a developer machine WER would show its dialog. The stress workflow's canaries prove it.
"""

from __future__ import annotations

import ctypes
import json
import subprocess
import sys
from pathlib import Path

import pytest

import wer_launch  # tools/ is on pytest's pythonpath

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "tools" / "wer_launch.py"
KERNEL32 = ctypes.WinDLL("kernel32")

PROBE = """\
import ctypes, json, sys
print(json.dumps({
    "mode": ctypes.WinDLL("kernel32").GetErrorMode(),
    "argv": sys.argv,
    "path0": sys.path[0],
    "name": __name__,
}))
raise SystemExit(int(sys.argv[1]) if sys.argv[1:] else 0)
"""


def _launch(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    (tmp_path / "probe_mod.py").write_text(PROBE, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(LAUNCHER), *args],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_it_clears_only_the_bit_that_keeps_wer_away() -> None:
    saved = KERNEL32.SetErrorMode(0x8003)  # the runner's mode
    try:
        assert wer_launch.allow_wer() == (0x8003, 0x8001)  # the other boxes stay off
        assert wer_launch.allow_wer() == (0x8001, 0x8001)
    finally:
        KERNEL32.SetErrorMode(saved)


def test_importing_it_changes_nothing() -> None:
    import importlib

    saved = KERNEL32.SetErrorMode(0x8003)  # the bit set, so a cleared one would show
    try:
        importlib.reload(wer_launch)
        assert KERNEL32.GetErrorMode() == 0x8003
    finally:
        KERNEL32.SetErrorMode(saved)


def test_the_module_runs_as_under_python_m(tmp_path: Path) -> None:
    done = _launch(tmp_path, "probe_mod", "0", "--flag")
    assert done.returncode == 0, done.stderr
    seen = json.loads(done.stdout)
    assert seen["name"] == "__main__"
    assert seen["argv"][1:] == ["0", "--flag"]
    assert Path(seen["argv"][0]) == tmp_path / "probe_mod.py"  # as runpy sets it for `-m`
    assert Path(seen["path0"]) == tmp_path  # the working folder, not tools/
    assert seen["mode"] & wer_launch.SEM_NOGPFAULTERRORBOX == 0
    assert "wer_launch: error mode" in done.stderr


def test_the_exit_code_passes_through(tmp_path: Path) -> None:
    assert _launch(tmp_path, "probe_mod", "3").returncode == 3  # a failed pytest still fails CI


def test_a_child_process_inherits_the_cleared_bit(tmp_path: Path) -> None:
    (tmp_path / "spawner.py").write_text(
        "import subprocess, sys\n"
        "raise SystemExit(subprocess.run([sys.executable, '-m', 'probe_mod', '0']).returncode)\n",
        encoding="utf-8",
    )
    done = _launch(tmp_path, "spawner")
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["mode"] & wer_launch.SEM_NOGPFAULTERRORBOX == 0


def test_no_module_is_a_usage_error() -> None:
    with pytest.raises(SystemExit, match="usage"):
        wer_launch.main([])
