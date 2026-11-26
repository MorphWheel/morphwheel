"""Qt application bootstrap (phase-4 §4.6, §9 S2 and S3): logging, the startup checks, the wiring.

The composition root (R4): the only module that knows every layer. S2 assembled the dev wheel; S3
adds the engine: the plugin registry (S6) and the engine registry build the catalog, a pool
of Qt-free processes runs the conversions, the ``JobDispatcher`` turns a ``DropRequest`` into
tasks and a ``JobResult``, and the result becomes a toast and an undo record. S5 adds the tray,
settings, the single-instance guard and the toast buttons.

Rules:

- **The elevated check runs first** (phase-2 §3.7, phase-3 §6.4). Drag and drop from an
  unelevated Explorer into an elevated window is blocked by UIPI, so an elevated Morphwheel sees
  no drags. The user gets "Restart normally" (``platform.system.restart_unelevated``) or "Quit".
- **Nothing in this module makes Win32 calls that take coordinates before the ``QApplication``
  exists.** Qt switches the process to per-monitor DPI awareness at construction.
- **The pool is warmed in ``start`` and shut down in ``stop``**, before the ``QApplication`` goes
  away, so no pool thread emits into a dead object.
- **The drop handler stays light:** ``drop_received`` is a queued signal; ``submit`` does no I/O.
- Exit codes: 0 normal; ``EXIT_ELEVATED`` when the app refused to run elevated; ``EXIT_FAILED``
  for a failed maintenance command.

Usage::

    morphwheel [--any-source] [--debug]
    morphwheel --install-heic        # download the opt-in HEIC engine (A6) and exit
    morphwheel --worker-check        # start the workers, report their executable and Qt state,
                                     # and whether the wheel icons load (the frozen smoke test)
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication, QScreen
from PySide6.QtWidgets import QApplication

from morphwheel import __version__, i18n
from morphwheel.app.controller import Controller
from morphwheel.core.catalog import Catalog, Target
from morphwheel.core.formats import FormatId
from morphwheel.core.jobs import DropRequest, JobResult
from morphwheel.engine import engines
from morphwheel.engine.dispatcher import JobDispatcher
from morphwheel.engine.undo import UndoRegistry
from morphwheel.engine.worker_pool import (
    DEFAULT_SIZE,
    DEFAULT_TASK_TIMEOUT_S,
    WorkerPool,
    default_worker_executable,
)
from morphwheel.logs import setup_logging
from morphwheel.platform import autostart, shell, system
from morphwheel.platform.modifier_poller import ModifierPoller
from morphwheel.platform.raw_input import RawInputMonitor
from morphwheel.platform.single_instance import SingleInstance
from morphwheel.plugins.discovery import discover
from morphwheel.plugins.registry import Registry, build_registry
from morphwheel.settings.model import PluginPrefs, Settings
from morphwheel.settings.paths import AppPaths, app_paths
from morphwheel.settings.store import SettingsStore
from morphwheel.ui.dialogs import DetailsWindow, ElevatedChoice, HeicConsent, PluginTrustPrompt
from morphwheel.ui.dialogs import ask_elevated as ask_elevated_dialog
from morphwheel.ui.dialogs import explain_failed_restart as explain_failed_restart_dialog
from morphwheel.ui.icon import app_icon
from morphwheel.ui.onboarding import ONBOARDING_DELAY_MS, ONBOARDING_KEY, onboarding_toast
from morphwheel.ui.settings_window import SettingsWindow
from morphwheel.ui.toasts.manager import ToastManager
from morphwheel.ui.toasts.model import (
    WORKING_DELAY_MS,
    ActionKind,
    EngineFailure,
    ToastKind,
    heic_failed_toast,
    heic_installed_toast,
    heic_offer_toast,
    heic_removed_toast,
    heic_working_toast,
    toast_for,
    undo_toast,
    working_toast,
)
from morphwheel.ui.tray import TrayIcon
from morphwheel.ui.wheel.glyphs import GlyphSet
from morphwheel.ui.wheel.window import WheelWindow

log = logging.getLogger("morphwheel.app")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_ELEVATED = 3

REPOSITORY_URL = "https://github.com/MorphWheel/morphwheel"
HEIC_TOAST_KEY = "engine:heic"


class _EngineJob(QObject):
    """One HEIC install, run on a plain thread so the GUI never waits on the network (A6).

    The app keeps a reference until ``done`` has been handled: a job held only by its thread is
    freed when the thread ends, and a freed sender's queued signal never arrives. ``abandoned``
    is set at ``stop()``: the thread then finishes quietly, and never raises on a dead signal.
    """

    done = Signal(object)  # the engine folder (Path), or the exception

    def __init__(self, engines_dir: Path, fetch: engines.Fetch | None) -> None:
        super().__init__()
        self._engines_dir = engines_dir
        self._fetch = fetch
        self.abandoned = False

    def start(self) -> None:
        threading.Thread(target=self._run, name="mw-heic-install", daemon=True).start()

    def _run(self) -> None:
        result: Path | engines.EngineInstallError
        try:
            result = engines.install_heic(self._engines_dir, fetch=self._fetch)
        except engines.EngineInstallError as e:  # reported in the toast, nothing installed
            result = e
        except Exception as e:  # not the engine's contract: still reported, never a lost thread
            result = engines.EngineInstallError(f"unexpected: {e}", kind="write")
        if self.abandoned:
            return
        try:
            self.done.emit(result)
        except RuntimeError:  # the sender was deleted first (interpreter exit)
            return


@dataclass(frozen=True)
class _JobView:
    """What the toasts need to know about a job; the dispatcher owns the rest. Noted at the drop,
    before ``submit`` (``count`` still 0), so ``job_started`` can find it (see ``_on_drop``)."""

    screen: QScreen | None = None
    label: str = ""
    name: str = ""  # the first file, for the single-file working toast
    count: int = 0


def build_catalog(targets: Iterable[Target], missing: frozenset[FormatId]) -> Catalog:
    """The wheel's targets (the plugin registry's, S6) and the engine registry's gaps (A6)."""
    return Catalog.of(targets, missing_engines=missing)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="morphwheel", description="Morphwheel")
    parser.add_argument("--version", action="version", version=f"Morphwheel {__version__}")
    parser.add_argument(
        "--any-source", action="store_true", help="open the wheel for drags from any window"
    )
    parser.add_argument("--debug", action="store_true", help="verbose log, also on the console")
    parser.add_argument(
        "--motion",
        choices=("auto", "on", "off"),
        default="auto",
        help="wheel animations: auto follows Windows' animation switch (off over RDP)",
    )
    parser.add_argument(
        "--install-heic",
        action="store_true",
        help="download the opt-in HEIC engine (pillow-heif, GPLv2) to the engines folder and exit",
    )
    parser.add_argument(
        "--worker-check",
        action="store_true",
        help="start the worker processes, report their executable and whether Qt loaded, and exit",
    )
    return parser.parse_args(list(argv))


