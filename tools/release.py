"""Release helpers for ``.github/workflows/release.yml`` (S7, RD-31). Standard library only.

    python tools/release.py version                    # the version; resource drift fails
    python tools/release.py check-tag v0.1.0           # the tag must be v<version>, or exit 1
    python tools/release.py notes 0.1.0 -o notes.md    # the CHANGELOG.md section for the version
    python tools/release.py checksums a.exe -o SHA256SUMS.txt
    python tools/release.py verify SHA256SUMS.txt      # every listed file present with that digest
    python tools/release.py check-installer DIR --version 0.1.0 --max-mb 45

Rules:

- **One version.** ``src/morphwheel/__init__.py`` is the source (hatch reads the same line) and must
  be canonical PEP 440; ``packaging/pyinstaller/file_version_info.txt`` must carry the same
  ``ProductVersion`` (the installer takes its version from that resource), and the tag must equal
  ``v<version>``. Any drift stops the release before the build. Files are read as text, so this
  works before the package is installed, on any Python 3.
- **Prerelease** is PEP 440's reading: an ``a``, ``b``, ``rc`` or ``dev`` segment (``post`` is not).
- **Files are written by this tool, as UTF-8 without a BOM and with LF** (``-o``): a PowerShell
  redirection would re-encode and write CRLF, and ``SHA256SUMS.txt`` must satisfy ``sha256sum -c``.
- ``version`` and ``check-tag`` also append ``version=`` and ``prerelease=`` to ``$GITHUB_OUTPUT``
  when that variable is set, so later steps can use them.
- ``notes`` prints the ``## [<version>]`` (or ``## <version>``) section of ``CHANGELOG.md``, without
  its heading, up to the next ``## `` heading, minus Keep a Changelog's trailing link references.
  When the file or the section is missing it writes a one-line fallback, prints a ``::warning::``
  and still exits 0: a missing changelog entry is not a reason to lose a draft release.
- ``check-installer`` holds T6 (installer download <= 45 MB) and the name: exactly one
  ``morphwheel-<version>-setup.exe`` in the folder.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERSION_FILE = REPO / "src" / "morphwheel" / "__init__.py"
RESOURCE_FILE = REPO / "packaging" / "pyinstaller" / "file_version_info.txt"
CHANGELOG = REPO / "CHANGELOG.md"
_VERSION_LINE = re.compile(r'^__version__\s*=\s*"([^"]+)"\s*$', re.MULTILINE)
_RESOURCE_LINE = re.compile(r"StringStruct\('ProductVersion',\s*'([^']+)'\)")
_CANONICAL = re.compile(r"^\d+(\.\d+)*(?P<pre>(a|b|rc)\d+)?(\.post\d+)?(?P<dev>\.dev\d+)?$")
_HEADING = re.compile(r"^## ")
_LINK_REFERENCE = re.compile(r"^\[[^\]]+\]:\s*\S+")  # Keep a Changelog's trailing "[0.1.0]: url"
_SUMS_LINE = re.compile(r"^([0-9a-f]{64})  (\S.*)$")


class ReleaseError(SystemExit):
    def __init__(self, message: str) -> None:
        super().__init__(f"release: {message}")


def read_version(path: Path = VERSION_FILE, resource: Path | None = RESOURCE_FILE) -> str:
    """``__version__``, canonical, and equal to the resource's ``ProductVersion`` when given."""
    match = _VERSION_LINE.search(path.read_text(encoding="utf-8"))
    if match is None:
        raise ReleaseError(f"no __version__ line in {path}")
    version = match.group(1)
    if not _CANONICAL.match(version):
        raise ReleaseError(f"__version__ {version!r} is not a canonical PEP 440 version")
    if resource is not None:
        found = _RESOURCE_LINE.search(resource.read_text(encoding="utf-8"))
        if found is None or found.group(1) != version:
            raise ReleaseError(
                f"{resource.name} says ProductVersion {found.group(1) if found else '?'}, "
                f"__version__ is {version}: update the resource"
            )
    return version


def is_prerelease(version: str) -> bool:
    """PEP 440 pre and dev releases: ``0.1.0.dev0``, ``1.0.0rc1``, ``1.0.0a1``; not ``.post1``."""
    match = _CANONICAL.match(version)
    if match is None:
        raise ReleaseError(f"{version!r} is not a canonical PEP 440 version")
    return bool(match.group("pre") or match.group("dev"))


