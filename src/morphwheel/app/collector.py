"""``MainThreadCollector``: Python's cyclic garbage collector runs on the main thread only (RD-38).

Python's automatic collection runs on whichever thread is allocating when a threshold is
crossed. In this process that can be the engine's supervisor threads, the sniffer or the HEIC
install thread. A cycle that holds a QObject, freed there, dies on the wrong thread: a running
timer of it stays registered with the main thread's dispatcher, pointing at freed memory, and the
main thread crashes on its next tick. CI crashed that way (a ``ModifierPoller``'s 8 ms timer,
read from the crash dumps of 2026-11-26).

So the GUI process turns automatic collection off and collects from a timer on the main thread:

- ``disable_automatic()`` runs in ``run()`` before the ``Application`` exists, so before any of
  its threads start. Automatic collection then stays off for the life of the process. At exit,
  the interpreter's own final collection runs on the main thread.
- Every ``INTERVAL_MS``, ``MainThreadCollector`` collects the generation that automatic
  collection would have collected (``due_generation``, CPython 3.12's rule: the oldest
  generation whose count passed its threshold). The counts keep climbing while collection is
  off. Measured in the app's process: a full collection takes about 3 ms.
- ``stop()`` runs a last full collection, here on the main thread, and leaves automatic
  collection off. Turning it back on while the app's threads may still run would reopen the gap.
- A tick that finds automatic collection on again (some library turned it on) logs a warning
  once and turns it off.

Limits: a QObject freed by its *reference count* on another thread still dies there, so app code
must not let a thread hold the last reference to one. The HEIC install's ``_EngineJob`` is held
by its own thread too, so the app lets go of it through ``_EngineJob.retire``. A library that
calls ``gc.collect()`` itself on another thread is not prevented. The worker processes are
separate interpreters, never load Qt and keep automatic collection.
"""

from __future__ import annotations

import gc
import logging
import threading

from PySide6.QtCore import QObject, QTimer

log = logging.getLogger(__name__)

INTERVAL_MS = 1000  # a plain timer (over 20 ms, so no multimedia timer on Windows)


def due_generation(counts: tuple[int, int, int], thresholds: tuple[int, int, int]) -> int | None:
    """The generation automatic collection would collect now, or ``None``: the oldest one whose
    count passed its threshold (``gc.get_count()``, ``gc.get_threshold()``). A threshold of 0
    means that generation is never collected automatically (``gc.set_threshold(0)``)."""
    for generation in (2, 1, 0):
        if thresholds[generation] and counts[generation] > thresholds[generation]:
            return generation
    return None


def disable_automatic() -> None:
    """Turn automatic collection off. Call it on the main thread before any other thread starts."""
    gc.disable()


class MainThreadCollector(QObject):
    def __init__(self, parent: QObject | None = None, *, interval_ms: int = INTERVAL_MS) -> None:
        super().__init__(parent)
        self._warned = False
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.tick)

    @property
    def active(self) -> bool:
        return self._timer.isActive()

    def start(self) -> None:
        """Turn automatic collection off and start collecting on this, the main, thread.
        Idempotent."""
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("the collector must run on the main thread")
        disable_automatic()
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        """A last full collection, on the main thread. Automatic collection stays off."""
        self._timer.stop()
        gc.collect()

    def tick(self) -> None:
        if gc.isenabled():
            if not self._warned:
                self._warned = True
                log.warning("automatic garbage collection was turned on again; turning it off")
            gc.disable()
        generation = due_generation(gc.get_count(), gc.get_threshold())
        if generation is not None:
            gc.collect(generation)
