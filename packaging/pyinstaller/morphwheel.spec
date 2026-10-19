# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Morphwheel (phase-4 §8): onedir, no UPX, version resource.

S0: ENTRY is the drag probe, which measures the frozen runtime (worker cold start, idle memory, build
size) and is used for the antivirus scan. S2 switches ENTRY to ``src/morphwheel/__main__.py``. S7
finalizes the spec (icon, builtin plugin data, release naming).

Build from the repo root::

    .venv\\Scripts\\pyinstaller.exe packaging\\pyinstaller\\morphwheel.spec --noconfirm ^
        --distpath packaging\\output\\dist --workpath packaging\\output\\build
"""

from pathlib import Path

HERE = Path(SPECPATH).resolve()  # noqa: F821 - SPECPATH is injected by PyInstaller
ROOT = HERE.parents[1]

ENTRY = ROOT / "tools" / "drag_probe.py"
NAME = "drag_probe"
CONSOLE = True  # the probe prints its measurements; the app (S2+) is windowed

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

a = Analysis(  # noqa: F821
    [str(ENTRY)],
    pathex=[str(ROOT / "src")],
    hiddenimports=["PIL.Image"],  # imported by name in the probe's workers
    excludes=EXCLUDES,
    noarchive=False,
)

# Native files Morphwheel never uses (S0 audit, ~28 MB). The wheel paints with QPainter's raster
# engine, images go through Pillow, and Qt makes no TLS connections. Python's own OpenSSL
# (libssl/libcrypto-3-x64) stays, because the opt-in HEIC download (A6) uses urllib over HTTPS.
DROP_FILES = {"opengl32sw.dll", "libcrypto-3.dll", "libssl-3.dll", "qdirect2d.dll"}
DROP_DIRS = ("plugins/tls/", "plugins/imageformats/", "plugins/generic/", "plugins/networkinformation/")


def _keep(dest: str) -> bool:
    dest = dest.replace("\\", "/")
    return dest.rsplit("/", 1)[-1].lower() not in DROP_FILES and not any(d in dest for d in DROP_DIRS)


a.binaries = [b for b in a.binaries if _keep(b[0])]

pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    console=CONSOLE,
    upx=False,
    version=str(HERE / "file_version_info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name=NAME)  # noqa: F821
