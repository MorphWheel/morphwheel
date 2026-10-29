"""Opt-in conversion engines: today only HEIC support (decision A6).

pillow-heif's wheels bundle x265 and are therefore GPLv2. Morphwheel never ships them. Instead the
user may download the **pinned** wheel from PyPI into ``%LOCALAPPDATA%\\Morphwheel\\engines\\heic``,
where the workers find it. The download is verified against a SHA-256 recorded here before a single
file is extracted, so a changed or tampered wheel installs nothing.

Rules:

- **Pinned by version and hash.** ``HEIC_WHEEL`` names the exact file, its URL on PyPI's file host
  and its digest. Upgrading the engine is a code change, reviewed like any other.
- **Verify, then extract, then rename.** The wheel is fetched to memory, hashed, unpacked into a
  temporary sibling directory, and the directory is renamed into place. A half-finished install
  can't be mistaken for a working one.
- **Flat layout.** The package ``pillow_heif/``, its extension module and the codec DLLs land side
  by side in the engine directory, which is what pillow-heif's own loader expects (it adds the
  package's parent to the DLL search path). Only those files are taken; nothing else in the wheel
  is written, and no path may escape the engine directory (zip-slip guard).
- The network call is injectable (``fetch``); the tests never go online. ``install_heic`` runs on
  the GUI thread only behind ``--install-heic`` (S3); S5 moves it to a thread behind a button.
- ``missing_engines`` feeds ``Catalog.missing_engines``: HEIC is blocked on the wheel until the
  engine is present (``Reason.ENGINE_MISSING``).
"""

from __future__ import annotations

import hashlib
import io
import logging
import shutil
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path, PurePosixPath

from morphwheel.core.formats import FormatId

log = logging.getLogger("morphwheel.engine.engines")

Fetch = Callable[[str], bytes]
DOWNLOAD_TIMEOUT_S = 60.0


@dataclass(frozen=True)
class WheelSpec:
    name: str
    url: str
    sha256: str
    size: int
    package: str  # the top-level package inside the wheel


HEIC_WHEEL = WheelSpec(
    name="pillow_heif-1.8.1-cp312-cp312-win_amd64.whl",
    url=(
        "https://files.pythonhosted.org/packages/db/fd/"
        "2ff579be4694ac68cc73bfaafe1abc255bd658b678bfb3b33922784ddaf0/"
        "pillow_heif-1.8.1-cp312-cp312-win_amd64.whl"
    ),
    sha256="ce0ff957ad901a5a6bf8cd22ea26c4304bab7cf2f93d0a2f03046487e5711910",
    size=6_604_108,
    package="pillow_heif",
)


HEIC_ENGINE_SUBDIR = "heic"  # engines_dir / "heic" holds the opt-in pillow-heif (A6)


class EngineInstallError(Exception):
    """The download or the install failed. Nothing was installed."""


# --------------------------------------------------------------------------- status
def heic_dir(engines_dir: Path) -> Path:
    return engines_dir / HEIC_ENGINE_SUBDIR


def heic_installed(engines_dir: Path) -> bool:
    """The downloaded engine is in place (its package directory and extension module exist)."""
    folder = heic_dir(engines_dir)
    return (folder / HEIC_WHEEL.package / "__init__.py").is_file() and any(
        folder.glob("_pillow_heif*.pyd")
    )


def heic_available(engines_dir: Path) -> bool:
    """Installed by the user, or importable anyway (a developer's venv with the ``heic`` extra)."""
    return heic_installed(engines_dir) or find_spec("pillow_heif") is not None


def missing_engines(engines_dir: Path) -> frozenset[FormatId]:
    return frozenset() if heic_available(engines_dir) else frozenset({FormatId.HEIC})


# --------------------------------------------------------------------------- install
def install_heic(engines_dir: Path, *, fetch: Fetch | None = None) -> Path:
    """Download, verify and unpack the pinned pillow-heif wheel. Returns the engine directory."""
    data = (fetch or _download)(HEIC_WHEEL.url)
    digest = hashlib.sha256(data).hexdigest()
    if digest != HEIC_WHEEL.sha256:
        raise EngineInstallError(
            f"{HEIC_WHEEL.name}: the download doesn't match the pinned hash "
            f"(got {digest[:16]}…); nothing was installed"
        )
    target = heic_dir(engines_dir)
    staging = target.with_name(target.name + ".installing")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        _extract(data, staging)
        if target.exists():
            shutil.rmtree(target)
        staging.rename(target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    log.info("HEIC engine installed in %s", target)
    return target


def remove_heic(engines_dir: Path) -> None:
    shutil.rmtree(heic_dir(engines_dir), ignore_errors=True)


def _download(url: str) -> bytes:
    log.info("downloading %s", url)
    try:
        with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_S) as response:
            data: bytes = response.read(HEIC_WHEEL.size + 1)
    except OSError as e:
        raise EngineInstallError(f"download failed: {e}") from e
    return data


def _extract(data: bytes, into: Path) -> None:
    """Take the package, the extension module and the DLLs; refuse paths that escape ``into``."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise EngineInstallError("the download is not a wheel") from e
    root = into.resolve()
    with archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            posix = PurePosixPath(member.filename)
            if posix.is_absolute() or ".." in posix.parts:
                raise EngineInstallError(f"refusing a path outside the engine dir: {posix}")
            is_package = posix.parts[0] == HEIC_WHEEL.package
            is_extension = len(posix.parts) == 1 and posix.suffix == ".pyd"
            if is_package or is_extension:
                relative = posix
            elif len(posix.parts) == 3 and posix.parts[1] == "platlib" and posix.suffix == ".dll":
                relative = PurePosixPath(posix.name)  # <dist>.data/platlib/x.dll -> x.dll
            else:
                continue  # metadata, licenses, caches
            dest = (root / Path(*relative.parts)).resolve()
            if root not in dest.parents:
                raise EngineInstallError(f"refusing a path outside the engine dir: {posix}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as src, dest.open("wb") as out:
                shutil.copyfileobj(src, out)
    if not any(root.glob("_pillow_heif*.pyd")) or not (root / HEIC_WHEEL.package).is_dir():
        raise EngineInstallError("the wheel doesn't contain the expected files")
