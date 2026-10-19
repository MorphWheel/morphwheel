"""Entry point for ``python -m morphwheel`` and the frozen ``morphwheel.exe``.

Worker processes are spawned from this same executable (multiprocessing "spawn"). They must never
load Qt (phase-4 §1, R2), so this module imports nothing heavy at the top level, and
``freeze_support()`` runs before anything else. In a frozen worker it takes over and never returns.
"""

from __future__ import annotations

import multiprocessing
import sys


def main() -> int:
    multiprocessing.freeze_support()
    from morphwheel.app.application import run  # Qt is imported only past this point

    return run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
