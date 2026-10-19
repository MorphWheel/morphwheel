"""Test helpers: the MVP builtin targets (phase-3 §2.2) and plugin-target / file builders."""

from __future__ import annotations

from pathlib import Path

from morphwheel.core.catalog import SlotPos, Target, TargetKind
from morphwheel.core.formats import FileInfo, FormatId

F = FormatId
IMAGE_INPUTS = frozenset({F.JPEG, F.PNG, F.WEBP, F.AVIF, F.HEIC, F.BMP, F.TIFF, F.GIF})


def convert(tid: str, label: str, out: FormatId, slot: SlotPos) -> Target:
    return Target(tid, label, TargetKind.CONVERT, out, IMAGE_INPUTS - {out}, "builtin", True, slot)


BUILTINS: tuple[Target, ...] = (
    convert("jpeg", "JPG", F.JPEG, SlotPos.N),
    convert("png", "PNG", F.PNG, SlotPos.NE),
    convert("webp", "WebP", F.WEBP, SlotPos.E),
    convert("avif", "AVIF", F.AVIF, SlotPos.SE),
    Target(
        "compress",
        "Compress",
        TargetKind.COMPRESS,
        None,
        frozenset({F.JPEG, F.PNG, F.WEBP, F.AVIF}),
        "builtin",
        True,
        SlotPos.S,
    ),
    convert("pdf", "PDF", F.PDF, SlotPos.SW),
    convert("ico", "ICO", F.ICO, SlotPos.W),
)


def plugin(tid: str, accepts: set[FormatId] | None = None, **kw: object) -> Target:
    args: dict[str, object] = {
        "id": tid,
        "label": tid.upper(),
        "kind": TargetKind.CONVERT,
        "output_format": F.TIFF,
        "accepts": frozenset(accepts or {F.HEIC}),
        "provider": "com.example." + tid,
    }
    args.update(kw)
    return Target(**args)  # type: ignore[arg-type]


def file(name: str, **kw: object) -> FileInfo:
    info = FileInfo.from_path(Path(name), is_dir=bool(kw.get("is_dir", False)))
    return FileInfo(
        path=info.path,
        format=info.format,
        animated=kw.get("animated"),  # type: ignore[arg-type]
        is_local=bool(kw.get("is_local", True)),
        is_dir=info.is_dir,
    )
