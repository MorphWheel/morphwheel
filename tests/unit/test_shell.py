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


def test_reveal_refuses_a_relative_path_and_fails_cleanly_for_a_missing_file(
    tmp_path: Path, opened_folders: list[Path]
) -> None:
    """Opening Explorer for real is a hand check (M2 check 7); here nothing is launched."""
    assert not shell.reveal_in_explorer(Path("photo.jpg"))
    assert opened_folders == []
    # The folder exists but the file doesn't: no PIDL, so the fallback opens the folder.
    assert shell.reveal_in_explorer(tmp_path / "missing.jpg")
    assert opened_folders == [tmp_path]
    # Neither exists: nothing to open.
    assert not shell.reveal_in_explorer(tmp_path / "gone" / "missing.jpg")
    assert opened_folders == [tmp_path]


def test_open_folder_opens_directories_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, opened_folders: list[Path]
) -> None:
    (tmp_path / "photo.jpg").write_bytes(b"x")
    assert not shell.open_folder(tmp_path / "photo.jpg")  # a file: never "opened" (run)
    assert not shell.open_folder(Path("relative"))
    assert not shell.open_folder(tmp_path / "gone")
    assert shell.open_folder(tmp_path)
    assert opened_folders == [tmp_path]

    def refused(p: object) -> None:
        raise OSError("no association")

    monkeypatch.setattr(shell.os, "startfile", refused)
    assert not shell.open_folder(tmp_path)


def test_reveal_never_builds_a_command_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file name is data: it reaches the shell only as a PIDL, never as an argument."""
    seen: list[str] = []

    def fake_pidl(path: str) -> None:
        seen.append(path)
        return None  # "not a shell item": forces the fallback, which must not run anything

    monkeypatch.setattr(shell.w.shell32, "ILCreateFromPathW", fake_pidl)
    monkeypatch.setattr(shell.os, "startfile", lambda p: None)
    nasty = tmp_path / 'a" & calc.exe & "b.jpg'
    assert shell.reveal_in_explorer(nasty)
    assert seen == [str(nasty)]


def test_com_apartment_tolerates_a_multithreaded_thread() -> None:
    """Qt's GUI thread is an STA; a worker thread may be an MTA. ``RPC_E_CHANGED_MODE`` there must
    be swallowed (and ``CoUninitialize`` not called), as the reveal runs from a button click."""
    import threading

    from morphwheel.platform import _win32 as w

    outcome: list[object] = []

    def run() -> None:
        w.ole32.CoInitializeEx(None, 0x0)  # COINIT_MULTITHREADED on this thread
        try:
            with shell._com_apartment():
                outcome.append("entered")
        except OSError as e:
            outcome.append(e)
        finally:
            w.ole32.CoUninitialize()

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(5)
    assert outcome == ["entered"]
