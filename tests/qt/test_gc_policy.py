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
import logging
import os
import subprocess
import sys
import threading
import weakref
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

import conftest
from morphwheel.app import collector
from morphwheel.app.application import _EngineJob
from morphwheel.app.collector import MainThreadCollector, due_generation
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


# ------------------------------------------------------------------ the app's collector (RD-38(e))
@pytest.mark.parametrize(
    ("counts", "thresholds", "due"),
    [
        ((0, 0, 0), (700, 10, 10), None),
        ((700, 10, 10), (700, 10, 10), None),  # at a threshold is not past it
        ((701, 0, 0), (700, 10, 10), 0),
        ((701, 11, 0), (700, 10, 10), 1),  # the oldest generation past its threshold
        ((0, 11, 0), (700, 10, 10), 1),
        ((701, 11, 11), (700, 10, 10), 2),
        ((5000, 0, 0), (0, 10, 10), None),  # a threshold of 0: never automatically
        ((0, 0, 11), (700, 10, 0), None),
    ],
)
def test_the_generation_due(
    counts: tuple[int, int, int], thresholds: tuple[int, int, int], due: int | None
) -> None:
    assert due_generation(counts, thresholds) == due


def test_the_counts_climb_while_automatic_collection_is_off() -> None:
    """The collector depends on it: with collection off, allocations still count, and a
    collection of the generation due resets its count and moves the next one up."""
    assert not gc.isenabled()
    gc.collect()
    assert due_generation(gc.get_count(), gc.get_threshold()) is None  # the control
    kept = [[] for _ in range(gc.get_threshold()[0] * 2)]
    assert due_generation(gc.get_count(), gc.get_threshold()) == 0
    before = gc.get_count()[1]
    gc.collect(0)
    assert due_generation(gc.get_count(), gc.get_threshold()) is None
    assert gc.get_count()[1] == before + 1
    del kept


class _Cycle:
    def __init__(self) -> None:
        self.me = self


def test_the_collector_frees_a_cycle_on_its_tick(qtbot: QtBot) -> None:
    cycle = _Cycle()
    gone = weakref.ref(cycle)
    del cycle
    kept = [[] for _ in range(gc.get_threshold()[0] * 2)]  # past generation 0's threshold
    qtbot.wait(100)
    assert gone() is not None  # the control: nothing collects while automatic collection is off
    sweeper = MainThreadCollector(interval_ms=50)
    sweeper.start()
    try:
        qtbot.waitUntil(lambda: gone() is None, timeout=2000)
    finally:
        sweeper.stop()
    del kept


def test_stop_collects_and_leaves_automatic_collection_off() -> None:
    sweeper = MainThreadCollector()
    sweeper.start()
    assert sweeper.active
    cycle = _Cycle()
    gone = weakref.ref(cycle)
    del cycle
    sweeper.stop()
    assert gone() is None
    assert not sweeper.active
    assert not gc.isenabled()


def test_the_collector_refuses_to_start_off_the_main_thread() -> None:
    sweeper = MainThreadCollector()
    errors: list[BaseException] = []

    def start() -> None:
        try:
            sweeper.start()
        except RuntimeError as e:
            errors.append(e)

    starter = threading.Thread(target=start, name="mw-test-starter")
    starter.start()
    starter.join()
    assert len(errors) == 1
    assert not sweeper.active


class _Recorder(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def test_a_tick_turns_automatic_collection_off_again() -> None:
    """Heard on the module's own logger: ``setup_logging`` stops ``morphwheel`` propagating."""
    recorder = _Recorder()
    collector.log.addHandler(recorder)
    sweeper = MainThreadCollector()
    try:
        gc.enable()
        sweeper.tick()
        assert not gc.isenabled()
        gc.enable()
        sweeper.tick()
        assert not gc.isenabled()
    finally:
        collector.disable_automatic()
        collector.log.removeHandler(recorder)
    assert recorder.messages == [  # once per collector
        "automatic garbage collection was turned on again; turning it off"
    ]
