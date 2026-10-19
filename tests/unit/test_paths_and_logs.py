"""Tests for ``settings.paths`` and ``logs``."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from morphwheel import logs
from morphwheel.settings.paths import APP_NAME, AppPaths


def test_paths_are_redirected_and_nothing_is_created(
    app_paths_tmp: AppPaths, tmp_path: Path
) -> None:
    assert app_paths_tmp.config_dir == tmp_path / "roaming" / APP_NAME
    assert app_paths_tmp.settings_file.name == "settings.toml"
    assert app_paths_tmp.plugins_dir.parent == app_paths_tmp.config_dir
    assert app_paths_tmp.logs_dir == tmp_path / "local" / APP_NAME / "logs"
    assert app_paths_tmp.engines_dir.parent == app_paths_tmp.data_dir
    assert not app_paths_tmp.config_dir.exists()
    assert not app_paths_tmp.data_dir.exists()


def test_setup_logging_is_idempotent_and_writes(app_paths_tmp: AppPaths) -> None:
    log_file = logs.setup_logging(app_paths_tmp.logs_dir)
    logs.setup_logging(app_paths_tmp.logs_dir)  # second call replaces, doesn't duplicate

    logger = logging.getLogger(logs.LOGGER_NAME)
    ours = [h for h in logger.handlers if getattr(h, "_morphwheel_handler", False)]
    assert len(ours) == 1

    logger.info("hello")
    for handler in ours:
        handler.flush()
    assert "hello" in log_file.read_text(encoding="utf-8")

    for handler in ours:  # release the file so tmp_path can be cleaned on Windows
        logger.removeHandler(handler)
        handler.close()


def test_timed_warns_only_when_over_budget(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("morphwheel.test")
    logger.propagate = True
    with caplog.at_level(logging.DEBUG, logger="morphwheel.test"):
        with logs.timed(logger, "fast", budget_ms=10_000):
            pass
        with logs.timed(logger, "slow", budget_ms=-1):
            pass

    levels = {r.getMessage().split()[0]: r.levelno for r in caplog.records}
    assert levels["fast"] == logging.DEBUG
    assert levels["slow"] == logging.WARNING
