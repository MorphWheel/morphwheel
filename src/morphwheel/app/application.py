"""Qt application bootstrap (phase-4 §4.6, §9 S2 and S3): logging, the startup checks, the wiring.

The composition root (R4): the only module that knows every layer. S2 assembled the dev wheel; S3
adds the engine: the builtin manifest and the engine registry build the catalog, a ``WorkerPool``
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
    morphwheel --worker-check        # start the workers, report their executable and Qt state
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QGuiApplication, QScreen
from PySide6.QtWidgets import QApplication, QMessageBox

from morphwheel import __version__
from morphwheel.app.controller import Controller
from morphwheel.core.catalog import Catalog
from morphwheel.core.formats import FormatId
from morphwheel.core.jobs import DropRequest, JobResult
from morphwheel.engine import engines
from morphwheel.engine.dispatcher import JobDispatcher
from morphwheel.engine.undo import UndoRegistry
from morphwheel.engine.worker_pool import WorkerPool, default_worker_executable
from morphwheel.logs import setup_logging
from morphwheel.platform import shell, system
from morphwheel.platform.modifier_poller import ModifierPoller
from morphwheel.platform.raw_input import RawInputMonitor
from morphwheel.plugins.loader import PluginSpec
from morphwheel.plugins.manifest import Manifest, builtin_manifest
from morphwheel.settings.paths import AppPaths, app_paths
from morphwheel.ui.toasts.manager import ToastManager
from morphwheel.ui.toasts.model import toast_for, working_toast
from morphwheel.ui.wheel.window import WheelWindow

log = logging.getLogger("morphwheel.app")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_ELEVATED = 3

ElevatedChoice = Literal["restart", "quit"]


@dataclass(frozen=True)
class _JobView:
    """What the toasts need to know about a running job; the dispatcher owns the rest."""

    screen: QScreen | None
    label: str
    count: int


def build_catalog(manifest: Manifest, missing: frozenset[FormatId]) -> Catalog:
    """The wheel's targets: the builtin manifest (S6 adds user plugins) and the engine registry."""
    return Catalog.of(manifest.targets, missing_engines=missing)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="morphwheel", description="Morphwheel")
    parser.add_argument("--version", action="version", version=f"Morphwheel {__version__}")
    parser.add_argument(
        "--any-source", action="store_true", help="open the wheel for drags from any window"
    )
    parser.add_argument("--debug", action="store_true", help="verbose log, also on the console")
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
        pool_size: int = 2,
    ) -> None:
        self.args = parse_args(argv[1:])
        self.paths = paths or app_paths()
        level = logging.DEBUG if self.args.debug else logging.INFO
        self.log_file = setup_logging(self.paths.logs_dir, level=level, console=self.args.debug)
        self._is_elevated = is_elevated
        self._restart = restart
        self._ask_elevated = ask_elevated or self._elevated_dialog
        self._explain_failed_restart = explain_failed_restart or self._failed_restart_dialog
        existing = QApplication.instance()
        self.qapp = existing if isinstance(existing, QApplication) else QApplication(list(argv))
        self.qapp.setApplicationName("Morphwheel")
        self.qapp.setApplicationVersion(__version__)
        self.qapp.setQuitOnLastWindowClosed(False)  # the wheel hides; the app lives in the tray

        # The catalog: what the wheel offers (phase-3 §2.2) and which engine is missing (A6).
        self.manifest = builtin_manifest()
        self.missing_engines = engines.missing_engines(self.paths.engines_dir)
        self.catalog = build_catalog(self.manifest, self.missing_engines)

        # The engine: Qt-free workers, the dispatcher on top, undo and toasts around it.
        self.pool = WorkerPool(
            size=pool_size,
            plugins=[PluginSpec(self.manifest.plugin.id, self.manifest.plugin.entry, None)],
            engines_dir=self.paths.engines_dir,
            log_level=level,
            executable=default_worker_executable(),
        )
        fallback = self.paths.fallback_output_dir
        self.dispatcher = JobDispatcher(self.pool, self.catalog, fallback_dir=fallback)
        self.undo = UndoRegistry(shell.recycle)
        self.toasts = ToastManager()
        self._pending: tuple[QScreen | None, str] = (None, "")  # the last drop's screen and label
        self._jobs: dict[str, _JobView] = {}

        self.window = WheelWindow(self.catalog)
        self.controller = Controller(
            RawInputMonitor(), ModifierPoller(), self.window, any_source=self.args.any_source
        )
        self.controller.drop_received.connect(self._on_drop)
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
            if self._restart():
                log.info("restarted without elevation; quitting this instance")
                return EXIT_OK
            self._explain_failed_restart()  # phase-3 §6.4: only Quit remains, with an explanation
        return EXIT_ELEVATED

    def start(self) -> None:
        self.pool.start()  # warm the workers while the user is still reaching for a file
        self.controller.start()

    def stop(self) -> None:
        self.controller.stop()
        self.toasts.dismiss_all()
        self.pool.shutdown()

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

    # ----------------------------------------------------------------- the conversion flow
    def _on_drop(self, request: DropRequest) -> None:
        # Noted before submit: a job whose files are all skipped finishes inside submit, and
        # job_started (emitted first) must already find the screen and the label.
        screen = QGuiApplication.screenAt(self.window.pos()) or QGuiApplication.primaryScreen()
        target = self.catalog.target(request.target_id)
        self._pending = (screen, target.label if target else "")
        self.dispatcher.submit(request)

    def _on_job_started(self, job_id: str, count: int) -> None:
        screen, label = self._pending
        self._jobs[job_id] = _JobView(screen, label, count)
        if count > 1:
            self._show_working(job_id, 0)

    def _on_job_progress(self, job_id: str, done: int, total: int) -> None:
        if total > 1 and job_id in self._jobs and done < total:
            self._show_working(job_id, done)

    def _show_working(self, job_id: str, done: int) -> None:
        job = self._jobs[job_id]
        self.toasts.show(working_toast(job.count, job.label, done), screen=job.screen, key=job_id)

    def _on_job_finished(self, result: JobResult) -> None:
        job = self._jobs.pop(result.job_id, None)
        self.undo.record(result.job_id, result.outputs)
        self.toasts.show(toast_for(result), screen=job.screen if job else None, key=result.job_id)

    # ----------------------------------------------------------------- maintenance commands
    def worker_check(self) -> int:
        """A5a: start the pool, report each worker, exit non-zero if any loaded Qt."""
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
        verdict = "OK" if ok else f"FAILED ({len(infos)} of {self.pool.size} ready)"
        print(f"worker check: {verdict}")
        return EXIT_OK if ok else EXIT_FAILED

    # ----------------------------------------------------------------- dialogs
    def _elevated_dialog(self) -> ElevatedChoice:
        box = QMessageBox(QMessageBox.Icon.Warning, "Morphwheel", "")
        box.setText(
            QCoreApplication.translate("Elevated", "Morphwheel is running as administrator")
        )
        box.setInformativeText(
            QCoreApplication.translate(
                "Elevated", "Dragging from File Explorer won't work in this mode."
            )
        )
        restart = box.addButton(
            QCoreApplication.translate("Elevated", "Restart normally"),
            QMessageBox.ButtonRole.AcceptRole,
        )
        box.addButton(
            QCoreApplication.translate("Elevated", "Quit"), QMessageBox.ButtonRole.RejectRole
        )
        box.exec()
        return "restart" if box.clickedButton() is restart else "quit"

    @staticmethod
    def _failed_restart_dialog() -> None:
        QMessageBox.critical(
            None,
            "Morphwheel",
            QCoreApplication.translate(
                "Elevated",
                "Couldn't start a normal instance. Please quit and start Morphwheel "
                "from the Start menu.",
            ),
        )


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
    if args.install_heic:
        paths = app_paths()
        setup_logging(paths.logs_dir, console=True)
        return install_heic(paths)
    app = Application(argv)
    if args.worker_check:
        return app.worker_check()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run(sys.argv))
