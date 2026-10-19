"""What flows between the wheel, the dispatcher and the workers (phase-4 §4.1).

``Task`` and ``TaskResult`` cross a process boundary (spawn; a separate worker executable under
A5a), so they must stay picklable. That means plain dataclasses, ``Path``, enums, and a plain
``dict`` for options.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

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
    options: dict[str, object] = field(default_factory=dict)  # quality / compress preset
    hash_limit_bytes: int = DEFAULT_HASH_LIMIT


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

    SUCCESS = "success"  # every file converted (some may have been skipped)
    PARTIAL = "partial"  # some converted, some failed
    FAILED = "failed"  # nothing converted
    ALREADY_COMPACT = "already_compact"  # Compress: nothing came out smaller
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
    def failed(self) -> tuple[TaskResult, ...]:
        return tuple(r for r in self.results if r.status is TaskStatus.FAILED)

    @property
    def outputs(self) -> tuple[CreatedFile, ...]:
        return tuple(r.output for r in self.results if r.output is not None)

    @property
    def outcome(self) -> JobOutcome:
        if any(not r.source_intact for r in self.results):
            return JobOutcome.SOURCE_CHANGED
        failed = self.failed
        if self.ok_count == 0 and not failed:
            return JobOutcome.NOTHING_TO_DO
        if not failed:
            return JobOutcome.SUCCESS
        if self.ok_count == 0:
            if all(r.error is ErrorCode.NOT_SMALLER for r in failed):
                return JobOutcome.ALREADY_COMPACT
            return JobOutcome.FAILED
        return JobOutcome.PARTIAL
