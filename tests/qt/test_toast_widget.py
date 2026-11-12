"""``ui.toasts.widget``: no focus ever, the buttons, the look per scheme, RTL, and the motion."""

from __future__ import annotations

import gc
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from conftest import render_widget
from morphwheel.ui.theme import Motion, Scheme, Theme
from morphwheel.ui.toasts.model import (
    ActionKind,
    Progress,
    ToastAction,
    ToastKind,
    ToastModel,
    working_toast,
)
from morphwheel.ui.toasts.widget import RISE_PX, STRIPE, ToastWidget, stripe_color

pytestmark = pytest.mark.usefixtures("qapp")

ACTIONS = (
    ToastAction(ActionKind.SHOW_IN_FOLDER, "Show in folder", Path("C:/x/a.jpg")),
    ToastAction(ActionKind.UNDO, "Undo", "job"),
)
SUCCESS = ToastModel(ToastKind.SUCCESS, "Converted to JPG", "a.jpg · 1 KB → 1 KB", 60_000, ACTIONS)


def make(
    model: ToastModel = SUCCESS, scheme: Scheme = Scheme.DARK, motion: bool = False
) -> ToastWidget:
    return ToastWidget(model, Theme.build(scheme), Motion(motion))


def render(toast: ToastWidget) -> QImage:
    image = render_widget(toast)
    assert isinstance(image, QImage)
    return image


def test_no_focus_ever(qtbot: QtBot) -> None:
    """M2 check 7: clickable buttons on a window that never takes focus or activation."""
    toast = make()
    qtbot.addWidget(toast)
    toast.appear()
    assert toast.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert toast.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert all(b.focusPolicy() == Qt.FocusPolicy.NoFocus for b in toast.buttons)
    assert toast.close_button.focusPolicy() == Qt.FocusPolicy.NoFocus
    with qtbot.waitSignal(toast.action_clicked, timeout=1000) as clicked:
        QTest.mouseClick(toast.buttons[1], Qt.MouseButton.LeftButton)
    assert clicked.args[0] is ACTIONS[1]
    assert QApplication.focusWidget() is None
    assert not toast.isVisible()  # acted, then dismissed (animations off: at once)


