"""Limited Undo (D5): only files the app created, only to the Recycle Bin, only if unchanged.

``UndoRegistry`` is session-scoped: it remembers the ``CreatedFile``s of each finished job and
forgets everything when the app exits. ``undo(job_id)`` sends those files, and only those, to the
Recycle Bin, one by one, each after a fresh check that it is still the file the worker wrote
(size, mtime and NTFS file id must match). A file that changed, moved or vanished is left alone and
reported, so the toast can say "Not undone".

The recycling itself is injected (``platform.shell.recycle`` in the app), so this module stays
free of Win32 and the tests never touch the real Recycle Bin. The recycler returns ``False`` when it
refuses; ``shell.recycle`` refuses locations without a Recycle Bin (network shares, removable
drives), where "recycle" would mean "delete for good".
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from morphwheel.core.jobs import CreatedFile

log = logging.getLogger("morphwheel.engine.undo")

Recycler = Callable[[Path], bool]


class UndoStatus(StrEnum):
    RECYCLED = "recycled"
    CHANGED = "changed"  # size, mtime or file id differ: not ours any more
    MISSING = "missing"  # already gone (moved, renamed or deleted by the user)
    REFUSED = "refused"  # the recycler said no (no Recycle Bin there, or an error)
    UNKNOWN_JOB = "unknown_job"


@dataclass(frozen=True)
class UndoItem:
    path: Path
    status: UndoStatus


@dataclass(frozen=True)
class UndoOutcome:
    job_id: str
    items: tuple[UndoItem, ...]

    def count(self, status: UndoStatus) -> int:
        return sum(1 for i in self.items if i.status is status)

    @property
    def recycled(self) -> tuple[Path, ...]:
        return tuple(i.path for i in self.items if i.status is UndoStatus.RECYCLED)

    @property
    def complete(self) -> bool:
        return bool(self.items) and all(i.status is UndoStatus.RECYCLED for i in self.items)


@dataclass
class UndoRegistry:
    recycle: Recycler
    _jobs: dict[str, tuple[CreatedFile, ...]] = field(default_factory=dict)

    def record(self, job_id: str, files: Sequence[CreatedFile]) -> None:
        """Remember what a job created. A job with no outputs has nothing to undo and isn't kept."""
        if files:
            self._jobs[job_id] = tuple(files)

    def can_undo(self, job_id: str) -> bool:
        return job_id in self._jobs

    def undo(self, job_id: str) -> UndoOutcome:
        """Recycle the job's outputs that are still exactly what the worker wrote. One shot."""
        files = self._jobs.pop(job_id, None)
        if files is None:
            return UndoOutcome(job_id, (UndoItem(Path(), UndoStatus.UNKNOWN_JOB),))
        items = []
        for created in files:
            status = self._undo_one(created)
            log.info("undo %s: %s %s", job_id, created.path.name, status.value)
            items.append(UndoItem(created.path, status))
        return UndoOutcome(job_id, tuple(items))

    def _undo_one(self, created: CreatedFile) -> UndoStatus:
        if created.path == created.source:
            return UndoStatus.REFUSED  # can't happen by construction; never recycle a source
        try:
            st = created.path.stat()
        except OSError:
            return UndoStatus.MISSING
        if (st.st_size, st.st_mtime_ns) != (created.size, created.mtime_ns):
            return UndoStatus.CHANGED
        if created.file_id and st.st_ino != created.file_id:
            return UndoStatus.CHANGED  # deleted and re-created with the same size and time
        try:
            recycled = self.recycle(created.path)
        except OSError as e:
            log.warning("undo: recycling %s failed: %s", created.path.name, e)
            return UndoStatus.REFUSED
        return UndoStatus.RECYCLED if recycled else UndoStatus.REFUSED
