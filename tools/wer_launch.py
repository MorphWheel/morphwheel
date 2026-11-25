"""Run a module as ``python -m`` would, with Windows Error Reporting allowed to see a crash.

Used by the CI and stress workflows (``.github/workflows/``) to run pytest. The GitHub runner
starts its processes with ``SEM_NOGPFAULTERRORBOX`` in their error mode, and a process with that bit
set never reaches WER, so the ``LocalDumps`` settings write nothing when it crashes (shown on the
runner, 2026-11-25). This clears that one bit, keeps the rest of the mode (no new message boxes),
and then runs the module. Child processes, the test workers included, inherit the mode.

    python tools/wer_launch.py pytest -q          # as: python -m pytest -q
    python tools/wer_launch.py --crash            # a real access violation, for a canary

``--crash`` really crashes the process. Run it only where WER is set not to show its dialog.
"""

from __future__ import annotations

import ctypes
import runpy
import sys
from pathlib import Path

SEM_NOGPFAULTERRORBOX = 0x0002


def allow_wer() -> tuple[int, int]:
    """Clear ``SEM_NOGPFAULTERRORBOX`` from this process's error mode; returns (before, after)."""
    kernel32 = ctypes.WinDLL("kernel32")
    before = int(kernel32.GetErrorMode())
    kernel32.SetErrorMode(before & ~SEM_NOGPFAULTERRORBOX)
    return before, int(kernel32.GetErrorMode())


def main(argv: list[str]) -> None:
    if not argv:
        raise SystemExit("usage: wer_launch.py MODULE [ARGS...] | --crash")
    before, after = allow_wer()
    print(f"wer_launch: error mode {before:#06x} -> {after:#06x}", file=sys.stderr, flush=True)
    if argv == ["--crash"]:
        # A plain read of address 1. Not ctypes.string_at(0): ctypes guards its foreign calls on
        # Windows and turns that fault into an OSError, so the process would not crash.
        ctypes.cast(1, ctypes.POINTER(ctypes.c_int))[0]
        raise SystemExit("wer_launch: --crash did not crash")
    module, *rest = argv
    sys.argv = [module, *rest]
    sys.path[0] = str(Path.cwd())  # as `python -m` has it, not this script's folder
    runpy.run_module(module, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main(sys.argv[1:])
