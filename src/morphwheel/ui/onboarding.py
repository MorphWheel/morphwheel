"""The first-run bubble (phase-3 §6.3): what it says. A sticky toast, shown by the toast manager.

Rules (RD-20):

- **A toast, not a window of its own.** The spec anchors the bubble to the work-area corner above
  the tray, not to the icon (a new icon usually sits in the overflow area), and that corner is
  where the toast stack lives. As a toast it never takes focus, waits while the wheel is up (C1),
  stacks with the result toasts, mirrors under RTL and follows High Contrast. No tail: it would
  point at nothing.
- **The key in the text is the key in the settings.** The bubble is worded once, when it is
  scheduled; opening the settings acknowledges it, so the key can't change under a live bubble.
- **Acknowledged by:** Got it, Settings (which also opens the window), ✕, opening the settings
  from the tray, or the first drop ("after the first conversion the regular toast appears; no
  celebration"). Quitting is not an acknowledgement: the bubble returns at the next start.
  The app records it as ``onboarding_done``; this module holds no state.
"""

from __future__ import annotations

from morphwheel.i18n import translate
from morphwheel.settings.model import TriggerKey
from morphwheel.ui.text import trigger_key_label
from morphwheel.ui.toasts.model import STICKY, ActionKind, ToastAction, ToastKind, ToastModel

ONBOARDING_KEY = "onboarding"
ONBOARDING_DELAY_MS = 800  # after the start: the tray icon is there first
SETTINGS_PAGE = "general"  # where the bubble's Settings button lands


def onboarding_toast(trigger_key: TriggerKey) -> ToastModel:
    body = translate("Onboarding", "Drag an image in File Explorer, then press %1.").replace(
        "%1", trigger_key_label(trigger_key)
    )
    actions = (
        ToastAction(ActionKind.DISMISS, translate("Onboarding", "Got it")),
        ToastAction(ActionKind.SETTINGS, translate("Onboarding", "Settings"), SETTINGS_PAGE),
    )
    return ToastModel(
        ToastKind.HINT, translate("Onboarding", "Morphwheel is running"), body, STICKY, actions
    )
