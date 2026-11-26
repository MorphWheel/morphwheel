"""``ui.wheel.glyphs``: the Fluent icons on the wheel (phase-3 §7, RD-36).

Held here: which targets carry an icon; the files are Microsoft's, byte for byte, with their
license; every icon loads at the wheel's sizes and pixel ratios; a draw puts ink of exactly the
given color inside the icon's square and nowhere else; a missing icon is logged once and never
raised; ``failures`` names it.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from morphwheel.core.catalog import Target, TargetKind
from morphwheel.core.formats import FormatId
from morphwheel.ui.wheel.glyphs import FLUENT_DIR, GLYPH_PX, Glyph, GlyphSet, glyph_for, physical_px

ROOT = Path(__file__).resolve().parents[2]
LICENSE = ROOT / "packaging" / "licenses" / "fluentui-system-icons" / "LICENSE.txt"

# sha256 of the files as fetched from microsoft/fluentui-system-icons at commit a3de632 (LF, as
# .gitattributes keeps them).
PINS = {
    Glyph.COMPRESS: "83983fcd3dc864a5e1772b39ef768f3c822b805304a74311b8c269fd1d370a65",
    Glyph.PDF: "e8c6aa2347edbac266e647bcc947709f07a72fd798183e992d9b857f5771f1ec",
    Glyph.MORE: "5cc969f49ca33c856fb72804f9355e84db26dc6c23f2a1fc85995b67ad1c0c8d",
    Glyph.CANCEL: "e84ad771fa8afba8e3ef52c98d9ab2d8ef4fc8e23c5954766a1c4e88fc13b355",
}
LICENSE_PIN = "69bc45dc42b9acb96a69823adbc6ae538374e3c0bde169b855b32c48eaaef52f"


def _target(
    tid: str, kind: TargetKind, out: FormatId | None, *, builtin: bool = True, provider: str = "b"
) -> Target:
    return Target(tid, tid.upper(), kind, out, frozenset({FormatId.PNG}), provider, builtin)


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        (_target("compress", TargetKind.COMPRESS, None), Glyph.COMPRESS),
        (_target("pdf", TargetKind.CONVERT, FormatId.PDF), Glyph.PDF),
        (
            _target("com.x:pdf", TargetKind.CONVERT, FormatId.PDF, builtin=False, provider="x"),
            Glyph.PDF,
        ),
        (_target("jpeg", TargetKind.CONVERT, FormatId.JPEG), None),
        (_target("png", TargetKind.CONVERT, FormatId.PNG), None),
        (None, None),
    ],
)
def test_which_targets_carry_an_icon(target: Target | None, expected: Glyph | None) -> None:
    assert glyph_for(target) is expected


def test_the_files_are_the_pinned_upstream_bytes_with_their_license() -> None:
    assert {p.name for p in FLUENT_DIR.iterdir()} == {g.value for g in Glyph}
    for glyph, pin in PINS.items():
        assert hashlib.sha256((FLUENT_DIR / glyph.value).read_bytes()).hexdigest() == pin, glyph
    assert hashlib.sha256(LICENSE.read_bytes()).hexdigest() == LICENSE_PIN
    assert "Copyright (c) 2020 Microsoft Corporation" in LICENSE.read_text(encoding="utf-8")


@pytest.mark.parametrize("dpr", [1.0, 1.25, 1.5, 2.0])
@pytest.mark.parametrize("scale", [0.8, 1.0, 1.25])
def test_every_icon_loads_at_the_wheels_sizes(qapp: object, dpr: float, scale: float) -> None:
    glyphs = GlyphSet()
    px = physical_px(GLYPH_PX * scale, dpr)
    for glyph in Glyph:
        mask = glyphs.mask(glyph, px)
        assert mask is not None, glyph
        assert (mask.width(), mask.height()) == (px, px)
        # real ink, not a blank image (thin strokes antialias: not all reach 255 at 13 px)
        assert max(mask.pixelColor(x, y).alpha() for x in range(px) for y in range(px)) >= 128


def test_warm_loads_everything_and_reports_its_time(qapp: object) -> None:
    glyphs = GlyphSet()
    took = glyphs.warm(1.5, (1.0,))
    assert took >= 0.0
    assert glyphs.failures() == []
    assert len(glyphs._masks) >= len(Glyph)  # the cache is what warm fills


def _ink(image: QImage) -> list[tuple[int, int, QColor]]:
    return [
        (x, y, image.pixelColor(x, y))
        for x in range(image.width())
        for y in range(image.height())
        if image.pixelColor(x, y).alpha() > 0
    ]


@pytest.mark.parametrize("glyph", list(Glyph))
def test_a_draw_inks_only_its_square_in_the_given_color(qapp: object, glyph: Glyph) -> None:
    image = QImage(80, 80, QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(2.0)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    assert GlyphSet().draw(p, glyph, QPointF(20, 20), 16, QColor(10, 120, 200, 160))
    p.end()
    ink = _ink(image)
    assert ink
    for x, y, color in ink:
        assert 24 <= x < 56  # the 16 logical px square at 2x, centered on 20, 20
        assert 24 <= y < 56
        assert color.alpha() <= 160
    solid = [c for *_, c in ink if c.alpha() == 160]
    assert solid  # the stroke's inside is the color exactly
    for c in solid:  # premultiplied storage rounds by one
        assert all(abs(a - b) <= 1 for a, b in zip(c.getRgb()[:3], (10, 120, 200), strict=True))


def test_a_missing_icon_is_logged_once_and_never_raised(
    qapp: object, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    for glyph in (Glyph.COMPRESS, Glyph.PDF, Glyph.MORE):
        shutil.copy(FLUENT_DIR / glyph.value, tmp_path)
    glyphs = GlyphSet(tmp_path)  # no Cancel
    image = QImage(40, 40, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    with caplog.at_level(logging.WARNING, logger="morphwheel.ui.wheel.glyphs"):
        assert not glyphs.draw(p, Glyph.CANCEL, QPointF(20, 20), 16, QColor("black"))
        assert not glyphs.draw(p, Glyph.CANCEL, QPointF(20, 20), 20, QColor("black"))
        assert glyphs.draw(p, Glyph.MORE, QPointF(20, 20), 16, QColor("black"))
    p.end()
    assert [r.getMessage() for r in caplog.records if "CANCEL" in r.getMessage()] == [
        caplog.records[0].getMessage()
    ]
    assert glyphs.failures() == ["CANCEL"]


def test_failures_is_empty_for_the_shipped_set_and_names_a_broken_one(
    qapp: object, tmp_path: Path
) -> None:
    assert GlyphSet().failures() == []
    for glyph in Glyph:
        (tmp_path / glyph.value).write_text("not an svg", encoding="utf-8")
    assert GlyphSet(tmp_path).failures() == [g.name for g in Glyph]  # the control: it can fail
