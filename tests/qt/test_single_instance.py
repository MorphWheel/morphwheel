"""``platform.single_instance``: the mutex guards, the pipe carries "open the settings". Unique
names per test, so a Morphwheel running on this machine is never touched."""

from __future__ import annotations

import pytest
from pytestqt.qtbot import QtBot

from morphwheel.platform.single_instance import SingleInstance, pipe_name, session_id

pytestmark = pytest.mark.usefixtures("qapp")


def test_the_names_follow_the_session() -> None:
    assert session_id() >= 0
    assert pipe_name() == f"morphwheel-{session_id()}"


def test_the_mutex_guards_and_release_frees_the_name(instance_names: tuple[str, str]) -> None:
    mutex, pipe = instance_names
    first = SingleInstance(mutex, pipe)
    assert first.acquire()
    assert first.held
    second = SingleInstance(mutex, pipe)
    assert not second.acquire()  # the same name, even from the same process
    assert not second.held
    first.release()
    first.release()  # idempotent
    assert not first.held
    third = SingleInstance(mutex, pipe)
    assert third.acquire()  # the refused handle was closed too, or the name would live on
    third.release()


def test_a_knock_asks_for_the_settings(qtbot: QtBot, instance_names: tuple[str, str]) -> None:
    mutex, pipe = instance_names
    first = SingleInstance(mutex, pipe)
    assert first.acquire()
    assert first.listen()
    assert first.listen()  # idempotent: start() may run twice
    second = SingleInstance(mutex, pipe)
    assert not second.acquire()
    with qtbot.waitSignal(first.settings_requested, timeout=2000):
        assert second.ping()
    first.release()
    assert not SingleInstance(mutex, pipe).ping(timeout_ms=200)  # nobody listens: fast, False


def test_a_knock_before_the_first_listens_is_lost_quietly(
    qtbot: QtBot, instance_names: tuple[str, str]
) -> None:
    mutex, pipe = instance_names
    first = SingleInstance(mutex, pipe)
    assert first.acquire()
    assert not SingleInstance(mutex, pipe).ping(timeout_ms=200)
    first.release()
