"""``JobDispatcher``: a ``DropRequest`` becomes tasks, and their results become one ``JobResult``.

GUI side (phase-4 §4.4). It is the only ``QObject`` in ``engine``: it owns the thread hop from the
pool's supervisor threads back to the GUI thread, through an internal signal connected with an
explicit ``QueuedConnection``. Everything the UI listens to (``job_started``, ``job_progress``,
``job_finished``) is therefore emitted on the GUI thread.

Rules:

- **One task per file; same-format files are skipped** (U2): a file already in the target format
  gets a ``SKIPPED`` result without a worker. The plan showed the slot as enabled with a skip count;
  this is where the count is honored.
- **The sniffed format travels as a hint** (``Task.source_format``) when the wheel's sniff ran;
  otherwise the worker reads the header itself.
- **The job is finished when every task has a result**, including those the pool produced itself
  (``TIMEOUT``, ``WORKER_CRASHED``). ``JobResult.outcome`` picks the toast (phase-3 §5).
- ``submit`` does no I/O and no waiting: it is called right after the drop, from the queued
  ``drop_received`` handler.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal

from morphwheel.core.catalog import Catalog, Target, Verdict
from morphwheel.core.jobs import DropRequest, JobResult, Task, TaskResult, TaskStatus
from morphwheel.engine.worker_pool import WorkerPool

log = logging.getLogger("morphwheel.engine.dispatcher")


@dataclass
class _Job:
    target: Target
    expected: int
    results: dict[int, TaskResult] = field(default_factory=dict)

    @property
    def done(self) -> bool:
        return len(self.results) >= self.expected


class JobDispatcher(QObject):
    job_started = Signal(str, int)  # job_id, task count
    job_progress = Signal(str, int, int)  # job_id, done, total
    job_finished = Signal(object)  # JobResult
    _task_done = Signal(object)  # TaskResult, emitted from a pool thread

    def __init__(
        self,
        pool: WorkerPool,
        catalog: Catalog,
        *,
        fallback_dir: Path,
        options: Mapping[str, object] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._pool = pool
        self._catalog = catalog
        self._fallback_dir = fallback_dir
        self._options: Mapping[str, object] = dict(options or {})
        self._jobs: dict[str, _Job] = {}
        self._task_done.connect(self._on_task_done, Qt.ConnectionType.QueuedConnection)

    @property
    def active_jobs(self) -> int:
        return len(self._jobs)

    def set_options(self, options: Mapping[str, object]) -> None:
        """Quality and compress presets for the tasks submitted from now on (S5 settings)."""
        self._options = dict(options)

    def submit(self, request: DropRequest) -> str:
        """Split the request per file and queue the conversions. Returns the job id."""
        target = self._catalog.target(request.target_id)
        if target is None:
            log.error("drop for an unknown target %r; ignored", request.target_id)
            return ""
        job_id = secrets.token_hex(4)
        job = _Job(target, expected=len(request.files))
        self._jobs[job_id] = job
        skipped: list[TaskResult] = []
        tasks: list[Task] = []
        for task_id, info in enumerate(request.files):
            if Catalog.classify(info, target) is Verdict.SKIP:
                skipped.append(TaskResult(job_id, task_id, info.path, TaskStatus.SKIPPED))
                continue
            tasks.append(
                Task(
                    job_id,
                    task_id,
                    info.path,
                    target,
                    self._fallback_dir,
                    self._options,
                    source_format=info.format if info.sniffed else None,
                )
            )
        log.info(
            "job %s: %d file(s) -> %s (%d skipped)",
            job_id,
            len(request.files),
            target.id,
            len(skipped),
        )
        self.job_started.emit(job_id, len(request.files))
        for task in tasks:
            self._pool.run(task, self._task_done.emit)  # a stopped pool fails the task itself
        for result in skipped:
            self._record(result)
        if not request.files:
            self._finish(job_id)
        return job_id

    # ----------------------------------------------------------------- results (GUI thread)
    def _on_task_done(self, result: TaskResult) -> None:
        self._record(result)

    def _record(self, result: TaskResult) -> None:
        job = self._jobs.get(result.job_id)
        if job is None:
            log.warning("result for an unknown job %s; dropped", result.job_id)
            return
        job.results[result.task_id] = result
        if result.status is TaskStatus.FAILED:
            log.log(
                logging.CRITICAL if not result.source_intact else logging.WARNING,
                "job %s: %s failed with %s: %s",
                result.job_id,
                result.source.name,
                result.error.value if result.error else "?",
                result.detail,
            )
        elif result.status is TaskStatus.OK and result.output is not None:
            log.info(
                "job %s: %s -> %s (%d bytes, %.0f ms%s)",
                result.job_id,
                result.source.name,
                result.output.path.name,
                result.output.size,
                result.duration_ms,
                ", fallback folder" if result.used_fallback else "",
            )
        self.job_progress.emit(result.job_id, len(job.results), job.expected)
        if job.done:
            self._finish(result.job_id)

    def _finish(self, job_id: str) -> None:
        job = self._jobs.pop(job_id)
        ordered = tuple(job.results[k] for k in sorted(job.results))
        job_result = JobResult(job_id, job.target, ordered)
        log.info("job %s finished: %s", job_id, job_result.outcome.value)
        self.job_finished.emit(job_result)
