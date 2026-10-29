"""The public plugin SDK (phase-4 §4.5). Plugin authors import **only** this module.

It uses the standard library alone (rule R3, enforced by import-linter), so a plugin needs nothing
from Morphwheel's internals, and this module can't change behind an author's back. Morphwheel's
own builtin converter (``morphwheel.builtin.pillow_images``) is written against the same API, so
the API is exercised from sprint S3 on.

Contract for a converter:

- ``convert(ctx)`` reads ``ctx.input_path`` and writes **only** to ``ctx.output_path``, a temp file
  Morphwheel chose. Morphwheel renames it to its final name afterwards; the converter never picks
  names, never writes elsewhere, and never touches the input (the source is fingerprinted before
  and after, and a change is reported as a critical error).
- Raise :class:`ConversionError` (or a subclass) for an expected failure. The message is shown to
  the user, so keep it short and free of paths. Any other exception is reported as a plugin error
  with its traceback in the log.
- ``ctx.progress(fraction)`` is optional and cheap; call it for long conversions.
- Converters run in worker processes without Qt. They must be importable without side effects.

Versioning: ``API_VERSION`` is ``(major, minor)``. A manifest's ``api`` must match the major and,
while the major is 0, also the minor.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, runtime_checkable

API_VERSION: tuple[int, int] = (0, 1)


@runtime_checkable
class ConversionContext(Protocol):
    """What a converter is given for one file."""

    @property
    def input_path(self) -> Path:
        """The source file. Read-only by contract."""
        ...

    @property
    def output_path(self) -> Path:
        """The temp file to write. It exists and is empty when ``convert`` starts."""
        ...

    @property
    def target_id(self) -> str:
        """The target's id as declared in ``plugin.toml`` (for example ``"jpeg"``)."""
        ...

    @property
    def options(self) -> Mapping[str, object]:
        """Quality and compress presets, read-only. Keys are documented per target."""
        ...

    def progress(self, fraction: float) -> None:
        """Report progress in ``[0.0, 1.0]``. May be called often; it never raises."""
        ...


@runtime_checkable
class Converter(Protocol):
    def convert(self, ctx: ConversionContext) -> None: ...


class ConversionError(Exception):
    """An expected failure. The message is shown in the toast."""


class UnreadableInputError(ConversionError):
    """The input can't be decoded: damaged, truncated, or not what its extension says."""


class UnsupportedAnimatedError(ConversionError):
    """The input is an animated image. Animated inputs are out of scope (phase-2 §3.3)."""


class EngineMissingError(ConversionError):
    """The format needs an engine that isn't installed, such as HEIC support (decision A6)."""
