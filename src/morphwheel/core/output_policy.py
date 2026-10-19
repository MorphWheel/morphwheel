"""Where an output goes, and what it is called (phase-2 §3.4, D2).

- **Name.** A conversion gives ``<stem><ext>``. Compress gives ``<stem> (compressed)<ext>``, keeping
  the source's own extension.
- **Collision.** The name gets `` (1)``, `` (2)``, … up to ``MAX_COLLISION_SUFFIX``. These are only
  *candidates*: ``engine.file_ops.reserve_unique`` claims one atomically (exclusive create), so a
  file is never overwritten, even in a race.
- **Never the source.** A candidate equal to the source path is never produced. That can happen when
  the bytes disagree with the extension, e.g. ``a.jpg`` that is really a PNG, converted to JPEG.
- **Fallback.** If the source folder can't be written to, outputs go to the fallback folder
  (``Downloads\\Morphwheel``), and the toast says so.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

from morphwheel.core.catalog import Target, TargetKind
from morphwheel.core.formats import OUTPUT_EXTENSION

MAX_COLLISION_SUFFIX = 999
COMPRESSED_TAG = "compressed"


def output_extension(source: Path, target: Target) -> str:
    if target.kind is TargetKind.COMPRESS or target.output_format is None:
        return source.suffix
    return OUTPUT_EXTENSION[target.output_format]


def candidate_paths(source: Path, target: Target, directory: Path | None = None) -> Iterator[Path]:
    """Output paths to try, in order. Finite: the base name, then ``(1)`` to ``(999)``."""
    folder = source.parent if directory is None else directory
    stem = source.stem
    if target.kind is TargetKind.COMPRESS:
        stem = f"{stem} ({COMPRESSED_TAG})"
    ext = output_extension(source, target)
    forbidden = str(source).casefold()  # Windows paths are case-insensitive
    names = (f"{stem}{ext}", *(f"{stem} ({n}){ext}" for n in range(1, MAX_COLLISION_SUFFIX + 1)))
    for name in names:
        candidate = folder / name
        if str(candidate).casefold() != forbidden:
            yield candidate


def output_directory(
    source: Path, *, writable: Callable[[Path], bool], fallback_dir: Path
) -> tuple[Path, bool]:
    """``(folder, used_fallback)``. The writability probe is injected, so this stays pure."""
    if writable(source.parent):
        return source.parent, False
    return fallback_dir, True
