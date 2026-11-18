"""``engine.worker_pool`` with real spawn processes: conversion, crash, timeout, logs, shutdown.

Traceability (phase-4 §3): a crashed or timed-out worker is replaced and the task is marked
``WORKER_CRASHED`` / ``TIMEOUT``; the GUI keeps running; nothing is left behind.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest

from morphwheel.core.errors import ErrorCode
from morphwheel.core.jobs import Task, TaskResult, TaskStatus
from morphwheel.engine.worker_pool import WorkerPool
from morphwheel.plugins.loader import PluginSpec
from morphwheel.plugins.manifest import MANIFEST_NAME, builtin_manifest, load_manifest

from .conftest import Collector, plugin_dir

pytestmark = pytest.mark.integration

BUILTIN = builtin_manifest()
TARGETS = {t.id: t for t in BUILTIN.targets}
PLUGINS = [PluginSpec(BUILTIN.plugin.id, BUILTIN.plugin.entry, None)]
for _name in ("echo", "crash", "sleep"):
    _m = load_manifest(plugin_dir(_name) / MANIFEST_NAME, is_builtin=False)
    PLUGINS.append(PluginSpec(_m.plugin.id, _m.plugin.entry, _m.directory))
    TARGETS[_m.targets[0].id] = _m.targets[0]


@pytest.fixture
def pool() -> Iterator[tuple[WorkerPool, Collector]]:
    collector = Collector()
    p = WorkerPool(
        size=2,
        task_timeout_s=3.0,
        plugins=PLUGINS,
        on_progress=collector.progress.append,
        on_log=collector.records.append,
    )
    p.start()
    try:
        yield p, collector
    finally:
        p.shutdown()


def task(n: int, source: Path, target: str, fallback: Path) -> Task:
    return Task("job", n, source, TARGETS[target], fallback)


def test_workers_come_up_qt_free_and_convert_in_parallel(
    pool: tuple[WorkerPool, Collector], images: Mapping[str, Path], tmp_path: Path
) -> None:
    p, c = pool
    infos = p.wait_ready()
    assert len(infos) == 2
    assert {i.index for i in infos} == {0, 1}
    assert all(not i.qt_loaded for i in infos)  # R2 from source; the frozen check repeats it
    assert len({i.pid for i in infos}) == 2
    out = tmp_path / "out"
    out.mkdir()
    sources = []
    for letter, name in zip(
        "abcd", ["photo.png", "photo.bmp", "photo.tiff", "photo.gif"], strict=True
    ):
        src = out / f"{letter}{Path(name).suffix}"
        src.write_bytes(images[name].read_bytes())
        sources.append(src)
    c.expect(len(sources))
    for n, src in enumerate(sources):
        p.run(task(n, src, "jpeg", tmp_path / "fb"), c.done)
    results = c.wait()
    assert {r.task_id for r in results} == set(range(len(sources)))
    assert all(r.status is TaskStatus.OK for r in results), [r.detail for r in results]
    assert sorted(x.name for x in out.iterdir()) == sorted(
        [s.name for s in sources] + [f"{s.stem}.jpg" for s in sources]
    )
    assert any(pr.fraction == 1.0 for pr in c.progress)


def test_crash_is_reported_and_the_worker_replaced(
    pool: tuple[WorkerPool, Collector], images: Mapping[str, Path], tmp_path: Path
) -> None:
    p, c = pool
    src = images["photo.jpg"]
    c.expect(1)
    p.run(task(1, src, "test.crash:copy", tmp_path / "fb"), c.done)
    (crashed,) = c.wait()
    assert crashed.status is TaskStatus.FAILED
    assert crashed.error is ErrorCode.WORKER_CRASHED
    assert "exit code 3" in (crashed.detail or "")
    leftovers = [
        x.name for x in src.parent.iterdir() if ".mwtmp" in x.name or x.name == "photo.png"
    ]
    assert leftovers == ["photo.png"]  # the fixture copy; no temp, no placeholder from the crash
    # The pool still works: both the survivor and the replacement take tasks.
    c.expect(3)
    for n in range(2, 4):
        p.run(task(n, images["photo.bmp"], "test.echo:copy", tmp_path / "fb"), c.done)
    results = c.wait()
    assert [r.status for r in results[1:]] == [TaskStatus.OK, TaskStatus.OK]


def test_timeout_terminates_and_sweeps_the_temp(
    pool: tuple[WorkerPool, Collector], images: Mapping[str, Path], tmp_path: Path
) -> None:
    p, c = pool
    src = images["photo.jpg"]
    c.expect(1)
    p.run(task(1, src, "test.sleep:copy", tmp_path / "fb"), c.done)
    (timed_out,) = c.wait()
    assert timed_out.error is ErrorCode.TIMEOUT
    assert not any(".mwtmp" in x.name for x in src.parent.iterdir())
    assert not (src.parent / "photo (1).png").exists()
    assert not (src.parent / "photo.png.0").exists()
    c.expect(2)
    p.run(task(2, images["photo.bmp"], "jpeg", tmp_path / "fb"), c.done)
    assert c.wait()[1].status is TaskStatus.OK


def test_worker_logs_reach_the_gui_side(
    pool: tuple[WorkerPool, Collector], images: Mapping[str, Path], tmp_path: Path
) -> None:
    p, c = pool
    c.expect(1)
    p.run(task(1, images["corrupt.jpg"], "png", tmp_path / "fb"), c.done)
    c.wait()
    p.wait_ready()
    assert any(r.name.startswith("morphwheel") for r in c.records) or c.records == []
    for record in c.records:
        assert record.args is None  # prepared for pickling
        assert isinstance(record.getMessage(), str)


def test_shutdown_is_quick_and_a_stopped_pool_fails_tasks_at_once(
    images: Mapping[str, Path],
) -> None:
    p = WorkerPool(size=1, task_timeout_s=3.0, plugins=PLUGINS)
    p.start()
    p.wait_ready()
    p.shutdown(timeout_s=3.0)
    assert not p.running
    results: list[TaskResult] = []
    p.run(task(1, images["photo.jpg"], "jpeg", images["photo.jpg"].parent), results.append)
    assert [r.error for r in results] == [ErrorCode.WORKER_CRASHED]  # the job can still finish
    assert "not running" in (results[0].detail or "")
    p.shutdown()  # idempotent


def test_reconfigure_is_the_gate_both_ways_and_replaces_the_worker(
    images: Mapping[str, Path], tmp_path: Path
) -> None:
    """S6: a worker loads only the plugins it was configured with; a change respawns it."""
    c = Collector()
    p = WorkerPool(size=1, task_timeout_s=10.0, plugins=PLUGINS[:1], on_log=c.records.append)
    p.start()
    try:
        (first,) = p.wait_ready()
        c.expect(1)
        p.run(task(1, images["photo.bmp"], "test.echo:copy", tmp_path / "fb"), c.done)
        (refused,) = c.wait()
        assert refused.error is ErrorCode.PLUGIN_ERROR
        assert (refused.detail or "").startswith("no plugin provides")

        p.reconfigure(PLUGINS)  # echo enabled: the next task runs on a fresh worker
        c.expect(2)
        p.run(task(2, images["photo.bmp"], "test.echo:copy", tmp_path / "fb"), c.done)
        results = c.wait()
        assert results[1].status is TaskStatus.OK
        (second,) = p.wait_ready()
        assert second.pid != first.pid

        p.reconfigure(PLUGINS)  # the same set: nothing happens, the worker stays
        c.expect(3)
        p.run(task(3, images["photo.bmp"], "test.echo:copy", tmp_path / "fb"), c.done)
        assert c.wait()[2].status is TaskStatus.OK
        assert p.wait_ready()[0].pid == second.pid
        p.reconfigure(PLUGINS, force=True)  # a replaced folder: the worker must go
        c.expect(4)
        p.run(task(4, images["photo.bmp"], "test.echo:copy", tmp_path / "fb"), c.done)
        assert c.wait()[3].status is TaskStatus.OK
        (forced,) = p.wait_ready()
        assert forced.pid != second.pid

        p.reconfigure(PLUGINS[:1])  # echo disabled again: refused, on yet another worker
        c.expect(5)
        p.run(task(5, images["photo.bmp"], "test.echo:copy", tmp_path / "fb"), c.done)
        results = c.wait()
        assert results[4].error is ErrorCode.PLUGIN_ERROR
        (last,) = p.wait_ready()
        assert last.pid not in {first.pid, second.pid, forced.pid}
    finally:
        p.shutdown()
