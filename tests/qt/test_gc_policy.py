"""The suite's garbage-collection rule (``tests/conftest.py``) and the cycles it exists for.

On 2026-11-26 three CI runs died with an access violation: the main thread delivered a tick of a
``ModifierPoller``'s 8 ms timer to a freed poller (read from the crash dumps). Python's cyclic GC
runs on whichever thread is allocating, so a cycle holding a QObject with a running timer can be
freed on a background thread; Qt can't unregister the timer from there and leaves it pointing at
freed memory. The suite therefore collects on the main thread only, and the app's own objects
avoid cycles where they can (``_EngineJob``).
"""

from __future__ import annotations

import gc
import os
import subprocess
import sys
import threading
import weakref
from pathlib import Path

import pytest

import conftest
from morphwheel.app.application import _EngineJob
from morphwheel.engine import engines

pytestmark = pytest.mark.usefixtures("qapp")


def test_automatic_collection_is_off_during_tests() -> None:
    assert not gc.isenabled()


def test_a_collection_off_the_main_thread_is_noted() -> None:
    before = list(conftest.off_main_collections)
    gc.collect()  # the control: the main thread's own collection is not noted
    assert conftest.off_main_collections == before
    collector = threading.Thread(target=gc.collect, name="mw-test-collector")
    collector.start()
    collector.join()
    try:
        assert conftest.off_main_collections[len(before) :] == ["generation 2 on mw-test-collector"]
    finally:
        conftest.off_main_collections.clear()  # this one was on purpose: the teardown mustn't fail


CYCLE_WITH_A_TIMER = """
import gc, os, sys, threading
from PySide6.QtCore import QCoreApplication, QObject, QTimer, qInstallMessageHandler

messages = []
qInstallMessageHandler(lambda mode, context, message: messages.append(message))
app = QCoreApplication([])
gc.disable()


class Cycle(QObject):
    def __init__(self):
        super().__init__()
        self.me = self  # only the cyclic GC can free it
        self.timer = QTimer(self)
        # Over 20 ms: Windows then runs it as a plain timer. A faster one is a multimedia timer,
        # whose thread can hang the process at exit once its object is freed (seen 1 in 8).
        self.timer.setInterval(1000)
        self.timer.start()


Cycle()
if sys.argv[1] == "worker":
    collector = threading.Thread(target=gc.collect)
    collector.start()
    collector.join()
else:
    gc.collect()
print(any("Timers cannot be stopped from another thread" in m for m in messages), flush=True)
os._exit(0)  # never process events: after a collection on the worker, the timer is dangling
"""


@pytest.mark.parametrize(("collected_on", "dangling"), [("worker", True), ("main", False)])
def test_a_cycle_with_a_running_timer_must_be_freed_on_the_main_thread(
    tmp_path: Path, collected_on: str, dangling: bool
) -> None:
    """Why the rule exists, in a separate process (a dangling timer would crash this one)."""
    script = tmp_path / "cycle.py"
    script.write_text(CYCLE_WITH_A_TIMER, encoding="utf-8")
    done = subprocess.run(
        [sys.executable, "-I", str(script), collected_on],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == str(dangling)


def _unexpected(url: str) -> bytes:
    raise RuntimeError("the network stack broke")


@pytest.mark.parametrize(
    "fetch", [lambda url: b"not the pinned wheel", _unexpected], ids=["mismatch", "unexpected"]
)
def test_a_failed_heic_install_leaves_no_cycle(tmp_path: Path, fetch: engines.Fetch) -> None:
    """A job that ends in a cycle is freed by the GC on whatever thread collects: a QObject must
    die on its own thread. Freed by its reference count, it dies where the app drops it."""
    job = _EngineJob(tmp_path / "engines", fetch)
    results: list[object] = []
    job.done.connect(results.append)
    job._run()  # on this thread, so the result arrives at once
    [error] = results
    assert isinstance(error, engines.EngineInstallError)
    gone = weakref.ref(job)
    del job, error
    results.clear()
    assert gone() is None
