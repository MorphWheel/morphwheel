"""The builtin converter: Pillow behind the public plugin API (phase-2 §3.3, phase-3 §2.2).

It is written like a third-party plugin: it imports ``morphwheel.plugins.api`` and Pillow, and
nothing else of Morphwheel. Workers import it through the manifest's ``entry``; the GUI never does.

Conversion rules (phase-2 §3.3):

- **Orientation is applied** (EXIF orientation → pixels), then the tag is dropped.
- **Transparency → white** for JPG and PDF, which have no alpha. Other outputs keep it.
- **Metadata travels when the format can carry it:** EXIF for JPG, PNG, WebP, AVIF; the ICC
  profile for JPG, PNG, WebP, AVIF. ICO and PDF carry neither.
- **Animated inputs are refused** (``UnsupportedAnimatedError``). The wheel already blocks them;
  the worker checks again for drops that came before the sniff finished.
- **HEIC needs the opt-in engine** (A6). ``pillow_heif`` is imported lazily, on the first HEIC
  input, and looked for again on every attempt, so an engine installed while the worker was alive
  is picked up. Without it: ``EngineMissingError``.
- **Decompression bombs:** Pillow's default limit stays on; an absurdly large image is an
  ``UnreadableInputError``.

Quality defaults (phase-3 §6.2): JPG 90, WebP 85, AVIF 70; Compress 2048 px longest side at
quality 80. ``ctx.options`` may override them with ``jpeg_quality``, ``webp_quality``,
``avif_quality``, ``compress_quality`` and ``compress_longest_side``.

**Compress (D2, RD-7):** never upscales. JPG, WebP and AVIF are resized to the longest side and
re-encoded at the compress quality. PNG has no quality: it is resized, re-encoded with
``optimize``, and turned into a palette image when that is lossless (at most 256 colors, no alpha).
Whether the result is smaller is judged by the worker, which discards it otherwise (NOT_SMALLER).
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageOps, UnidentifiedImageError

from morphwheel.plugins.api import (
    ConversionContext,
    ConversionError,
    EngineMissingError,
    UnreadableInputError,
    UnsupportedAnimatedError,
)

QUALITY: Mapping[str, int] = {"jpeg": 90, "webp": 85, "avif": 70}
# The lossy outputs: Pillow's format name and how the pixels are prepared (JPEG has no alpha).
LOSSY: Mapping[str, tuple[str, Callable[[Image.Image], Image.Image]]] = {
    "jpeg": ("JPEG", lambda im: _flatten(im)),
    "webp": ("WEBP", lambda im: _rgb_or_rgba(im)),
    "avif": ("AVIF", lambda im: _rgb_or_rgba(im)),
}
COMPRESS_LONGEST_SIDE = 2048
COMPRESS_QUALITY = 80
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
PNG_MODES = frozenset({"1", "L", "LA", "I", "P", "RGB", "RGBA"})
_HEIF_EXTENSIONS = frozenset({".heic", ".heif", ".hif"})
_HEIF_BRANDS = (b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1", b"msf1")

_heif_registered = False


class PillowConverter:
    def convert(self, ctx: ConversionContext) -> None:
        target = ctx.target_id
        with _open(ctx.input_path) as im:
            if getattr(im, "is_animated", False) or getattr(im, "n_frames", 1) > 1:
                raise UnsupportedAnimatedError("Animated images aren't supported")
            source_format = im.format or ""
            try:
                im.load()
            except (OSError, SyntaxError, ValueError) as e:  # truncated / damaged data
                raise UnreadableInputError("The file couldn't be read") from e
            ctx.progress(0.1)
            exif = im.getexif()
            icc = im.info.get("icc_profile")
            dpi = im.info.get("dpi")
            image = ImageOps.exif_transpose(im) or im
        exif = _strip_orientation(exif)
        ctx.progress(0.3)
        kwargs: dict[str, Any] = {}
        if len(exif):
            kwargs["exif"] = exif.tobytes()
        if icc:
            kwargs["icc_profile"] = icc

        if target in LOSSY:
            fmt, prepare = LOSSY[target]
            _save(prepare(image), ctx.output_path, fmt, quality=_q(ctx, target), **kwargs)
        elif target == "png":
            _save(_png_mode(image), ctx.output_path, "PNG", optimize=True, **kwargs)
        elif target == "ico":
            sizes = _ico_sizes(image)
            ico_kwargs: dict[str, Any] = {"sizes": sizes} if sizes else {}
            _save(_rgb_or_rgba(image), ctx.output_path, "ICO", **ico_kwargs)
        elif target == "pdf":
            resolution = float(dpi[0]) if isinstance(dpi, tuple) and dpi[0] else 72.0
            _save(_flatten(image), ctx.output_path, "PDF", resolution=resolution)
        elif target == "compress":
            _compress(ctx, image, source_format, kwargs)
        else:
            raise ConversionError(f"Unknown target {target!r}")
        ctx.progress(1.0)


# --------------------------------------------------------------------------- opening
def _open(path: Path) -> Image.Image:
    if path.suffix.lower() in _HEIF_EXTENSIONS:
        _ensure_heif()  # a mislabeled HEIC is caught below, after Pillow has refused it
    try:
        return Image.open(path)
    except UnidentifiedImageError as e:
        if _looks_like_heif(path):
            _ensure_heif()  # raises EngineMissingError when the engine isn't there
            try:
                return Image.open(path)  # HEIF is registered now
            except (UnidentifiedImageError, OSError):
                pass
        raise UnreadableInputError("The file couldn't be read") from e
    except Image.DecompressionBombError as e:
        raise UnreadableInputError("The image is too large to convert") from e
    except OSError as e:
        raise UnreadableInputError("The file couldn't be read") from e


def _looks_like_heif(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            head = f.read(32)
    except OSError:
        return False
    return head[4:8] == b"ftyp" and any(b in head[8:32] for b in _HEIF_BRANDS)


def _ensure_heif() -> None:
    """Register pillow-heif with Pillow, importing it now if it has appeared since the last try."""
    global _heif_registered
    if _heif_registered:
        return
    try:
        heif = importlib.import_module("pillow_heif")
    except ImportError as e:
        raise EngineMissingError("HEIC support isn't installed") from e
    heif.register_heif_opener()
    _heif_registered = True


# --------------------------------------------------------------------------- modes
def _flatten(im: Image.Image) -> Image.Image:
    """RGB on a white background (phase-2 §3.3): for JPG and PDF."""
    if im.mode == "RGB":
        return im
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return im.convert("RGB")


def _rgb_or_rgba(im: Image.Image) -> Image.Image:
    if im.mode in ("RGB", "RGBA"):
        return im
    has_alpha = im.mode in ("LA", "PA") or (im.mode == "P" and "transparency" in im.info)
    return im.convert("RGBA" if has_alpha else "RGB")


def _png_mode(im: Image.Image) -> Image.Image:
    return im if im.mode in PNG_MODES else _rgb_or_rgba(im)


def _ico_sizes(im: Image.Image) -> list[tuple[int, int]]:
    """The standard icon sizes that fit the image. Empty for a tiny one: Pillow keeps its size."""
    return [s for s in ICO_SIZES if s[0] <= im.width and s[1] <= im.height]


def _strip_orientation(exif: Image.Exif) -> Image.Exif:
    if 0x0112 in exif:
        del exif[0x0112]  # the pixels are upright now
    return exif


def _q(ctx: ConversionContext, fmt: str) -> int:
    return _int_option(ctx.options, f"{fmt}_quality", QUALITY[fmt])


def _int_option(options: Mapping[str, object], key: str, default: int) -> int:
    value = options.get(key, default)
    return value if isinstance(value, int) and not isinstance(value, bool) else default


# --------------------------------------------------------------------------- compress
def _compress(
    ctx: ConversionContext, image: Image.Image, source_format: str, kwargs: dict[str, Any]
) -> None:
    longest = _int_option(ctx.options, "compress_longest_side", COMPRESS_LONGEST_SIDE)
    quality = _int_option(ctx.options, "compress_quality", COMPRESS_QUALITY)
    image = _shrink(image, longest)
    ctx.progress(0.5)
    lossy = LOSSY.get(source_format.lower())
    if lossy is not None:
        fmt, prepare = lossy
        _save(prepare(image), ctx.output_path, fmt, quality=quality, **kwargs)
    elif source_format == "PNG":
        _save(
            _palette_if_lossless(_png_mode(image)), ctx.output_path, "PNG", optimize=True, **kwargs
        )
    else:
        raise ConversionError("Compress works on JPG, PNG, WebP and AVIF; convert first")


def _shrink(im: Image.Image, longest: int) -> Image.Image:
    if max(im.size) <= longest:
        return im
    scale = longest / max(im.size)
    size = (max(1, round(im.width * scale)), max(1, round(im.height * scale)))
    return im.resize(size, Image.Resampling.LANCZOS)


def _palette_if_lossless(im: Image.Image) -> Image.Image:
    """A palette PNG when the image has at most 256 colors and no alpha, and the pixels survive."""
    if im.mode not in ("RGB", "L"):
        return im
    colors = im.getcolors(256)
    if not colors:
        return im
    palette = im.convert("P", palette=Image.Palette.ADAPTIVE, colors=len(colors))
    if ImageChops.difference(palette.convert(im.mode), im).getbbox() is not None:
        return im  # the quantizer merged something: keep the truecolor pixels
    return palette


# --------------------------------------------------------------------------- saving
def _save(im: Image.Image, path: Path, fmt: str, **kwargs: Any) -> None:
    """Pillow writes to ``path`` only; a save error that isn't an OSError is a conversion error."""
    try:
        im.save(path, fmt, **kwargs)
    except OSError:
        raise  # the worker maps disk errors (no space, write failed)
    except (ValueError, TypeError, KeyError) as e:  # a mode or option the encoder refuses
        raise ConversionError(f"Can't encode this image as {fmt}") from e
