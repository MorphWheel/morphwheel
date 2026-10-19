"""Image formats: identifying a file by its extension, or by its first bytes.

``sniff()`` is pure. It looks at a byte prefix the caller already read (at most ``SNIFF_BYTES``) and
reports the real format, plus whether the image is animated. Callers do the I/O off the GUI thread,
after DragEnter (phase-4 §3). Until a sniff has run, the extension decides.
"""

from __future__ import annotations

import struct
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

SNIFF_BYTES = 64 * 1024  # enough to find a second GIF frame or an APNG acTL in normal files


class FormatId(StrEnum):
    JPEG = "jpeg"
    PNG = "png"
    WEBP = "webp"
    AVIF = "avif"
    HEIC = "heic"  # HEIF family: .heic / .heif
    BMP = "bmp"
    TIFF = "tiff"
    GIF = "gif"
    ICO = "ico"
    PDF = "pdf"


EXTENSIONS: Mapping[str, FormatId] = MappingProxyType(
    {
        ".jpg": FormatId.JPEG,
        ".jpeg": FormatId.JPEG,
        ".jpe": FormatId.JPEG,
        ".jfif": FormatId.JPEG,
        ".png": FormatId.PNG,
        ".webp": FormatId.WEBP,
        ".avif": FormatId.AVIF,
        ".heic": FormatId.HEIC,
        ".heif": FormatId.HEIC,
        ".hif": FormatId.HEIC,
        ".bmp": FormatId.BMP,
        ".dib": FormatId.BMP,
        ".tif": FormatId.TIFF,
        ".tiff": FormatId.TIFF,
        ".gif": FormatId.GIF,
        ".ico": FormatId.ICO,
        ".pdf": FormatId.PDF,
    }
)

# The extension Morphwheel writes for each output format.
OUTPUT_EXTENSION: Mapping[FormatId, str] = MappingProxyType(
    {
        FormatId.JPEG: ".jpg",
        FormatId.PNG: ".png",
        FormatId.WEBP: ".webp",
        FormatId.AVIF: ".avif",
        FormatId.HEIC: ".heic",
        FormatId.BMP: ".bmp",
        FormatId.TIFF: ".tiff",
        FormatId.GIF: ".gif",
        FormatId.ICO: ".ico",
        FormatId.PDF: ".pdf",
    }
)


def format_from_path(path: Path) -> FormatId | None:
    """The format implied by the file extension (case-insensitive), or ``None``."""
    return EXTENSIONS.get(path.suffix.lower())


@dataclass(frozen=True)
class Sniff:
    format: FormatId | None
    animated: bool | None  # None = can't tell from this prefix; the worker decides


@dataclass(frozen=True)
class FileInfo:
    """What the wheel knows about one dragged item."""

    path: Path
    format: FormatId | None
    animated: bool | None = None
    is_local: bool = True  # False for virtual files / URLs (not supported in the MVP)
    is_dir: bool = False

    @classmethod
    def from_path(cls, path: Path, *, is_dir: bool = False, is_local: bool = True) -> FileInfo:
        fmt = None if is_dir else format_from_path(path)
        return cls(path=path, format=fmt, is_local=is_local, is_dir=is_dir)

    def with_sniff(self, result: Sniff) -> FileInfo:
        """Refine this info with a sniff.

        The bytes win over the extension when they're recognized.
        """
        return replace(
            self,
            format=result.format if result.format is not None else self.format,
            animated=result.animated,
        )


# --------------------------------------------------------------------------- sniffing
_HEIF_BRANDS = frozenset({b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1", b"msf1"})
_HEIF_SEQUENCE_BRANDS = frozenset({b"hevc", b"hevx", b"msf1"})


def sniff(header: bytes) -> Sniff:
    """Identify an image from its first bytes. Unknown data gives ``Sniff(None, None)``."""
    if header.startswith(b"\xff\xd8\xff"):
        return Sniff(FormatId.JPEG, False)
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return Sniff(FormatId.PNG, _png_animated(header))
    if header.startswith((b"GIF87a", b"GIF89a")):
        return Sniff(FormatId.GIF, _gif_animated(header))
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return Sniff(FormatId.WEBP, _webp_animated(header))
    if header[4:8] == b"ftyp":
        return _isobmff(header)
    if header.startswith((b"II*\x00", b"MM\x00*")):
        return Sniff(FormatId.TIFF, False)
    if header.startswith(b"BM"):
        return Sniff(FormatId.BMP, False)
    if header.startswith(b"\x00\x00\x01\x00"):
        return Sniff(FormatId.ICO, False)
    if header.startswith(b"%PDF-"):
        return Sniff(FormatId.PDF, False)
    return Sniff(None, None)


def _png_animated(data: bytes) -> bool | None:
    """APNG files carry an ``acTL`` chunk before the first ``IDAT``."""
    pos = 8
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        if kind == b"acTL":
            return True
        if kind in (b"IDAT", b"IEND"):
            return False
        pos += 12 + length
    return None


def _webp_animated(data: bytes) -> bool | None:
    chunk = data[12:16]
    if chunk == b"VP8X":
        return bool(data[20] & 0x02) if len(data) > 20 else None
    if chunk in (b"VP8 ", b"VP8L"):
        return False
    return None


def _gif_animated(data: bytes) -> bool | None:
    """Count image frames by walking GIF blocks. Two or more frames means animated."""
    if len(data) < 13:
        return None
    packed = data[10]
    pos = 13 + (3 * 2 ** ((packed & 7) + 1) if packed & 0x80 else 0)
    frames, netscape = 0, False

    def skip_sub_blocks(p: int) -> int:
        while p < len(data):
            size = data[p]
            p += 1
            if size == 0:
                return p
            p += size
        return -1  # truncated

    while pos < len(data):
        block = data[pos]
        if block == 0x3B:  # trailer
            return frames >= 2
        if block == 0x21:  # extension
            if pos + 1 >= len(data):
                break
            if data[pos + 1] == 0xFF and data[pos + 3 : pos + 14] == b"NETSCAPE2.0":
                netscape = True
            pos = skip_sub_blocks(pos + 2)
        elif block == 0x2C:  # image descriptor
            frames += 1
            if frames >= 2:
                return True
            if pos + 10 > len(data):
                break
            local = data[pos + 9]
            pos += 10 + (3 * 2 ** ((local & 7) + 1) if local & 0x80 else 0)
            pos = skip_sub_blocks(pos + 1)  # +1: LZW minimum code size
        else:
            return frames >= 2  # malformed; judge by what we saw
        if pos < 0:
            break
    return True if netscape else None  # truncated before the trailer


def _isobmff(data: bytes) -> Sniff:
    """AVIF and HEIF share the ISO base media format; the ``ftyp`` brands tell them apart."""
    (size,) = struct.unpack(">I", data[:4])
    major = data[8:12]
    brands = {major} | {data[i : i + 4] for i in range(16, min(size, len(data)) - 3, 4)}
    if b"avif" in brands or b"avis" in brands:
        return Sniff(FormatId.AVIF, major == b"avis")
    if brands & _HEIF_BRANDS:
        return Sniff(FormatId.HEIC, major in _HEIF_SEQUENCE_BRANDS)
    return Sniff(None, None)
