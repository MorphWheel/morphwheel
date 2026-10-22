"""What flows between the wheel, the dispatcher and the workers (phase-4 §4.1).

``Task`` and ``TaskResult`` cross a process boundary (spawn; a separate worker executable under
A5a), so they must stay picklable: plain dataclasses, ``Path`` and enums. ``Task.options`` is a
read-only copy of the caller's mapping. It pickles as a plain ``dict``, but ``dataclasses.asdict``
can't copy it, so don't use ``asdict`` on a ``Task``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from morphwheel.core.catalog import Target
from morphwheel.core.errors import ErrorCode

DEFAULT_HASH_LIMIT = 64 * 2**20  # sources up to 64 MB get a sha256 in the integrity check


@dataclass(frozen=True)
class DropRequest:
    files: tuple[Path, ...]
    target_id: str
    received_at_ns: int


@dataclass(frozen=True)
class Task:
    job_id: str
    task_id: int
    source: Path
    target: Target
    fallback_dir: Path  # Downloads\Morphwheel, used when the source folder is read-only
    # Quality / compress preset. Values may be unhashable, so the options stay out of hash().
    options: Mapping[str, object] = field(default_factory=dict, hash=False)
    hash_limit_bytes: int = DEFAULT_HASH_LIMIT

    def __post_init__(self) -> None:
        object.__setattr__(self, "options", MappingProxyType(dict(self.options)))

    # A mappingproxy can't be pickled: send the options as a dict and wrap them again on arrival.
    def __getstate__(self) -> dict[str, Any]:
        return {**self.__dict__, "options": dict(self.options)}

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.__dict__.update(state)
        object.__setattr__(self, "options", MappingProxyType(dict(state["options"])))


@dataclass(frozen=True)
class CreatedFile:
    path: Path
    size: int
    mtime_ns: int
    source: Path


class TaskStatus(StrEnum):
    OK = "ok"
    SKIPPED = "skipped"  # already in the target format (U2)
    FAILED = "failed"


@dataclass(frozen=True)
class TaskResult:
    job_id: str
    task_id: int
    source: Path
    status: TaskStatus
    output: CreatedFile | None = None
    error: ErrorCode | None = None
    detail: str | None = None  # technical detail, for the log only
    used_fallback: bool = False
    source_intact: bool = True  # integrity guard verdict
    duration_ms: float = 0.0


class JobOutcome(StrEnum):
    """Which toast a finished job gets (phase-3 §5)."""

    SUCCESS = "success"  # every file converted (some may have been skipped or already compact)
    PARTIAL = "partial"  # some converted, some failed
    FAILED = "failed"  # nothing converted
    ALREADY_COMPACT = "already_compact"  # Compress: nothing came out smaller, nothing failed
    NOTHING_TO_DO = "nothing_to_do"  # every file was skipped
    SOURCE_CHANGED = "source_changed"  # critical; overrides everything else


@dataclass(frozen=True)
class JobResult:
    job_id: str
    target: Target
    results: tuple[TaskResult, ...]

    def _count(self, status: TaskStatus) -> int:
        return sum(1 for r in self.results if r.status is status)

    @property
    def ok_count(self) -> int:
        return self._count(TaskStatus.OK)

    @property
    def skipped_count(self) -> int:
        return self._count(TaskStatus.SKIPPED)

    @property
    def already_compact(self) -> tuple[TaskResult, ...]:
        """Compress results that weren't smaller: not failures (RD-2), shown with ✓ (phase-3 §5)."""
        return tuple(
            r
            for r in self.results
            if r.status is TaskStatus.FAILED and r.error is ErrorCode.NOT_SMALLER
        )

    @property
    def failed(self) -> tuple[TaskResult, ...]:
        """Real failures, without ``already_compact``."""
        return tuple(
            r
            for r in self.results
            if r.status is TaskStatus.FAILED and r.error is not ErrorCode.NOT_SMALLER
        )

    @property
    def outputs(self) -> tuple[CreatedFile, ...]:
        return tuple(r.output for r in self.results if r.output is not None)

    @property
    def outcome(self) -> JobOutcome:
        if any(not r.source_intact for r in self.results):
            return JobOutcome.SOURCE_CHANGED
        if self.failed:
            return JobOutcome.PARTIAL if self.ok_count else JobOutcome.FAILED
        if self.ok_count:
            return JobOutcome.SUCCESS
        return JobOutcome.ALREADY_COMPACT if self.already_compact else JobOutcome.NOTHING_TO_DO
