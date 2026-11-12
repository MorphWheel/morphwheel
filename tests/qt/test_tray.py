"""``ui.tray``: the four states and their icons, the tooltips, the menu's signals, the click
routing, and the working animation (phase-3 §6.1, §8)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QSystemTrayIcon
from pytestqt.qtbot import QtBot

from morphwheel.ui.tray import ALERT_COLOR, FRAMES, TrayIcon, TrayState, tray_icon

pytestmark = pytest.mark.usefixtures("qapp")

Trigger = QSystemTrayIcon.ActivationReason.Trigger


def image(
    state: TrayState, size: int = 32, *, frame: int = 0, light: bool = False, motion: bool = True
) -> QImage:
    icon = tray_icon(state, frame=frame, light=light, motion=motion)
    return icon.pixmap(QSize(size, size)).toImage()


def ring_alpha(img: QImage) -> int:
    """The ring's strength: the most opaque pixel down the top half of the middle column."""
    x = img.width() // 2
    return max(img.pixelColor(x, y).alpha() for y in range(img.height() // 2))


@pytest.mark.parametrize("size", [16, 20, 24, 25, 32, 40, 48])
def test_the_icon_paints_at_any_requested_size(size: int) -> None:
    img = image(TrayState.NORMAL, size)
    assert img.width() == size
    assert img.height() == size
    assert ring_alpha(img) == 255  # the ring is drawn
    assert img.pixelColor(size // 2, size // 2).alpha() == 0  # the hub is empty


def test_the_ink_follows_the_taskbar() -> None:
    dark = image(TrayState.NORMAL, light=False)
    light = image(TrayState.NORMAL, light=True)
    x = dark.width() // 2
    y = next(y for y in range(dark.height()) if dark.pixelColor(x, y).alpha() == 255)
    assert dark.pixelColor(x, y).lightness() > 200  # white on a dark taskbar
    assert light.pixelColor(x, y).lightness() < 60  # near-black on a light one


def test_paused_dims_the_ring_and_marks_the_centre() -> None:
    normal = image(TrayState.NORMAL)
    paused = image(TrayState.PAUSED)
    assert 0 < ring_alpha(paused) < ring_alpha(normal)
    c = paused.width() // 2
    assert paused.pixelColor(c - 3, c).alpha() == 255  # the ‖ bars
    assert normal.pixelColor(c - 3, c).alpha() == 0


def test_alert_adds_a_red_badge() -> None:
    img = image(TrayState.ALERT)
    s = img.width()
    probe = int(s * 0.9)  # inside the badge, outside the ring
    badge = img.pixelColor(probe, probe)
    assert badge.alpha() == 255
    assert badge.name() == ALERT_COLOR.name()
    assert image(TrayState.NORMAL).pixelColor(probe, probe).alpha() == 0


def test_working_walks_an_arc_with_motion_and_shows_a_dot_without() -> None:
    frames = [image(TrayState.WORKING, frame=i, motion=True) for i in range(FRAMES)]
    assert len({f.constBits().tobytes() for f in frames}) == FRAMES  # eight different frames
    still = [image(TrayState.WORKING, frame=i, motion=False) for i in range(FRAMES)]
    assert len({f.constBits().tobytes() for f in still}) == 1  # nothing moves (C7)
    c = still[0].width() // 2
    assert still[0].pixelColor(c, c).alpha() == 255  # the fixed dot
    assert frames[0].pixelColor(c, c).alpha() == 0


# ----------------------------------------------------------------------------- the tray object
def test_tooltips_and_precedence(qtbot: QtBot) -> None:
    tray = TrayIcon(motion_enabled=lambda: False)
    assert tray.state is TrayState.NORMAL
    assert tray.tooltip == "Morphwheel — Shift-drag to convert"
    tray.set_trigger_key("ctrl+shift")
    assert tray.tooltip == "Morphwheel — Ctrl+Shift-drag to convert"
    tray.set_paused(True)
    assert tray.state is TrayState.PAUSED
    assert tray.tooltip == "Morphwheel — paused"
    tray.set_working(5, 12)
    assert tray.state is TrayState.WORKING  # a paused app can still finish a job
    assert tray.tooltip == "Converting 5 / 12…"
    tray.add_alert("a")
    tray.add_alert("b")
    assert tray.state is TrayState.ALERT  # an alert must be seen
    assert tray.tooltip == "2 problems — click for details"
    tray.clear_alerts()
    tray.clear_working()
    assert tray.state is TrayState.PAUSED
    tray.set_paused(False)
    assert tray.state is TrayState.NORMAL


def test_the_menu_asks_and_pause_does_not_loop(qtbot: QtBot) -> None:
    tray = TrayIcon(motion_enabled=lambda: False)
    pause, settings, log_folder, about, quit_ = tray.actions
    assert [a.text() for a in tray.actions] == [
        "Pause Morphwheel",
        "Settings…",
        "Open log folder",
        "About Morphwheel",
        "Quit",
    ]
    assert tray.menu.actions()[3].isSeparator()
    asked: list[object] = []
    tray.pause_toggled.connect(lambda v: asked.append(("pause", v)))
    tray.settings_requested.connect(lambda: asked.append("settings"))
    tray.log_folder_requested.connect(lambda: asked.append("log"))
    tray.about_requested.connect(lambda: asked.append("about"))
    tray.quit_requested.connect(lambda: asked.append("quit"))
    pause.trigger()  # a user click
    assert asked == [("pause", True)]
    assert tray.paused  # checked by the click itself; the store confirms with set_paused
    tray.set_paused(True)  # the store's answer: no second ask
    tray.set_paused(False)
    assert asked == [("pause", True)]
    assert not tray.paused
    for action in (settings, log_folder, about, quit_):
        action.trigger()
    assert asked == [("pause", True), "settings", "log", "about", "quit"]


def test_a_click_shows_the_alerts_or_asks_for_the_settings(qtbot: QtBot) -> None:
    tray = TrayIcon(motion_enabled=lambda: False)
    seen: list[object] = []
    tray.settings_requested.connect(lambda: seen.append("settings"))
    tray.alert_clicked.connect(seen.append)
    tray._on_activated(Trigger)
    assert seen == ["settings"]
    tray.add_alert("first")
    tray.add_alert("second")
    tray._on_activated(
        QSystemTrayIcon.ActivationReason.DoubleClick
    )  # ignored (Windows: after a Trigger)
    assert seen == ["settings"]
    tray._on_activated(Trigger)
    assert seen == ["settings", "first\n\nsecond"]
    assert tray.alerts == ()
    assert tray.state is TrayState.NORMAL


def test_the_animation_runs_only_while_working_shown_and_moving(qtbot: QtBot) -> None:
    motion = [True]
    tray = TrayIcon(motion_enabled=lambda: motion[0])
    tray.set_working(0, 4)
    assert not tray.animating  # not shown yet
    tray.show()
    assert tray.visible
    assert tray.animating
    qtbot.waitUntil(lambda: tray.frame >= 2, timeout=2000)  # the arc walks
    painted: list[object] = []
    tray._icon.setIcon = painted.append  # type: ignore[method-assign]
    tray.set_working(1, 4)  # a progress tick doesn't restart the timer…
    tray.set_working(2, 4)
    assert painted == []  # …and doesn't hand the shell an unchanged icon
    assert tray.animating
    before = tray.frame
    qtbot.waitUntil(lambda: tray.frame != before, timeout=2000)
    tray.add_alert("x")
    assert not tray.animating  # the alert covers the arc: nothing to animate
    tray.clear_alerts()
    assert tray.animating
    tray.hide()
    assert not tray.animating
    assert not tray.visible
    tray.show()
    assert tray.animating
    tray.clear_working()
    assert not tray.animating
    motion[0] = False
    tray.set_working(0, 4)
    assert not tray.animating  # C7: a fixed dot, no timer
    tray.hide()
