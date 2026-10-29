"""A fixed pool of worker processes with a supervisor per worker (phase-4 §3, §4.4; A5, A5a).

``WorkerPool`` is Qt-free: the dispatcher (a ``QObject``) sits on top of it. Each of the ``size``
supervisor threads owns one spawn process and one duplex pipe, pulls tasks from a shared queue, and
waits on the pipe *and* the process sentinel, so a crash is seen at once and a timeout can't be
delayed by a hung worker.

Rules:

- **Spawn, warmed at start.** ``start()`` spawns every worker and sends ``Configure``; the first
  task finds a warm process. The frozen app points ``multiprocessing`` at the Qt-free
  ``morphwheel-worker.exe`` (A5a) through ``executable``.
- **Timeout → terminate → respawn.** A task over ``task_timeout_s`` kills its worker; the task is
  reported ``TIMEOUT``. A worker that dies mid-task gives ``WORKER_CRASHED``. Either way a fresh
  worker replaces it, and the other workers never notice.
- **Nothing left behind.** The worker reports its temp path (``Reserved``) before converting; after
  a kill the supervisor removes that temp (the placeholder removes itself: delete-on-close).
- **Callbacks run on the supervisor threads.** ``done``, ``on_progress`` and ``on_log`` are called
  from a pool thread; the dispatcher hops to the GUI thread with a queued signal.
- **Shutdown** sends ``Shutdown`` to every worker, waits ``timeout_s``, then terminates the rest and
  joins the threads. The application calls it before the ``QApplication`` goes away.
- Worker log records come through ``on_log`` and are written by the GUI's handlers only.
"""

from __future__ import annotations

import contextlib
import logging
import multiprocessing
import multiprocessing.connection
import queue
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from morphwheel.core.errors import ErrorCode
from morphwheel.core.jobs import Task, TaskResult
from morphwheel.engine import file_ops
from morphwheel.engine.worker_main import (
    Configure,
    LogEvent,
    Progress,
    Ready,
    Reserved,
    Shutdown,
    worker_loop,
)
from morphwheel.plugins.loader import PluginSpec

log = logging.getLogger("morphwheel.engine.pool")

DEFAULT_SIZE = 2  # A5
DEFAULT_TASK_TIMEOUT_S = 120.0
READY_TIMEOUT_S = 60.0  # a scanner may hold the first frozen spawn for a while (S0)
RESPAWN_BACKOFF_S = 1.0
SPAWN_FAILURES_BEFORE_FAILING_TASKS = 3  # then queued tasks fail instead of waiting forever
WORKER_EXE_NAME = "morphwheel-worker.exe"

Done = Callable[[TaskResult], None]


@dataclass(frozen=True)
class WorkerInfo:
    """What a worker said when it came up. ``--worker-check`` prints these (A5a)."""

    index: int
    pid: int
    executable: str
    qt_loaded: bool


class _Stop:
    pass


_STOP = _Stop()


def default_worker_executable() -> Path | None:
    """The Qt-free worker exe beside a frozen ``morphwheel.exe``; ``None`` from source."""
    if not getattr(sys, "frozen", False):
        return None
    return Path(sys.executable).with_name(WORKER_EXE_NAME)


