"""Tests for ``core.errors`` and ``core.formats``.

Real image bytes are produced with Pillow (a test dependency; core itself never imports it).
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from morphwheel.core.errors import SEVERITY, ErrorCode, Severity, severity
from morphwheel.core.formats import (
    EXTENSIONS,
    OUTPUT_EXTENSION,
    FileInfo,
    FormatId,
    Sniff,
    format_from_path,
    sniff,
)

# --------------------------------------------------------------------------- errors


def test_every_error_code_has_a_severity() -> None:
    assert set(SEVERITY) == set(ErrorCode)


def test_only_source_changed_is_critical() -> None:
    assert [c for c in ErrorCode if severity(c) is Severity.CRITICAL] == [ErrorCode.SOURCE_CHANGED]
    assert severity(ErrorCode.NOT_SMALLER) is Severity.INFO


# --------------------------------------------------------------------------- extensions


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("a.JPG", FormatId.JPEG),
        ("a.jpeg", FormatId.JPEG),
        ("a.PNG", FormatId.PNG),
        ("a.heif", FormatId.HEIC),
        ("a.HEIC", FormatId.HEIC),
        ("a.tif", FormatId.TIFF),
        ("a.webp", FormatId.WEBP),
        ("a.txt", None),
        ("noext", None),
    ],
)
def test_format_from_path(name: str, expected: FormatId | None) -> None:
    assert format_from_path(Path(name)) == expected


def test_every_format_has_an_output_extension_that_maps_back() -> None:
    assert set(OUTPUT_EXTENSION) == set(FormatId)
    for fmt, ext in OUTPUT_EXTENSION.items():
        assert EXTENSIONS[ext] is fmt


def test_file_info_from_path_and_sniff_override() -> None:
    info = FileInfo.from_path(Path(r"C:\x\photo.jpg"))
    assert info.format is FormatId.JPEG
    assert info.animated is None

    really_png = info.with_sniff(Sniff(FormatId.PNG, False))
    assert really_png.format is FormatId.PNG
    assert really_png.animated is False

    unknown_bytes = info.with_sniff(Sniff(None, None))
    assert unknown_bytes.format is FormatId.JPEG  # the extension stays when the bytes aren't known

    folder = FileInfo.from_path(Path(r"C:\x\photos.png"), is_dir=True)
    assert folder.format is None


# --------------------------------------------------------------------------- sniffing


def _encode(fmt: str, frames: int = 1, **kwargs: object) -> bytes:
    images = [Image.new("RGB", (16, 16), (i * 60 % 256, 100, 200)) for i in range(frames)]
    buf = io.BytesIO()
    if frames > 1:
        images[0].save(buf, fmt, save_all=True, append_images=images[1:], **kwargs)
    else:
        images[0].save(buf, fmt, **kwargs)
    return buf.getvalue()


@pytest.mark.parametrize(
    ("pil_format", "frames", "expected"),
    [
        ("JPEG", 1, Sniff(FormatId.JPEG, False)),
        ("PNG", 1, Sniff(FormatId.PNG, False)),
        ("PNG", 3, Sniff(FormatId.PNG, True)),  # APNG
        ("GIF", 1, Sniff(FormatId.GIF, False)),
        ("GIF", 3, Sniff(FormatId.GIF, True)),
        ("WEBP", 1, Sniff(FormatId.WEBP, False)),
        ("WEBP", 3, Sniff(FormatId.WEBP, True)),
        ("AVIF", 1, Sniff(FormatId.AVIF, False)),
        ("TIFF", 1, Sniff(FormatId.TIFF, False)),
        ("BMP", 1, Sniff(FormatId.BMP, False)),
        ("ICO", 1, Sniff(FormatId.ICO, False)),
        ("PDF", 1, Sniff(FormatId.PDF, False)),
    ],
)
def test_sniff_real_images(pil_format: str, frames: int, expected: Sniff) -> None:
    assert sniff(_encode(pil_format, frames)) == expected


def test_sniff_animated_avif() -> None:
    assert sniff(_encode("AVIF", 3)) == Sniff(FormatId.AVIF, True)


def test_sniff_heic() -> None:
    pillow_heif = pytest.importorskip("pillow_heif")
    pillow_heif.register_heif_opener()
    assert sniff(_encode("HEIF")) == Sniff(FormatId.HEIC, False)


def test_sniff_bytes_win_over_a_misleading_extension() -> None:
    png_bytes = _encode("PNG")
    info = FileInfo.from_path(Path("not-really.jpg")).with_sniff(sniff(png_bytes))
    assert info.format is FormatId.PNG


def test_sniff_truncated_animated_gif_is_unknown_or_animated() -> None:
    data = _encode("GIF", 3)
    first_frame_only = data[: data.index(b"\x2c") + 12]  # cut inside the first image
    assert sniff(first_frame_only).animated in (None, True)


@pytest.mark.parametrize("junk", [b"", b"hello world", b"\x00" * 64, b"RIFF\x00\x00\x00\x00AVI "])
def test_sniff_unknown(junk: bytes) -> None:
    assert sniff(junk) == Sniff(None, None)
