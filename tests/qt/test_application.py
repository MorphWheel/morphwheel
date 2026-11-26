"""``app.application``: it builds offscreen, the elevated gate, the catalog, and a drop end to end.

The end-to-end test is the S3 exit criterion in one place: a ``DropRequest`` for a real PNG goes
through the dispatcher and a real worker process, a JPG appears beside it, the toast says so, and
Undo knows the new file.
"""

from __future__ import annotations

import shutil
import sys
import threading
import time
import weakref
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from functools import partial
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSystemTrayIcon
from pytestqt.qtbot import QtBot

import morphwheel.app.application as application_module
from morphwheel.app.application import (
    EXIT_ELEVATED,
    EXIT_FAILED,
    EXIT_OK,
    HEIC_TOAST_KEY,
    Application,
    _EngineJob,
    build_catalog,
    motion_switch,
    parse_args,
)
from morphwheel.core.catalog import MORE_SLOT, SLOT_ORDER, Reason
from morphwheel.core.errors import ErrorCode
from morphwheel.core.formats import FileInfo, FormatId, Sniff
from morphwheel.core.jobs import DropRequest, JobOutcome, JobResult, TaskResult, TaskStatus
from morphwheel.engine import engines
from morphwheel.i18n import translate
from morphwheel.platform import autostart, system
from morphwheel.platform.single_instance import SingleInstance
from morphwheel.plugins.manifest import builtin_manifest
from morphwheel.settings.model import PluginPrefs, Quality, Settings
from morphwheel.settings.paths import AppPaths
from morphwheel.settings.store import load_settings, save_settings
from morphwheel.ui.onboarding import ONBOARDING_KEY
from morphwheel.ui.toasts.model import ToastKind, ToastModel
from morphwheel.ui.toasts.widget import ToastWidget

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
from fake_heic import fake_wheel, pin

from conftest import teardown_app
from morphwheel.ui.tray import TrayState
from morphwheel.ui.wheel.glyphs import GlyphSet

pytestmark = pytest.mark.usefixtures("qapp")


def test_parse_args_and_version() -> None:
    args = parse_args(["--any-source", "--debug"])
    assert args.any_source
    assert args.debug
    assert not args.install_heic
    assert not args.worker_check
    assert not parse_args([]).any_source
    assert parse_args(["--install-heic"]).install_heic
    assert parse_args(["--worker-check"]).worker_check
    with pytest.raises(SystemExit) as exit_:
        parse_args(["--version"])
    assert exit_.value.code == 0


def test_catalog_comes_from_the_manifest_and_the_engine_registry() -> None:
    catalog = build_catalog(builtin_manifest().targets, frozenset({FormatId.HEIC}))
    plan = catalog.plan([FileInfo.from_path(Path("photo.png"))])
    assert plan.ok
    labels = {pos: s.target.label if s.target else None for pos, s in plan.slots.items()}
    assert labels[SLOT_ORDER[0]] == "JPG"
    assert labels[MORE_SLOT] is None
    assert not plan.slots[MORE_SLOT].enabled  # no plugins yet (S6)
    assert plan.slots[SLOT_ORDER[1]].reason is not None  # PNG onto PNG: the source
    heic = catalog.plan([FileInfo.from_path(Path("photo.heic"))])
    assert not heic.ok  # the engine is an opt-in download (A6)
    with_engine = build_catalog(builtin_manifest().targets, frozenset())
    assert with_engine.plan([FileInfo.from_path(Path("photo.heic"))]).ok


MakeApp = Callable[..., Application]


@pytest.fixture
def make_app(app_paths_tmp: AppPaths) -> Iterator[MakeApp]:
    """Build Applications on the test's paths; every one is torn down, whatever the test does."""
    built: list[Application] = []

    def make(motion: str = "off", **overrides: object) -> Application:
        kwargs: dict[str, object] = {
            "paths": app_paths_tmp,
            "is_elevated": lambda: False,
            "pool_size": 1,
            **overrides,
        }
        application = Application(["morphwheel", "--debug", "--motion", motion], **kwargs)  # type: ignore[arg-type]
        built.append(application)
        return application

    try:
        yield make
    finally:
        for application in built:
            teardown_app(application)


@pytest.fixture
def app(make_app: MakeApp) -> Application:
    return make_app()


def test_builds_offscreen_and_logs_to_the_app_paths(
    app: Application, app_paths_tmp: AppPaths
) -> None:
    assert app.log_file.parent == app_paths_tmp.logs_dir
    assert not app.qapp.quitOnLastWindowClosed()
    assert not app.window.isVisible()
    assert app.startup_checks() is None
    assert app.dispatcher.active_jobs == 0
    assert app.catalog.target("jpeg") is not None
    app.start()
    app.start()  # idempotent
    assert app.pool.running
    assert app.toasts.pending == (ONBOARDING_KEY,)  # a fresh profile: the bubble is on its way
    text = app.log_file.read_text(encoding="utf-8")
    assert "Morphwheel" in text
    assert "fallback output:" in text
    assert app.paths.fallback_output_dir == app_paths_tmp.fallback_output_dir
    assert app.paths.fallback_output_dir.name == "Morphwheel"


