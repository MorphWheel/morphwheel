"""S6 file 7: a plugin that crashes, hangs, breaks at import or tampers never takes the app down.

The M3 exit criterion (phase-2 §3: isolation): four fixture plugins installed and enabled as a
user would, each dropped on through the real app with real workers. After each failure the app
is alive, the toast says what happened in the fixed words, nothing is left beside the source,
and the next conversion through the builtin plugin succeeds on a replaced worker.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from PIL import Image
from pytestqt.qtbot import QtBot

from conftest import teardown_app
from morphwheel.app.application import Application
from morphwheel.core.errors import ErrorCode
from morphwheel.core.formats import FileInfo, FormatId, Sniff
from morphwheel.core.jobs import DropRequest, JobOutcome, JobResult
from morphwheel.settings.model import PluginPrefs, Settings
from morphwheel.settings.paths import AppPaths
from morphwheel.settings.store import save_settings
from morphwheel.ui.toasts.model import ToastKind
from morphwheel.ui.tray import TrayState

pytestmark = pytest.mark.usefixtures("qapp")

FIXTURE_PLUGINS = Path(__file__).resolve().parents[1] / "fixtures" / "plugins"
FAILING = ("crash", "sleep", "broken", "tamper")
TASK_TIMEOUT_S = 10.0  # a cold worker imports Pillow and the plugin before its first task


@pytest.fixture
def app(app_paths_tmp: AppPaths) -> Iterator[Application]:
    """The four failing fixtures installed under their ids and enabled, the app started."""
    for name in FAILING:
        shutil.copytree(FIXTURE_PLUGINS / name, app_paths_tmp.plugins_dir / f"test.{name}")
    prefs = PluginPrefs(enabled=tuple(f"test.{name}" for name in FAILING))
    # onboarding_done: the first-run bubble would otherwise land among the visible toasts.
    save_settings(app_paths_tmp.settings_file, Settings(onboarding_done=True, plugins=prefs))
    application = Application(
        ["morphwheel", "--debug", "--motion", "off"],
        paths=app_paths_tmp,
        is_elevated=lambda: False,
        pool_size=1,
        task_timeout_s=TASK_TIMEOUT_S,
    )
    assert application.registry.broken == ()
    assert {t.id for t in application.registry.arc_targets} == {
        f"test.{name}:copy" for name in FAILING
    }
    application.start()
    try:
        yield application
    finally:
        teardown_app(application)


def jpeg(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    src = folder / "photo.jpg"
    Image.new("RGB", (32, 24), (200, 100, 50)).save(src, "JPEG", quality=90)
    return src


def drop(app: Application, qtbot: QtBot, src: Path, target_id: str) -> JobResult:
    info = FileInfo.from_path(src).with_sniff(Sniff(FormatId.JPEG, False))
    with qtbot.waitSignal(app.dispatcher.job_finished, timeout=60_000) as blocker:
        app.controller.drop_received.emit(DropRequest((info,), target_id, 0))
    return blocker.args[0]  # type: ignore[no-any-return]


def worker_pid(app: Application) -> int:
    (info,) = app.pool.wait_ready()
    return info.pid


def the_app_still_converts(app: Application, qtbot: QtBot, src: Path, *, replaced: bool) -> None:
    """The builtin target works after the failure, on a replaced worker (a crash, a hang) or the
    same one (a plugin error): the app is alive either way, and nothing landed in the fallback."""
    assert app.pool.running
    before = worker_pid(app)
    result = drop(app, qtbot, src, "png")
    assert result.outcome is JobOutcome.SUCCESS, result
    assert (src.parent / "photo.png").is_file()
    assert app.dispatcher.active_jobs == 0
    assert not app.paths.fallback_output_dir.exists()
    assert (worker_pid(app) != before) is replaced  # before: the pid the failure left behind


def failure_toast(app: Application, name: str) -> str:
    (toast,) = [t for t in app.toasts.visible if t.model.kind is ToastKind.ERROR]
    assert toast.model.title == f"Couldn't convert {name}"
    return toast.model.body


def test_a_crashing_plugin_fails_its_file_and_the_app_goes_on(
    app: Application, qtbot: QtBot, tmp_path: Path
) -> None:
    src = jpeg(tmp_path / "pictures")
    first = worker_pid(app)
    result = drop(app, qtbot, src, "test.crash:copy")
    assert result.outcome is JobOutcome.FAILED
    assert result.failed[0].error is ErrorCode.WORKER_CRASHED
    assert "exit code 3" in (result.failed[0].detail or "")  # the fixture's own exit
    assert failure_toast(app, "photo.jpg") == "The converter stopped unexpectedly."
    assert app.tray.state is TrayState.NORMAL  # a failure is not an alert (RD-18)
    assert sorted(p.name for p in src.parent.iterdir()) == ["photo.jpg"]  # no temp, no partial
    the_app_still_converts(app, qtbot, src, replaced=True)
    assert worker_pid(app) != first


def test_a_hanging_plugin_is_stopped_at_the_timeout_and_the_app_goes_on(
    app: Application, qtbot: QtBot, tmp_path: Path
) -> None:
    src = jpeg(tmp_path / "pictures")
    result = drop(app, qtbot, src, "test.sleep:copy")
    assert result.outcome is JobOutcome.FAILED
    assert result.failed[0].error is ErrorCode.TIMEOUT
    assert failure_toast(app, "photo.jpg") == "The conversion took too long and was stopped."
    assert sorted(p.name for p in src.parent.iterdir()) == ["photo.jpg"]
    the_app_still_converts(app, qtbot, src, replaced=True)


def test_a_plugin_broken_at_import_is_a_plugin_error_not_a_crash(
    app: Application, qtbot: QtBot, tmp_path: Path
) -> None:
    src = jpeg(tmp_path / "pictures")
    result = drop(app, qtbot, src, "test.broken:copy")
    assert result.outcome is JobOutcome.FAILED
    assert result.failed[0].error is ErrorCode.PLUGIN_ERROR
    assert "can't import 'broken_plugin'" in (result.failed[0].detail or "")  # the log's line
    assert failure_toast(app, "photo.jpg") == "The converter reported an error."
    assert sorted(p.name for p in src.parent.iterdir()) == ["photo.jpg"]
    the_app_still_converts(app, qtbot, src, replaced=False)  # a plugin error, not a crash


def test_a_tampering_plugin_is_caught_and_raises_the_alert(
    app: Application, qtbot: QtBot, tmp_path: Path
) -> None:
    """Phase-4 §6: the integrity guard; the critical toast and the tray alert (RD-18)."""
    src = jpeg(tmp_path / "pictures")
    before = src.read_bytes()
    result = drop(app, qtbot, src, "test.tamper:copy")
    assert result.outcome is JobOutcome.SOURCE_CHANGED
    assert result.failed[0].error is ErrorCode.SOURCE_CHANGED
    assert not result.failed[0].source_intact
    (toast,) = [t for t in app.toasts.visible if t.model.kind is ToastKind.CRITICAL]
    assert toast.model.title == "Source file changed during conversion"
    assert toast.model.body.startswith("photo.jpg — size or date differs.")
    assert app.tray.state is TrayState.ALERT
    assert src.read_bytes() != before  # the fixture did change it; that is what was caught
    assert sorted(p.name for p in src.parent.iterdir()) == ["photo.jpg"]  # its output: discarded
    the_app_still_converts(app, qtbot, src, replaced=False)