def motion_switch(mode: str) -> Callable[[], bool]:
    """``auto`` follows Windows' animation switch (C7); ``on`` and ``off`` force it (RDP tests)."""
    if mode == "on":
        return lambda: True
    if mode == "off":
        return lambda: False
    return system.animations_enabled


class Application:
    """Everything the GUI process owns. Built once, in ``run``; tests build it without ``exec``."""

    def __init__(
        self,
        argv: Sequence[str],
        *,
        paths: AppPaths | None = None,
        is_elevated: Callable[[], bool] = system.is_elevated,
        restart: Callable[[], bool] = system.restart_unelevated,
        ask_elevated: Callable[[], ElevatedChoice] | None = None,
        explain_failed_restart: Callable[[], None] | None = None,
        pool_size: int = DEFAULT_SIZE,
        task_timeout_s: float = DEFAULT_TASK_TIMEOUT_S,
        engine_fetch: engines.Fetch | None = None,
        instance: SingleInstance | None = None,
    ) -> None:
        """``instance`` is the guard ``run`` acquired (``None``: no pipe, no release: tests and
        the maintenance modes). The Run key is read and written through ``platform.autostart``
        at call time, so the test fixtures can stand in for it."""
        self.args = parse_args(argv[1:])
        self.paths = paths or app_paths()
        level = logging.DEBUG if self.args.debug else logging.INFO
        self.log_file = setup_logging(self.paths.logs_dir, level=level, console=self.args.debug)
        self._is_elevated = is_elevated
        self._restart = restart
        self._ask_elevated = ask_elevated or ask_elevated_dialog
        self._explain_failed_restart = explain_failed_restart or explain_failed_restart_dialog
        self._engine_fetch = engine_fetch  # tests inject a wheel; None is the real download
        self._instance = instance
        existing = QApplication.instance()
        self.qapp = existing if isinstance(existing, QApplication) else QApplication(list(argv))
        self.qapp.setApplicationName("Morphwheel")
        self.qapp.setApplicationVersion(__version__)
        self.qapp.setWindowIcon(app_icon())  # the settings window, the prompts, the taskbar (S7)
        self.qapp.setQuitOnLastWindowClosed(False)  # the wheel hides; the app lives in the tray

        # The settings file (phase-4 §4.6): read once here and pushed to its owners below, then
        # again on every change. The store logged any problems; the S5 settings window reports
        # them under a translated line, with the raw lines as details (D3a).
        self.settings_store = SettingsStore(self.paths.settings_file)
        settings = self.settings_store.load()
        # Start with Windows: the registry is the truth at start (the installer's checkbox,
        # the uninstaller, Task Manager), the setting after a change (RD-23).
        enabled = autostart.is_enabled()
        if enabled is not None and enabled != settings.start_with_windows:  # None: from source
            settings = self.settings_store.update(start_with_windows=enabled)

        # The plugins (S6): the folder is scanned here and on the user's ask, the settings
        # say which are enabled and in which order; then the catalog: what the wheel offers
        # (phase-3 §2.2) and which engine is missing (A6).
        self._discovery = discover(self.paths.plugins_dir)
        self.registry: Registry = build_registry(self._discovery, settings.plugins)
        self.missing_engines = engines.missing_engines(self.paths.engines_dir)
        self.catalog = build_catalog(self.registry.targets, self.missing_engines)

        # The engine: Qt-free workers, the dispatcher on top, undo and toasts around it.
        self.pool = WorkerPool(
            size=pool_size,
            task_timeout_s=task_timeout_s,
            plugins=self.registry.specs,
            engines_dir=self.paths.engines_dir,
            log_level=level,
            executable=default_worker_executable(),
        )
        fallback = self.paths.fallback_output_dir
        self.dispatcher = JobDispatcher(self.pool, self.catalog, fallback_dir=fallback)
        self.undo = UndoRegistry(shell.recycle)
        self._pending = _JobView()  # the last drop
        self._jobs: dict[str, _JobView] = {}
        self._details: DetailsWindow | None = None  # built on first use
        self._engine_job: _EngineJob | None = None  # the one install that may run at a time
        self._heic_offered = False  # the offer toast, once per run (A6)
        self.settings_window: SettingsWindow | None = None  # built on first use

        motion = motion_switch(self.args.motion)
        # The language (D3, D3a): the catalog and the layout direction, before any widget or
        # toast text exists. Read at start only: there is no picker in v0.1.
        self._language = i18n.install(self.qapp, settings.language)
        self.window = WheelWindow(
            self.catalog, motion_enabled=motion, high_contrast=system.high_contrast
        )
        self.controller = Controller(
            RawInputMonitor(), ModifierPoller(), self.window, any_source=self.args.any_source
        )
        self.controller.drop_received.connect(self._on_drop)
        # The toasts (U6) wait while the wheel is up: it must be the only window then (C1).
        self.toasts = ToastManager(
            motion_enabled=motion, high_contrast=system.high_contrast, hold=self.window.isVisible
        )
        self.window.hidden.connect(self.toasts.release)
        self.toasts.undo_clicked.connect(self._on_undo)
        self.toasts.show_in_folder_clicked.connect(self._on_show_in_folder)
        self.toasts.details_clicked.connect(self._on_details)
        self.toasts.settings_clicked.connect(self.show_settings)
        self.toasts.closed.connect(self._on_toast_closed)
        self.toasts.install_heic_clicked.connect(self._ask_install_heic)
        if self._instance is not None:
            self._instance.settings_requested.connect(self.show_settings)
        self.window.engine_missing.connect(self._offer_heic)
        self.consent = HeicConsent()
        self.consent.confirmed.connect(self._install_heic)
        self.trust = PluginTrustPrompt()  # phase-3 §6.5: before a plugin is enabled
        self.trust.confirmed.connect(self._enable_plugin)
        # The tray (phase-3 §6.1): built before the settings reach their owners below.
        self.tray = TrayIcon(motion_enabled=motion, light_taskbar=system.light_taskbar)
        self.tray.pause_toggled.connect(self._on_pause_toggled)
        self.tray.settings_requested.connect(self.show_settings)
        self.tray.log_folder_requested.connect(self._on_log_folder_requested)
        self.tray.about_requested.connect(self._on_about_requested)
        self.tray.quit_requested.connect(self.qapp.quit)
        self.tray.alert_clicked.connect(self._on_details)
        self.settings_store.changed.connect(self._apply_settings)
        self._apply_settings(settings, at_start=True)
        self.dispatcher.job_started.connect(self._on_job_started)
        self.dispatcher.job_progress.connect(self._on_job_progress)
        self.dispatcher.job_finished.connect(self._on_job_finished)
        log.info(
            "Morphwheel %s starting (log: %s; fallback output: %s; missing engines: %s)",
            __version__,
            self.log_file,
            fallback,
            ", ".join(sorted(f.value for f in self.missing_engines)) or "none",
        )

    # ----------------------------------------------------------------- lifecycle
    def startup_checks(self) -> int | None:
        """Return an exit code to stop with, or ``None`` to carry on."""
        if not self._is_elevated():
            return None
        log.warning("running elevated: drags from Explorer can't reach this process")
        if self._ask_elevated() == "restart":
            if self._instance is not None:
                self._instance.release()  # the normal instance must be able to take the name
            if self._restart():
                log.info("restarted without elevation; quitting this instance")
                return EXIT_OK
            self._explain_failed_restart()  # phase-3 §6.4: only Quit remains, with an explanation
        return EXIT_ELEVATED

    def start(self) -> None:
        self.pool.start()  # warm the workers while the user is still reaching for a file
        self.controller.start()
        self.tray.show()
        if self._instance is not None:
            self._instance.listen()  # later starts knock here to open the settings
        self._schedule_onboarding()

    def stop(self) -> None:
        if self._instance is not None:
            self._instance.release()
        if self._engine_job is not None:
            self._engine_job.abandoned = True  # a download in flight finishes quietly
            self._engine_job = None
        if self.settings_window is not None:
            self.settings_window.hide()  # flushes a pending slider save
        self.tray.hide()
        self.controller.stop()
        self.toasts.dismiss_all()
        self.pool.shutdown()
        self._language.remove(self.qapp)  # the tests' application outlives this one

    def exec(self) -> int:
        code = self.startup_checks()
        if code is not None:
            return code
        self.start()
        try:
            return int(self.qapp.exec())
        finally:
            self.stop()
            log.info("Morphwheel stopped")

    # ----------------------------------------------------------------- settings
    def _apply_settings(self, settings: Settings, *, at_start: bool = False) -> None:
        """Push the whole value to its owners, at start and after every change. Each owner is
        idempotent, so nothing is diffed here: the one place a new field has to be wired."""
        self.controller.set_trigger_key(settings.trigger_key)  # D8: at the next sample
        self.dispatcher.set_options(settings.converter_options())
        self._set_plugin_prefs(settings.plugins)
        if settings.paused:
            self.controller.pause()
        else:
            self.controller.resume()
        self.window.apply_size(settings.wheel_size)  # U4: waits for the hide if the wheel shows
        self.tray.set_paused(settings.paused)
        self.tray.set_trigger_key(settings.trigger_key)
        # At start the registry was adopted, so only an "on" needs a write (the path is
        # refreshed); an "off" at start would turn Task Manager's Disable into a delete.
        write = settings.start_with_windows or not at_start
        if write and not autostart.sync(settings.start_with_windows):
            log.warning("start with Windows: the Run value couldn't be changed; it stays")

    # ----------------------------------------------------------------- plugins (S6)
    def _set_plugin_prefs(self, prefs: PluginPrefs) -> None:
        """A change of ``enabled`` or ``order`` rebuilds the registry from the last scan; the
        same value is a no-op."""
        if prefs != self.registry.prefs:
            self._rebuild_plugins(build_registry(self._discovery, prefs))

    def rescan_plugins(self) -> None:
        """Read the plugins folder again, on the user's explicit ask (the Plugins page's
        button): a plugin added, removed or replaced reaches the wheel and the workers without
        a restart. Every call replaces the workers, so it is never called on a page show."""
        self._discovery = discover(self.paths.plugins_dir)
        registry = build_registry(self._discovery, self.registry.prefs)
        self._rebuild_plugins(registry, replace_workers=True)

    def _rebuild_plugins(self, registry: Registry, *, replace_workers: bool = False) -> None:
        # The workers first, the catalog second: a drop on a new target can't reach a worker
        # that doesn't know its plugin. A worker respawns before its next task.
        self.registry = registry
        self.pool.reconfigure(registry.specs, force=replace_workers)
        self._refresh_catalog()
        self._push_plugins()

    def _push_plugins(self) -> None:
        if self.settings_window is not None:
            self.settings_window.set_plugins(self.registry, self._discovery.user_dir_error)
        pending = self.trust.plugin_id
        if pending is not None:
            entry = self.registry.entry(pending)
            if entry is None or entry.enabled:
                self.trust.dismiss()  # gone, or enabled meanwhile: nothing left to ask

    def _ask_enable_plugin(self, plugin_id: str) -> None:
        """The trust prompt (phase-3 §6.5) before a plugin's code may run. Never mid-drag."""
        if self.window.isVisible():
            log.info("trust prompt not shown: a drag is in progress")
            return
        entry = self.registry.entry(plugin_id)
        if entry is None or entry.enabled:
            log.info("trust prompt not shown: %r is not a disabled plugin", plugin_id)
            return
        plugin = entry.manifest.plugin
        self.trust.ask(plugin_id, plugin.name, plugin.version, entry.manifest.directory)

    def _enable_plugin(self, plugin_id: str) -> None:
        """The user said Enable: the id joins the trust record; the store tells everyone."""
        entry = self.registry.entry(plugin_id)
        if entry is None or entry.enabled:
            log.info("plugin %r not enabled: gone or already enabled", plugin_id)
            return
        prefs = self.settings_store.settings.plugins
        self.settings_store.update(plugins=replace(prefs, enabled=(*prefs.enabled, plugin_id)))
        log.info("plugin enabled: %s", plugin_id)

    def _open_plugins_folder(self) -> None:
        """Morphwheel's own folder under the profile (§5): created on the way if need be."""
        folder = self.paths.plugins_dir
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            log.warning("couldn't create the plugins folder %s: %s", folder, e.strerror or e)
        if not shell.open_folder(folder):
            log.warning("couldn't open the plugins folder %s", folder)

    # ----------------------------------------------------------------- the conversion flow
    def _on_drop(self, request: DropRequest) -> None:
        # Noted before submit: a job whose files are all skipped finishes inside submit, and
        # job_started (emitted first) must already find the screen and the label.
        screen = QGuiApplication.screenAt(self.window.pos()) or QGuiApplication.primaryScreen()
        target = self.catalog.target(request.target_id)
        name = request.files[0].path.name if request.files else ""
        self._pending = _JobView(screen, target.label if target else "", name)
        self.dispatcher.submit(request)
        self._finish_onboarding()  # after submit: the first drop is the acknowledgement (RD-20)

    def _on_job_started(self, job_id: str, count: int) -> None:
        job = self._jobs[job_id] = replace(self._pending, count=count)
        self.tray.set_working(0, count)
        if count > 1:
            self._show_working(job_id, 0)
        else:  # one file: "working" only when it takes longer than a moment (phase-3 §3)
            model = working_toast(1, job.label, name=job.name)
            self.toasts.show_later(model, WORKING_DELAY_MS, screen=job.screen, key=job_id)

    def _on_job_progress(self, job_id: str, done: int, total: int) -> None:
        self.tray.set_working(done, total)
        if total > 1 and job_id in self._jobs and done < total:
            self._show_working(job_id, done)

    def _show_working(self, job_id: str, done: int) -> None:
        job = self._jobs[job_id]
        self.toasts.show(working_toast(job.count, job.label, done), screen=job.screen, key=job_id)

    def _on_job_finished(self, result: JobResult) -> None:
        job = self._jobs.pop(result.job_id, None)
        self.undo.record(result.job_id, result.outputs)
        model = toast_for(result)
        self.toasts.show(model, screen=job.screen if job else None, key=result.job_id)
        if self.dispatcher.active_jobs == 0:  # the dispatcher drops the job before it emits
            self.tray.clear_working()
        if model.kind is ToastKind.CRITICAL:  # the alert outlives the toast (RD-18): same text
            details = next(a for a in model.actions if a.kind is ActionKind.DETAILS)
            self.tray.add_alert(str(details.payload))

    # ----------------------------------------------------------------- the tray menu
    def _on_pause_toggled(self, paused: bool) -> None:
        self.settings_store.update(paused=paused)  # the store answers through _apply_settings

    def show_settings(self, page: str | None = None) -> None:
        """One window, built on first use, back on the page it was left on unless ``page`` says
        otherwise (the onboarding bubble, S5 file 5). Never while the wheel is up (C1): activating
        another window would end Explorer's drag."""
        if self.window.isVisible():
            log.info("settings window not opened: a drag is in progress")
            return
        self._finish_onboarding()  # the user found the settings: the bubble has done its job
        if self.settings_window is None:
            self.settings_window = SettingsWindow(
                self.settings_store, version=__version__, repository_url=REPOSITORY_URL
            )
            self.settings_window.heic_install_requested.connect(self._ask_install_heic)
            self.settings_window.heic_remove_requested.connect(self._remove_heic)
            self.settings_window.set_heic_state(self._heic_state())
            self.settings_window.plugin_enable_requested.connect(self._ask_enable_plugin)
            self.settings_window.plugins_folder_requested.connect(self._open_plugins_folder)
            self.settings_window.rescan_requested.connect(self.rescan_plugins)
            self._push_plugins()
        if page is not None:
            self.settings_window.select_page(page)
        self.settings_window.open_and_raise()

    def _on_about_requested(self) -> None:
        self.show_settings("about")

    def _on_log_folder_requested(self) -> None:
        if not shell.open_folder(self.paths.logs_dir):
            log.warning("couldn't open the log folder %s", self.paths.logs_dir)

    # ----------------------------------------------------------------- the first run
    def _schedule_onboarding(self) -> None:
        """The bubble (phase-3 §6.3), a moment after the start, until it is acknowledged once.
        An unreadable settings file isn't a first run: its flag is unknown."""
        settings = self.settings_store.settings
        if settings.onboarding_done or self.settings_store.unread:
            return
        self.toasts.show_later(
            onboarding_toast(settings.trigger_key), ONBOARDING_DELAY_MS, key=ONBOARDING_KEY
        )

    def _on_toast_closed(self, key: str) -> None:
        if key == ONBOARDING_KEY:  # Got it, Settings or ✕
            self._finish_onboarding()

    def _finish_onboarding(self) -> None:
        """Take the bubble away, wherever it is, and remember it (once: later calls return)."""
        if self.settings_store.settings.onboarding_done:
            return
        self.settings_store.update(onboarding_done=True)  # first: ``closed`` re-enters here
        self.toasts.dismiss(ONBOARDING_KEY)

    # ----------------------------------------------------------------- the HEIC engine (A6)
    def _heic_state(self) -> Literal["missing", "installing", "installed"]:
        if self._engine_job is not None:
            return "installing"
        return "missing" if FormatId.HEIC in self.missing_engines else "installed"

    def _offer_heic(self) -> None:
        """A drag the engine would have served: offer the download, once per run."""
        if self._heic_offered or FormatId.HEIC not in self.missing_engines:
            return
        self._heic_offered = True
        self.toasts.show(heic_offer_toast(engines.HEIC_WHEEL.size), key=HEIC_TOAST_KEY)

    def _ask_install_heic(self) -> None:
        """Consent first (A6): the file, the size, the source, the licence. Never mid-drag."""
        if self.window.isVisible():
            log.info("HEIC consent not shown: a drag is in progress")
            return
        if self._engine_job is not None:
            log.info("HEIC install already running")
            return
        if FormatId.HEIC not in self.missing_engines:
            log.info("HEIC engine already installed")  # a stale offer toast's button
            return
        self.consent.ask(engines.HEIC_WHEEL.name, engines.HEIC_WHEEL.size)

    def _install_heic(self) -> None:
        if self._engine_job is not None:
            return
        job = _EngineJob(self.paths.engines_dir, self._engine_fetch)
        job.done.connect(self._on_heic_done, Qt.ConnectionType.QueuedConnection)
        self._engine_job = job  # held here, or the result could be lost with the thread
        self._push_heic_state()
        self.toasts.show_later(heic_working_toast(), WORKING_DELAY_MS, key=HEIC_TOAST_KEY)
        job.start()

    def _on_heic_done(self, result: object) -> None:
        self._engine_job = None
        if isinstance(result, Path):
            self._refresh_catalog()
            self.toasts.show(heic_installed_toast(), key=HEIC_TOAST_KEY)
            return
        assert isinstance(result, engines.EngineInstallError)  # the job's contract
        failure = EngineFailure(result.kind)
        log.error("HEIC install failed (%s): %s", failure.value, result)
        self._push_heic_state()
        self.toasts.show(heic_failed_toast(failure, str(result)), key=HEIC_TOAST_KEY)

    def _remove_heic(self) -> None:
        gone = engines.remove_heic(self.paths.engines_dir)
        if not gone:
            log.warning("HEIC engine: files still in use remain until the next start")
        self._refresh_catalog()
        self.toasts.show(heic_removed_toast(leftover=not gone), key=HEIC_TOAST_KEY)

    def _refresh_catalog(self) -> None:
        """An engine or a plugin came or went: the wheel plans with the new catalog from its
        next plan on, the dispatcher resolves new drops against it (a job in flight keeps its
        target), and the workers find an engine that appeared after start-up by themselves."""
        self.missing_engines = engines.missing_engines(self.paths.engines_dir)
        self.catalog = build_catalog(self.registry.targets, self.missing_engines)
        self.window.set_catalog(self.catalog)
        self.dispatcher.set_catalog(self.catalog)
        self._push_heic_state()
        log.info(
            "catalog refreshed: %d plugin target(s) in the arc, missing engines %s",
            len(self.registry.arc_targets),
            sorted(self.missing_engines) or "none",
        )

    def _push_heic_state(self) -> None:
        if self.settings_window is not None:
            self.settings_window.set_heic_state(self._heic_state())

    # ----------------------------------------------------------------- the toast buttons
    def _on_undo(self, job_id: str) -> None:
        outcome = self.undo.undo(job_id)  # D5: only what this job created, only if unchanged
        self.toasts.show(undo_toast(outcome), key=job_id)  # lands on the replaced toast's screen

    def _on_show_in_folder(self, path: object) -> None:
        if isinstance(path, Path) and not shell.reveal_in_explorer(path):
            log.warning("couldn't show %s in Explorer", path)

    def _on_details(self, text: str) -> None:
        """The failure list behind a toast's Details, or a tray alert: one window, reused."""
        if self._details is None:
            self._details = DetailsWindow()
        self._details.show_text(text)

    # ----------------------------------------------------------------- maintenance commands
    def worker_check(self, glyphs: GlyphSet | None = None) -> int:
        """A5a: start the pool, report each worker, exit non-zero if any loaded Qt. The frozen
        build's smoke test, so it also loads the wheel's icons, which need Qt's SVG plugin and the
        bundled files, and fails if one doesn't load (RD-36)."""
        self.pool.start()
        try:
            infos = self.pool.wait_ready()
        finally:
            self.pool.shutdown()
        ok = len(infos) == self.pool.size and not any(i.qt_loaded for i in infos)
        for info in infos:
            line = (
                f"worker {info.index}: pid {info.pid}, {info.executable}, "
                f"qt_loaded={info.qt_loaded}"
            )
            log.info(line)
            print(line)
        broken = (glyphs if glyphs is not None else GlyphSet()).failures()
        icons = "OK" if not broken else "FAILED (" + ", ".join(broken) + ")"
        log.info("wheel icons: %s", icons)
        print(f"wheel icons: {icons}")
        verdict = "OK" if ok else f"FAILED ({len(infos)} of {self.pool.size} ready)"
        if ok and broken:
            verdict = "FAILED (wheel icons)"
        print(f"worker check: {verdict}")
        return EXIT_OK if ok and not broken else EXIT_FAILED


