"""The wheel's small icons: Fluent UI System Icons for Compress, PDF, More and Cancel (phase-3 §7).

The four SVGs in ``fluent/`` are Microsoft's, byte for byte (MIT, commit a3de632 of
microsoft/fluentui-system-icons; the text is in ``packaging/licenses/fluentui-system-icons/``).
Formats stay text: an icon sits *above* a label, never in place of it (RD-36).

Rules:

- **Which target gets one** (RD-36): a Compress target gets ``COMPRESS`` and a target whose output
  is PDF gets ``PDF``, whoever provides it. The More slot gets ``MORE``; the hub's Cancel gets
  ``CANCEL``. Every other label stays text only. ⊘ (Not supported) stays a glyph in the text.
- **Loaded before a drag** (RD-36): the first read of an SVG loads Qt's ``qsvg`` plugin and
  ``Qt6Svg.dll``. ``warm`` does that when the wheel window is built, so no drag ever pays for it
  inside Explorer's DragEnter.
- **Tinted per draw**: the mask (the SVG's alpha at a physical size) is cached; the color is applied
  at each draw, because a hovered slot's label color animates and a cache keyed by color would grow
  without end.
- **Never fatal**: an icon that won't load is logged once and the label is drawn alone.
  ``failures`` lists them for ``--worker-check``, the frozen build's smoke test (RD-31f, RD-36).
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize
from PySide6.QtGui import QColor, QImage, QImageReader, QPainter

from morphwheel.core.catalog import Target, TargetKind
from morphwheel.core.formats import FormatId

log = logging.getLogger(__name__)

FLUENT_DIR = Path(__file__).resolve().parent / "fluent"
GLYPH_PX = 16.0  # logical, at size M; scaled with the wheel


class Glyph(StrEnum):
    """An icon, by its file in ``fluent/`` (the upstream names, so the pins can be traced)."""

    COMPRESS = "ic_fluent_arrow_minimize_20_regular.svg"
    PDF = "ic_fluent_document_pdf_20_regular.svg"
    MORE = "ic_fluent_more_horizontal_20_regular.svg"
    CANCEL = "ic_fluent_dismiss_20_regular.svg"


def glyph_for(target: Target | None) -> Glyph | None:
    """The icon a target's label carries, or ``None`` for a plain label (RD-36)."""
    if target is None:
        return None
    if target.kind is TargetKind.COMPRESS:
        return Glyph.COMPRESS
    if target.output_format is FormatId.PDF:
        return Glyph.PDF
    return None


class GlyphSet:
    """The loaded icons. One per wheel window; the renderer takes it as an argument."""

    def __init__(self, folder: Path = FLUENT_DIR) -> None:
        self._folder = folder
        self._masks: dict[tuple[Glyph, int], QImage] = {}
        self._failed: set[Glyph] = set()

    def mask(self, glyph: Glyph, px: int) -> QImage | None:
        """The icon's alpha at ``px`` by ``px`` physical pixels, or ``None`` if it won't load."""
        key = (glyph, px)
        cached = self._masks.get(key)
        if cached is not None:
            return cached
        if glyph in self._failed:
            return None
        reader = QImageReader(str(self._folder / glyph.value))
        reader.setScaledSize(QSize(px, px))
        image = reader.read()
        if image.isNull():
            self._failed.add(glyph)
            log.warning("wheel icon %s did not load: %s", glyph.name, reader.errorString())
            return None
        image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        self._masks[key] = image
        return image

    def warm(self, dpr: float, scales: Iterable[float] = (1.0,)) -> float:
        """Load every icon at these sizes now; returns the milliseconds it took."""
        started = time.perf_counter()
        for scale in scales:
            px = physical_px(GLYPH_PX * scale, dpr)
            for glyph in Glyph:
                self.mask(glyph, px)
        return (time.perf_counter() - started) * 1000

    def failures(self) -> list[str]:
        """The icons that don't load at the base size (empty: all load)."""
        px = physical_px(GLYPH_PX, 1.0)
        return [g.name for g in Glyph if self.mask(g, px) is None]

    def draw(self, p: QPainter, glyph: Glyph, center: QPointF, size: float, color: QColor) -> bool:
        """Draw the icon in ``color``, ``size`` logical px square, centered; False if not loaded."""
        device = p.device()
        dpr = device.devicePixelRatioF() if device is not None else 1.0
        px = physical_px(size, dpr)
        mask = self.mask(glyph, px)
        if mask is None:
            return False
        tinted = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
        tinted.fill(color)
        q = QPainter(tinted)
        q.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        q.drawImage(0, 0, mask)
        q.end()
        side = px / dpr  # one mask pixel per device pixel: no resampling at fractional sizes
        p.drawImage(QRectF(center.x() - side / 2, center.y() - side / 2, side, side), tinted)
        return True


def physical_px(size: float, dpr: float) -> int:
    return max(1, math.ceil(size * dpr - 1e-6))
