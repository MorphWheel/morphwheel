"""``platform.shell``: recycling refuses what has no Recycle Bin.

A real recycle of a real file is a manual check (phase-4 §6, D5): the tests never put anything in
the user's Recycle Bin. They prove the refusals and the shape of the call.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

if sys.platform != "win32":  # pragma: no cover
    pytest.skip("Win32 only", allow_module_level=True)

from morphwheel.platform import shell


def test_recycle_bin_detection(tmp_path: Path) -> None:
    assert shell.has_recycle_bin(tmp_path)  # the temp folder is on a fixed local drive
    assert not shell.has_recycle_bin(Path(r"\\server\share\photo.jpg"))
    assert not shell.has_recycle_bin(Path("relative/photo.jpg"))


def test_recycle_refuses_without_touching(tmp_path: Path) -> None:
    assert not shell.recycle(Path(r"\\server\share\photo.jpg"))
    assert not shell.recycle(tmp_path / "missing.jpg")
    assert not shell.recycle(tmp_path)  # a directory, not a file
    assert not shell.recycle(Path("photo.jpg"))  # relative
