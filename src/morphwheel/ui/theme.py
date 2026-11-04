"""Theme tokens and motion rules for the wheel and the surrounding UI (phase-3 §7 and §8).

The colors are WinUI's tokens, taken from ``Common_themeresources_any.xaml`` and listed in phase-3
§7. Light or Dark follows the system (``QStyleHints.colorScheme``); the accent is the system accent
(``QPalette.ColorRole.Accent``), lightened in Dark and darkened in Light the way WinUI uses its
Light2 and Dark1 variants. In High Contrast (C7) the theme uses the system palette roles only:
opaque fills, 2 px borders, no shadow and no transparency.

Motion (§8, C7): three WinUI durations and the "0,0,0,1" curve (fast start, slow end). When
Windows' animations are off, every duration is 0 and only the color changes remain. Whether they
are off is decided by the caller: this package imports no Win32 (P2), so the switch arrives as a
value.

This module has no state and no Qt objects beyond colors, fonts and an easing curve. It is safe to
build a ``Theme`` on every scheme change.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from enum import StrEnum

from PySide6.QtCore import QEasingCurve, QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPalette, QStyleHints

# WinUI durations (phase-3 §8), in milliseconds.
FASTER_MS = 83
FAST_MS = 167
NORMAL_MS = 250

DEFAULT_ACCENT = QColor("#0078D4")  # Windows' default accent, when the platform reports none
# "Segoe UI Variable Text" is a legacy family with no Semibold face (it resolves to Bold); the
# variable family carries the Text optical size and the 600 weight.
FONT_FAMILIES = ("Segoe UI Variable", "Segoe UI")


class Scheme(StrEnum):
    LIGHT = "light"
    DARK = "dark"
    HIGH_CONTRAST = "high_contrast"


@dataclass(frozen=True)
class Palette:
    """Color roles. Names follow the "use" column of the phase-3 §7 table."""

    disc: QColor  # the wheel surface, 92 % opaque (U5)
    surface: QColor  # a slot at rest, the hub, a toast
    text: QColor  # labels
    text_secondary: QColor  # the hub's second line
    text_disabled: QColor  # a disabled slot
    text_on_accent: QColor  # the hovered slot's label
    outline: QColor  # slot borders
    outline_surface: QColor  # the ring around the disc, and the halo edge line (U1)
    accent: QColor
    critical: QColor
    critical_bg: QColor
    success: QColor
    caution: QColor
    shadow: QColor  # the soft shadow's darkest color; alpha 0 means no shadow
    skeleton: QColor  # the label placeholders while the plan is still unknown (phase-3 §3)


@dataclass(frozen=True)
class Fonts:
    """The Windows type ramp (phase-3 §7), in pixels."""

    slot_label: QFont  # 12 px semibold
    hub_top: QFont  # 14 px semibold
    hub_bottom: QFont  # 11 px
    toast_title: QFont  # 14 px semibold
    toast_body: QFont  # 12 px


@dataclass(frozen=True)
class Theme:
    scheme: Scheme
    palette: Palette
    fonts: Fonts

    @property
    def high_contrast(self) -> bool:
        return self.scheme is Scheme.HIGH_CONTRAST

    @property
    def border_width(self) -> float:
        """2 px borders in High Contrast (phase-3 §7), hairlines otherwise."""
        return 2.0 if self.high_contrast else 1.0

    @property
    def has_shadow(self) -> bool:
        return self.palette.shadow.alpha() > 0

    @classmethod
    def build(
        cls,
        scheme: Scheme,
        *,
        accent: QColor | None = None,
        system: QPalette | None = None,
    ) -> Theme:
        """A theme for ``scheme``. High Contrast needs the system palette; the others the accent."""
        if scheme is Scheme.HIGH_CONTRAST:
            palette = _high_contrast_palette(system if system is not None else QPalette())
        else:
            base = accent if accent is not None and accent.isValid() else DEFAULT_ACCENT
            palette = _dark_palette(base) if scheme is Scheme.DARK else _light_palette(base)
        return cls(scheme, palette, _fonts())


def detect_scheme(hints: QStyleHints) -> Scheme:
    """The platform's Light or Dark; Unknown means Light (Windows' default). High Contrast is the
    caller's call (``platform.system.high_contrast``), because Qt reports a Light/Dark scheme for
    High Contrast themes too."""
    if hints.colorScheme() == Qt.ColorScheme.Dark:
        return Scheme.DARK
    return Scheme.LIGHT


def system_accent(palette: QPalette) -> QColor:
    """The accent the platform reports, or Windows' default when it reports none."""
    color = palette.color(QPalette.ColorRole.Accent)
    return color if color.isValid() else QColor(DEFAULT_ACCENT)


def accent_for(scheme: Scheme, base: QColor) -> QColor:
    """WinUI's Light2 in Dark and Dark1 in Light, approximated from the base accent."""
    if scheme is Scheme.DARK:
        return base.lighter(130)
    if scheme is Scheme.LIGHT:
        return base.darker(115)
    return QColor(base)


