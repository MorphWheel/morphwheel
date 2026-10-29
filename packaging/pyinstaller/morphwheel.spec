# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Morphwheel (phase-4 §8): onedir, no UPX, version resource, two executables.

- ``morphwheel.exe``: the GUI, windowed, from ``src/morphwheel/__main__.py``.
- ``morphwheel-worker.exe`` (decision A5a): the Qt-free worker, from ``worker_entry.py``, built from
  its own Analysis that excludes PySide6, so PyInstaller's PySide6 runtime hook never runs in a
  worker (S0 finding 1). Both share one ``_internal`` folder.
- The builtin plugin's ``plugin.toml`` ships as a data file beside the code (read by path, R5).

S0 built the drag probe from this spec; the probe now runs from source only. S7 finalizes the spec
(icon, release naming, license texts).

Build from the repo root::

    .venv\\Scripts\\pyinstaller.exe packaging\\pyinstaller\\morphwheel.spec --noconfirm ^
        --distpath packaging\\output\\dist --workpath packaging\\output\\build

Then check the workers in the frozen build (A5a): ``dist\\morphwheel\\morphwheel.exe --worker-check``
writes one line per worker to ``%LOCALAPPDATA%\\Morphwheel\\logs\\morphwheel.log`` with the worker's
executable and ``qt_loaded``, and exits 0 only when every worker came up Qt-free.
"""

import os
import sys
from pathlib import Path

HERE = Path(SPECPATH).resolve()  # noqa: F821 - SPECPATH is injected by PyInstaller
ROOT = HERE.parents[1]
SRC = ROOT / "src"

GUI_ENTRY = SRC / "morphwheel" / "__main__.py"
WORKER_ENTRY = HERE / "worker_entry.py"
NAME = "morphwheel"
WORKER_NAME = "morphwheel-worker"
VERSION_FILE = str(HERE / "file_version_info.txt")

EXCLUDES = [
    # Decision A6: pillow-heif wheels are GPLv2 (x265). It must never be bundled.
    "pillow_heif",
    # Qt modules Morphwheel doesn't use (keeps the build small; revisit if a sprint needs one).
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQuickControls2",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtDesigner",
    "PySide6.QtUiTools",
    "PySide6.QtHelp",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtXml",
    "PySide6.QtConcurrent",
    "PySide6.QtPrintSupport",
    "PySide6.QtDBus",
    "tkinter",
]
# The worker must not contain Qt at all (R2, A5a).
WORKER_EXCLUDES = [*EXCLUDES, "PySide6", "shiboken6"]

DATAS = [
    (
        str(SRC / "morphwheel" / "builtin" / "pillow_images" / "plugin.toml"),
        "morphwheel/builtin/pillow_images",
    )
]

gui = Analysis(  # noqa: F821
    [str(GUI_ENTRY)],
    pathex=[str(SRC)],
    datas=DATAS,
    excludes=EXCLUDES,
    noarchive=False,
)
worker = Analysis(  # noqa: F821
    [str(WORKER_ENTRY)],
    pathex=[str(SRC)],
    excludes=WORKER_EXCLUDES,
    noarchive=False,
)

# Native files Morphwheel never uses (S0 audit, ~28 MB). The wheel paints with QPainter's raster
# engine, images go through Pillow, and Qt makes no TLS connections. The "-3-x64" OpenSSL pair is
# whatever copy PyInstaller found on PATH for Qt's TLS backend (Git's MinGW build on the dev box),
# and nothing else imports it.
DROP_FILES = {"opengl32sw.dll", "libcrypto-3-x64.dll", "libssl-3-x64.dll", "qdirect2d.dll"}
DROP_DIRS = ("plugins/tls/", "plugins/imageformats/", "plugins/generic/", "plugins/networkinformation/")

# Python's own OpenSSL must stay: the frozen _ssl.pyd and _hashlib.pyd import exactly these, and the
# opt-in HEIC download (A6) uses urllib over HTTPS. Other copies with the same names are on PATH, so
# the build also checks that they come from this interpreter (RF-1).
PYTHON_OPENSSL = ("libcrypto-3.dll", "libssl-3.dll")
PYTHON_DLLS = os.path.normcase(os.path.realpath(os.path.join(sys.base_prefix, "DLLs")))


def _name(dest: str) -> str:
    return dest.replace("\\", "/").rsplit("/", 1)[-1].lower()


def _keep(dest: str) -> bool:
    dest = dest.replace("\\", "/")
    return _name(dest) not in DROP_FILES and not any(d in dest for d in DROP_DIRS)


gui.binaries = [b for b in gui.binaries if _keep(b[0])]
worker.binaries = [b for b in worker.binaries if _keep(b[0])]

for dll in PYTHON_OPENSSL:
    sources = [src for dest, src, _ in gui.binaries if _name(dest) == dll]
    if [os.path.normcase(os.path.realpath(os.path.dirname(s))) for s in sources] != [PYTHON_DLLS]:
        raise SystemExit(f"morphwheel.spec: bundle {dll} once, from {PYTHON_DLLS}; got {sources}")

# The worker's own analysis must be Qt-free before anything is built (R2, A5a).
qt_in_worker = sorted(
    {m for m in worker.pure.filenames() if m.split(".")[0] in ("PySide6", "shiboken6")}
    if hasattr(worker.pure, "filenames")
    else {name for name, _, _ in worker.pure if name.split(".")[0] in ("PySide6", "shiboken6")}
)
if qt_in_worker:
    raise SystemExit(f"morphwheel.spec: the worker analysis pulled in Qt: {qt_in_worker[:5]}")

gui_pyz = PYZ(gui.pure)  # noqa: F821
worker_pyz = PYZ(worker.pure)  # noqa: F821

gui_exe = EXE(  # noqa: F821
    gui_pyz,
    gui.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    console=False,
    upx=False,
    version=VERSION_FILE,
)
worker_exe = EXE(  # noqa: F821
    worker_pyz,
    worker.scripts,
    [],
    exclude_binaries=True,
    name=WORKER_NAME,
    console=False,
    upx=False,
    version=VERSION_FILE,
)
coll = COLLECT(  # noqa: F821
    gui_exe,
    gui.binaries,
    gui.datas,
    worker_exe,
    worker.binaries,
    worker.datas,
    upx=False,
    name=NAME,
)
