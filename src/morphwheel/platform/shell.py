"""The Recycle Bin (phase-4 §2, §4.4; decision D5). No Qt.

Rules:

- **Recycle, never delete.** ``recycle`` uses ``SHFileOperationW`` with ``FOF_ALLOWUNDO`` and no
  confirmation. On a location without a Recycle Bin (a network share, a removable drive, a
  non-fixed volume) the shell would silently delete for good, so ``recycle`` refuses those first:
  it only ever acts on a fixed local drive. The undo registry (``engine.undo``) reports a refusal
  as "not undone".
- **One file per call.** The caller has already checked the file is the one it created.

The Downloads folder (the fallback output location, phase-4 §5) comes from ``platformdirs`` in
``settings.paths``, not from here.
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import byref
from ctypes import wintypes as wt
from pathlib import Path

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
