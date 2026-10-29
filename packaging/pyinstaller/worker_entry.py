"""Entry point of ``morphwheel-worker.exe``, the Qt-free worker executable (decision A5a).

PyInstaller's PySide6 runtime hook loads QtCore into every process started from ``morphwheel.exe``,
spawned workers included (S0 finding 1). So the workers run from this second executable, built from
its own Analysis that excludes PySide6. ``multiprocessing.set_executable`` points the pool at it
(``engine.worker_pool.default_worker_executable``).

The process is only ever started by ``multiprocessing``: its command line carries
``--multiprocessing-fork``, and ``freeze_support()`` (patched by PyInstaller's multiprocessing hook)
takes over and runs ``morphwheel.engine.worker_main.worker_loop``. Started by hand, it says so and
exits.

The imports below make the worker's code, and the builtin converter it loads by name, part of this
executable's bundle. Nothing here may import Qt (R2).
"""

from __future__ import annotations

import multiprocessing
import sys

import morphwheel.builtin.pillow_images.converter
import morphwheel.engine.worker_main  # noqa: F401  the pickled Process target lives here

if __name__ == "__main__":
    multiprocessing.freeze_support()  # a spawned worker never returns from this call
    sys.exit("morphwheel-worker.exe is started by Morphwheel, not by hand")