def test_an_action_fires_once_and_the_close_button_dismisses(qtbot: QtBot) -> None:
    toast = make(motion=True)
    qtbot.addWidget(toast)
    toast.appear()
    toast.settle()
    fired: list[object] = []
    toast.action_clicked.connect(fired.append)
    toast.buttons[1].click()
    toast.buttons[1].click()  # during the fade: ignored (a second Undo would say "Not undone")
    toast.buttons[0].click()
    assert fired == [ACTIONS[1]]
    assert toast.dismissing
    assert not all(b.isEnabled() for b in toast.buttons)
    toast.settle()
    assert not toast.isVisible()

    toast = make()
    qtbot.addWidget(toast)
    toast.appear()
    QTest.mouseClick(toast, Qt.MouseButton.LeftButton, pos=QPoint(toast.width() // 2, 8))
    assert toast.isVisible()  # a click on the body is not a dismiss (it would lose Undo)
    with qtbot.waitSignal(toast.dismissed, timeout=1000):
        toast.close_button.click()
    assert not toast.isVisible()


@pytest.mark.parametrize("scheme", [Scheme.DARK, Scheme.LIGHT, Scheme.HIGH_CONTRAST])
def test_the_look_per_scheme(qtbot: QtBot, scheme: Scheme) -> None:
    theme = Theme.build(scheme)
    toast = make(scheme=scheme)
    qtbot.addWidget(toast)
    toast.appear()
    image = render(toast)
    corner = image.pixelColor(0, 0)
    inside = image.pixelColor(toast.width() // 2, 4)
    stripe = image.pixelColor(1, toast.height() // 2)
    if scheme is Scheme.HIGH_CONTRAST:
        assert corner.alpha() == 255  # opaque, square (phase-3 §7)
        assert theme.border_width == 2.0
        assert not toast.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    else:
        assert corner.alpha() == 0  # the rounded corner shows the desktop
        assert inside.name() == theme.palette.surface.name()
    assert stripe.name() == stripe_color(ToastKind.SUCCESS, theme.palette).name()
    assert stripe.name() == theme.palette.success.name()
    critical = make(ToastModel(ToastKind.CRITICAL, "changed", "x", 0), scheme=scheme)
    qtbot.addWidget(critical)
    critical.appear()
    image = render(critical)
    assert image.pixelColor(critical.width() // 2, 4).name() == theme.palette.critical_bg.name()
    assert image.pixelColor(1, critical.height() // 2).name() == theme.palette.critical.name()


def test_stripe_colors_follow_the_kind() -> None:
    p = Theme.build(Scheme.LIGHT).palette
    assert stripe_color(ToastKind.WORKING, p) == p.accent
    assert stripe_color(ToastKind.WARNING, p) == p.caution
    assert stripe_color(ToastKind.ERROR, p) == p.critical
    assert stripe_color(ToastKind.INFO, p) == p.text_secondary


def test_the_bar_shows_for_a_batch_and_text_only_without_motion(qtbot: QtBot) -> None:
    batch = make(working_toast(4, "WebP", done=1), motion=True)
    qtbot.addWidget(batch)
    batch.appear()
    batch.settle()
    assert batch.bar.isVisible()
    assert batch.bar.progress == (1, 4)
    batch.update_model(working_toast(4, "WebP", done=3))
    assert batch.bar.progress == (3, 4)
    assert batch.model.body == "3 / 4"
    quiet = make(working_toast(4, "WebP", done=1), motion=False)
    qtbot.addWidget(quiet)
    quiet.appear()
    assert not quiet.bar.isVisible()  # §8: "5 / 12" as text when animations are off
    assert quiet.model.body == "1 / 4"
    single = make(working_toast(1, "WebP", name="a.png"), motion=True)
    qtbot.addWidget(single)
    single.appear()
    assert not single.bar.isVisible()
    assert single.model.progress is None
    assert single.buttons == []


@pytest.mark.usefixtures("rtl")
def test_rtl_mirrors_the_layout(qtbot: QtBot) -> None:
    toast = make(ToastModel(ToastKind.SUCCESS, "t", "b.jpg", 60_000, ACTIONS, Progress(1, 2)))
    qtbot.addWidget(toast)
    toast.appear()
    assert toast.close_button.geometry().left() < toast.width() // 2  # ✕ on the left
    # A Latin file name sits at the layout's leading edge too, not at its own script's
    assert toast._body.alignment() & Qt.AlignmentFlag.AlignRight
    assert toast._body.alignment() & Qt.AlignmentFlag.AlignAbsolute
    assert toast._body.contentsMargins().left() == 0
    assert toast._body.contentsMargins().right() > 0  # the indent under the title, mirrored
    assert toast.buttons[0].geometry().right() > toast.buttons[1].geometry().right()
    image = render(toast)
    assert image.pixelColor(toast.width() - 2, toast.height() // 2).name() == (
        stripe_color(ToastKind.SUCCESS, toast.theme.palette).name()
    )  # the stripe on the leading (right) edge
    assert image.pixelColor(STRIPE + 2, toast.height() // 2).name() == (
        toast.theme.palette.surface.name()
    )


def test_motion_off_appears_settled_and_dismisses_at_once(qtbot: QtBot) -> None:
    toast = make(motion=False)
    qtbot.addWidget(toast)
    toast.place(QPoint(100, 200))
    toast.appear()
    assert toast.isVisible()
    assert toast.pos() == QPoint(100, 200)
    assert toast.windowOpacity() == 1.0
    assert toast.settled
    with qtbot.waitSignal(toast.dismissed, timeout=1000):
        toast.dismiss()
    assert not toast.isVisible()


def test_motion_on_rises_fades_in_and_fades_out(qtbot: QtBot) -> None:
    toast = make(motion=True)
    qtbot.addWidget(toast)
    toast.place(QPoint(100, 200))
    toast.appear()
    assert toast.isVisible()
    assert toast.pos() == QPoint(100, 200 + RISE_PX)  # the first frame: 12 px lower, invisible
    assert toast.windowOpacity() == 0.0
    assert not toast.settled
    toast.settle()
    assert toast.pos() == QPoint(100, 200)
    assert toast.windowOpacity() == 1.0
    toast.dismiss()
    assert toast.isVisible()  # fading
    toast.settle()
    assert not toast.isVisible()  # hide() at the end of the fade
    assert toast.windowOpacity() == 0.0


def test_a_relayout_during_the_rise_wins(qtbot: QtBot) -> None:
    """The manager owns the position: a toast placed again mid-rise lands at the new spot."""
    toast = make(motion=True)
    qtbot.addWidget(toast)
    toast.place(QPoint(100, 200))
    toast.appear()
    toast.place(QPoint(100, 120))  # another toast arrived below
    assert toast.pos().x() == 100
    assert 120 <= toast.pos().y() <= 120 + RISE_PX
    toast.settle()
    assert toast.pos() == QPoint(100, 120)


def test_the_fade_survives_garbage_collection(qtbot: QtBot) -> None:
    """A fade that is collected halfway would leave a ghost toast; the animations are owned."""
    toast = make(motion=True)
    qtbot.addWidget(toast)
    toast.appear()
    toast.settle()
    toast.dismiss()
    gc.collect()
    qtbot.waitUntil(lambda: not toast.isVisible(), timeout=3000)
    assert toast.windowOpacity() == 0.0


def test_drop_hides_at_once_without_a_signal(qtbot: QtBot) -> None:
    toast = make(motion=True)
    qtbot.addWidget(toast)
    toast.appear()
    signalled: list[object] = []
    toast.dismissed.connect(signalled.append)
    toast.drop()
    assert not toast.isVisible()
    assert toast.settled
    qtbot.wait(50)
    assert signalled == []
    assert not toast.counting_down


def test_every_label_is_plain_text(qtbot: QtBot) -> None:
    markup = "<b>bold</b>"
    toast = make(ToastModel(ToastKind.ERROR, markup, markup, 60_000))
    qtbot.addWidget(toast)
    toast.appear()
    assert toast._title.textFormat() == Qt.TextFormat.PlainText
    assert toast._body.textFormat() == Qt.TextFormat.PlainText
    assert toast._title.text() == markup
    assert QColor(toast.theme.palette.text).isValid()