class WorkerPool:
    def __init__(
        self,
        size: int = DEFAULT_SIZE,
        task_timeout_s: float = DEFAULT_TASK_TIMEOUT_S,
        *,
        plugins: Sequence[PluginSpec] = (),
        engines_dir: Path | None = None,
        log_level: int = logging.INFO,
        executable: Path | None = None,
        on_progress: Callable[[Progress], None] | None = None,
        on_log: Callable[[logging.LogRecord], None] | None = None,
    ) -> None:
        if size < 1:
            raise ValueError("a pool needs at least one worker")
        self._size = size
        self._timeout = task_timeout_s
        self._configure = Configure(tuple(plugins), engines_dir, log_level)
        self._executable = executable
        self._on_progress = on_progress
        self._on_log = on_log or _forward_to_gui_logger
        self._queue: queue.Queue[tuple[Task, Done] | _Stop] = queue.Queue()
        self._threads: list[threading.Thread] = []
        self._ctx = multiprocessing.get_context("spawn")
        self._stopping = threading.Event()
        self._ready: dict[int, WorkerInfo] = {}
        self._ready_lock = threading.Lock()
        self._ready_event = threading.Event()

    # ----------------------------------------------------------------- lifecycle
    @property
    def size(self) -> int:
        return self._size

    @property
    def running(self) -> bool:
        return bool(self._threads) and not self._stopping.is_set()

    def start(self) -> None:
        if self._threads:
            return
        if self._executable is not None:
            self._ctx.set_executable(str(self._executable))
        self._stopping.clear()
        for index in range(self._size):
            thread = threading.Thread(
                target=self._supervise, args=(index,), name=f"mw-supervisor-{index}", daemon=True
            )
            thread.start()
            self._threads.append(thread)

    def run(self, task: Task, done: Done) -> None:
        """Queue a task. ``done`` is called exactly once: from a pool thread, or right here when
        the pool isn't running (the task then fails as ``WORKER_CRASHED``)."""
        if not self.running:
            log.error("%s not queued: the pool is not running", task.source.name)
            done(TaskResult.failure(task, ErrorCode.WORKER_CRASHED, "the pool is not running"))
            return
        self._queue.put((task, done))

    def shutdown(self, timeout_s: float = 3.0) -> None:
        if not self._threads:
            return
        self._stopping.set()
        for _ in self._threads:
            self._queue.put(_STOP)
        deadline = time.monotonic() + timeout_s + 1.0
        for thread in self._threads:
            thread.join(max(0.1, deadline - time.monotonic()))
        self._threads.clear()

    def wait_ready(self, timeout_s: float = READY_TIMEOUT_S) -> tuple[WorkerInfo, ...]:
        """Block until every worker has reported in (or the timeout passes); return what came."""
        deadline = time.monotonic() + timeout_s
        while len(self._ready) < self._size and time.monotonic() < deadline:
            self._ready_event.wait(max(0.0, deadline - time.monotonic()))
            self._ready_event.clear()
        with self._ready_lock:
            return tuple(self._ready[i] for i in sorted(self._ready))

    # ----------------------------------------------------------------- one supervisor
    def _supervise(self, index: int) -> None:
        worker: _Worker | None = None
        spawn_failures = 0
        try:
            while not self._stopping.is_set():
                if worker is None:
                    worker = self._spawn(index)
                    if worker is None:
                        spawn_failures += 1
                        if spawn_failures >= SPAWN_FAILURES_BEFORE_FAILING_TASKS:
                            self._fail_queued("the worker process can't start")
                        if self._stopping.wait(RESPAWN_BACKOFF_S):
                            break
                        continue
                    spawn_failures = 0
                item = self._queue.get()
                if isinstance(item, _Stop):
                    break
                task, done = item
                if self._stopping.is_set():
                    log.info("shutting down: %s not converted", task.source.name)
                    continue  # the GUI is going away; its callbacks must not run now
                result, alive = self._run_one(worker, task)
                try:
                    done(result)
                except Exception:
                    log.exception("the done callback raised for %s", task.source.name)
                if not alive:
                    worker.kill()
                    worker = None
        finally:
            if worker is not None:
                worker.stop()

    def _fail_queued(self, detail: str) -> None:
        """Report every queued task as crashed, so jobs finish while workers can't start."""
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                return
            if isinstance(item, _Stop):
                self._queue.put(item)  # keep the sentinel for its thread
                return
            task, done = item
            log.error("%s not converted: %s", task.source.name, detail)
            try:
                done(TaskResult.failure(task, ErrorCode.WORKER_CRASHED, detail))
            except Exception:
                log.exception("the done callback raised for %s", task.source.name)

    def _spawn(self, index: int) -> _Worker | None:
        parent, child = self._ctx.Pipe(duplex=True)
        process = self._ctx.Process(
            target=worker_loop, args=(child,), name=f"morphwheel-worker-{index}", daemon=True
        )
        try:
            process.start()
        except OSError:
            log.exception("worker %d: can't start", index)
            parent.close()
            child.close()
            return None
        child.close()  # only the worker holds this end: its death reads as EOF
        worker = _Worker(index, process, parent)
        ready = worker.wait_message(READY_TIMEOUT_S)
        if not isinstance(ready, Ready):
            log.error("worker %d: no Ready within %.0f s (%r)", index, READY_TIMEOUT_S, ready)
            worker.kill()
            return None
        if ready.qt_loaded:
            log.error("worker %d loaded Qt (R2/A5a broken): %s", index, ready.executable)
        info = WorkerInfo(index, ready.pid, ready.executable, ready.qt_loaded)
        with self._ready_lock:
            self._ready[index] = info
        self._ready_event.set()
        try:
            worker.conn.send(self._configure)
        except (OSError, ValueError):
            worker.kill()
            return None
        log.debug("worker %d ready: pid %d, %s", index, ready.pid, ready.executable)
        return worker

    def _run_one(self, worker: _Worker, task: Task) -> tuple[TaskResult, bool]:
        """Send one task and wait for its result. Returns ``(result, worker still usable)``."""
        start = time.monotonic()
        deadline = start + self._timeout
        temp: Path | None = None
        try:
            worker.conn.send(task)
        except (OSError, ValueError) as e:
            detail = f"can't reach the worker: {e}"
            return TaskResult.failure(task, ErrorCode.WORKER_CRASHED, detail), False
        while True:
            message = worker.wait_message(deadline - time.monotonic())
            if message is _TIMEOUT or message is _DEAD:
                if message is _TIMEOUT:
                    code, detail = ErrorCode.TIMEOUT, f"over {self._timeout:.0f} s"
                    log.error(
                        "worker %d: %s timed out; terminating", worker.index, task.source.name
                    )
                else:
                    worker.process.join(2.0)  # let the exit code land before it is reported
                    code, detail = ErrorCode.WORKER_CRASHED, f"exit code {worker.process.exitcode}"
                    log.error(
                        "worker %d died during %s (%s)", worker.index, task.source.name, detail
                    )
                worker.kill()
                _sweep(temp)  # the worker can't abort any more; its placeholder went with it
                return TaskResult.failure(task, code, detail), False
            if isinstance(message, TaskResult):
                return message, True
            if isinstance(message, Reserved):
                temp = message.temp
            elif isinstance(message, Progress):
                if self._on_progress is not None:
                    self._on_progress(message)
            elif isinstance(message, LogEvent):
                self._on_log(message.record)
            else:
                log.warning("worker %d sent an unexpected %r", worker.index, type(message).__name__)


