"""``app.application``: it builds offscreen, the elevated gate, the catalog, and a drop end to end.

The end-to-end test is the S3 exit criterion in one place: a ``DropRequest`` for a real PNG goes
through the dispatcher and a real worker process, a JPG appears beside it, the toast says so, and
Undo knows the new file.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from PIL import Image
from pytestqt.qtbot import QtBot

from morphwheel.app.application import (
    EXIT_ELEVATED,
    EXIT_OK,
    Application,
    build_catalog,
    parse_args,
)
from morphwheel.core.catalog import MORE_SLOT, SLOT_ORDER
from morphwheel.core.formats import FileInfo, FormatId, Sniff
from morphwheel.core.jobs import DropRequest, JobOutcome
from morphwheel.plugins.manifest import builtin_manifest
from morphwheel.settings.paths import AppPaths
from morphwheel.ui.toasts.model import ToastKind

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
    catalog = build_catalog(builtin_manifest(), frozenset({FormatId.HEIC}))
    plan = catalog.plan([FileInfo.from_path(Path("photo.png"))])
    assert plan.ok
    labels = {pos: s.target.label if s.target else None for pos, s in plan.slots.items()}
    assert labels[SLOT_ORDER[0]] == "JPG"
    assert labels[MORE_SLOT] is None
    assert not plan.slots[MORE_SLOT].enabled  # no plugins yet (S6)
    assert plan.slots[SLOT_ORDER[1]].reason is not None  # PNG onto PNG: the source
    heic = catalog.plan([FileInfo.from_path(Path("photo.heic"))])
    assert not heic.ok  # the engine is an opt-in download (A6)
    with_engine = build_catalog(builtin_manifest(), frozenset())
    assert with_engine.plan([FileInfo.from_path(Path("photo.heic"))]).ok


def _teardown(app: Application) -> None:
    app.stop()
    logger = logging.getLogger("morphwheel")
    for handler in [h for h in logger.handlers if getattr(h, "_morphwheel_handler", False)]:
        logger.removeHandler(handler)
        handler.close()


@pytest.fixture
def app(app_paths_tmp: AppPaths) -> Iterator[Application]:
    application = Application(
        ["morphwheel", "--debug"], paths=app_paths_tmp, is_elevated=lambda: False, pool_size=1
    )
    try:
        yield application
    finally:
        _teardown(application)


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
    text = app.log_file.read_text(encoding="utf-8")
    assert "Morphwheel" in text
    assert "fallback output:" in text
    assert app.paths.fallback_output_dir == app_paths_tmp.fallback_output_dir
    assert app.paths.fallback_output_dir.name == "Morphwheel"


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


@pytest.mark.integration
def test_worker_check_reports_qt_free_workers(
    app: Application, capsys: pytest.CaptureFixture[str]
) -> None:
    assert app.worker_check() == EXIT_OK
    out = capsys.readouterr().out
    assert "qt_loaded=False" in out
    assert out.strip().endswith("worker check: OK")
    assert sys.executable.lower() in out.lower()  # from source: python itself runs the workers


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
        _teardown(app)
