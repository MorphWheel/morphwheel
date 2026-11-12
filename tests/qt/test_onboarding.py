"""The first-run bubble (phase-3 §6.3, RD-20): what it says, and the manager's ``closed`` and
``dismiss`` that the app builds the acknowledgement on."""

from __future__ import annotations

import pytest
from pytestqt.qtbot import QtBot

from morphwheel.settings.model import TRIGGER_KEYS, TriggerKey
from morphwheel.ui.onboarding import ONBOARDING_KEY, SETTINGS_PAGE, onboarding_toast
from morphwheel.ui.settings_window import PAGES
from morphwheel.ui.theme import Motion, Scheme, Theme
from morphwheel.ui.toasts.manager import ToastManager
from morphwheel.ui.toasts.model import STICKY, ActionKind, ToastKind, ToastModel
from morphwheel.ui.toasts.widget import ToastWidget, stripe_color

pytestmark = pytest.mark.usefixtures("qapp")

BUBBLE = onboarding_toast("shift")
OTHER = ToastModel(ToastKind.SUCCESS, "done", "", 60_000)


KEY_NAMES = {"shift": "Shift", "ctrl": "Ctrl", "ctrl+shift": "Ctrl+Shift"}


@pytest.mark.parametrize("key", TRIGGER_KEYS)  # a new key without a name fails here
def test_the_bubble_names_the_key_from_the_settings(key: TriggerKey) -> None:
    model = onboarding_toast(key)
    assert model.body == f"Drag an image in File Explorer, then press {KEY_NAMES[key]}."


def test_the_bubble_is_a_sticky_hint_with_two_buttons() -> None:
    assert BUBBLE.kind is ToastKind.HINT
    assert BUBBLE.title == "Morphwheel is running"
    assert BUBBLE.duration_ms == STICKY  # it waits for the user
    assert [(a.kind, a.label) for a in BUBBLE.actions] == [
        (ActionKind.DISMISS, "Got it"),
        (ActionKind.SETTINGS, "Settings"),
    ]
    assert BUBBLE.actions[1].payload == SETTINGS_PAGE
    assert SETTINGS_PAGE in PAGES  # a page the settings window really has


def test_the_hint_looks_like_the_app_speaking(qtbot: QtBot) -> None:
    theme = Theme.build(Scheme.DARK)
    toast = ToastWidget(BUBBLE, theme, Motion(False))
    qtbot.addWidget(toast)
    assert stripe_color(ToastKind.HINT, theme.palette) == theme.palette.accent
    assert [b.text() for b in toast.buttons] == ["Got it", "Settings"]
    assert toast.model.sticky


def still(**kw: object) -> ToastManager:
    return ToastManager(motion_enabled=lambda: False, **kw)  # type: ignore[arg-type]


def test_closed_means_the_user_closed_it(qtbot: QtBot) -> None:
    manager = still()
    closed: list[str] = []
    pages: list[str] = []
    manager.closed.connect(closed.append)
    manager.settings_clicked.connect(pages.append)

    toast = manager.show(BUBBLE, key=ONBOARDING_KEY)
    assert toast is not None
    toast.buttons[1].click()  # Settings: the page, then the close
    assert pages == [SETTINGS_PAGE]
    assert closed == [ONBOARDING_KEY]
    assert manager.visible == ()

    toast = manager.show(BUBBLE, key=ONBOARDING_KEY)
    assert toast is not None
    toast.buttons[0].click()  # Got it
    toast = manager.show(BUBBLE, key=ONBOARDING_KEY)
    assert toast is not None
    toast.close_button.click()  # ✕
    manager.show(BUBBLE, key=ONBOARDING_KEY)
    manager.dismiss(ONBOARDING_KEY)  # the app, on the first drop
    assert closed == [ONBOARDING_KEY] * 4
    assert pages == [SETTINGS_PAGE]

    manager.show(BUBBLE, key=ONBOARDING_KEY)
    manager.show(OTHER, key=ONBOARDING_KEY)  # a replacement by key is nobody closing anything
    assert closed == [ONBOARDING_KEY] * 4
    manager.dismiss_all()  # nor is the shutdown
    assert closed == [ONBOARDING_KEY] * 4
    unkeyed = manager.show(OTHER)
    assert unkeyed is not None
    unkeyed.close_button.click()  # no key, no signal
    assert closed == [ONBOARDING_KEY] * 4


def test_dismiss_reaches_a_delayed_and_a_held_toast(qtbot: QtBot) -> None:
    held = [False]
    manager = still(hold=lambda: held[0])
    closed: list[str] = []
    manager.closed.connect(closed.append)
    manager.show_later(BUBBLE, 20, key=ONBOARDING_KEY)
    manager.dismiss(ONBOARDING_KEY)  # the first drop came before the bubble showed
    qtbot.wait(80)
    assert manager.visible == ()
    assert manager.pending == ()

    held[0] = True
    manager.show(BUBBLE, key=ONBOARDING_KEY)
    manager.show(BUBBLE, key=ONBOARDING_KEY)  # held twice: both go
    assert manager.held == 2
    manager.dismiss(ONBOARDING_KEY)
    assert manager.held == 0
    held[0] = False
    manager.release()
    assert manager.visible == ()
    assert closed == []  # nothing was shown, nothing was closed
    manager.dismiss("no such key")  # harmless
    first = manager.show(OTHER, key="a")
    second = manager.show(OTHER, key="b")
    manager.dismiss("a")  # leaves at once (animations off): the walk must not skip a beat
    assert manager.visible == (second,)
    assert first is not None
    assert not first.isVisible()
    manager.dismiss_all()


def test_a_closed_slot_may_show_toasts_itself(qtbot: QtBot) -> None:
    """``closed`` fires last, after the toast left the stack: a slot can use the manager."""
    manager = still()
    shown: list[object] = []

    def on_closed(key: str) -> None:
        shown.append(manager.show(OTHER, key=key))

    manager.closed.connect(on_closed)
    toast = manager.show(BUBBLE, key=ONBOARDING_KEY)
    assert toast is not None
    toast.close_button.click()
    assert manager.visible == (shown[0],)
    assert manager.visible[0].model is OTHER
    manager.dismiss_all()


def test_dismiss_fades_then_closes_once_with_motion(qtbot: QtBot) -> None:
    manager = ToastManager(motion_enabled=lambda: True)
    closed: list[str] = []
    manager.closed.connect(closed.append)
    toast = manager.show(BUBBLE, key=ONBOARDING_KEY)
    assert toast is not None
    toast.settle()
    manager.dismiss(ONBOARDING_KEY)
    manager.dismiss(ONBOARDING_KEY)  # during the fade: still one close
    assert closed == []
    assert toast.dismissing
    toast.settle()
    assert closed == [ONBOARDING_KEY]
    assert manager.visible == ()
