"""Start with Windows (phase-4 §5): the user's Run value, ``HKCU\\…\\Run\\Morphwheel``. No Qt.

Rules (RD-23):

- **The registry is the truth at start, the setting after a change.** The installer's checkbox
  writes the same value (phase-4 §10), the uninstaller deletes it, and Task Manager's "Disable"
  marks it in ``StartupApproved``; none of them can edit ``settings.toml``. So the app adopts
  ``is_enabled()`` into the setting when it starts, and ``sync`` writes the registry only when the
  user changes the toggle, or to refresh the path of an entry that is on.
- **Only the installed app touches the registry.** From source the command would be a venv's
  ``python.exe`` at every sign-in, and a delete could take an installed Morphwheel's entry away on
  the same machine: ``sync`` then changes nothing, and ``is_enabled`` has no verdict (``None``),
  so the app doesn't adopt the registry either. The setting still saves.
- **Idempotent and quiet.** A missing value on ``sync(False)`` is fine; any other failure is a
  warning and ``False`` (the user's own hive is writable in practice).
- Tests pass their own key paths and never touch the real ones.
"""

from __future__ import annotations

import logging
import winreg

from morphwheel.platform import system

log = logging.getLogger("morphwheel.platform.autostart")

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
VALUE_NAME = "Morphwheel"
_DISABLED_MARK = 0x03  # the first byte Task Manager writes for a disabled entry


def command_line() -> str | None:
    """What the Run value should say, or ``None`` from source (not an installed app)."""
    if not system.is_frozen():
        return None
    return system.restart_command_line()


def is_enabled(*, run_key: str = RUN_KEY, approved_key: str = APPROVED_KEY) -> bool | None:
    """The Run value exists and Task Manager hasn't disabled it; ``None`` from source."""
    if not system.is_frozen():
        return None
    if system.hkcu_value(run_key, VALUE_NAME) is None:
        return False
    mark = system.hkcu_value(approved_key, VALUE_NAME)  # None: no verdict from Task Manager
    return not (isinstance(mark, bytes) and mark[:1] == bytes([_DISABLED_MARK]))


def sync(enabled: bool, *, run_key: str = RUN_KEY, approved_key: str = APPROVED_KEY) -> bool:
    """Make the registry say ``enabled``: write the current command, or delete the value."""
    command = command_line()
    if command is None:
        log.info("autostart: not an installed app, the Run value is left alone")
        return True
    try:
        if enabled:
            if system.hkcu_value(run_key, VALUE_NAME) != command:  # every settings change comes
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, run_key) as key:  # through here
                    winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
                log.info("autostart on: %s", command)
            _delete_value(approved_key)  # Task Manager's "Disable" would otherwise still hold
        elif _delete_value(run_key):
            log.info("autostart off")
    except OSError as e:
        log.warning("autostart: couldn't change the Run value: %s", e)
        return False
    return True


def _delete_value(key_path: str) -> bool:
    """``True`` when something was deleted; a missing key or value is nothing to do."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        return False
    return True