def luminance(color: QColor) -> float:
    """Relative luminance (WCAG), 0 for black and 1 for white."""

    def channel(v: float) -> float:
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * channel(color.redF())
        + 0.7152 * channel(color.greenF())
        + 0.0722 * channel(color.blueF())
    )


def text_on(color: QColor) -> QColor:
    """Black on a light accent, white on a dark one (the §7 table, kept true for any accent)."""
    return QColor(Qt.GlobalColor.black) if luminance(color) > 0.35 else QColor(Qt.GlobalColor.white)


# ----------------------------------------------------------------------------- palettes


def _dark_palette(accent_base: QColor) -> Palette:
    accent = accent_for(Scheme.DARK, accent_base)
    return Palette(
        disc=QColor("#EB202020"),  # 92 % (U5)
        surface=QColor("#2C2C2C"),
        text=QColor("#FFFFFF"),
        text_secondary=QColor("#C5FFFFFF"),
        text_disabled=QColor("#5DFFFFFF"),
        text_on_accent=text_on(accent),
        outline=QColor("#12FFFFFF"),
        outline_surface=QColor("#66757575"),
        accent=accent,
        critical=QColor("#FF99A4"),
        critical_bg=QColor("#442726"),
        success=QColor("#6CCB5F"),
        caution=QColor("#FCE100"),
        shadow=QColor(0, 0, 0, 110),
        skeleton=QColor("#1FFFFFFF"),
    )


def _light_palette(accent_base: QColor) -> Palette:
    accent = accent_for(Scheme.LIGHT, accent_base)
    return Palette(
        disc=QColor("#EBF3F3F3"),  # 92 % (U5)
        surface=QColor("#FFFFFF"),
        text=QColor("#E4000000"),
        text_secondary=QColor("#9E000000"),
        text_disabled=QColor("#5C000000"),
        text_on_accent=text_on(accent),
        outline=QColor("#0F000000"),
        outline_surface=QColor("#66757575"),
        accent=accent,
        critical=QColor("#C42B1C"),
        critical_bg=QColor("#FDE7E9"),
        success=QColor("#0F7B0F"),
        caution=QColor("#9D5D00"),
        shadow=QColor(0, 0, 0, 70),
        skeleton=QColor("#1A000000"),
    )


def _high_contrast_palette(system: QPalette) -> Palette:
    """System colors only (phase-3 §7): Window, WindowText, Highlight, HighlightedText."""
    active = QPalette.ColorGroup.Active
    window = _opaque(system.color(active, QPalette.ColorRole.Window))
    text = _opaque(system.color(active, QPalette.ColorRole.WindowText))
    highlight = _opaque(system.color(active, QPalette.ColorRole.Highlight))
    on_highlight = _opaque(system.color(active, QPalette.ColorRole.HighlightedText))
    disabled = _opaque(system.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText))
    return Palette(
        disc=window,
        surface=window,
        text=text,
        text_secondary=text,
        text_disabled=disabled,
        text_on_accent=on_highlight,
        outline=text,
        outline_surface=text,
        accent=highlight,
        critical=text,
        critical_bg=window,
        success=text,
        caution=text,
        shadow=QColor(0, 0, 0, 0),
        skeleton=disabled,
    )


def _opaque(color: QColor) -> QColor:
    out = QColor(color)
    out.setAlpha(255)
    return out


# ----------------------------------------------------------------------------- fonts


def _font(px: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont()
    font.setFamilies(list(FONT_FAMILIES))
    font.setPixelSize(px)
    font.setWeight(weight)
    return font


@functools.cache
def _fonts() -> Fonts:
    """Built once: the ramp depends on neither the scheme nor the accent."""
    semibold = QFont.Weight.DemiBold
    return Fonts(
        slot_label=_font(12, semibold),
        hub_top=_font(14, semibold),
        hub_bottom=_font(11),
        toast_title=_font(14, semibold),
        toast_body=_font(12),
    )


# ----------------------------------------------------------------------------- motion


def _winui_curve() -> QEasingCurve:
    curve = QEasingCurve(QEasingCurve.Type.BezierSpline)
    curve.addCubicBezierSegment(QPointF(0.0, 0.0), QPointF(0.0, 1.0), QPointF(1.0, 1.0))
    return curve


_EASING = _winui_curve()


def ease(progress: float) -> float:
    """The WinUI "0,0,0,1" curve: fast start, slow end. Clamped to [0, 1]."""
    if progress <= 0.0:
        return 0.0
    if progress >= 1.0:
        return 1.0
    return _EASING.valueForProgress(progress)


@dataclass(frozen=True)
class Motion:
    """Durations, or none at all when Windows' animations are off (C7)."""

    enabled: bool = True

    def ms(self, duration_ms: int) -> int:
        return duration_ms if self.enabled else 0

    def ns(self, duration_ms: int) -> int:
        return self.ms(duration_ms) * 1_000_000

    @property
    def faster_ns(self) -> int:
        return self.ns(FASTER_MS)

    @property
    def fast_ns(self) -> int:
        return self.ns(FAST_MS)

    @property
    def normal_ns(self) -> int:
        return self.ns(NORMAL_MS)
