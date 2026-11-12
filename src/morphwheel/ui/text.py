"""The labels several surfaces share (the tray tooltip, the settings window, the first-run bubble).

The texts live in a table, so they are marked for the extractor with ``QT_TRANSLATE_NOOP`` and
looked up with Qt's own ``translate``: ``i18n.translate`` takes literals only (its docstring says
why), and a test holds every ``ui`` module to that.
"""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication

from morphwheel.i18n import QT_TRANSLATE_NOOP
from morphwheel.settings.model import TriggerKey

_KEY_LABELS: dict[str, str] = {
    "shift": QT_TRANSLATE_NOOP("Keys", "Shift"),
    "ctrl": QT_TRANSLATE_NOOP("Keys", "Ctrl"),
    "ctrl+shift": QT_TRANSLATE_NOOP("Keys", "Ctrl+Shift"),
}


def trigger_key_label(key: TriggerKey) -> str:
    """The key's name as Windows writes it."""
    return QCoreApplication.translate("Keys", _KEY_LABELS[key])
