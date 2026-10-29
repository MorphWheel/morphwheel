"""``platform.modifier_poller``: the key table, edges only, the reset on start, and the timer.

The reader and the clock are injected, so every sample is deterministic. One test lets the real
QTimer fire, to prove the wiring; the rest call ``_sample()`` directly.
"""

from __future__ import annotations

from typing import Any

import pytest
from pytestqt.qtbot import QtBot

from morphwheel.platform import _win32 as w
from morphwheel.platform.modifier_poller import (
    POLL_INTERVAL_MS,
    TRIGGER_KEYS,
    ModifierPoller,
    TriggerKey,
    key_state,
)

pytestmark = pytest.mark.usefixtures("qapp")


class Keys:
    """A fake keyboard: a set of virtual keys that are down."""

    def __init__(self) -> None:
        self.down: set[int] = set()

    def __call__(self, vk: int) -> bool:
        return vk in self.down


@pytest.mark.parametrize(
    ("key", "held", "expected"),
    [
        ("shift", {w.VK_SHIFT}, True),
        ("shift", {w.VK_SHIFT, w.VK_CONTROL}, True),  # inclusive
        ("shift", {w.VK_CONTROL}, False),
        ("ctrl", {w.VK_CONTROL}, True),
        ("ctrl", {w.VK_SHIFT}, False),
        ("ctrl+shift", {w.VK_CONTROL, w.VK_SHIFT}, True),
        ("ctrl+shift", {w.VK_SHIFT}, False),
        ("ctrl+shift", set(), False),
    ],
)
def test_key_table(key: TriggerKey, held: set[int], expected: bool) -> None:
    keys = Keys()
    keys.down = held
    assert key_state(keys, key) is expected


def test_every_trigger_key_is_accepted_and_unknown_ones_are_not() -> None:
    poller = ModifierPoller(reader=Keys())
    for key in TRIGGER_KEYS:
        poller.set_key(key)
        assert poller.key == key
    with pytest.raises(ValueError, match="alt"):
        poller.set_key("alt")  # type: ignore[arg-type]  # D8: no Alt


@pytest.fixture
def poller() -> tuple[ModifierPoller, Keys, list[Any], list[int]]:
    keys = Keys()
    ticks: list[int] = [0]

    def clock() -> int:
        ticks[0] += 8_000_000
        return ticks[0]

    p = ModifierPoller(reader=keys, clock=clock)
    seen: list[Any] = []
    sampled: list[int] = []
    p.changed.connect(lambda v: seen.append(("changed", v)))
    p.escape.connect(lambda: seen.append("esc"))
    p.sampled.connect(sampled.append)
    return p, keys, seen, sampled


def test_edges_only_and_a_tick_every_sample(
    poller: tuple[ModifierPoller, Keys, list[Any], list[int]],
) -> None:
    p, keys, seen, sampled = poller
    p._sample()
    p._sample()  # still up: no edge
    keys.down.add(w.VK_SHIFT)
    p._sample()
    p._sample()  # still down: no edge
    keys.down.clear()
    p._sample()
    assert seen == [("changed", True), ("changed", False)]
    assert sampled == [8_000_000 * n for n in range(1, 6)]  # t_ns from the clock, every sample


def test_start_forgets_a_held_key(
    poller: tuple[ModifierPoller, Keys, list[Any], list[int]],
) -> None:
    p, keys, seen, _ = poller
    keys.down.add(w.VK_SHIFT)
    p.start()
    p._sample()
    p.stop()
    p.start()  # a new gesture while Shift is still held: the first sample is an edge again
    p._sample()
    p.stop()
    assert seen == [("changed", True), ("changed", True)]


def test_set_key_applies_at_the_next_sample(
    poller: tuple[ModifierPoller, Keys, list[Any], list[int]],
) -> None:
    p, keys, seen, _ = poller
    keys.down.add(w.VK_SHIFT)
    p.set_key("ctrl")
    p._sample()
    assert seen == []
    p.set_key("shift")
    p._sample()
    assert seen == [("changed", True)]
    p.set_key("ctrl+shift")
    p._sample()
    assert seen == [("changed", True), ("changed", False)]


def test_escape_is_an_edge(
    poller: tuple[ModifierPoller, Keys, list[Any], list[int]],
) -> None:
    p, keys, seen, _ = poller
    keys.down.add(w.VK_ESCAPE)
    p._sample()
    p._sample()
    keys.down.clear()
    p._sample()
    keys.down.add(w.VK_ESCAPE)
    p._sample()
    assert seen == ["esc", "esc"]


def test_the_timer_really_samples(qtbot: QtBot) -> None:
    keys = Keys()
    p = ModifierPoller(reader=keys)
    assert p._timer.interval() == POLL_INTERVAL_MS
    assert not p.active
    p.start()
    p.start()  # idempotent
    assert p.active
    with qtbot.waitSignal(p.sampled, timeout=2000):
        pass
    keys.down.add(w.VK_SHIFT)
    with qtbot.waitSignal(p.changed, timeout=2000) as blocker:
        pass
    assert blocker.args == [True]
    p.stop()
    assert not p.active
