"""The license texts the frozen app ships (S7; the S0 audit found none in the bundle).

Collected at build time from the installed distributions of the runtime dependencies (their
``dist-info`` license files) plus Python's own ``LICENSE.txt`` and the texts under
``packaging/licenses/`` that a wheel doesn't carry: the ``*.txt`` at its top are Qt's (LGPL-3.0 and
GPL-3.0: the PySide6 wheels ship only the commercial reference file), and each subfolder is a
component of its own (``aom/``: the AV1 encoder inside Pillow's libavif, whose texts Pillow's
license file omits). The spec adds the result to the bundle as ``licenses/<name>/<file>``;
``THIRD_PARTY_NOTICES.md`` is the human summary.

Qt-free and importable by the spec (``packaging/pyinstaller`` put on ``sys.path`` for the import,
then taken off) and by a test.
"""

from __future__ import annotations

import re
import sys
from importlib import metadata
from pathlib import Path

RUNTIME_DISTRIBUTIONS = ("PySide6_Essentials", "shiboken6", "Pillow", "platformdirs", "tomli_w")
QT_DISTRIBUTIONS = ("PySide6_Essentials", "shiboken6")  # LGPL-3.0: the text is not in the wheels
_LICENSE_FILE = re.compile(r"(licen[cs]e|copying|notice|authors)", re.IGNORECASE)
_TEXT_SUFFIXES = {"", ".txt", ".md", ".rst"}
EXTRA_TEXTS = Path(__file__).resolve().parents[1] / "licenses"  # packaging/licenses/


def _normalised(name: str) -> str:
    """``tomli_w`` and ``Pillow`` as one style: lowercase, hyphens (PEP 503)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _is_license_text(name: str) -> bool:
    """A license, notice or authors file in a text form; not the commercial-reference stub Qt's
    wheels carry (it grants nothing and would sit beside the real LGPL text)."""
    if name.startswith("LicenseRef-"):
        return False
    return bool(_LICENSE_FILE.search(name)) and Path(name).suffix.lower() in _TEXT_SUFFIXES


class LicenseError(RuntimeError):
    """A dependency without a license text: the build must not ship without one."""


def license_files() -> list[tuple[Path, str]]:
    """``(source path, destination folder)`` pairs for every text, destination relative to
    ``licenses/``. Raises if a runtime dependency has no license file at all."""
    found: list[tuple[Path, str]] = []
    for name in RUNTIME_DISTRIBUTIONS:
        dist = metadata.distribution(name)
        folder = f"{_normalised(dist.metadata['Name'])}-{dist.version}"
        files = [
            Path(str(dist.locate_file(f)))
            for f in dist.files or []
            if _is_license_text(Path(str(f)).name)
        ]
        files = [f for f in files if f.is_file()]
        if not files and name not in QT_DISTRIBUTIONS:  # Qt's text comes from packaging/licenses/
            raise LicenseError(f"{name} {dist.version} ships no license file")
        found += [(f, folder) for f in files]
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise LicenseError(f"Python's LICENSE.txt not found at {python_license}")
    found.append((python_license, f"Python-{sys.version_info.major}.{sys.version_info.minor}"))
    qt_texts = sorted(EXTRA_TEXTS.glob("*.txt")) if EXTRA_TEXTS.is_dir() else []
    if not qt_texts:  # the test fails on this; the build says it, so a measuring build can run
        print(f"licenses: no Qt texts under {EXTRA_TEXTS}; the bundle must not ship without them")
    found += [(p, "Qt") for p in qt_texts]
    if EXTRA_TEXTS.is_dir():
        for folder in sorted(p for p in EXTRA_TEXTS.iterdir() if p.is_dir()):
            texts = sorted(folder.glob("*.txt"))
            if not texts:
                raise LicenseError(f"{folder} holds no .txt license text")
            found += [(p, folder.name) for p in texts]
    return found


def datas() -> list[tuple[str, str]]:
    """PyInstaller ``datas`` entries: each text under ``licenses/<folder>/``."""
    return [(str(src), f"licenses/{folder}") for src, folder in license_files()]
