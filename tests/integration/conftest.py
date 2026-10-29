"""Fixtures for the engine tests: small real images of every supported format, generated once.

Nothing binary is checked in. The images are made with Pillow into a session directory, so every
test that needs a "real JPG with an EXIF orientation" or "an animated GIF" copies from here. The
HEIC fixture exists only when ``pillow_heif`` is importable (the ``heic`` extra); tests that need it
skip otherwise.
"""

from __future__ import annotations

import importlib.util
import shutil
from collections.abc import Mapping
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

HAS_HEIF = importlib.util.find_spec("pillow_heif") is not None
FIXTURE_PLUGINS = Path(__file__).resolve().parents[1] / "fixtures" / "plugins"


def _photo(size: tuple[int, int] = (64, 48)) -> Image.Image:
    """A small opaque image with a gradient and a marker, so orientation and colors are testable."""
    im = Image.new("RGB", size)
    px = im.load()
    assert px is not None
    for y in range(size[1]):
        for x in range(size[0]):
            px[x, y] = (x * 255 // size[0], y * 255 // size[1], 128)
    ImageDraw.Draw(im).rectangle((2, 2, 10, 10), fill=(255, 0, 0))  # top-left marker
    return im


def _exif(orientation: int) -> bytes:
    exif = Image.Exif()
    exif[0x0112] = orientation
    exif[0x010F] = "Morphwheel tests"
    return exif.tobytes()


@pytest.fixture(scope="session")
def fixture_images(tmp_path_factory: pytest.TempPathFactory) -> Mapping[str, Path]:
    root = tmp_path_factory.mktemp("images")
    photo = _photo()
    files: dict[str, Path] = {}

    def save(name: str, im: Image.Image, fmt: str, **kw: object) -> None:
        path = root / name
        im.save(path, fmt, **kw)
        files[name] = path

    save("photo.jpg", photo, "JPEG", quality=95, exif=_exif(1))
    save("rotated.jpg", photo.transpose(Image.Transpose.ROTATE_270), "JPEG", exif=_exif(6))
    rgba = photo.convert("RGBA")
    ImageDraw.Draw(rgba).rectangle((20, 20, 40, 40), fill=(0, 0, 0, 0))  # a transparent hole
    save("alpha.png", rgba, "PNG")
    save("photo.png", photo, "PNG")
    save("flat.png", Image.new("RGB", (64, 48), (10, 20, 30)), "PNG")  # 1 color: palette wins
    save("big.jpg", _photo((600, 400)), "JPEG", quality=100)  # big enough for compress to win
    save("photo.webp", photo, "WEBP", quality=90)
    save("photo.avif", photo, "AVIF", quality=80)
    save("photo.bmp", photo, "BMP")
    save("photo.tiff", photo, "TIFF")
    save("photo.gif", photo.convert("P"), "GIF")
    frames = [photo, photo.transpose(Image.Transpose.FLIP_LEFT_RIGHT)]
    save("anim.gif", frames[0], "GIF", save_all=True, append_images=frames[1:], duration=100)
    save("anim.png", frames[0], "PNG", save_all=True, append_images=frames[1:], duration=100)
    save("anim.webp", frames[0], "WEBP", save_all=True, append_images=frames[1:], duration=100)
    corrupt = root / "corrupt.jpg"
    corrupt.write_bytes(files["photo.jpg"].read_bytes()[:200])  # truncated: header ok, data cut
    files["corrupt.jpg"] = corrupt
    mislabeled = root / "actually-png.jpg"
    shutil.copyfile(files["photo.png"], mislabeled)
    files["actually-png.jpg"] = mislabeled
    mislabeled_jpeg = root / "actually-jpeg.png"
    shutil.copyfile(files["big.jpg"], mislabeled_jpeg)
    files["actually-jpeg.png"] = mislabeled_jpeg
    save("compact.jpg", photo, "JPEG", quality=10)  # re-encoding at quality 80 can only grow it
    text = root / "notes.txt"
    text.write_bytes(b"not an image at all\n")
    files["notes.txt"] = text
    if HAS_HEIF:
        import pillow_heif

        pillow_heif.register_heif_opener()
        save("photo.heic", photo, "HEIF", quality=80)
    return files


@pytest.fixture
def images(fixture_images: Mapping[str, Path], tmp_path: Path) -> Mapping[str, Path]:
    """Per-test copies, so a test may tamper with its own source."""
    copies = {}
    for name, path in fixture_images.items():
        dest = tmp_path / name
        shutil.copyfile(path, dest)
        copies[name] = dest
    return copies


def plugin_dir(name: str) -> Path:
    return FIXTURE_PLUGINS / name
