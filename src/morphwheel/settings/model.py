"""The user's settings: the model, its defaults and a tolerant parser (phase-4 §4.6).

Pure Python: no Qt, no I/O and no UI strings (the problem lines are for the log). ``store.py``
reads and writes the TOML file; this module only says what a settings document means.

Rules:

- **Every field has a default**, and the defaults are the product's (phase-3 §6.2, U4, P1-3):
  Shift, size M, JPG 90 / WebP 85 / AVIF 70, Compress at 2048 px and quality 80.
- **Parsing is tolerant.** Unknown keys are ignored, so a file written by a newer version still
  loads; a wrong type or an out-of-range value falls back to that field's default and is reported
  in ``Parsed.problems``. A document never fails to parse.
- **A bool is not an int.** ``quality.jpeg = true`` is a problem, not quality 1.
- **``language`` is a BCP-47 tag or empty** (Windows' display language, D3). It is read at
  start by ``i18n.install``; this module can't judge a tag (no Qt), so any string passes and
  an unknown one is the app's warning. No picker shows it in v0.1 (phase-3 §6.2).
- **The enums are case-insensitive** on the way in (``"Ctrl"``, ``"m"``) and canonical on the
  way out.
- ``WheelSize`` lives here and ``ui.wheel.window`` imports it. ``TriggerKey`` is spelled again in
  ``platform.modifier_poller``, which P1 keeps free of every other layer; the Literals are
  structural, so the value flows into ``set_key`` without a cast, and a test pins the two together.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from typing import Any, Literal, get_args

SCHEMA = 1

TriggerKey = Literal["shift", "ctrl", "ctrl+shift"]
WheelSize = Literal["S", "M", "L"]
TRIGGER_KEYS: tuple[TriggerKey, ...] = get_args(TriggerKey)
WHEEL_SIZES: tuple[WheelSize, ...] = get_args(WheelSize)

QUALITY_RANGE = (1, 100)
LONGEST_SIDE_RANGE = (1, 65_535)  # a side longer than the image means "no resize"


@dataclass(frozen=True)
class Quality:
    """Encoder quality per lossy format (phase-3 §6.2)."""

    jpeg: int = 90
    webp: int = 85
    avif: int = 70


@dataclass(frozen=True)
class Compress:
    """The Compress preset (D2, RD-7): resize to ``longest_side`` and re-encode at ``quality``."""

    longest_side: int = 2048
    quality: int = 80


@dataclass(frozen=True)
class PluginPrefs:
    """Which plugins are enabled and the order of the More arc (U3; consumed in S6)."""

    enabled: tuple[str, ...] = ()
    order: tuple[str, ...] = ()


@dataclass(frozen=True)
class Settings:
    schema: int = SCHEMA
    trigger_key: TriggerKey = "shift"
    wheel_size: WheelSize = "M"
    start_with_windows: bool = False
    paused: bool = False
    onboarding_done: bool = False
    language: str = ""  # "": Windows' display language; else a BCP-47 tag ("he")
    quality: Quality = Quality()
    compress: Compress = Compress()
    plugins: PluginPrefs = PluginPrefs()

    def converter_options(self) -> dict[str, object]:
        """The ``Task.options`` the built-in converter documents (``builtin/pillow_images``)."""
        return {
            "jpeg_quality": self.quality.jpeg,
            "webp_quality": self.quality.webp,
            "avif_quality": self.quality.avif,
            "compress_longest_side": self.compress.longest_side,
            "compress_quality": self.compress.quality,
        }


DEFAULTS = Settings()


def to_mapping(settings: Settings) -> dict[str, Any]:
    """The TOML document for ``settings``: scalars at the top, one table per group (the tuples
    become arrays)."""
    return asdict(settings)


@dataclass(frozen=True)
class Parsed:
    settings: Settings
    problems: tuple[str, ...]  # one line per field that fell back to its default


def parse_settings(data: Mapping[str, object]) -> Parsed:
    """Read a settings document tolerantly: bad values become defaults and problem lines."""
    p = _Parser(data)
    schema = p.int("schema", DEFAULTS.schema, 1, None)
    if schema > SCHEMA:
        p.problems.append(
            f"schema: {schema} was written by a newer Morphwheel (this one reads {SCHEMA}); "
            "settings it doesn't know are kept"
        )
    quality = p.table("quality")
    compress = p.table("compress")
    plugins = p.table("plugins")
    settings = Settings(
        schema=schema,
        trigger_key=p.choice("trigger_key", TRIGGER_KEYS, DEFAULTS.trigger_key, str.lower),
        wheel_size=p.choice("wheel_size", WHEEL_SIZES, DEFAULTS.wheel_size, str.upper),
        start_with_windows=p.bool("start_with_windows", DEFAULTS.start_with_windows),
        paused=p.bool("paused", DEFAULTS.paused),
        onboarding_done=p.bool("onboarding_done", DEFAULTS.onboarding_done),
        language=p.text("language", DEFAULTS.language),
        quality=Quality(
            jpeg=quality.int("jpeg", DEFAULTS.quality.jpeg, *QUALITY_RANGE),
            webp=quality.int("webp", DEFAULTS.quality.webp, *QUALITY_RANGE),
            avif=quality.int("avif", DEFAULTS.quality.avif, *QUALITY_RANGE),
        ),
        compress=Compress(
            longest_side=compress.int(
                "longest_side", DEFAULTS.compress.longest_side, *LONGEST_SIDE_RANGE
            ),
            quality=compress.int("quality", DEFAULTS.compress.quality, *QUALITY_RANGE),
        ),
        plugins=PluginPrefs(
            enabled=plugins.str_list("enabled"),
            order=plugins.str_list("order"),
        ),
    )
    return Parsed(settings, tuple(p.problems))


class _Parser:
    """One level of the document. ``table`` returns a nested parser that shares the problems."""

    def __init__(
        self, data: Mapping[str, object], prefix: str = "", problems: list[str] | None = None
    ) -> None:
        self._data = data
        self._prefix = prefix
        self.problems: list[str] = problems if problems is not None else []

    def _name(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def _problem(self, key: str, expected: str, value: object) -> None:
        self.problems.append(f"{self._name(key)}: expected {expected}, got {value!r}")

    def table(self, key: str) -> _Parser:
        value = self._data.get(key)
        if value is None:
            value = {}
        elif not isinstance(value, Mapping):
            self._problem(key, "a table", value)
            value = {}
        return _Parser(value, f"{key}.", self.problems)

    def int(self, key: str, default: int, low: int, high: int | None) -> int:
        value = self._data.get(key)
        if value is None:
            return default
        bound = f"{low}..{high}" if high is not None else f"{low} or more"
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < low
            or (high is not None and value > high)
        ):
            self._problem(key, f"an integer {bound}", value)
            return default
        return value

    def bool(self, key: str, default: bool) -> bool:
        value = self._data.get(key)
        if value is None:
            return default
        if not isinstance(value, bool):
            self._problem(key, "true or false", value)
            return default
        return value

    def choice[T: str](
        self, key: str, choices: tuple[T, ...], default: T, normalize: Callable[[str], str]
    ) -> T:
        value = self._data.get(key)
        if value is None:
            return default
        if isinstance(value, str):
            wanted = normalize(value.strip())
            for choice in choices:
                if choice == wanted:
                    return choice
        self._problem(key, "one of " + ", ".join(repr(c) for c in choices), value)
        return default

    def text(self, key: str, default: str) -> str:
        value = self._data.get(key)
        if value is None:
            return default
        if not isinstance(value, str):
            self._problem(key, "a string", value)
            return default
        return value.strip()

    def str_list(self, key: str) -> tuple[str, ...]:
        value = self._data.get(key)
        if value is None:
            return ()
        if not isinstance(value, list | tuple):
            self._problem(key, "a list of strings", value)
            return ()
        kept: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                self._problem(key, "a list of strings", item)
                continue
            if item not in kept:
                kept.append(item)
        return tuple(kept)
