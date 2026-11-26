"""``tools/wheel_driver.py``: it reads the lines the app really writes, and C23's checks can fail.

The driver itself needs a live desktop (the user runs it). What can be held here:

- the S3 lines, as the dispatcher and the toast manager emit them and the app's own formatter writes
  them, parse into the driver's tags, so a change of wording in the app fails here first;
- C23's checks pass on a real conversion's lines and output, and each one fails on its own fault
  (the negative controls);
- the list of outputs a run created never names a source, an older file, or a file elsewhere;
- the JPG point is only accepted inside the item list.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication

from morphwheel.core.catalog import Catalog
from morphwheel.core.errors import ErrorCode
from morphwheel.core.formats import FileInfo, FormatId, Sniff
from morphwheel.core.jobs import CreatedFile, DropRequest, JobResult, Task, TaskResult, TaskStatus
from morphwheel.engine.dispatcher import JobDispatcher
from morphwheel.logs import _DATE_FORMAT, _FORMAT
from morphwheel.ui.toasts.manager import ToastManager
from morphwheel.ui.toasts.model import toast_for

if sys.platform != "win32":  # pragma: no cover - the driver loads user32 on import
    pytest.skip("Win32 only", allow_module_level=True)

import wheel_driver as wd  # tools/ is on pytest's pythonpath
from drag_driver import Line

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
from builtin_targets import BUILTINS

pytestmark = pytest.mark.usefixtures("qapp")


SOURCE = "mw-test-a.png"


class FakePool:
    def __init__(self) -> None:
        self.tasks: list[tuple[Task, Callable[[TaskResult], None]]] = []

    def run(self, task: Task, done: Callable[[TaskResult], None]) -> None:
        self.tasks.append((task, done))


def app_lines(records: list[logging.LogRecord]) -> list[Line]:
    """Format the records as ``morphwheel.log`` does, then read them back as the driver does."""
    formatter = logging.Formatter(_FORMAT, _DATE_FORMAT)
    lines = []
    for record in records:
        m = wd.APP_LINE_RE.match(formatter.format(record))
        assert m is not None, formatter.format(record)
        stamp = datetime.strptime(m[1], "%Y-%m-%d %H:%M:%S.%f").timestamp() * 1000
        lines.append(Line(stamp, *wd.translate(m[3], m[4])))
    return lines


@pytest.fixture
def converted(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> Iterator[dict[str, Any]]:
    """A real dispatcher and toast manager log one PNG converted to a JPG beside it."""
    folder = tmp_path / "dragtest"
    folder.mkdir()
    source = folder / SOURCE
    Image.new("RGB", (64, 64), (40, 120, 200)).save(source)
    before = {p.name for p in folder.iterdir()}
    output = folder / "mw-test-a.jpg"
    Image.new("RGB", (64, 64), (40, 120, 200)).save(output, "JPEG")

    pool = FakePool()
    dispatcher = JobDispatcher(
        pool,  # type: ignore[arg-type]
        Catalog.of(BUILTINS),
        fallback_dir=tmp_path / "Downloads" / "Morphwheel",
        options={},
    )
    results: list[JobResult] = []
    dispatcher.job_finished.connect(results.append)
    manager = ToastManager(motion_enabled=lambda: False)
    info = FileInfo.from_path(source).with_sniff(Sniff(FormatId.PNG, False))
    with caplog.at_level(logging.DEBUG, logger="morphwheel"):
        job = dispatcher.submit(DropRequest((info,), "jpeg", 0))
        task, done = pool.tasks[0]
        size = output.stat().st_size
        done(
            TaskResult(
                job,
                task.task_id,
                source,
                TaskStatus.OK,
                output=CreatedFile(output, size, 1, source),
                duration_ms=12.0,
            )
        )
        QApplication.processEvents()
        assert len(results) == 1
        manager.show(toast_for(results[0]), key=job)
    yield {
        "lines": app_lines(caplog.records),
        "folder": folder,
        "before": before,
        "source": source,
        "output": output,
        "job": job,
    }
    manager.dismiss_all()


def checks_of(lines: list[Line], folder: Path, before: set[str]) -> dict[str, bool]:
    checks, _ = wd.conversion_checks(
        lines,
        source=SOURCE,
        target="jpeg",
        pil_format="JPEG",
        folder=folder,
        before=before,
    )
    return checks


# ----------------------------------------------------------------------------- the app's lines
def test_the_apps_s3_lines_get_the_drivers_tags(converted: dict[str, Any]) -> None:
    tags = [(x.tag, x.msg) for x in converted["lines"]]
    job = converted["job"]
    assert ("JOB", f"job {job}: 1 file(s) -> jpeg (0 skipped)") in tags
    size = converted["output"].stat().st_size
    assert ("OUT", f"job {job}: {SOURCE} -> mw-test-a.jpg ({size} bytes, 12 ms)") in tags
    assert ("DONE", f"job {job} finished: success") in tags
    assert ("toast", "toast: success 'Converted to JPG'") in tags
    out = wd.job_outputs(converted["lines"])
    assert [(o.job, o.source, o.output, o.ms, o.fallback) for o in out] == [
        (job, SOURCE, "mw-test-a.jpg", 12, False)
    ]
    assert out[0].size == converted["output"].stat().st_size


def test_a_failure_line_is_tagged_and_is_no_output(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    pool = FakePool()
    dispatcher = JobDispatcher(
        pool,  # type: ignore[arg-type]
        Catalog.of(BUILTINS),
        fallback_dir=tmp_path / "fallback",
        options={},
    )
    info = FileInfo.from_path(tmp_path / SOURCE).with_sniff(Sniff(FormatId.PNG, False))
    with caplog.at_level(logging.DEBUG, logger="morphwheel"):
        job = dispatcher.submit(DropRequest((info,), "jpeg", 0))
        task, done = pool.tasks[0]
        done(TaskResult(job, task.task_id, task.source, TaskStatus.FAILED, error=ErrorCode.TIMEOUT))
        QApplication.processEvents()
    lines = app_lines(caplog.records)
    assert [x.tag for x in lines if x.tag in {"JOB", "OUT", "FAIL", "DONE"}] == [
        "JOB",
        "FAIL",
        "DONE",
    ]
    assert wd.job_outputs(lines) == []
    assert wd.job_outcome(lines, job) == "failed"


@pytest.mark.parametrize(
    ("msg", "tag"),
    [
        ("press at (10, 20), allowed=True, chain=['DirectUIHWND']", "down"),
        ("state pressed -> dragging", "thresh"),
        ("wheel shown: press at (1, 2), cursor (3, 4), center (5, 6), screen x", "SHOW"),
        ("DropRequest: 1 file(s) -> jpeg, handled 0.5 ms after the drop", "DROP"),
        ("hide: dropped", "hide"),
    ],
)
def test_the_s2_tags_stay(msg: str, tag: str) -> None:
    assert wd.translate("morphwheel.app.controller", msg)[0] == tag


# ----------------------------------------------------------------------------- C23's checks
def test_c23_passes_on_a_real_conversion(converted: dict[str, Any]) -> None:
    checks = checks_of(converted["lines"], converted["folder"], converted["before"])
    assert len(checks) == 6
    assert all(checks.values()), checks


def drop_tag(lines: list[Line], tag: str) -> list[Line]:
    return [x for x in lines if x.tag != tag]


@pytest.mark.parametrize(
    ("fault", "failing"),
    [
        ("no job line", "job: 1 file(s) -> jpeg (0 skipped)"),
        ("no finished line", "job finished: success"),
        ("no toast", "toast: success"),
        ("a toast of another kind", "toast: success"),
        ("outcome failed", "job finished: success"),
        ("fallback folder", "mw-test-a.png -> a new file beside it"),
        ("an output from an earlier run", "mw-test-a.png -> a new file beside it"),
        ("output missing", "mw-test-a.png -> a new file beside it"),
        ("size differs", "the output's size is the logged size"),
        ("a PNG named .jpg", "the output is a real JPEG"),
    ],
)
def test_each_c23_check_can_fail(converted: dict[str, Any], fault: str, failing: str) -> None:
    lines: list[Line] = converted["lines"]
    folder: Path = converted["folder"]
    before: set[str] = set(converted["before"])
    output: Path = converted["output"]
    if fault == "no job line":
        lines = drop_tag(lines, "JOB")
    elif fault == "no finished line":
        lines = drop_tag(lines, "DONE")
    elif fault == "no toast":
        lines = drop_tag(lines, "toast")
    elif fault == "a toast of another kind":
        lines = [
            Line(x.t_ms, x.tag, x.msg.replace("toast: success", "toast: error")) for x in lines
        ]
    elif fault == "outcome failed":
        lines = [
            Line(x.t_ms, x.tag, x.msg.replace("finished: success", "finished: failed"))
            for x in lines
        ]
    elif fault == "fallback folder":
        lines = [
            Line(x.t_ms, x.tag, x.msg.replace(" ms)", " ms, fallback folder)"))
            if x.tag == "OUT"
            else x
            for x in lines
        ]
    elif fault == "an output from an earlier run":
        before.add(output.name)
    elif fault == "output missing":
        output.unlink()
    elif fault == "size differs":
        with output.open("ab") as f:
            f.write(b"\0")
    elif fault == "a PNG named .jpg":
        size = output.stat().st_size
        Image.new("RGB", (64, 64)).save(output, "PNG")
        lines = [
            Line(x.t_ms, x.tag, x.msg.replace(f"({size} bytes", f"({output.stat().st_size} bytes"))
            for x in lines
        ]
    checks = checks_of(lines, folder, before)
    assert checks[failing] is False, checks


# ----------------------------------------------------------------------------- outputs and points
def test_created_outputs_names_only_this_runs_new_files(
    converted: dict[str, Any], tmp_path: Path
) -> None:
    lines: list[Line] = converted["lines"]
    folder: Path = converted["folder"]
    source: Path = converted["source"]
    assert wd.created_outputs(lines, folder, converted["before"], [source]) == [converted["output"]]
    # an older file, a source, a name with a folder in it, a fallback output: never listed
    assert wd.created_outputs(lines, folder, {"mw-test-a.jpg"}, [source]) == []
    assert wd.created_outputs(lines, folder, set(), [folder / "mw-test-a.jpg"]) == []
    sneaky = [
        Line(x.t_ms, x.tag, x.msg.replace("-> mw-test-a.jpg", "-> ..\\mw-test-a.jpg"))
        for x in lines
    ]
    assert wd.created_outputs(sneaky, folder, set(), [source]) == []
    fallback = [Line(x.t_ms, x.tag, x.msg.replace(" ms)", " ms, fallback folder)")) for x in lines]
    assert wd.created_outputs(fallback, folder, set(), [source]) == []


@pytest.mark.parametrize(
    ("point", "margin", "expected"),
    [
        ((50, 50), 0, True),
        ((10, 10), 0, True),
        ((9, 50), 0, False),  # left of the list
        ((50, 9), 0, False),  # above it: the command bar
        ((50, 17), 8, False),  # inside, but within the margin
        ((50, 18), 8, True),
        ((100, 50), 0, False),  # right edge is outside
    ],
)
def test_inside(point: tuple[int, int], margin: int, expected: bool) -> None:
    assert wd.inside((10, 10, 100, 100), point, margin) is expected


class FakeLog:
    def __init__(self, lines: list[Line]) -> None:
        self.lines = lines
        self.closed = False

    def since(self, mark: int) -> list[Line]:
        return self.lines[mark:]

    def close(self) -> None:
        self.closed = True


def test_the_outputs_are_still_listed_after_teardown_closes_the_log(
    converted: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wd, "TEST_DIR", converted["folder"])
    run = wd.WheelRun(dry_run=True, rows=None)
    log = FakeLog(converted["lines"])
    run.log = log  # type: ignore[assignment]
    run.before = converted["before"]
    run.hashes = {converted["source"]: ""}
    assert run.outputs() == [converted["output"]]
    run.stop_probe()  # what teardown does before main() writes the results
    assert log.closed
    assert run.log is None
    assert run.outputs() == [converted["output"]]
