"""Render the app icon assets from ``morphwheel.ui.icon`` (S7).

Writes, under ``assets/icon/``:

- ``morphwheel.ico``: the sizes Windows asks for, each painted at its own size (no downscaling),
  for the executables' resources and the installer;
- ``morphwheel.svg``: the master, from the same constants;
- ``morphwheel-256.png``: for the README and the repository.

Run from the repo root::

    .venv\\Scripts\\python.exe tools\\make_icon.py

The files are committed; this tool is run again only when the mark changes. ``--check`` renders
to memory and exits 1 if the committed files differ in content (the SVG as text, the images as
pixels); it is for the developer's machine, since rasterizers may differ elsewhere.
"""

from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "icon"
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
PNG_SIZE = 256


def render_all() -> dict[str, bytes]:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtWidgets import QApplication

    from morphwheel.ui.icon import render_app_icon, svg_document

    _app = QApplication.instance() or QApplication(["make_icon"])  # kept alive while rendering

    def png_bytes(size: int) -> bytes:
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        render_app_icon(size).save(buffer, "PNG")
        return bytes(buffer.data().data())

    frames = [Image.open(io.BytesIO(png_bytes(s))).convert("RGBA") for s in ICO_SIZES]
    ico = io.BytesIO()
    frames[-1].save(
        ico,
        format="ICO",
        sizes=[(s, s) for s in ICO_SIZES],
        append_images=frames[:-1],
        bitmap_format="png",
    )
    return {
        "morphwheel.ico": ico.getvalue(),
        "morphwheel.svg": svg_document().encode("utf-8"),
        f"morphwheel-{PNG_SIZE}.png": png_bytes(PNG_SIZE),
    }


def _same(path: Path, data: bytes) -> bool:
    """Equal content: text with any line ending for the SVG, decoded pixels for the images."""
    if not path.exists():
        return False
    if path.suffix == ".svg":
        return path.read_bytes().replace(b"\r\n", b"\n") == data
    from PIL import Image

    with Image.open(path) as on_disk, Image.open(io.BytesIO(data)) as fresh:
        if path.suffix == ".ico":
            sizes = sorted(on_disk.info["sizes"])
            if sizes != sorted(fresh.info["sizes"]):
                return False
            for size in sizes:  # the ICO plugin's frame accessor, one image per size
                a = cast(Any, on_disk).ico.getimage(size).convert("RGBA")
                b = cast(Any, fresh).ico.getimage(size).convert("RGBA")
                if a.tobytes() != b.tobytes():
                    return False
            return True
        return on_disk.convert("RGBA").tobytes() == fresh.convert("RGBA").tobytes()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the app icon assets")
    parser.add_argument("--check", action="store_true", help="compare with the committed files")
    args = parser.parse_args(argv)
    files = render_all()
    if args.check:
        stale = [n for n, data in files.items() if not _same(OUT / n, data)]
        if stale:
            print("stale:", ", ".join(stale), "(run tools/make_icon.py)")
            return 1
        print("icon assets up to date")
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (OUT / name).write_bytes(data)
        print(f"wrote {OUT / name} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
