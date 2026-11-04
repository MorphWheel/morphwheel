"""``ui.theme``: the WinUI tokens per scheme, High Contrast from the system palette, and motion.

Traceability (phase-4 §6): "animations off: duration 0" (C7, the ``Motion`` half; the animator
half is in ``test_animator.py``); phase-3 §7 (tokens, High Contrast) and §8 (durations, curve).
"""

from __future__ import annotations

import itertools

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette

from morphwheel.ui.theme import (
    FAST_MS,
    FASTER_MS,
    NORMAL_MS,
    Motion,
    Scheme,
    Theme,
    accent_for,
    detect_scheme,
    ease,
    luminance,
    system_accent,
    text_on,
)

pytestmark = pytest.mark.usefixtures("qapp")

WINDOWS_BLUE = QColor("#0078D4")


def test_dark_and_light_follow_the_token_table() -> None:
    dark = Theme.build(Scheme.DARK, accent=WINDOWS_BLUE).palette
    light = Theme.build(Scheme.LIGHT, accent=WINDOWS_BLUE).palette
    # The disc is 92 % opaque (U5): 235/255.
    assert (dark.disc.name(), dark.disc.alpha()) == ("#202020", 235)
    assert (light.disc.name(), light.disc.alpha()) == ("#f3f3f3", 235)
    assert dark.surface.name() == "#2c2c2c"
    assert light.surface.name() == "#ffffff"
    # #AARRGGBB tokens keep their alpha.
    assert (dark.text_secondary.alpha(), light.text_secondary.alpha()) == (0xC5, 0x9E)
    assert (dark.text_disabled.alpha(), light.text_disabled.alpha()) == (0x5D, 0x5C)
    assert (dark.outline.alpha(), light.outline.alpha()) == (0x12, 0x0F)
    assert dark.outline_surface == light.outline_surface == QColor("#66757575")
    assert (dark.critical.name(), light.critical.name()) == ("#ff99a4", "#c42b1c")
    assert (dark.success.name(), light.success.name()) == ("#6ccb5f", "#0f7b0f")
    assert Theme.build(Scheme.DARK).has_shadow
    assert Theme.build(Scheme.LIGHT).has_shadow


def test_accent_is_lightened_in_dark_and_darkened_in_light() -> None:
    dark = accent_for(Scheme.DARK, WINDOWS_BLUE)
    light = accent_for(Scheme.LIGHT, WINDOWS_BLUE)
    assert luminance(dark) > luminance(WINDOWS_BLUE) > luminance(light)
    assert accent_for(Scheme.HIGH_CONTRAST, WINDOWS_BLUE) == WINDOWS_BLUE
    # The table: black text on the (light) Dark-scheme accent, white on the Light-scheme one.
    assert Theme.build(Scheme.DARK, accent=QColor("#4CC2FF")).palette.text_on_accent == QColor(
        Qt.GlobalColor.black
    )
    assert Theme.build(Scheme.LIGHT, accent=WINDOWS_BLUE).palette.text_on_accent == QColor(
        Qt.GlobalColor.white
    )
    # ... and the rule holds for any accent, by luminance.
    assert text_on(QColor("#FFFF00")) == QColor(Qt.GlobalColor.black)
    assert text_on(QColor("#400080")) == QColor(Qt.GlobalColor.white)


def test_an_invalid_or_missing_accent_falls_back_to_windows_blue() -> None:
    fallback = Theme.build(Scheme.DARK, accent=QColor()).palette.accent
    assert fallback == Theme.build(Scheme.DARK, accent=WINDOWS_BLUE).palette.accent
    assert fallback == Theme.build(Scheme.DARK).palette.accent
    assert system_accent(QGuiApplication.palette()).isValid()


def test_high_contrast_uses_the_system_roles_opaque_with_no_shadow() -> None:
    system = QPalette()
    active = QPalette.ColorGroup.Active
    system.setColor(active, QPalette.ColorRole.Window, QColor(0, 0, 0, 200))  # alpha is dropped
    system.setColor(active, QPalette.ColorRole.WindowText, QColor("#FFFFFF"))
    system.setColor(active, QPalette.ColorRole.Highlight, QColor("#1AEBFF"))
    system.setColor(active, QPalette.ColorRole.HighlightedText, QColor("#000000"))
    system.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor("#3FF23F"))
    theme = Theme.build(Scheme.HIGH_CONTRAST, system=system)
    p = theme.palette
    assert theme.high_contrast
    assert theme.border_width == 2.0
    assert not theme.has_shadow
    assert (p.disc.name(), p.disc.alpha()) == ("#000000", 255)
    assert p.surface == p.disc
    assert p.critical_bg == p.disc
    assert p.text == p.outline == p.outline_surface == QColor("#FFFFFF")
    assert p.accent.name() == "#1aebff"
    assert p.text_on_accent.name() == "#000000"
    assert p.text_disabled.name() == "#3ff23f"
    # Every role is opaque: High Contrast has no transparency (phase-3 §7).
    for name in ("text_secondary", "skeleton", "success", "caution", "critical"):
        assert getattr(p, name).alpha() == 255, name
    assert Theme.build(Scheme.DARK).border_width == 1.0


def test_detect_scheme_table() -> None:
    hints = QGuiApplication.styleHints()
    expected = Scheme.DARK if hints.colorScheme() == Qt.ColorScheme.Dark else Scheme.LIGHT
    assert detect_scheme(hints) is expected  # offscreen: Unknown → Light


def test_fonts_follow_the_type_ramp() -> None:
    fonts = Theme.build(Scheme.LIGHT).fonts
    assert fonts.slot_label.pixelSize() == 12
    assert fonts.hub_top.pixelSize() == 14
    assert fonts.hub_top.weight() == QFont.Weight.DemiBold
    assert fonts.hub_bottom.pixelSize() == 11
    assert fonts.hub_bottom.weight() == QFont.Weight.Normal
    assert (fonts.toast_title.pixelSize(), fonts.toast_body.pixelSize()) == (14, 12)
    assert fonts.slot_label.families()[0] == "Segoe UI Variable"  # not "…Variable Text" (Bold only)
    assert fonts.slot_label.families()[-1] == "Segoe UI"  # the fallback (phase-3 §7)


# ----------------------------------------------------------------------------- motion (C7, §8)


def test_motion_off_makes_every_duration_zero() -> None:
    on, off = Motion(enabled=True), Motion(enabled=False)
    assert (on.ms(FASTER_MS), on.ms(FAST_MS), on.ms(NORMAL_MS)) == (83, 167, 250)
    assert (on.faster_ns, on.fast_ns, on.normal_ns) == (83_000_000, 167_000_000, 250_000_000)
    assert (off.ms(FASTER_MS), off.ms(FAST_MS), off.ms(NORMAL_MS)) == (0, 0, 0)
    assert (off.faster_ns, off.fast_ns, off.normal_ns) == (0, 0, 0)


def test_easing_is_fast_at_the_start_slow_at_the_end_and_monotone() -> None:
    assert ease(-1.0) == 0.0
    assert ease(0.0) == 0.0
    assert ease(1.0) == 1.0
    assert ease(2.0) == 1.0
    assert ease(0.5) > 0.8  # "0,0,0,1": most of the way there at half time
    samples = [ease(i / 50) for i in range(51)]
    assert all(b >= a for a, b in itertools.pairwise(samples))
    assert all(0.0 <= s <= 1.0 for s in samples)
