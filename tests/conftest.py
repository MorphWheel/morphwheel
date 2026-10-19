"""Shared test setup.

Qt runs headless (``offscreen``) unless the caller overrides ``QT_QPA_PLATFORM``. That variable
must be set before pytest-qt creates the QApplication. Tests never touch the real user profile;
they use :func:`app_paths_tmp`.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from morphwheel.settings.paths import AppPaths, app_paths


@pytest.fixture
def app_paths_tmp(tmp_path: Path) -> AppPaths:
    """Morphwheel's locations, redirected into a per-test temporary directory."""
    return app_paths(roaming_base=tmp_path / "roaming", local_base=tmp_path / "local")
