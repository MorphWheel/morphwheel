"""``platform.autostart``: the Run value, against a throwaway key, never the real one (RD-23)."""

from __future__ import annotations

import sys
import uuid
import winreg
from collections.abc import Iterator

import pytest

if sys.platform != "win32":  # pragma: no cover
    pytest.skip("Win32 only", allow_module_level=True)

import contextlib

from morphwheel.platform import autostart, system
from morphwheel.platform.autostart import VALUE_NAME, command_line, is_enabled, sync


@pytest.fixture
def keys() -> Iterator[tuple[str, str]]:
    """A throwaway Run key and StartupApproved key under HKCU, deleted afterwards."""
    root = r"Software\Morphwheel\Test\autostart-" + uuid.uuid4().hex[:8]
    run_key, approved_key = root + r"\Run", root + r"\StartupApproved"
    try:
        yield run_key, approved_key
    finally:
        for key in (run_key, approved_key):
            with contextlib.suppress(OSError):
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        with contextlib.suppress(OSError):
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, root)


@pytest.fixture
def frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system, "is_frozen", lambda: True)


def _value(key: str) -> object:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
        return winreg.QueryValueEx(handle, VALUE_NAME)[0]


@pytest.mark.usefixtures("frozen")
def test_the_installed_app_writes_its_own_command(keys: tuple[str, str]) -> None:
    run_key, approved_key = keys
    command = command_line()
    assert command is not None
    assert command.startswith('"')
    assert command.endswith('"')
    assert not is_enabled(run_key=run_key, approved_key=approved_key)
    assert sync(True, run_key=run_key, approved_key=approved_key)
    assert _value(run_key) == command
    assert is_enabled(run_key=run_key, approved_key=approved_key)

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, run_key) as handle:
        winreg.SetValueEx(handle, VALUE_NAME, 0, winreg.REG_SZ, '"C:\\old\\morphwheel.exe"')
    assert sync(True, run_key=run_key, approved_key=approved_key)  # a moved exe: refreshed
    assert _value(run_key) == command

    assert sync(False, run_key=run_key, approved_key=approved_key)
    assert not is_enabled(run_key=run_key, approved_key=approved_key)
    assert sync(False, run_key=run_key, approved_key=approved_key)  # nothing there: still fine


@pytest.mark.usefixtures("frozen")
def test_task_managers_disable_counts_as_off(keys: tuple[str, str]) -> None:
    run_key, approved_key = keys
    assert sync(True, run_key=run_key, approved_key=approved_key)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, approved_key) as handle:
        winreg.SetValueEx(handle, VALUE_NAME, 0, winreg.REG_BINARY, bytes([3]) + bytes(11))
    assert not is_enabled(run_key=run_key, approved_key=approved_key)
    assert sync(True, run_key=run_key, approved_key=approved_key)  # the user turned it on again
    assert is_enabled(run_key=run_key, approved_key=approved_key)
    with pytest.raises(FileNotFoundError):
        _value(approved_key)  # the Disable mark is gone


def test_from_source_the_registry_is_left_alone(
    keys: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    run_key, approved_key = keys
    monkeypatch.setattr(system, "is_frozen", lambda: True)
    assert sync(True, run_key=run_key, approved_key=approved_key)  # an installed app's entry
    monkeypatch.setattr(system, "is_frozen", lambda: False)
    assert command_line() is None
    assert is_enabled(run_key=run_key, approved_key=approved_key) is None  # no verdict
    assert sync(True, run_key=run_key, approved_key=approved_key)  # true: the setting may save
    assert sync(False, run_key=run_key, approved_key=approved_key)  # and nothing is deleted
    monkeypatch.setattr(system, "is_frozen", lambda: True)
    assert is_enabled(run_key=run_key, approved_key=approved_key)  # the installed entry survived


@pytest.mark.usefixtures("frozen")
def test_a_refused_write_is_a_false_not_an_error(
    keys: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    run_key, approved_key = keys

    def refused(*a: object, **k: object) -> None:
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(autostart.winreg, "SetValueEx", refused)
    assert not sync(True, run_key=run_key, approved_key=approved_key)
    assert not is_enabled(run_key=run_key, approved_key=approved_key)
