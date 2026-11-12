"""``settings.model``: defaults, the TOML round trip, and the tolerant parser's fallback table."""

from __future__ import annotations

import tomllib
from typing import Any

import pytest
import tomli_w

from morphwheel.settings.model import (
    DEFAULTS,
    SCHEMA,
    TRIGGER_KEYS,
    WHEEL_SIZES,
    Compress,
    PluginPrefs,
    Quality,
    Settings,
    parse_settings,
    to_mapping,
)


def test_defaults_are_the_products() -> None:
    assert (
        Settings(
            schema=1,
            trigger_key="shift",
            wheel_size="M",
            start_with_windows=False,
            paused=False,
            onboarding_done=False,
            quality=Quality(jpeg=90, webp=85, avif=70),
            compress=Compress(longest_side=2048, quality=80),
            plugins=PluginPrefs(enabled=(), order=()),
        )
        == DEFAULTS
    )
    assert SCHEMA == 1
    assert TRIGGER_KEYS == ("shift", "ctrl", "ctrl+shift")  # D8: no Alt
    assert WHEEL_SIZES == ("S", "M", "L")


def test_converter_options_use_the_converters_keys() -> None:
    from morphwheel.builtin.pillow_images import converter

    settings = Settings(quality=Quality(1, 2, 3), compress=Compress(4, 5))
    assert settings.converter_options() == {
        "jpeg_quality": 1,
        "webp_quality": 2,
        "avif_quality": 3,
        "compress_longest_side": 4,
        "compress_quality": 5,
    }
    # The defaults agree with the converter's own, so a missing file changes nothing.
    assert DEFAULTS.converter_options() == {
        **{f"{fmt}_quality": q for fmt, q in converter.QUALITY.items()},
        "compress_longest_side": converter.COMPRESS_LONGEST_SIDE,
        "compress_quality": converter.COMPRESS_QUALITY,
    }


def test_round_trip_through_real_toml() -> None:
    settings = Settings(
        trigger_key="ctrl+shift",
        wheel_size="L",
        start_with_windows=True,
        paused=True,
        onboarding_done=True,
        language="he",
        quality=Quality(jpeg=50, webp=60, avif=70),
        compress=Compress(longest_side=1024, quality=40),
        plugins=PluginPrefs(enabled=("a", "b"), order=("b", "a")),
    )
    text = tomli_w.dumps(to_mapping(settings))
    parsed = parse_settings(tomllib.loads(text))
    assert parsed.settings == settings
    assert parsed.problems == ()


def test_empty_document_is_the_defaults() -> None:
    assert parse_settings({}) == parse_settings(to_mapping(DEFAULTS))
    assert parse_settings({}).settings == DEFAULTS
    assert parse_settings({}).problems == ()


def test_unknown_keys_are_ignored_without_a_problem() -> None:
    parsed = parse_settings({"future": 1, "quality": {"jxl": 90}, "plugins": {"pinned": ["x"]}})
    assert parsed.settings == DEFAULTS
    assert parsed.problems == ()


def test_a_newer_schema_is_read_and_reported() -> None:
    parsed = parse_settings({"schema": 7, "wheel_size": "L"})
    assert parsed.settings.schema == 7
    assert parsed.settings.wheel_size == "L"
    assert len(parsed.problems) == 1
    assert parsed.problems[0].startswith("schema: 7 was written by a newer Morphwheel")


@pytest.mark.parametrize(
    ("document", "field_name"),
    [
        ({"schema": 0}, "schema"),
        ({"schema": "1"}, "schema"),
        ({"trigger_key": "alt"}, "trigger_key"),  # D8: no Alt
        ({"trigger_key": 1}, "trigger_key"),
        ({"wheel_size": "XL"}, "wheel_size"),
        ({"wheel_size": ["M"]}, "wheel_size"),
        ({"start_with_windows": "yes"}, "start_with_windows"),
        ({"paused": 1}, "paused"),
        ({"onboarding_done": "true"}, "onboarding_done"),
        ({"quality": {"jpeg": 0}}, "quality.jpeg"),
        ({"quality": {"jpeg": 101}}, "quality.jpeg"),
        ({"quality": {"webp": True}}, "quality.webp"),  # a bool is not an int
        ({"quality": {"avif": "high"}}, "quality.avif"),
        ({"quality": {"avif": 70.0}}, "quality.avif"),
        ({"quality": 5}, "quality"),  # a table given as a scalar
        ({"compress": {"longest_side": 0}}, "compress.longest_side"),
        ({"compress": {"longest_side": 65_536}}, "compress.longest_side"),
        ({"compress": {"quality": -1}}, "compress.quality"),
        ({"compress": [{"quality": 1}]}, "compress"),  # an array of tables
        ({"language": 3}, "language"),
        ({"plugins": {"enabled": "a"}}, "plugins.enabled"),
        ({"plugins": {"order": [1]}}, "plugins.order"),
        ({"plugins": {"order": [""]}}, "plugins.order"),
    ],
)
def test_a_bad_value_falls_back_to_its_default_and_is_reported(
    document: dict[str, Any], field_name: str
) -> None:
    parsed = parse_settings(document)
    assert parsed.settings == DEFAULTS
    assert len(parsed.problems) == 1, parsed.problems
    assert parsed.problems[0].startswith(field_name + ":"), parsed.problems[0]


def test_problems_accumulate_and_the_good_fields_survive() -> None:
    parsed = parse_settings(
        {"trigger_key": "alt", "wheel_size": "S", "quality": {"jpeg": 200, "webp": 30}}
    )
    assert parsed.settings.wheel_size == "S"
    assert parsed.settings.quality == Quality(jpeg=90, webp=30, avif=70)
    assert [p.split(":")[0] for p in parsed.problems] == ["trigger_key", "quality.jpeg"]


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("trigger_key", "Ctrl", "ctrl"),
        ("trigger_key", " CTRL+SHIFT ", "ctrl+shift"),
        ("wheel_size", "m", "M"),
        ("wheel_size", "l", "L"),
    ],
)
def test_enums_are_normalized(key: str, value: str, expected: str) -> None:
    parsed = parse_settings({key: value})
    assert getattr(parsed.settings, key) == expected
    assert parsed.problems == ()


def test_the_language_is_windows_unless_a_tag_is_given() -> None:
    assert DEFAULTS.language == ""  # Windows' display language (D3); no picker in v0.1
    assert parse_settings({"language": " he "}).settings.language == "he"
    assert parse_settings({"language": "xx-nonsense"}).problems == ()  # the app judges a tag


def test_plugin_lists_are_deduplicated_and_cleaned() -> None:
    parsed = parse_settings({"plugins": {"enabled": ["a", "b", "a"], "order": ["b", 2, "b", "c"]}})
    assert parsed.settings.plugins == PluginPrefs(enabled=("a", "b"), order=("b", "c"))
    assert len(parsed.problems) == 1  # the 2
    assert parsed.problems[0].startswith("plugins.order:")


def test_the_model_is_frozen_and_hashable() -> None:
    with pytest.raises(AttributeError):
        DEFAULTS.paused = True  # type: ignore[misc]
    assert hash(DEFAULTS) == hash(Settings())
    assert DEFAULTS is not Settings()
