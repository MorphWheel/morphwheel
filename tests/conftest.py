"""Shared test setup.

Qt runs headless (``offscreen``) unless the caller overrides ``QT_QPA_PLATFORM``. That variable
must be set before pytest-qt creates the QApplication. Tests never touch the real user profile;
they use :func:`app_paths_tmp`.
"""

from __future__ import annotations

import getpass
import os
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from morphwheel.settings.paths import AppPaths, app_paths


@pytest.fixture
def app_paths_tmp(tmp_path: Path) -> AppPaths:
    """Morphwheel's locations, redirected into a per-test temporary directory."""
    return app_paths(
        roaming_base=tmp_path / "roaming",
        local_base=tmp_path / "local",
        downloads=tmp_path / "Downloads",
    )


@pytest.fixture
def lock_directory() -> Iterator[Callable[[Path], None]]:
    """Deny this user the right to add files to a directory (an NTFS deny ACE); restored afterwards.

    Used by the file_ops and worker tests for the read-only-folder rows of phase-4 §6. Seed the
    directory first; the ACE only blocks *new* files.
    """
    user = rf"{os.environ.get('USERDOMAIN', '')}\{getpass.getuser()}"
    locked: list[Path] = []

    def lock(directory: Path) -> None:
        done = subprocess.run(
            ["icacls", str(directory), "/deny", f"{user}:(WD)"],
            capture_output=True,
            text=True,
            check=False,
        )
        if done.returncode != 0:
            pytest.skip(f"icacls can't set a deny ACE here: {done.stderr.strip()}")
        locked.append(directory)

    try:
        yield lock
    finally:
        for directory in locked:
            subprocess.run(
                ["icacls", str(directory), "/remove:d", user], capture_output=True, check=False
            )


@pytest.fixture
def read_only_dir(tmp_path: Path, lock_directory: Callable[[Path], None]) -> Path:
    """An empty directory this user may not add files to."""
    d = tmp_path / "locked"
    d.mkdir()
    lock_directory(d)
    return d