def test_the_main_thread_collects_while_the_app_runs(app: Application) -> None:
    """RD-38: the collector's timer runs between start and stop, started before the pool."""
    started: list[bool] = []
    original = app.pool.start
    app.pool.start = lambda: (started.append(app.collector.active), original())[1]  # type: ignore[method-assign]
    assert not app.collector.active
    app.start()
    assert started == [True]  # running before the pool's threads exist
    app.stop()
    assert not app.collector.active


def test_run_turns_automatic_collection_off_before_the_app_exists(
    instance_names: tuple[str, str], monkeypatch: pytest.MonkeyPatch, app_paths_tmp: AppPaths
) -> None:
    """In the suite collection is already off, so the order is what's asserted."""
    order: list[str] = []

    class Built:
        def __init__(self, *a: object, **k: object) -> None:
            order.append("app")

        def exec(self) -> int:
            return EXIT_OK

    mutex, pipe = instance_names
    monkeypatch.setattr(application_module, "SingleInstance", partial(SingleInstance, mutex, pipe))
    monkeypatch.setattr(application_module, "app_paths", lambda: app_paths_tmp)
    monkeypatch.setattr(application_module, "Application", Built)
    monkeypatch.setattr(
        application_module.collector, "disable_automatic", lambda: order.append("disable")
    )
    assert application_module.run(["morphwheel"]) == EXIT_OK
    assert order == ["disable", "app"]


@pytest.mark.integration
def test_a_drop_converts_toasts_and_registers_undo(
    app: Application, qtbot: QtBot, tmp_path: Path
) -> None:
    folder = tmp_path / "pictures"
    folder.mkdir()
    src = folder / "photo.png"
    Image.new("RGB", (32, 24), (200, 100, 50)).save(src)
    app.start()
    info = FileInfo.from_path(src).with_sniff(Sniff(FormatId.PNG, False))
    with qtbot.waitSignal(app.dispatcher.job_finished, timeout=60_000) as blocker:
        app.controller.drop_received.emit(DropRequest((info,), "jpeg", 0))
    result = blocker.args[0]
    assert result.outcome is JobOutcome.SUCCESS
    out = folder / "photo.jpg"
    assert out.is_file()
    with Image.open(out) as im:
        assert im.format == "JPEG"
        assert im.size == (32, 24)
    assert sorted(p.name for p in folder.iterdir()) == ["photo.jpg", "photo.png"]
    assert len(app.toasts.visible) == 1
    toast = app.toasts.visible[0]
    assert toast.model.kind is ToastKind.SUCCESS
    assert toast.model.title == "Converted to JPG"
    assert toast.model.body.startswith("photo.jpg · ")
    assert app.undo.can_undo(result.job_id)
    assert app.dispatcher.active_jobs == 0
    assert app.toasts.pending == ()  # the single-file "working" toast was cancelled by the result

    # Undo from the toast (D5): the registry recycles the JPG it created, and only that.
    recycled: list[Path] = []

    def fake_recycle(path: Path) -> bool:  # never the user's real Recycle Bin in a test
        recycled.append(path)
        path.unlink()
        return True

    app.undo.recycle = fake_recycle
    assert [a.label for a in toast.model.actions] == ["Show in folder", "Undo"]
    toast.buttons[1].click()
    assert recycled == [out]
    assert sorted(p.name for p in folder.iterdir()) == ["photo.png"]
    assert len(app.toasts.visible) == 1
    assert app.toasts.visible[0].model.title == "Moved to Recycle Bin"
    assert not app.undo.can_undo(result.job_id)


def test_settings_reach_their_owners_at_start_and_on_change(app_paths_tmp: AppPaths) -> None:
    """Phase-4 §6, D8 row: the key reaches the poller at once; U4: the size waits for a hide."""
    save_settings(
        app_paths_tmp.settings_file,
        Settings(trigger_key="ctrl", wheel_size="L", paused=True, quality=Quality(55, 85, 70)),
    )
    application = Application(
        ["morphwheel", "--debug"], paths=app_paths_tmp, is_elevated=lambda: False, pool_size=1
    )
    try:
        assert application.settings_store.problems == ()
        assert application.controller.trigger_key == "ctrl"
        assert application.window.wheel_size == "L"
        assert application.controller.paused
        assert application.dispatcher.options["jpeg_quality"] == 55

        store = application.settings_store
        store.update(
            trigger_key="ctrl+shift", paused=False, quality=Quality(jpeg=10, webp=85, avif=70)
        )
        assert application.controller.trigger_key == "ctrl+shift"
        assert not application.controller.paused
        assert application.dispatcher.options["jpeg_quality"] == 10

        application.window.show()  # a visible wheel keeps its hit regions (U4)
        store.update(wheel_size="S")
        assert application.window.wheel_size == "L"
        application.window.hide()
        assert application.window.wheel_size == "S"
        assert load_settings(app_paths_tmp.settings_file).settings.wheel_size == "S"
    finally:
        teardown_app(application)


def test_a_single_file_shows_working_only_after_a_moment(app: Application) -> None:
    """Phase-3 §3: the working toast for one file waits ``WORKING_DELAY_MS``; a quick result
    cancels it. The wait itself is proven on the manager (``test_toasts.py``)."""
    app._on_job_started("slow", 1)
    assert app.toasts.pending == ("slow",)
    assert app.toasts.visible == () or app.toasts.visible[0].key != "slow"
    app._on_job_finished(JobResult("slow", app.catalog.target("jpeg"), ()))  # type: ignore[arg-type]
    assert app.toasts.pending == ()
    app._on_job_started("batch", 3)
    assert app.toasts.pending == ()  # a batch shows its working toast at once
    assert any(t.key == "batch" for t in app.toasts.visible)


