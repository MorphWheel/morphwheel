"""Test helpers: the MVP builtin targets (phase-3 §2.2) and plugin-target / file builders."""

from __future__ import annotations

from pathlib import Path

from morphwheel.core.catalog import Catalog, SlotPos, Target, TargetKind
from morphwheel.core.formats import FileInfo, FormatId
from morphwheel.core.geometry import Point, WheelGeometry
from morphwheel.core.wheel_session import WheelSession

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


TWO_PNG_PLUGINS = Catalog.of(
    [*BUILTINS, plugin("p0", {FormatId.PNG}), plugin("p1", {FormatId.PNG})]
)


def planned_session(
    catalog: Catalog, files: tuple[str, ...], geometry: WheelGeometry | None = None
) -> WheelSession:
    """A session that appeared at the center at t=0 with ``files`` planned (none: waiting)."""
    session = WheelSession(geometry or WheelGeometry(), appear_at=Point(0, 0), t0_ns=0)
    if files:
        session.set_plan(catalog.plan([file(n) for n in files]))
    return session


def file(name: str, **kw: object) -> FileInfo:
    info = FileInfo.from_path(Path(name), is_dir=bool(kw.get("is_dir", False)))
    return FileInfo(
        path=info.path,
        format=info.format,
        animated=kw.get("animated"),  # type: ignore[arg-type]
        is_local=bool(kw.get("is_local", True)),
        is_dir=info.is_dir,
    )
