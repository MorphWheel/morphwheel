"""``engine.dispatcher`` with a fake pool: splitting, skipping (U2), the thread hop, the outcome.

The fake pool records tasks and lets the test complete them from a *different* thread, as the real
supervisor threads do; the finished signal must still arrive on the GUI thread.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

from morphwheel.core.catalog import Catalog
from morphwheel.core.errors import ErrorCode
from morphwheel.core.formats import FileInfo, FormatId, Sniff
from morphwheel.core.jobs import CreatedFile, DropRequest, JobOutcome, Task, TaskResult, TaskStatus
from morphwheel.engine.dispatcher import JobDispatcher

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
from builtin_targets import BUILTINS

pytestmark = pytest.mark.usefixtures("qapp")


class FakePool:
    def __init__(self) -> None:
        self.tasks: list[tuple[Task, Callable[[TaskResult], None]]] = []

    def run(self, task: Task, done: Callable[[TaskResult], None]) -> None:
        self.tasks.append((task, done))

    def complete(self, index: int, result: TaskResult, *, from_thread: bool = True) -> None:
        _, done = self.tasks[index]
        if from_thread:
            t = threading.Thread(target=done, args=(result,))
            t.start()
            t.join()
        else:
            done(result)


@pytest.fixture
def rig(tmp_path: Path) -> tuple[JobDispatcher, FakePool, list[Any]]:
    pool = FakePool()
    dispatcher = JobDispatcher(
        pool,  # type: ignore[arg-type]
        Catalog.of(BUILTINS),
        fallback_dir=tmp_path / "Downloads" / "Morphwheel",
        options={"jpeg_quality": 80},
    )
    events: list[Any] = []
    dispatcher.job_started.connect(lambda j, n: events.append(("started", j, n)))
    dispatcher.job_progress.connect(lambda j, d, t: events.append(("progress", j, d, t)))
    dispatcher.job_finished.connect(lambda r: events.append(("finished", r)))
    return dispatcher, pool, events


def ok(task: Task) -> TaskResult:
    out = task.source.with_suffix(".jpg")
    return TaskResult(
        task.job_id,
        task.task_id,
        task.source,
        TaskStatus.OK,
        output=CreatedFile(out, 100, 1, task.source),
        duration_ms=5.0,
    )


def test_split_skip_and_finish_on_the_gui_thread(
    rig: tuple[JobDispatcher, FakePool, list[Any]], tmp_path: Path
) -> None:
    dispatcher, pool, events = rig
    png = FileInfo.from_path(tmp_path / "a.png").with_sniff(Sniff(FormatId.PNG, False))
    jpg = FileInfo.from_path(tmp_path / "b.jpg")  # not sniffed: no hint for the worker
    bmp = FileInfo.from_path(tmp_path / "c.bmp").with_sniff(Sniff(FormatId.BMP, False))
    job_id = dispatcher.submit(DropRequest((png, jpg, bmp), "jpeg", 0))
    assert job_id
    assert dispatcher.active_jobs == 1
    assert events[0] == ("started", job_id, 3)
    assert [t.task_id for t, _ in pool.tasks] == [0, 2]  # b.jpg is already a JPG: skipped
    task0 = pool.tasks[0][0]
    assert task0.source_format is FormatId.PNG
    assert task0.fallback_dir == tmp_path / "Downloads" / "Morphwheel"
    assert task0.options == {"jpeg_quality": 80}
    assert task0.target.id == "jpeg"
    assert ("progress", job_id, 1, 3) in events  # the skip counted at once

    seen_threads: list[Any] = []
    dispatcher.job_finished.connect(lambda r: seen_threads.append(QThread.currentThread()))
    pool.complete(0, ok(task0))
    pool.complete(1, ok(pool.tasks[1][0]))
    QApplication.processEvents()
    finished = [e for e in events if e[0] == "finished"]
    assert len(finished) == 1
    result = finished[0][1]
    assert result.job_id == job_id
    assert result.outcome is JobOutcome.SUCCESS
    assert result.ok_count == 2
    assert result.skipped_count == 1
    assert [r.task_id for r in result.results] == [0, 1, 2]
    assert seen_threads == [QApplication.instance().thread()]  # type: ignore[union-attr]
    assert dispatcher.active_jobs == 0


def test_pool_failures_finish_the_job_too(
    rig: tuple[JobDispatcher, FakePool, list[Any]], tmp_path: Path
) -> None:
    dispatcher, pool, events = rig
    files = tuple(FileInfo.from_path(tmp_path / f"{i}.png") for i in range(2))
    job_id = dispatcher.submit(DropRequest(files, "webp", 0))
    t0, t1 = (t for t, _ in pool.tasks)
    pool.complete(0, ok(t0))
    pool.complete(
        1,
        TaskResult(job_id, 1, t1.source, TaskStatus.FAILED, error=ErrorCode.TIMEOUT),
        from_thread=False,
    )
    QApplication.processEvents()
    result = next(e[1] for e in events if e[0] == "finished")
    assert result.outcome is JobOutcome.PARTIAL
    assert [r.error for r in result.failed] == [ErrorCode.TIMEOUT]


def test_source_changed_is_critical(
    rig: tuple[JobDispatcher, FakePool, list[Any]], tmp_path: Path
) -> None:
    dispatcher, pool, events = rig
    job_id = dispatcher.submit(DropRequest((FileInfo.from_path(tmp_path / "a.png"),), "jpeg", 0))
    task = pool.tasks[0][0]
    pool.complete(
        0,
        TaskResult(
            job_id,
            0,
            task.source,
            TaskStatus.FAILED,
            error=ErrorCode.SOURCE_CHANGED,
            source_intact=False,
        ),
    )
    QApplication.processEvents()
    result = next(e[1] for e in events if e[0] == "finished")
    assert result.outcome is JobOutcome.SOURCE_CHANGED


def test_unknown_target_and_empty_request(rig: tuple[JobDispatcher, FakePool, list[Any]]) -> None:
    dispatcher, pool, events = rig
    assert dispatcher.submit(DropRequest((), "nope", 0)) == ""
    assert events == []
    job_id = dispatcher.submit(DropRequest((), "jpeg", 0))
    assert pool.tasks == []
    assert events[-1][0] == "finished"
    assert events[-1][1].job_id == job_id
    assert events[-1][1].outcome is JobOutcome.NOTHING_TO_DO


def test_set_options_applies_to_later_tasks(
    rig: tuple[JobDispatcher, FakePool, list[Any]], tmp_path: Path
) -> None:
    dispatcher, pool, _ = rig
    dispatcher.set_options({"compress_quality": 50})
    dispatcher.submit(DropRequest((FileInfo.from_path(tmp_path / "a.jpg"),), "compress", 0))
    assert pool.tasks[0][0].options == {"compress_quality": 50}
