"""Qt application bootstrap (phase-4 §4.6, §9 S2): logging, the startup checks, the controller.

What S2 assembles is the *dev wheel*: raw input, the poller, the controller and the wheel window
with the builtin targets. S3 adds the dispatcher and the workers, S5 the tray, settings, toasts and
the single-instance guard.

Rules:

- **The elevated check runs first** (phase-2 §3.7, phase-3 §6.4). Drag and drop from an
  unelevated Explorer into an elevated window is blocked by UIPI, so an elevated Morphwheel sees
  no drags. The user gets "Restart normally" (``platform.system.restart_unelevated``) or "Quit".
- **Nothing in this module makes Win32 calls that take coordinates before the ``QApplication``
  exists.** Qt switches the process to per-monitor DPI awareness at construction.
- Exit codes: 0 normal; ``EXIT_ELEVATED`` when the app refused to run elevated.

Usage::

    morphwheel [--any-source] [--debug]
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from typing import Literal

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QMessageBox

from morphwheel import __version__
from morphwheel.app.controller import Controller
from morphwheel.core.catalog import Catalog, SlotPos, Target, TargetKind
from morphwheel.core.formats import FormatId
from morphwheel.logs import setup_logging
from morphwheel.platform import system
from morphwheel.platform.modifier_poller import ModifierPoller
from morphwheel.platform.raw_input import RawInputMonitor
from morphwheel.settings.paths import AppPaths, app_paths
from morphwheel.ui.wheel.window import WheelWindow

log = logging.getLogger("morphwheel.app")

EXIT_OK = 0
EXIT_ELEVATED = 3

ElevatedChoice = Literal["restart", "quit"]


def dev_catalog() -> Catalog:
    """The MVP builtin targets (phase-3 §2.2). S3 replaces this with the builtin plugin manifest."""
    f = FormatId
    inputs = frozenset({f.JPEG, f.PNG, f.WEBP, f.AVIF, f.HEIC, f.BMP, f.TIFF, f.GIF})

    def convert(tid: str, label: str, out: FormatId, slot: SlotPos) -> Target:
        return Target(tid, label, TargetKind.CONVERT, out, inputs - {out}, "builtin", True, slot)

    return Catalog.of(
        [
            convert("jpeg", "JPG", f.JPEG, SlotPos.N),
            convert("png", "PNG", f.PNG, SlotPos.NE),
            convert("webp", "WebP", f.WEBP, SlotPos.E),
            convert("avif", "AVIF", f.AVIF, SlotPos.SE),
            Target(
                "compress",
                "Compress",
                TargetKind.COMPRESS,
                None,
                frozenset({f.JPEG, f.PNG, f.WEBP, f.AVIF}),
                "builtin",
                True,
                SlotPos.S,
            ),
            convert("pdf", "PDF", f.PDF, SlotPos.SW),
            convert("ico", "ICO", f.ICO, SlotPos.W),
        ],
        missing_engines={f.HEIC},  # the opt-in engine (A6) arrives in S3
    )


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="morphwheel", description="Morphwheel")
    parser.add_argument("--version", action="version", version=f"Morphwheel {__version__}")
    parser.add_argument(
        "--any-source", action="store_true", help="open the wheel for drags from any window"
    )
    parser.add_argument("--debug", action="store_true", help="verbose log, also on the console")
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
    ) -> None:
        self.args = parse_args(argv[1:])
        self.paths = paths or app_paths()
        self.log_file = setup_logging(
            self.paths.logs_dir,
            level=logging.DEBUG if self.args.debug else logging.INFO,
            console=self.args.debug,
        )
        self._is_elevated = is_elevated
        self._restart = restart
        self._ask_elevated = ask_elevated or self._elevated_dialog
        self._explain_failed_restart = explain_failed_restart or self._failed_restart_dialog
        existing = QApplication.instance()
        self.qapp = existing if isinstance(existing, QApplication) else QApplication(list(argv))
        self.qapp.setApplicationName("Morphwheel")
        self.qapp.setApplicationVersion(__version__)
        self.qapp.setQuitOnLastWindowClosed(False)  # the wheel hides; the app lives in the tray
        self.window = WheelWindow(dev_catalog())
        self.controller = Controller(
            RawInputMonitor(), ModifierPoller(), self.window, any_source=self.args.any_source
        )
        log.info("Morphwheel %s starting (log: %s)", __version__, self.log_file)

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
        self.controller.start()

    def stop(self) -> None:
        self.controller.stop()

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


def run(argv: list[str]) -> int:
    """Start Morphwheel and return the process exit code."""
    try:
        app = Application(argv)
    except SystemExit as exit_:  # --version / --help (0), or a usage error (2)
        return exit_.code if isinstance(exit_.code, int) else (0 if exit_.code is None else 1)
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run(sys.argv))
