"""The builtin converter on real files: every target from every input, and the refusals.

Traceability (phase-2 §3.3): transparency → white for JPG and PDF, orientation applied, metadata
kept where the format allows, animated refused. HEIC runs only with the ``heic`` extra.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest
from PIL import Image

from morphwheel.builtin.pillow_images.converter import PillowConverter
from morphwheel.plugins.api import (
    ConversionError,
    UnreadableInputError,
    UnsupportedAnimatedError,
)

from .conftest import HAS_HEIF

pytestmark = pytest.mark.integration


class Ctx:
    def __init__(self, src: Path, out: Path, target: str, **options: object) -> None:
        self.input_path = src
        self.output_path = out
        self.target_id = target
        self.options = options
        self.progress_calls: list[float] = []

    def progress(self, fraction: float) -> None:
        self.progress_calls.append(fraction)


def run(images: Mapping[str, Path], name: str, target: str, **options: object) -> Path:
    src = images[name]
    out = src.with_name(f"{src.stem}.out.{target}")
    out.write_bytes(b"")
    ctx = Ctx(src, out, target, **options)
    PillowConverter().convert(ctx)
    assert ctx.progress_calls[-1] == 1.0
    return out


INPUTS = [
    "photo.jpg",
    "photo.png",
    "photo.webp",
    "photo.avif",
    "photo.bmp",
    "photo.tiff",
    "photo.gif",
]
CONVERT = {"jpeg": "JPEG", "png": "PNG", "webp": "WEBP", "avif": "AVIF", "ico": "ICO", "pdf": "PDF"}


@pytest.mark.parametrize("name", INPUTS)
@pytest.mark.parametrize("target", list(CONVERT))
def test_every_input_converts_to_every_target(
    images: Mapping[str, Path], name: str, target: str
) -> None:
    out = run(images, name, target)
    assert out.stat().st_size > 0
    if target == "pdf":  # Pillow writes PDFs but doesn't read them
        assert out.read_bytes().startswith(b"%PDF-")
        return
    with Image.open(out) as im:
        assert im.format == CONVERT[target]
        if target != "ico":
            assert im.size == (64, 48)


def test_transparency_becomes_white_for_jpg_and_pdf(images: Mapping[str, Path]) -> None:
    with Image.open(run(images, "alpha.png", "jpeg")) as im:
        assert im.mode == "RGB"
        r, g, b = im.getpixel((30, 30))  # type: ignore[misc]
        assert min(r, g, b) > 240  # the hole is white, not black
    with Image.open(run(images, "alpha.png", "png")) as im:
        assert im.mode == "RGBA"
        assert im.getpixel((30, 30))[3] == 0  # type: ignore[index]
    with Image.open(run(images, "alpha.png", "webp")) as im:
        assert im.mode == "RGBA"
    assert run(images, "alpha.png", "pdf").read_bytes().startswith(b"%PDF-")


def test_orientation_is_applied_and_the_tag_dropped(images: Mapping[str, Path]) -> None:
    with Image.open(run(images, "rotated.jpg", "png")) as im:
        assert im.size == (64, 48)  # upright again
        exif = im.getexif()
        assert 0x0112 not in exif
        assert exif.get(0x010F) == "Morphwheel tests"  # the rest of the EXIF travels


@pytest.mark.parametrize("target", ["jpeg", "webp", "avif", "png"])
def test_exif_travels_where_the_format_allows(images: Mapping[str, Path], target: str) -> None:
    with Image.open(run(images, "photo.jpg", target)) as im:
        assert im.getexif().get(0x010F) == "Morphwheel tests"


def test_ico_has_sizes_up_to_the_image_and_tiny_inputs_work(
    images: Mapping[str, Path], tmp_path: Path
) -> None:
    with Image.open(run(images, "big.jpg", "ico")) as im:
        sizes = {max(s) for s in im.info["sizes"]}
        assert 256 in sizes
        assert 16 in sizes
    tiny = tmp_path / "tiny.png"
    Image.new("RGBA", (5, 5), (1, 2, 3, 4)).save(tiny)
    out = run({"tiny.png": tiny}, "tiny.png", "ico")
    with Image.open(out) as im:
        assert im.format == "ICO"


@pytest.mark.parametrize("name", ["anim.gif", "anim.png", "anim.webp"])
def test_animated_inputs_are_refused(images: Mapping[str, Path], name: str) -> None:
    with pytest.raises(UnsupportedAnimatedError):
        run(images, name, "jpeg")


def test_unreadable_inputs(images: Mapping[str, Path]) -> None:
    with pytest.raises(UnreadableInputError):
        run(images, "corrupt.jpg", "png")
    with pytest.raises(UnreadableInputError):
        run(images, "notes.txt", "png")


def test_mislabeled_file_converts_by_its_bytes(images: Mapping[str, Path]) -> None:
    with Image.open(run(images, "actually-png.jpg", "webp")) as im:
        assert im.format == "WEBP"


def test_unknown_target(images: Mapping[str, Path]) -> None:
    with pytest.raises(ConversionError, match="Unknown target"):
        run(images, "photo.jpg", "tiff")


# ----------------------------------------------------------------------------- compress
def test_compress_jpeg_shrinks_and_requantizes(images: Mapping[str, Path]) -> None:
    out = run(images, "big.jpg", "compress", compress_longest_side=300, compress_quality=60)
    with Image.open(out) as im:
        assert im.format == "JPEG"
        assert im.size == (300, 200)
    assert out.stat().st_size < images["big.jpg"].stat().st_size


def test_compress_never_upscales(images: Mapping[str, Path]) -> None:
    with Image.open(run(images, "photo.jpg", "compress")) as im:
        assert im.size == (64, 48)


def test_compress_png_goes_to_a_lossless_palette(images: Mapping[str, Path]) -> None:
    out = run(images, "flat.png", "compress")
    with Image.open(out) as im:
        assert im.format == "PNG"
        assert im.mode == "P"
        assert im.convert("RGB").getpixel((5, 5)) == (10, 20, 30)
    assert out.stat().st_size < images["flat.png"].stat().st_size
    photo = run(images, "photo.png", "compress")  # thousands of colors: stays truecolor
    with Image.open(photo) as im:
        assert im.mode == "RGB"


@pytest.mark.parametrize("name", ["photo.webp", "photo.avif"])
def test_compress_webp_and_avif(images: Mapping[str, Path], name: str) -> None:
    with Image.open(run(images, name, "compress", compress_quality=30)) as im:
        assert im.format == name.rsplit(".", 1)[1].upper()


def test_compress_refuses_formats_it_cannot_re_encode(images: Mapping[str, Path]) -> None:
    with pytest.raises(ConversionError, match="convert first"):
        run(images, "photo.bmp", "compress")


# ----------------------------------------------------------------------------- HEIC (A6)
@pytest.mark.skipif(not HAS_HEIF, reason="pillow_heif (the heic extra) is not installed")
def test_heic_converts_when_the_engine_is_present(images: Mapping[str, Path]) -> None:
    with Image.open(run(images, "photo.heic", "jpeg")) as im:
        assert im.format == "JPEG"
        assert im.size == (64, 48)
