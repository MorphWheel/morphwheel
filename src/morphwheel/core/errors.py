"""Error codes shared by the engine, the toasts and the logs.

Core returns codes, never sentences. The UI turns a code into translated text (D3, D3a).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType


class ErrorCode(StrEnum):
    UNREADABLE = "unreadable"  # the input can't be decoded (damaged, or not what its name says)
    UNSUPPORTED_ANIMATED = "unsupported_animated"  # animated images are out of MVP scope
    ENGINE_MISSING = "engine_missing"  # e.g. HEIC support is not installed (A6)
    NOT_SMALLER = "not_smaller"  # Compress produced nothing smaller, so the output was discarded
    WRITE_FAILED = "write_failed"
    NO_SPACE = "no_space"
    TIMEOUT = "timeout"
    WORKER_CRASHED = "worker_crashed"
    PLUGIN_ERROR = "plugin_error"
    SOURCE_CHANGED = "source_changed"  # integrity guard: the source differs after the job


class Severity(StrEnum):
    INFO = "info"  # an expected outcome, shown neutrally (e.g. "Already compact")
    ERROR = "error"  # the job failed; the source is untouched
    CRITICAL = "critical"  # must never happen; a persistent alert (phase-3 §5)


SEVERITY: Mapping[ErrorCode, Severity] = MappingProxyType(
    {
        ErrorCode.UNREADABLE: Severity.ERROR,
        ErrorCode.UNSUPPORTED_ANIMATED: Severity.ERROR,
        ErrorCode.ENGINE_MISSING: Severity.ERROR,
        ErrorCode.NOT_SMALLER: Severity.INFO,
        ErrorCode.WRITE_FAILED: Severity.ERROR,
        ErrorCode.NO_SPACE: Severity.ERROR,
        ErrorCode.TIMEOUT: Severity.ERROR,
        ErrorCode.WORKER_CRASHED: Severity.ERROR,
        ErrorCode.PLUGIN_ERROR: Severity.ERROR,
        ErrorCode.SOURCE_CHANGED: Severity.CRITICAL,
    }
)


def severity(code: ErrorCode) -> Severity:
    return SEVERITY[code]