def notes_section(version: str, changelog: Path = CHANGELOG) -> str | None:
    """The body of the version's ``## `` section; ``None`` when the file or section is missing."""
    if not changelog.is_file():
        return None
    lines = changelog.read_text(encoding="utf-8-sig").splitlines()
    wanted = re.compile(rf"^## \[?v?{re.escape(version)}\]?(\s|$)")
    body: list[str] = []
    inside = False
    for line in lines:
        if inside and _HEADING.match(line):
            break
        if inside and not _LINK_REFERENCE.match(line):
            body.append(line)
        elif wanted.match(line):
            inside = True
    if not inside:
        return None
    return "\n".join(body).strip() + "\n"


def checksums(files: list[Path]) -> str:
    """``sha256sum`` lines (two spaces, the file name only), sorted by name."""
    rows = []
    for path in sorted(files, key=lambda p: p.name):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(f"{digest}  {path.name}\n")
    return "".join(rows)


def verify(sums: Path, folder: Path | None = None) -> list[str]:
    """The names whose digest matches; raises on a missing or changed file or an empty list."""
    folder = folder or sums.parent
    verified: list[str] = []
    for raw in sums.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        match = _SUMS_LINE.match(raw)
        if match is None:
            raise ReleaseError(f"{sums.name}: not a sha256sum line: {raw!r}")
        digest, name = match.groups()
        target = folder / name
        if not target.is_file():
            raise ReleaseError(f"{name}: listed in {sums.name} but missing")
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ReleaseError(f"{name}: SHA-256 does not match {sums.name}")
        verified.append(name)
    if not verified:
        raise ReleaseError(f"{sums.name} lists no files")
    return verified


def check_installer(folder: Path, version: str, max_mb: float) -> Path:
    """Exactly one ``morphwheel-<version>-setup.exe`` in ``folder``, at most ``max_mb`` MB (T6)."""
    exes = sorted(folder.glob("*.exe"))
    expected = f"morphwheel-{version}-setup.exe"
    if [p.name for p in exes] != [expected]:
        raise ReleaseError(
            f"expected exactly {expected} in {folder}, found {[p.name for p in exes]}"
        )
    size_mb = exes[0].stat().st_size / 2**20
    if size_mb > max_mb:
        raise ReleaseError(f"{expected} is {size_mb:.1f} MB, over the {max_mb:g} MB limit (T6)")
    print(f"{expected}: {size_mb:.1f} MB (limit {max_mb:g} MB)")
    return exes[0]


def _emit(text: str, output: Path | None) -> None:
    if output is None:
        sys.stdout.write(text)
    else:
        output.write_bytes(text.encode("utf-8"))


def _flag(version: str) -> str:
    return "true" if is_prerelease(version) else "false"


def _github_output(version: str) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with Path(target).open("a", encoding="utf-8") as f:
            f.write(f"version={version}\nprerelease={_flag(version)}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Morphwheel release helpers")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("version", help="print the version; set version= and prerelease= outputs")
    tag = sub.add_parser("check-tag", help="fail unless TAG is v<version>; then as `version`")
    tag.add_argument("tag")
    notes = sub.add_parser("notes", help="the CHANGELOG.md section for VERSION")
    notes.add_argument("version")
    notes.add_argument("--changelog", type=Path, default=CHANGELOG)
    notes.add_argument("-o", "--output", type=Path)
    sums = sub.add_parser("checksums", help="sha256sum-style lines for FILES")
    sums.add_argument("files", nargs="+", type=Path)
    sums.add_argument("-o", "--output", type=Path)
    ver = sub.add_parser("verify", help="check every file listed in SUMS (beside it, or in --dir)")
    ver.add_argument("sums", type=Path)
    ver.add_argument("--dir", type=Path)
    inst = sub.add_parser(
        "check-installer", help="exactly one installer for VERSION, within --max-mb"
    )
    inst.add_argument("folder", type=Path)
    inst.add_argument("--version", required=True)
    inst.add_argument("--max-mb", type=float, default=45.0)
    args = parser.parse_args(argv)

    if args.command in ("version", "check-tag"):
        version = read_version()
        if args.command == "check-tag" and args.tag != f"v{version}":
            print(f"release: tag {args.tag} is not v{version} (__version__ is {version})")
            return 1
        _github_output(version)
        print(f"version={version}")
        print(f"prerelease={_flag(version)}")
        return 0
    if args.command == "notes":
        section = notes_section(args.version, args.changelog)
        if section is None:
            _emit(f"Morphwheel {args.version}. See the repository for details.\n", args.output)
            print(f"::warning::no CHANGELOG.md section for {args.version}; fallback written")
            return 0
        _emit(section, args.output)
        return 0
    if args.command == "checksums":
        _emit(checksums(args.files), args.output)
        return 0
    if args.command == "verify":
        for name in verify(args.sums, args.dir):
            print(f"{name}: OK")
        return 0
    check_installer(args.folder, args.version, args.max_mb)
    return 0


if __name__ == "__main__":
    sys.exit(main())