def test_toasts_wait_while_the_wheel_is_up(app: Application, qtbot: QtBot) -> None:
    """C1 at the app level: a result that arrives during a drag shows after the wheel hides."""
    app.window.show()
    app._on_job_finished(JobResult("j", app.catalog.target("jpeg"), ()))  # type: ignore[arg-type]
    assert app.toasts.visible == ()
    assert app.toasts.held == 1
    qtbot.wait(100)
    assert app.toasts.visible == ()  # still up: still held
    app.window.hide()  # hideEvent → hidden → release: on the very hide, no polling
    assert [t.key for t in app.toasts.visible] == ["j"]


def test_the_tray_follows_the_settings_the_jobs_and_the_alerts(
    app: Application, qtbot: QtBot, opened_folders: list[Path]
) -> None:
    """Phase-3 §6.1 wired: pause through the store, the working badge, the alert, the menu."""
    tray = app.tray
    assert tray.state is TrayState.NORMAL
    assert tray.tooltip == "Morphwheel — Shift-drag to convert"
    app.settings_store.update(trigger_key="ctrl")
    assert tray.tooltip == "Morphwheel — Ctrl-drag to convert"

    tray.pause_toggled.emit(True)  # the menu's Pause: the store, then the controller and the tray
    assert app.controller.paused
    assert tray.paused
    assert tray.state is TrayState.PAUSED
    assert load_settings(app.paths.settings_file).settings.paused
    app.settings_store.update(paused=False)
    assert not app.controller.paused
    assert not tray.paused

    app._on_job_started("j", 3)
    assert tray.state is TrayState.WORKING
    assert tray.tooltip == "Converting 0 / 3…"
    app._on_job_progress("j", 2, 3)
    assert tray.tooltip == "Converting 2 / 3…"
    target = app.catalog.target("jpeg")
    assert target is not None
    app._on_job_finished(JobResult("j", target, ()))
    assert tray.state is TrayState.NORMAL

    src = Path("C:/x/photo.png")
    changed = TaskResult(
        "k", 0, src, TaskStatus.FAILED, error=ErrorCode.SOURCE_CHANGED, source_intact=False
    )
    app._on_job_started("k", 1)
    app._on_job_finished(JobResult("k", target, (changed,)))
    assert tray.state is TrayState.ALERT
    assert tray.tooltip == "1 problem — click for details"
    tray._on_activated(QSystemTrayIcon.ActivationReason.Trigger)  # a left click: the details
    assert tray.state is TrayState.NORMAL
    details = app._details
    assert details is not None
    assert details.isVisible()
    assert str(src) in details.text.toPlainText()
    details.hide()

    tray.log_folder_requested.emit()
    assert opened_folders == [app.paths.logs_dir]


def test_the_tray_opens_the_settings_and_they_reach_their_owners(app: Application) -> None:
    assert app.settings_window is None
    app.window.show()  # a drag in progress: never a second window (C1)
    app.tray.settings_requested.emit()
    assert app.settings_window is None
    app.window.hide()
    app.tray.settings_requested.emit()
    window = app.settings_window
    assert window is not None
    assert window.isVisible()
    assert window.page == "general"
    window.trigger_key.setCurrentIndex(1)
    window.trigger_key.activated.emit(1)  # the user picked Ctrl
    assert app.controller.trigger_key == "ctrl"
    assert app.tray.tooltip == "Morphwheel — Ctrl-drag to convert"
    app.show_settings("about")  # the bubble asks for a page…
    assert app.settings_window is window  # reused
    assert window.page == "about"
    window.hide()
    app.tray.settings_requested.emit()  # …the tray brings it back where it was left
    assert window.isVisible()
    assert window.page == "about"
    app.stop()
    assert not window.isVisible()


# ----------------------------------------------------------------------------- the first run
def _bubble(app: Application) -> list[ToastWidget]:
    return [t for t in app.toasts.visible if t.key == ONBOARDING_KEY]


FirstRun = Callable[..., Application]


@pytest.fixture
def first_run(make_app: MakeApp, monkeypatch: pytest.MonkeyPatch, qtbot: QtBot) -> FirstRun:
    """An app with the bubble on screen (no worker processes: ``start`` isn't run)."""
    monkeypatch.setattr(application_module, "ONBOARDING_DELAY_MS", 10)

    def run(motion: str = "off") -> Application:
        application = make_app(motion)
        application._schedule_onboarding()
        assert application.toasts.pending == (ONBOARDING_KEY,)
        qtbot.waitUntil(lambda: len(_bubble(application)) == 1, timeout=3000)
        return application

    return run


def _done_on_disk(paths: AppPaths) -> bool:
    return load_settings(paths.settings_file).settings.onboarding_done


