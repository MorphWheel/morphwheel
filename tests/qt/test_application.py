"""``app.application``: it builds offscreen, the elevated gate, and the dev catalog."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from morphwheel.app.application import EXIT_ELEVATED, EXIT_OK, Application, dev_catalog, parse_args
from morphwheel.core.catalog import MORE_SLOT, SLOT_ORDER
from morphwheel.core.formats import FileInfo, FormatId
from morphwheel.settings.paths import AppPaths

pytestmark = pytest.mark.usefixtures("qapp")


def test_parse_args_and_version() -> None:
    args = parse_args(["--any-source", "--debug"])
    assert args.any_source
    assert args.debug
    assert not parse_args([]).any_source
    with pytest.raises(SystemExit) as exit_:
        parse_args(["--version"])
    assert exit_.value.code == 0


def test_dev_catalog_fills_seven_slots_and_leaves_more_to_plugins() -> None:
    plan = dev_catalog().plan([FileInfo.from_path(Path("photo.png"))])
    assert plan.ok
    labels = {pos: s.target.label if s.target else None for pos, s in plan.slots.items()}
    assert labels[SLOT_ORDER[0]] == "JPG"
    assert labels[MORE_SLOT] is None
    assert not plan.slots[MORE_SLOT].enabled  # no plugins yet (S6)
    heic = dev_catalog().plan([FileInfo.from_path(Path("photo.heic"))])
    assert not heic.ok  # the engine is an opt-in download (A6)
    assert plan.slots[SLOT_ORDER[1]].reason is not None  # PNG onto PNG: the source


def _teardown(app: Application) -> None:
    app.stop()
    logger = logging.getLogger("morphwheel")
    for handler in [h for h in logger.handlers if getattr(h, "_morphwheel_handler", False)]:
        logger.removeHandler(handler)
        handler.close()


def test_builds_offscreen_and_logs_to_the_app_paths(app_paths_tmp: AppPaths) -> None:
    app = Application(["morphwheel", "--debug"], paths=app_paths_tmp, is_elevated=lambda: False)
    try:
        assert app.log_file.parent == app_paths_tmp.logs_dir
        assert not app.qapp.quitOnLastWindowClosed()
        assert not app.window.isVisible()
        assert app.startup_checks() is None
        app.start()
        app.start()  # idempotent
        assert app.log_file.read_text(encoding="utf-8").count("Morphwheel") >= 1
    finally:
        _teardown(app)


@pytest.mark.parametrize(
    ("choice", "restart_ok", "code"),
    [("quit", True, EXIT_ELEVATED), ("restart", False, EXIT_ELEVATED), ("restart", True, EXIT_OK)],
)
def test_elevated_gate(app_paths_tmp: AppPaths, choice: str, restart_ok: bool, code: int) -> None:
    asked: list[str] = []

    def ask() -> str:
        asked.append("asked")
        return choice

    def explain() -> None:
        asked.append("explained")

    app = Application(
        ["morphwheel"],
        paths=app_paths_tmp,
        is_elevated=lambda: True,
        restart=lambda: restart_ok,
        ask_elevated=ask,  # type: ignore[arg-type]
        explain_failed_restart=explain,
    )
    try:
        assert app.startup_checks() == code
        expected = ["asked", "explained"] if choice == "restart" and not restart_ok else ["asked"]
        assert asked == expected
        asked.clear()
        assert app.exec() == code  # exec stops at the gate: no event loop is entered
        assert not app.window.isVisible()
    finally:
        _teardown(app)
    assert FormatId.HEIC in dev_catalog().missing_engines