def install_heic(paths: AppPaths) -> int:
    """``--install-heic``: the opt-in download (A6), from the console, with the result printed."""
    try:
        folder = engines.install_heic(paths.engines_dir)
    except engines.EngineInstallError as e:
        print(f"HEIC engine: {e}")
        return EXIT_FAILED
    print(f"HEIC engine installed in {folder}")
    return EXIT_OK


def run(argv: list[str]) -> int:
    """Start Morphwheel and return the process exit code."""
    try:
        args = parse_args(argv[1:])
    except SystemExit as exit_:  # --version / --help (0), or a usage error (2)
        return exit_.code if isinstance(exit_.code, int) else (0 if exit_.code is None else 1)
    paths = app_paths()
    if args.install_heic:
        setup_logging(paths.logs_dir, console=True)
        return install_heic(paths)
    instance: SingleInstance | None = None
    if not args.worker_check:  # one instance per session; the maintenance modes need none
        instance = SingleInstance()
        if not instance.acquire():
            setup_logging(paths.logs_dir, console=args.debug)
            reached = instance.ping()
            log.info("already running: asked it to open the settings (%s)", reached)
            return EXIT_OK
    try:
        app = Application(argv, paths=paths, instance=instance)
        if args.worker_check:
            return app.worker_check()
        return app.exec()
    finally:
        if instance is not None:
            instance.release()  # every exit, the early ones included


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run(sys.argv))