# --------------------------------------------------------------------------- helpers
_TIMEOUT = object()
_DEAD = object()


class _Worker:
    def __init__(self, index: int, process: Any, conn: Any) -> None:
        self.index = index
        self.process = process
        self.conn = conn

    def wait_message(self, timeout_s: float) -> object:
        """The next message, ``_TIMEOUT``, or ``_DEAD`` (EOF or the process sentinel fired)."""
        while True:
            if timeout_s <= 0:
                return _TIMEOUT
            ready = multiprocessing.connection.wait(
                [self.conn, self.process.sentinel], timeout=timeout_s
            )
            if not ready:
                return _TIMEOUT
            if self.conn in ready:
                try:
                    return self.conn.recv()
                except (EOFError, OSError):
                    return _DEAD
            # Only the sentinel fired: drain anything still buffered before calling it dead.
            if self.conn.poll(0.05):
                continue
            return _DEAD

    def stop(self, timeout_s: float = 3.0) -> None:
        with contextlib.suppress(OSError, ValueError):
            self.conn.send(Shutdown())
        self.process.join(timeout_s)
        self.kill()

    def kill(self) -> None:
        if self.process.is_alive():
            self.process.terminate()
        self.process.join(5.0)
        with contextlib.suppress(OSError):
            self.conn.close()


def _sweep(temp: Path | None) -> None:
    """After a kill: the temp is removed here (the killed process holds no handle on it)."""
    if temp is not None:
        file_ops.remove_quietly(temp)


def _forward_to_gui_logger(record: logging.LogRecord) -> None:
    logging.getLogger("morphwheel").handle(record)