def test_got_it_is_remembered_and_quitting_is_not(
    first_run: FirstRun, make_app: MakeApp, app_paths_tmp: AppPaths
) -> None:
    first = first_run()
    assert _bubble(first)[0].model.body == "Drag an image in File Explorer, then press Shift."
    first.stop()  # quit with the bubble up: not an acknowledgement
    assert not _done_on_disk(app_paths_tmp)

    second = first_run()  # so it is back
    _bubble(second)[0].buttons[0].click()  # Got it
    assert _bubble(second) == []
    assert second.settings_store.settings.onboarding_done
    assert _done_on_disk(app_paths_tmp)

    third = make_app()
    third._schedule_onboarding()
    assert third.toasts.pending == ()  # never again


def test_the_settings_button_opens_the_window_and_acknowledges(
    first_run: FirstRun, app_paths_tmp: AppPaths
) -> None:
    application = first_run()
    _bubble(application)[0].buttons[1].click()  # Settings
    window = application.settings_window
    assert window is not None
    assert window.isVisible()
    assert window.page == "general"
    assert _bubble(application) == []
    assert _done_on_disk(app_paths_tmp)


def test_opening_the_settings_from_the_tray_acknowledges_too(
    first_run: FirstRun, app_paths_tmp: AppPaths
) -> None:
    application = first_run()
    application.window.show()  # a drag: no window opens, nothing is acknowledged
    application.tray.settings_requested.emit()
    assert len(_bubble(application)) == 1
    assert not _done_on_disk(app_paths_tmp)
    application.window.hide()
    application.tray.settings_requested.emit()
    assert _bubble(application) == []
    assert _done_on_disk(app_paths_tmp)


def test_the_first_drop_takes_the_bubble_away_for_good(
    first_run: FirstRun, make_app: MakeApp, app_paths_tmp: AppPaths, qtbot: QtBot
) -> None:
    """With animations on: the bubble fades while the wheel is still up, the settings change
    arrives mid-fade, and nothing brings the bubble back when the wheel hides (the S5 review)."""
    application = first_run("on")
    application.window.show()  # the wheel is up, as at a real drop
    info = FileInfo.from_path(Path("C:/no/such/photo.png"))
    application.controller.drop_received.emit(DropRequest((info,), "jpeg", 0))
    assert _done_on_disk(app_paths_tmp)
    application.window.hide()  # releases whatever was held; a second bubble would show here
    qtbot.waitUntil(lambda: _bubble(application) == [], timeout=3000)
    assert ONBOARDING_KEY not in application.toasts.pending
    application.toasts.release()
    assert _bubble(application) == []

    again = make_app()
    again._schedule_onboarding()
    assert again.toasts.pending == ()  # done: no bubble is scheduled
    again.controller.drop_received.emit(DropRequest((info,), "jpeg", 0))
    assert ONBOARDING_KEY not in again.toasts.pending


def test_a_drop_before_the_bubble_shows_cancels_it(app: Application) -> None:
    app._schedule_onboarding()  # still delayed
    assert app.toasts.pending == (ONBOARDING_KEY,)
    info = FileInfo.from_path(Path("C:/no/such/photo.png"))
    app.controller.drop_received.emit(DropRequest((info,), "jpeg", 0))
    assert ONBOARDING_KEY not in app.toasts.pending
    assert app.settings_store.settings.onboarding_done


def test_a_failed_save_hides_the_bubble_for_this_run_only(
    first_run: FirstRun,
    app_paths_tmp: AppPaths,
    refused_saves: Callable[[], AbstractContextManager[None]],
) -> None:
    application = first_run()
    with refused_saves():
        _bubble(application)[0].buttons[0].click()  # Got it
    assert _bubble(application) == []
    assert application.settings_store.settings.onboarding_done  # in force for this run
    assert not _done_on_disk(app_paths_tmp)  # it returns at the next start


@pytest.mark.usefixtures("hebrew")
def test_the_language_setting_picks_the_catalog_and_the_direction(
    make_app: MakeApp, app_paths_tmp: AppPaths
) -> None:
    """D3, D3a: the catalog for the setting's language is installed before any widget, the
    application mirrors, and stop() puts the session's application back."""
    save_settings(app_paths_tmp.settings_file, Settings(language="he"))
    app = make_app()
    assert app.qapp.layoutDirection() == Qt.LayoutDirection.RightToLeft
    assert translate("Tray", "Quit") == "יציאה"
    app.stop()
    assert app.qapp.layoutDirection() == Qt.LayoutDirection.LeftToRight
    assert translate("Tray", "Quit") == "Quit"


def test_an_unreadable_settings_file_is_not_a_first_run(
    make_app: MakeApp,
    app_paths_tmp: AppPaths,
    unreadable: Callable[[Path], AbstractContextManager[None]],
) -> None:
    save_settings(app_paths_tmp.settings_file, Settings(onboarding_done=True, wheel_size="L"))
    with unreadable(app_paths_tmp.settings_file):
        application = make_app()
    assert application.settings_store.unread
    application._schedule_onboarding()
    assert application.toasts.pending == ()  # the flag is unknown: no bubble
    application.tray.pause_toggled.emit(True)  # the first write re-reads the file first
    assert application.settings_store.settings == Settings(
        onboarding_done=True, wheel_size="L", paused=True
    )
    assert load_settings(app_paths_tmp.settings_file).settings.wheel_size == "L"
    assert application.window.wheel_size == "L"  # the owners got the real values


