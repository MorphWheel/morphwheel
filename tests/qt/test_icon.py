"""``ui.icon`` and ``tools/make_icon.py``: one geometry for the window icon, the ico and the SVG.

The assets under ``assets/icon/`` are committed; the tests hold them to the painter's constants
by structure (the sizes, the SVG text, the colours at known points), never by pixel bytes, which
a different rasterizer could change.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtGui import QColor

from morphwheel.ui.icon import (
    ACCENT,
    ARCS,
    DISC,
    DISC_RADIUS,
    INK,
    RING_RADIUS,
    app_icon,
    arcs,
    disc_radius_for,
    gap_for,
    render_app_icon,
    svg_document,
)

pytestmark = pytest.mark.usefixtures("qapp")

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "assets" / "icon"
ICO_SIZES = {16, 20, 24, 32, 40, 48, 64, 128, 256}


def test_the_eight_arcs_sit_where_the_tray_draws_them() -> None:
    starts = [a.start_deg for a in arcs()]
    assert len(starts) == ARCS
    assert starts[0] == 90 - 19  # the first arc centred on 12 o'clock, 38° wide
    assert [round(b - a) for a, b in itertools.pairwise(starts)] == [-45] * 7
    # Small sizes widen the gaps so eight slots stay eight, and the disc fills the frame.
    assert gap_for(256) == 7.0
    assert 15 < gap_for(16) < 20
    assert arcs(gap_for(16))[0].span_deg == 45 - gap_for(16)
    assert disc_radius_for(16) == 8
    assert disc_radius_for(256) == 256 * DISC_RADIUS


@pytest.mark.parametrize("size", [16, 32, 256])
def test_the_mark_paints_disc_ring_and_hub(size: int) -> None:
    image = render_app_icon(size).toImage()
    assert image.size().width() == size
    c = size / 2
    assert image.pixelColor(0, 0).alpha() == 0  # air around the disc
    assert image.pixelColor(int(c), int(c)).name() == ACCENT.lower()  # the hub
    if size >= 32:
        # On the ring at 12 o'clock: an arc (ink); between the disc and the ring: the disc.
        assert image.pixelColor(int(c), int(c - size * RING_RADIUS)).name() == INK.lower()
        between = int(c - size * (RING_RADIUS + DISC_RADIUS) / 2 - size * 0.02)
        assert image.pixelColor(int(c), between).name() == DISC.lower()


def test_the_window_icon_is_the_same_painter() -> None:
    icon = app_icon()
    assert not icon.isNull()
    pixmap = icon.pixmap(48, 48)
    assert pixmap.toImage().pixelColor(24, 24) == QColor(ACCENT)


def test_the_committed_assets_match_the_painter() -> None:
    svg = (ASSETS / "morphwheel.svg").read_text(encoding="utf-8")
    assert svg == svg_document()
    assert svg.count("<path ") == ARCS
    assert f'fill="{DISC}"' in svg
    assert f'fill="{ACCENT}"' in svg
    assert f'stroke="{INK}"' in svg
    with Image.open(ASSETS / "morphwheel.ico") as ico:
        assert {w for w, _ in ico.info["sizes"]} == ICO_SIZES
        ico.size = (256, 256)
        ico.load()
        assert ico.convert("RGBA").getpixel((128, 128))[:3] == (0x4C, 0xC2, 0xFF)
    with Image.open(ASSETS / "morphwheel-256.png") as png:
        assert png.size == (256, 256)
        assert png.convert("RGBA").getpixel((0, 0))[3] == 0
        assert png.convert("RGBA").getpixel((128, 128))[:3] == (0x4C, 0xC2, 0xFF)


def test_the_tool_renders_the_same_files_in_memory() -> None:
    from make_icon import ICO_SIZES as TOOL_SIZES  # pyproject's pythonpath has tools/
    from make_icon import render_all

    assert set(TOOL_SIZES) == ICO_SIZES
    files = render_all()
    assert set(files) == {"morphwheel.ico", "morphwheel.svg", "morphwheel-256.png"}
    assert files["morphwheel.svg"].decode("utf-8") == svg_document()
