"""The source integrity guard (phase-2 §3.4, phase-4 §4.4): a fingerprint before and after.

A worker fingerprints the source before it starts and again after the converter has run. If the two
differ, the output is discarded and the task is reported as ``SOURCE_CHANGED``, a critical alert
(phase-3 §5): it means a converter, builtin or plugin, touched the file it was given. This catches
bugs in our own code too.

The fingerprint is ``(size, mtime_ns, file id)`` for every file, plus a SHA-256 for files up to
``hash_limit`` bytes (64 MB by default, ``Task.hash_limit_bytes``). The file id (NTFS file
reference, ``st_ino``) catches a file that was deleted and re-created with the same size and time.
Two fingerprints compare equal only when both were taken with the same hash policy, so a hashed
"before" never matches an unhashed "after". This module is stdlib-only, like everything the workers
import.

Known hole: a file over the hash limit on FAT (2 s mtime resolution) that is rewritten in place
with the same size within the same 2 s window is not detected.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from morphwheel.core.jobs import DEFAULT_HASH_LIMIT

_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class Fingerprint:
    size: int
    mtime_ns: int
    file_id: int  # st_ino: the NTFS file reference number (0 where the file system has none)
    sha256: str | None  # None when the file was over the hash limit

    @property
    def hashed(self) -> bool:
        return self.sha256 is not None


def fingerprint(path: Path, *, hash_limit: int = DEFAULT_HASH_LIMIT) -> Fingerprint:
    """Fingerprint ``path``. Raises ``OSError`` if it can't be read (missing, locked, no access).

    The stat is taken *after* the hash, so a write that lands during the hash still shows up as a
    size or mtime difference on the next fingerprint.
    """
    size = path.stat().st_size
    digest: str | None = None
    if size <= hash_limit:
        h = hashlib.sha256()
        with path.open("rb") as f:
            while chunk := f.read(_CHUNK):
                h.update(chunk)
        digest = h.hexdigest()
    st = path.stat()
    return Fingerprint(st.st_size, st.st_mtime_ns, st.st_ino, digest)


def unchanged(before: Fingerprint, after: Fingerprint) -> bool:
    """Both fingerprints must agree on every field, including whether a hash was taken."""
    return before == after