def test_details_opens_a_window_that_blocks_nothing(app: Application, qtbot: QtBot) -> None:
    """A modal box would make every toast button dead and the wheel refuse drags; the Details
    window is a plain non-modal window (RD-17(g) closed by file 6)."""
    toast = app.toasts.show(ToastModel(ToastKind.ERROR, "e", "", 60_000))
    assert toast is not None
    app._on_details("scan.tiff — The file couldn't be read.")
    details = app._details
    assert details is not None
    assert details.isVisible()
    assert details.text.toPlainText().startswith("scan.tiff")
    app._on_details("other")
    assert app._details is details  # reused, not stacked
    assert details.text.toPlainText() == "other"
    assert not details.isModal()
    assert not (details.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
    with qtbot.waitSignal(toast.dismissed, timeout=1000):
        toast.close_button.click()  # still clickable while the window is open
    details.hide()


# ----------------------------------------------------------------------------- start with Windows
def test_the_registry_is_the_truth_at_start_and_the_setting_after(
    app_paths_tmp: AppPaths,
    make_app: MakeApp,
    recorded_autostart: list[bool],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RD-23: the installer's checkbox survives the first start; a toggle writes the registry."""
    app = make_app()
    assert not app.settings_store.settings.start_with_windows
    assert recorded_autostart == []  # an "off" at start writes nothing (Task Manager's Disable)
    app.settings_store.update(start_with_windows=True)
    assert recorded_autostart == [True]
    app.settings_store.update(start_with_windows=False)  # the user's own change: written
    assert recorded_autostart == [True, False]
    teardown_app(app)

    monkeypatch.setattr(autostart, "is_enabled", lambda **_: True)  # the installer's checkbox
    save_settings(app_paths_tmp.settings_file, Settings(start_with_windows=False))
    recorded_autostart.clear()
    adopted = make_app()
    assert adopted.settings_store.settings.start_with_windows  # adopted, not deleted
    assert load_settings(app_paths_tmp.settings_file).settings.start_with_windows
    assert recorded_autostart == [True]  # refreshed, never turned off at start

    def refused(enabled: bool, **_: object) -> bool:
        recorded_autostart.append(enabled)
        return False

    monkeypatch.setattr(autostart, "sync", refused)
    adopted.settings_store.update(start_with_windows=False)  # the registry refuses: logged, kept
    assert not adopted.settings_store.settings.start_with_windows


# ----------------------------------------------------------------------------- one instance
def test_a_second_start_opens_the_settings_of_the_first(
    make_app: MakeApp, instance_names: tuple[str, str], qtbot: QtBot
) -> None:
    mutex, pipe = instance_names
    guard = SingleInstance(mutex, pipe)
    assert guard.acquire()
    first = make_app(instance=guard)
    first.start()  # start() is what listens
    knock = SingleInstance(mutex, pipe)
    assert not knock.acquire()
    with qtbot.waitSignal(guard.settings_requested, timeout=2000):
        assert knock.ping()
    qtbot.waitUntil(lambda: first.settings_window is not None, timeout=2000)
    assert first.settings_window is not None
    assert first.settings_window.isVisible()
    first.stop()
    assert not guard.held  # stop() released the name…
    again = SingleInstance(mutex, pipe)
    assert again.acquire()  # …so the next start may take it
    again.release()


def test_run_hands_a_second_start_to_the_first(
    app_paths_tmp: AppPaths,
    instance_names: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
    qtbot: QtBot,
) -> None:
    """``run()`` never builds the pool, the wheel or the tray for a second start: it knocks."""
    mutex, pipe = instance_names
    holder = SingleInstance(mutex, pipe)
    assert holder.acquire()
    assert holder.listen()

    def never(*a: object, **k: object) -> None:
        raise AssertionError("a second start must not build an Application")

    monkeypatch.setattr(application_module, "SingleInstance", partial(SingleInstance, mutex, pipe))
    monkeypatch.setattr(application_module, "Application", never)
    monkeypatch.setattr(application_module, "app_paths", lambda: app_paths_tmp)
    with qtbot.waitSignal(holder.settings_requested, timeout=2000):
        assert application_module.run(["morphwheel"]) == EXIT_OK
    holder.release()


def test_a_restart_from_elevated_frees_the_name_first(
    make_app: MakeApp, instance_names: tuple[str, str]
) -> None:
    mutex, pipe = instance_names
    guard = SingleInstance(mutex, pipe)
    assert guard.acquire()
    taken: list[bool] = []

    def restart() -> bool:
        taken.append(SingleInstance(mutex, pipe).acquire())  # the normal instance's own try
        return True

    app = make_app(
        instance=guard, is_elevated=lambda: True, restart=restart, ask_elevated=lambda: "restart"
    )
    assert app.startup_checks() == EXIT_OK
    assert taken == [True]  # the name was free when the restart ran


def test_about_opens_the_settings_on_the_about_page(app: Application) -> None:
    app.tray.about_requested.emit()
    assert app.settings_window is not None
    assert app.settings_window.isVisible()
    assert app.settings_window.page == "about"


# ----------------------------------------------------------------------------- the HEIC engine (A6)
def _heic_toast(app: Application) -> ToastWidget | None:
    return next((t for t in app.toasts.visible if t.key == HEIC_TOAST_KEY), None)


def _heic_plan_ok(app: Application) -> bool:
    return app.catalog.plan([FileInfo.from_path(Path("C:/x/photo.heic"))]).ok


def _no_venv_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """The dev venv has pillow-heif importable (the ``heic`` extra); a user's machine doesn't."""
    monkeypatch.setattr(engines, "find_spec", lambda name: None)


def test_the_offer_leads_to_a_consent_a_download_and_a_live_catalog(
    make_app: MakeApp, monkeypatch: pytest.MonkeyPatch, qtbot: QtBot
) -> None:
    _no_venv_engine(monkeypatch)
    data = fake_wheel()
    pin(monkeypatch, data)
    fetched: list[str] = []

    def fetch(url: str) -> bytes:
        fetched.append(url)
        return data

    app = make_app(engine_fetch=fetch)
    assert not _heic_plan_ok(app)
    app.window.engine_missing.emit()  # a HEIC drag the wheel refused
    app.window.engine_missing.emit()  # and another: the offer is once per run
    offer = _heic_toast(app)
    assert offer is not None
    assert offer.model.kind is ToastKind.INFO
    assert offer.model.title == "HEIC support isn't installed."
    assert "929 B" in offer.model.body  # the pinned spec's size: the fake wheel's here
    assert [b.text() for b in offer.buttons] == ["Install"]
    assert fetched == []  # nothing downloaded before a consent

    app.window.show()  # mid-drag: no consent window may open
    offer.buttons[0].click()
    assert not app.consent.is_open
    app.window.hide()
    app.toasts.show(offer.model, key=HEIC_TOAST_KEY)  # the offer again (it was dismissed)
    toast = _heic_toast(app)
    assert toast is not None
    toast.buttons[0].click()
    assert app.consent.is_open
    assert fetched == []  # still nothing: consent first (A6)
    install = app.consent.install_button
    assert install is not None
    install.click()
    assert app._engine_job is not None
    assert app._heic_state() == "installing"
    app._ask_install_heic()  # a second request while one runs
    assert not app.consent.is_open
    qtbot.waitUntil(lambda: app._engine_job is None, timeout=5000)
    assert fetched == [engines.HEIC_WHEEL.url]
    assert FormatId.HEIC not in app.missing_engines
    assert _heic_plan_ok(app)
    done = _heic_toast(app)
    assert done is not None
    assert done.model.title == "HEIC support installed"
    assert HEIC_TOAST_KEY not in app.toasts.pending  # the working toast never flashed

    app.show_settings("conversion")
    window = app.settings_window
    assert window is not None
    assert window.heic_state == "installed"
    window.heic_button.click()  # Remove: no consent needed for a re-downloadable folder
    assert window.heic_state == "missing"
    assert not _heic_plan_ok(app)
    removed = _heic_toast(app)
    assert removed is not None
    assert removed.model.title == "HEIC support removed"
    assert removed.model.body == ""
    assert not engines.heic_dir(app.paths.engines_dir).exists()
    app._ask_install_heic()  # the engine is gone: an offer may ask again
    assert app.consent.is_open
    assert app.consent.box is not None
    app.consent.box.hide()


def test_a_removal_with_files_in_use_says_the_rest_goes_later(
    make_app: MakeApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_venv_engine(monkeypatch)
    app = make_app()
    folder = engines.heic_dir(app.paths.engines_dir)
    folder.mkdir(parents=True)
    (folder / "pillow_heif").mkdir()
    (folder / "pillow_heif" / "__init__.py").write_bytes(b"")
    (folder / "_pillow_heif.pyd").write_bytes(b"MZ")
    (folder / "libheif.dll").write_bytes(b"MZ")
    app._refresh_catalog()
    assert app._heic_state() == "installed"
    app._ask_install_heic()  # already there: no consent, no download
    assert not app.consent.is_open
    with (folder / "libheif.dll").open("rb"):  # a worker holding the DLL: Windows keeps it
        app._remove_heic()
    assert app._heic_state() == "missing"  # the package is gone, so the engine is
    toast = _heic_toast(app)
    assert toast is not None
    assert toast.model.title == "HEIC support removed"
    assert toast.model.body == "The files still in use go at the next start."
    assert folder.exists()


def test_a_bad_download_installs_nothing_and_says_why(
    make_app: MakeApp, monkeypatch: pytest.MonkeyPatch, qtbot: QtBot
) -> None:
    _no_venv_engine(monkeypatch)
    app = make_app(engine_fetch=lambda url: fake_wheel())  # the real pin doesn't match a fake
    app._install_heic()
    qtbot.waitUntil(lambda: app._engine_job is None, timeout=5000)
    failed = _heic_toast(app)
    assert failed is not None
    assert failed.model.kind is ToastKind.ERROR
    assert failed.model.title == "Couldn't install HEIC support"
    assert failed.model.body == (
        "The download didn't match the expected file. Nothing was installed."
    )
    assert "pinned hash" in str(failed.model.actions[0].payload)  # the raw reason, in Details
    assert FormatId.HEIC in app.missing_engines
    assert not engines.heic_dir(app.paths.engines_dir).exists()
    assert app._heic_state() == "missing"

    def refused(url: str) -> bytes:
        raise engines.EngineInstallError("download failed: no route", kind="download")

    app2 = make_app(engine_fetch=refused)
    app2._install_heic()
    qtbot.waitUntil(lambda: app2._engine_job is None, timeout=5000)
    failed = _heic_toast(app2)
    assert failed is not None
    assert failed.model.body.startswith("The download failed.")


def test_a_download_in_flight_at_stop_finishes_quietly(
    make_app: MakeApp, monkeypatch: pytest.MonkeyPatch, qtbot: QtBot
) -> None:
    data = fake_wheel()
    pin(monkeypatch, data)
    gate = threading.Event()

    def slow(url: str) -> bytes:
        gate.wait(5)
        return data

    app = make_app(engine_fetch=slow)
    app._install_heic()
    job = app._engine_job
    assert job is not None
    app.stop()  # quits while the download runs
    assert job.abandoned
    assert app._engine_job is None
    done: list[object] = []
    job.done.connect(done.append)
    freed_on: list[str] = []
    weakref.finalize(job, lambda: freed_on.append(threading.current_thread().name))
    assert job in application_module._RETIRED_JOBS  # RD-38: its thread mustn't hold the last ref
    thread = job._thread
    assert thread is not None
    del job
    gate.set()
    thread.join(5)
    qtbot.wait(300)
    assert done == []  # nothing arrives at a stopped app, and nothing raised in the thread
    assert freed_on == []  # the thread ended without freeing it
    application_module._RETIRED_JOBS.clear()  # here, on the main thread
    assert freed_on == ["MainThread"]


def test_the_install_job_dies_on_the_main_thread_when_its_thread_lingers(
    make_app: MakeApp, monkeypatch: pytest.MonkeyPatch, qtbot: QtBot
) -> None:
    """RD-38: the job's thread holds it too. One still returning when ``done`` is handled would
    free the QObject there, unless the app waits for it (seen in a probe: 5 of 5 without)."""
    run = _EngineJob._run

    def lingering(self: _EngineJob) -> None:
        run(self)
        time.sleep(0.2)  # ``done`` is out; the thread still holds the job

    monkeypatch.setattr(_EngineJob, "_run", lingering)
    _no_venv_engine(monkeypatch)
    data = fake_wheel()
    pin(monkeypatch, data)  # a success: a failure's traceback would hold the job's frame
    app = make_app(engine_fetch=lambda url: data)
    app._install_heic()
    job = app._engine_job
    assert job is not None
    freed_on: list[str] = []
    weakref.finalize(job, lambda: freed_on.append(threading.current_thread().name))
    del job
    qtbot.waitUntil(lambda: app._engine_job is None, timeout=5000)
    assert freed_on == ["MainThread"]
    assert application_module._RETIRED_JOBS == []


@pytest.mark.integration
def test_worker_check_reports_qt_free_workers(
    app: Application, capsys: pytest.CaptureFixture[str]
) -> None:
    assert app.worker_check() == EXIT_OK
    out = capsys.readouterr().out
    assert "qt_loaded=False" in out
    assert out.strip().endswith("worker check: OK")
    assert sys.executable.lower() in out.lower()  # from source: python itself runs the workers
    assert "wheel icons: OK" in out


@pytest.mark.integration
def test_worker_check_fails_when_a_wheel_icon_does_not_load(
    app: Application, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert app.worker_check(GlyphSet(tmp_path)) == EXIT_FAILED  # an empty folder: none load
    out = capsys.readouterr().out
    assert "wheel icons: FAILED (COMPRESS, PDF, MORE, CANCEL)" in out
    assert out.strip().endswith("worker check: FAILED (wheel icons)")


@pytest.mark.parametrize(
    ("choice", "restart_ok", "code"),
    [("quit", True, EXIT_ELEVATED), ("restart", True, EXIT_OK), ("restart", False, EXIT_ELEVATED)],
)
def test_elevated_gate(app_paths_tmp: AppPaths, choice: str, restart_ok: bool, code: int) -> None:
    explained: list[bool] = []
    app = Application(
        ["morphwheel"],
        paths=app_paths_tmp,
        is_elevated=lambda: True,
        restart=lambda: restart_ok,
        ask_elevated=lambda: choice,  # type: ignore[arg-type, return-value]
        explain_failed_restart=lambda: explained.append(True),
        pool_size=1,
    )
    try:
        assert app.startup_checks() == code
        assert explained == ([True] if choice == "restart" and not restart_ok else [])
    finally:
        teardown_app(app)


def test_motion_switch_follows_the_argument() -> None:
    assert parse_args([]).motion == "auto"
    assert parse_args(["--motion", "on"]).motion == "on"
    assert motion_switch("on")() is True
    assert motion_switch("off")() is False
    assert motion_switch("auto") is system.animations_enabled


# --------------------------------------------------------------------------- plugins (S6)
FIXTURE_PLUGINS = Path(__file__).resolve().parents[1] / "fixtures" / "plugins"


def install_fixture(paths: AppPaths, name: str) -> Path:
    """Copy a fixture plugin into the test profile under its id, as a user would."""
    target = paths.plugins_dir / f"test.{name}"
    shutil.copytree(FIXTURE_PLUGINS / name, target)
    return target


def test_plugins_are_disabled_until_enabled_and_a_change_reaches_the_wheel_and_the_workers(
    make_app: MakeApp, app_paths_tmp: AppPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase-2 §3: trust; phase-3 §2.3: the arc in the settings' order; S6 wiring."""
    install_fixture(app_paths_tmp, "echo")
    install_fixture(app_paths_tmp, "crash")  # never run here: it only needs an id and a target
    app = make_app()
    assert app.registry.broken == ()  # the control: both folders are usable plugins
    assert [e.id for e in app.registry.third_party] == ["test.crash", "test.echo"]
    assert not any(e.enabled for e in app.registry.third_party)
    png = FileInfo.from_path(Path("x.png")).with_sniff(Sniff(FormatId.PNG, False))
    assert app.catalog.plan([png]).slots[MORE_SLOT].reason is Reason.NO_PLUGINS
    assert app.catalog.target("test.echo:copy") is None

    calls: list[list[str]] = []
    monkeypatch.setattr(
        app.pool,
        "reconfigure",
        lambda specs, force=False: calls.append([s.plugin_id for s in specs]),
    )
    app.settings_store.update(paused=True)  # an unrelated change rebuilds nothing
    assert calls == []

    app.settings_store.update(plugins=PluginPrefs(enabled=("test.echo",)))
    assert calls == [["pillow_images", "test.echo"]]  # the workers first…
    assert app.catalog.target("test.echo:copy") is not None  # …then the catalog
    assert app.window._catalog is app.catalog
    assert app.dispatcher._catalog is app.catalog
    arc = [s.target.id for s in app.catalog.plan([png]).more if s.target]
    assert arc == ["test.echo:copy"]

    both = PluginPrefs(enabled=("test.echo", "test.crash"), order=("test.crash", "test.echo"))
    app.settings_store.update(plugins=both)
    arc = [s.target.id for s in app.catalog.plan([png]).more if s.target]
    assert arc == ["test.crash:copy", "test.echo:copy"]
    app.settings_store.update(plugins=PluginPrefs(enabled=both.enabled, order=("test.echo",)))
    arc = [s.target.id for s in app.catalog.plan([png]).more if s.target]
    assert arc == ["test.echo:copy", "test.crash:copy"]  # the rest follow by folder name
    assert calls[-1] == ["pillow_images", "test.echo", "test.crash"]

    # A folder removed while the app runs: the page asks for a rescan.
    shutil.rmtree(app_paths_tmp.plugins_dir / "test.crash")
    app.rescan_plugins()
    assert app.registry.entry("test.crash") is None  # still in the settings, names nothing
    assert app.catalog.target("test.crash:copy") is None
    assert calls[-1] == ["pillow_images", "test.echo"]


def test_the_plugins_page_and_the_trust_prompt_drive_the_registry(
    make_app: MakeApp,
    app_paths_tmp: AppPaths,
    monkeypatch: pytest.MonkeyPatch,
    opened_folders: list[Path],
) -> None:
    """Phase-3 §6.2 and §6.5 wired: the rows, the prompt, the folder, the rescan."""
    install_fixture(app_paths_tmp, "echo")
    app = make_app()
    forced: list[bool] = []
    monkeypatch.setattr(app.pool, "reconfigure", lambda specs, force=False: forced.append(force))
    app.show_settings("plugins")
    window = app.settings_window
    assert window is not None
    assert window.plugin_rows() == (("test.echo", False),)

    # The switch asks; the prompt names the plugin; Enable writes the trust record.
    window.plugin_list.item(0).setCheckState(Qt.CheckState.Checked)
    assert window.plugin_rows() == (("test.echo", False),)  # reverted: the prompt decides
    assert app.trust.plugin_id == "test.echo"
    assert app.trust.box is not None
    assert str(app_paths_tmp.plugins_dir / "test.echo") in app.trust.box.informativeText()
    assert load_settings(app.paths.settings_file).settings.plugins.enabled == ()
    assert app.trust.enable_button is not None
    app.trust.enable_button.click()
    assert load_settings(app.paths.settings_file).settings.plugins.enabled == ("test.echo",)
    assert app.catalog.target("test.echo:copy") is not None
    assert window.plugin_rows() == (("test.echo", True),)
    assert forced == [False]

    # Unchecking writes at once, no prompt.
    window.plugin_list.item(0).setCheckState(Qt.CheckState.Unchecked)
    assert not app.trust.is_open
    assert load_settings(app.paths.settings_file).settings.plugins.enabled == ()
    assert app.catalog.target("test.echo:copy") is None

    # No prompt mid-drag (C1); none for an unknown or already enabled id.
    app.window.show()
    window.plugin_enable_requested.emit("test.echo")
    assert not app.trust.is_open
    app.window.hide()
    window.plugin_enable_requested.emit("nope")
    assert not app.trust.is_open

    # A prompt whose plugin disappears is dismissed by the rescan that notices.
    window.plugin_enable_requested.emit("test.echo")
    assert app.trust.plugin_id == "test.echo"
    shutil.rmtree(app_paths_tmp.plugins_dir / "test.echo")
    window.rescan.click()
    assert not app.trust.is_open
    assert window.plugin_rows() == ()
    assert forced[-1] is True  # a rescan replaces the workers

    # The folder button creates Morphwheel's folder if need be, then opens it.
    shutil.rmtree(app_paths_tmp.plugins_dir)
    window.open_plugins_folder.click()
    assert app_paths_tmp.plugins_dir.is_dir()
    assert opened_folders == [app_paths_tmp.plugins_dir]

    # A plugin copied in later shows up on Rescan, disabled.
    install_fixture(app_paths_tmp, "crash")
    window.rescan.click()
    assert window.plugin_rows() == (("test.crash", False),)
