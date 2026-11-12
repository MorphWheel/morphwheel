"""The Recycle Bin (phase-4 §2, §4.4; decision D5). No Qt.

Rules:

- **Recycle, never delete.** ``recycle`` uses ``SHFileOperationW`` with ``FOF_ALLOWUNDO`` and no
  confirmation. On a location without a Recycle Bin (a network share, a removable drive, a
  non-fixed volume) the shell would silently delete for good, so ``recycle`` refuses those first:
  it only ever acts on a fixed local drive. The undo registry (``engine.undo``) reports a refusal
  as "not undone".
- **One file per call.** The caller has already checked the file is the one it created.
- **Reveal, never run.** ``reveal_in_explorer`` selects a file in Explorer through a PIDL
  (``SHOpenFolderAndSelectItems``), never through a command line built from the path, so a file
  name can't become an argument. The fallback opens the *folder* with the shell's "open" verb,
  and only when it is a folder.

The Downloads folder (the fallback output location, phase-4 §5) comes from ``platformdirs`` in
``settings.paths``, not from here.
"""

from __future__ import annotations

import contextlib
import ctypes
import logging
import os
from collections.abc import Iterator
from ctypes import byref
from ctypes import wintypes as wt
from pathlib import Path

from morphwheel.logs import timed
from morphwheel.platform import _win32 as w

log = logging.getLogger("morphwheel.platform.shell")


def has_recycle_bin(path: Path) -> bool:
    """Only a fixed local drive has a Recycle Bin we can trust. UNC and removable media don't."""
    drive = path.drive  # "C:" or "\\\\server\\share"
    if not drive or drive.startswith("\\\\"):
        return False
    return int(w.kernel32.GetDriveTypeW(drive + "\\")) == w.DRIVE_FIXED


def recycle(path: Path) -> bool:
    """Send ``path`` to the Recycle Bin. ``False`` when refused, or when the shell fails."""
    path = Path(path)
    if not path.is_absolute() or not has_recycle_bin(path):
        log.info("recycle refused for %s: no Recycle Bin there", path)
        return False
    if not path.is_file():
        return False
    op = w.SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = w.FO_DELETE
    buffer = ctypes.create_unicode_buffer(str(path) + "\0")  # double NUL: a one-item list
    op.pFrom = ctypes.cast(buffer, wt.LPCWSTR)
    op.pTo = None
    op.fFlags = w.FOF_ALLOWUNDO | w.FOF_NOCONFIRMATION | w.FOF_SILENT | w.FOF_NOERRORUI
    result = int(w.shell32.SHFileOperationW(byref(op)))
    if result != 0 or op.fAnyOperationsAborted:
        log.warning("recycle of %s failed: shell error %#x", path.name, result)
        return False
    return not path.exists()


# --------------------------------------------------------------------------- Explorer
def reveal_in_explorer(path: Path) -> bool:
    """Open the file's folder in Explorer with the file selected (phase-4 §4.3).

    ``False`` when the path is relative or gone, or when both the shell call and the fallback
    (opening the folder) fail. Talks to the Explorer process synchronously: it can take a moment.
    """
    path = Path(path)
    if not path.is_absolute():
        return False
    with timed(log, f"reveal {path.name}"):
        try:
            if _select_in_explorer(path):
                return True
        except OSError as e:  # COM itself failed: a button click must not raise
            log.warning("couldn't reveal %s: %s", path.name, e)
        return open_folder(path.parent)


def open_folder(folder: Path) -> bool:
    """Open an existing folder in Explorer (the shell's "open" verb on a directory, never on a
    file). ``False`` for anything that isn't an absolute, existing directory, or when the shell
    refuses."""
    folder = Path(folder)
    if not folder.is_absolute() or not folder.is_dir():
        return False
    try:
        os.startfile(folder)
    except OSError as e:
        log.warning("couldn't open %s: %s", folder, e)
        return False
    return True


def _select_in_explorer(path: Path) -> bool:
    with _com_apartment():
        pidl = w.shell32.ILCreateFromPathW(str(path))
        if not pidl:
            return False  # the file is gone, or the path isn't a shell item
        try:
            w.shell32.SHOpenFolderAndSelectItems(pidl, 0, None, 0)
        except OSError as e:  # ctypes raises for a failed HRESULT
            log.warning("SHOpenFolderAndSelectItems failed for %s: %s", path.name, e)
            return False
        finally:
            w.shell32.ILFree(pidl)
    return True


@contextlib.contextmanager
def _com_apartment() -> Iterator[None]:
    """COM on this thread for the duration. Qt's GUI thread is already an STA (``OleInitialize``),
    so the call returns ``S_FALSE`` and is balanced; ``RPC_E_CHANGED_MODE`` means the thread is an
    MTA, in which case nothing is initialized and nothing is uninitialized."""
    try:
        w.ole32.CoInitializeEx(None, w.COINIT_APARTMENTTHREADED)
    except OSError as e:
        if e.winerror != w.RPC_E_CHANGED_MODE:
            raise
        yield
        return
    try:
        yield
    finally:
        w.ole32.CoUninitialize()
