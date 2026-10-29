"""Creating an output file without ever overwriting anything (phase-2 §3.4, phase-4 §4.4).

Three steps, all in the output's own directory, so the final rename stays on one volume:

1. **Reserve.** ``reserve_unique`` walks the candidate names from ``core.output_policy`` and claims
   the first free one with an exclusive create (``O_CREAT | O_EXCL``). The claim is a 0-byte
   *placeholder* that the worker keeps **open with delete-on-close** (``O_TEMPORARY``): if the
   worker is killed on a timeout, or crashes, the kernel removes the placeholder by itself, and
   the user never finds an empty ``photo.jpg`` that looks like a result. Beside it, a *temp* file
   is created the same way; the converter writes there.
2. **Commit.** ``commit`` closes the placeholder (which deletes it) and renames the temp onto the
   final name with ``os.rename``, which on Windows **fails if the name exists**. Nothing in this
   module ever replaces an existing file. If someone took the name in the few microseconds
   between the close and the rename, the rename moves on to the next candidate name. A rename
   refused because a scanner still holds the destination is retried briefly.
3. **Abort.** ``abort`` closes the placeholder and removes the temp. It never raises for files that
   are already gone.

Everything here is stdlib-only: it runs in the workers (R2). The GUI side gets the temp path in a
``Reserved`` message (``worker_main``) and removes it after a kill, when no handle is left open.

Known limits: paths longer than ``MAX_PATH`` need long-path support on the machine; this module
doesn't add the ``\\\\?\\`` prefix.
"""

from __future__ import annotations

import contextlib
import itertools
import os
import secrets
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from morphwheel.core.jobs import CreatedFile

TEMP_SUFFIX = ".mwtmp"
_EXCLUSIVE = os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_BINARY", 0)
_DELETE_ON_CLOSE = getattr(os, "O_TEMPORARY", 0)  # Windows: FILE_FLAG_DELETE_ON_CLOSE
_RENAME_RETRIES = 10
_RENAME_RETRY_S = 0.05


class NoCandidateError(OSError):
    """Every candidate name was taken."""


class EmptyOutputError(OSError):
    """The converter left the temp file empty, so there is nothing to commit."""


@dataclass
class Reservation:
    final: Path  # the placeholder, and the output's intended name
    temp: Path  # where the converter writes
    _fd: int | None = field(repr=False)  # the open placeholder; None once closed
    _more: Iterator[Path] = field(repr=False)  # the remaining candidate names

    @property
    def held(self) -> bool:
        return self._fd is not None

    def release(self) -> None:
        """Close the placeholder. With delete-on-close, this removes it."""
        if self._fd is not None:
            fd, self._fd = self._fd, None
            os.close(fd)


def reserve_unique(candidates: Iterable[Path]) -> Reservation:
    """Claim the first free candidate atomically. The candidates' directory must exist.

    Raises :class:`NoCandidateError` when the names run out, and ``OSError`` for any other failure
    (a read-only directory, a missing directory, no space for the two empty files).
    """
    names = iter(candidates)
    for candidate in names:
        try:
            fd = os.open(candidate, _EXCLUSIVE | _DELETE_ON_CLOSE)
        except FileExistsError:
            continue
        try:
            temp = _create_temp_beside(candidate)
        except OSError:
            os.close(fd)
            raise
        return Reservation(candidate, temp, fd, names)
    raise NoCandidateError("no free output name")


def commit(reservation: Reservation, *, source: Path) -> CreatedFile:
    """Give the temp its final name and describe the result. Never overwrites.

    Raises :class:`EmptyOutputError` for an empty temp, :class:`NoCandidateError` if every name is
    taken by now, and ``OSError`` when the rename keeps failing. In every failing case the temp is
    removed and the placeholder is gone.
    """
    temp = reservation.temp
    try:
        if temp.stat().st_size == 0:
            raise EmptyOutputError(f"{temp.name} is empty")
        reservation.release()
        final = _rename_to_a_free_name(temp, reservation.final, reservation._more)
    except OSError:
        abort(reservation)
        raise
    st = final.stat()
    return CreatedFile(
        path=final, size=st.st_size, mtime_ns=st.st_mtime_ns, source=source, file_id=st.st_ino
    )


def abort(reservation: Reservation) -> None:
    """Undo a reservation: the placeholder goes with its handle, and the temp is removed."""
    reservation.release()
    remove_quietly(reservation.temp)


def remove_quietly(path: Path) -> None:
    """Remove a file of ours that may already be gone. Used for leftover temps too."""
    with contextlib.suppress(OSError):
        path.unlink()


# --------------------------------------------------------------------------- internals
def _create_temp_beside(final: Path) -> Path:
    for _ in range(8):
        temp = final.with_name(f"{final.name}.{secrets.token_hex(4)}{TEMP_SUFFIX}")
        try:
            fd = os.open(temp, _EXCLUSIVE)
        except FileExistsError:
            continue
        os.close(fd)
        return temp
    raise FileExistsError(f"can't find a free temp name beside {final.name}")


def _rename_to_a_free_name(temp: Path, first: Path, more: Iterator[Path]) -> Path:
    """``os.rename`` onto ``first``, else onto the next free candidate. Never replaces a file."""
    for target in itertools.chain((first,), more):
        for attempt in range(_RENAME_RETRIES):
            try:
                temp.rename(target)
            except FileExistsError:
                break  # someone took this name: try the next one
            except PermissionError:
                # Delete-pending placeholder (a scanner still holds it) or a locked destination.
                if attempt == _RENAME_RETRIES - 1:
                    raise
                time.sleep(_RENAME_RETRY_S)
            else:
                return target
    raise NoCandidateError("no free output name")
