"""The worker process: one task at a time, no Qt (phase-4 §3, §4.4; rule R2).

A worker is a ``multiprocessing`` spawn process (A5), in the frozen app a separate Qt-free
executable (A5a). It talks to the pool over one duplex pipe with the picklable messages below, loads
converters lazily through ``plugins.loader`` (the only place plugin code is imported, R5), and
forwards its log records to the GUI, which alone writes the log file.

Per task (§4.4), in this order, and every failure leaves nothing behind:

1. ``fp0 = fingerprint(source)``: a source that can't be read is ``UNREADABLE``.
2. The output format follows the sniffed bytes (``Task.source_format``, or a header read here).
3. ``reserve_unique`` in the source folder; if that folder refuses (read-only, Controlled Folder
   Access), in the fallback folder (``Task.fallback_dir``, created on demand), with
   ``used_fallback=True`` so the toast can say where the file went. The pool is told the temp path
   (``Reserved``), so it can sweep the temp if this process is killed.
4. ``converter.convert(ctx)``; the converter sees the source and the temp only.
5. Compress: an output that isn't smaller than ``fp0.size`` is discarded (``NOT_SMALLER``, RD-2).
6. ``fp1 = fingerprint(source)``; a difference discards the output and reports ``SOURCE_CHANGED``
   with ``source_intact=False``: the critical alert.
7. ``commit``: the temp gets its final name. Never a replace (``file_ops``).

Exceptions map to ``ErrorCode`` in ``_error_code``: the API's errors to their codes, ``ENOSPC`` to
``NO_SPACE``, other ``OSError`` to ``WRITE_FAILED``, anything else to ``PLUGIN_ERROR`` with the
traceback in ``detail`` (log only; the toast shows the code's text).
"""

from __future__ import annotations

import errno
import logging
import multiprocessing
import os
import sys
import time
import traceback
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from morphwheel.core.catalog import TargetKind
from morphwheel.core.errors import ErrorCode
from morphwheel.core.formats import SNIFF_BYTES, FormatId, sniff
from morphwheel.core.jobs import Task, TaskResult, TaskStatus
from morphwheel.core.output_policy import candidate_paths
from morphwheel.engine import file_ops
from morphwheel.engine.engines import heic_dir
from morphwheel.engine.integrity import Fingerprint, fingerprint, unchanged
from morphwheel.logs import elapsed_ms
from morphwheel.plugins.api import (
    ConversionError,
    EngineMissingError,
    UnreadableInputError,
    UnsupportedAnimatedError,
)
from morphwheel.plugins.loader import ConverterCache, PluginLoadError, PluginSpec, add_search_path

_ENOSPC_WINERROR = 112  # ERROR_DISK_FULL
_PROGRESS_STEP = 0.05


# --------------------------------------------------------------------------- messages
@dataclass(frozen=True)
class Configure:
    plugins: tuple[PluginSpec, ...]
    engines_dir: Path | None
    log_level: int = logging.INFO


@dataclass(frozen=True)
class Shutdown:
    pass


@dataclass(frozen=True)
class Ready:
    pid: int
    executable: str
    qt_loaded: bool  # must be False (R2, A5a); the frozen check reads it


@dataclass(frozen=True)
class Reserved:
    job_id: str
    task_id: int
    temp: Path


@dataclass(frozen=True)
class Progress:
    job_id: str
    task_id: int
    fraction: float


@dataclass(frozen=True)
class LogEvent:
    record: logging.LogRecord  # prepared: message rendered, no args, no exc_info


ToPool = Ready | Reserved | Progress | LogEvent | TaskResult
Send = Callable[[ToPool], None]


# --------------------------------------------------------------------------- one task
class _Context:
    """The ``ConversionContext`` a converter sees: two paths, the options, a progress sink."""

    def __init__(self, task: Task, temp: Path, send: Send | None) -> None:
        self._task = task
        self._temp = temp
        self._send = send
        self._last = -1.0

    @property
    def input_path(self) -> Path:
        return self._task.source

    @property
    def output_path(self) -> Path:
        return self._temp

    @property
    def target_id(self) -> str:
        return self._task.target.id.rpartition(":")[2]  # the plugin's own id for the target

    @property
    def options(self) -> Mapping[str, object]:
        return MappingProxyType(dict(self._task.options))

    def progress(self, fraction: float) -> None:
        if self._send is None:
            return
        fraction = min(1.0, max(0.0, float(fraction)))
        if fraction >= 1.0 or fraction - self._last >= _PROGRESS_STEP:
            self._last = fraction
            self._send(Progress(self._task.job_id, self._task.task_id, fraction))


def run_task(
    task: Task,
    converters: ConverterCache,
    plugins: Mapping[str, PluginSpec],
    *,
    send: Send | None = None,
) -> TaskResult:
    """Run one task to a ``TaskResult``. Never raises; never leaves a temp or placeholder."""
    start = time.perf_counter_ns()

    def failed(code: ErrorCode, detail: str | None = None, *, intact: bool = True) -> TaskResult:
        return TaskResult.failure(task, code, detail, intact=intact, duration_ms=elapsed_ms(start))

    spec = plugins.get(task.target.provider)
    if spec is None:
        return failed(ErrorCode.PLUGIN_ERROR, f"no plugin provides {task.target.id!r}")
    try:
        fp0 = fingerprint(task.source, hash_limit=task.hash_limit_bytes)
    except OSError as e:
        return failed(ErrorCode.UNREADABLE, f"can't read the source: {e.strerror or e}")
    source_format = task.source_format if task.source_format is not None else _sniff(task.source)

    try:
        reservation, used_fallback = _reserve(task, source_format)
    except OSError as e:
        return failed(_disk_code(e), f"can't create the output: {e.strerror or e}")
    if send is not None:
        send(Reserved(task.job_id, task.task_id, reservation.temp))

    try:
        converters.get(spec).convert(_Context(task, reservation.temp, send))
        if task.target.kind is TargetKind.COMPRESS and _size(reservation.temp) >= fp0.size:
            file_ops.abort(reservation)
            return failed(ErrorCode.NOT_SMALLER, "the output isn't smaller than the source")
        verdict = _verify_source(task, fp0)
        if verdict is not None:
            file_ops.abort(reservation)
            return failed(ErrorCode.SOURCE_CHANGED, verdict, intact=False)
        created = file_ops.commit(reservation, source=task.source)
    except BaseException as e:  # every failure ends the same way: abort, then report
        file_ops.abort(reservation)
        if isinstance(e, KeyboardInterrupt | SystemExit):
            raise
        return failed(*_error_code(e))
    return TaskResult(
        task.job_id,
        task.task_id,
        task.source,
        TaskStatus.OK,
        output=created,
        used_fallback=used_fallback,
        duration_ms=elapsed_ms(start),
    )


def _error_code(e: BaseException) -> tuple[ErrorCode, str]:
    """What a failure during convert, verify or commit means (log detail included)."""
    if isinstance(e, UnreadableInputError):
        return ErrorCode.UNREADABLE, str(e)
    if isinstance(e, UnsupportedAnimatedError):
        return ErrorCode.UNSUPPORTED_ANIMATED, str(e)
    if isinstance(e, EngineMissingError):
        return ErrorCode.ENGINE_MISSING, str(e)
    if isinstance(e, ConversionError | PluginLoadError):
        return ErrorCode.PLUGIN_ERROR, str(e)
    if isinstance(e, file_ops.EmptyOutputError):
        return ErrorCode.PLUGIN_ERROR, "the converter produced no output"
    if isinstance(e, OSError):
        return _disk_code(e), f"{type(e).__name__}: {e}"
    if isinstance(e, MemoryError):
        return ErrorCode.PLUGIN_ERROR, "out of memory"
    return ErrorCode.PLUGIN_ERROR, "".join(traceback.format_exception(e))


def _reserve(task: Task, source_format: FormatId | None) -> tuple[file_ops.Reservation, bool]:
    """Beside the source when possible, else in the fallback folder (phase-2 §3.4)."""
    try:
        return file_ops.reserve_unique(
            candidate_paths(task.source, task.target, None, source_format=source_format)
        ), False
    except PermissionError:
        pass  # read-only folder, or a folder the system protects
    task.fallback_dir.mkdir(parents=True, exist_ok=True)
    return file_ops.reserve_unique(
        candidate_paths(task.source, task.target, task.fallback_dir, source_format=source_format)
    ), True


def _verify_source(task: Task, before: Fingerprint) -> str | None:
    """``None`` when the source is intact, else what differs (for the log)."""
    try:
        after = fingerprint(task.source, hash_limit=task.hash_limit_bytes)
    except OSError as e:
        return f"the source can't be read after the conversion: {e.strerror or e}"
    if unchanged(before, after):
        return None
    return f"source changed during the conversion: before {before}, after {after}"


def _sniff(path: Path) -> FormatId | None:
    try:
        with path.open("rb") as f:
            return sniff(f.read(SNIFF_BYTES)).format
    except OSError:
        return None


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _disk_code(e: OSError) -> ErrorCode:
    if e.errno == errno.ENOSPC or getattr(e, "winerror", None) == _ENOSPC_WINERROR:
        return ErrorCode.NO_SPACE
    return ErrorCode.WRITE_FAILED


# --------------------------------------------------------------------------- the loop
class _PipeHandler(logging.Handler):
    """Forwards records to the GUI, rendered first (as ``QueueHandler.prepare`` does) to pickle."""

    def __init__(self, send: Send) -> None:
        super().__init__()
        self._send = send

    def emit(self, record: logging.LogRecord) -> None:
        try:
            record.message = record.getMessage()
            if record.exc_info:
                record.exc_text = "".join(traceback.format_exception(*record.exc_info))
            record.msg = (
                record.message if not record.exc_text else f"{record.message}\n{record.exc_text}"
            )
            record.args = None
            record.exc_info = None
            record.exc_text = None
            self._send(LogEvent(record))
        except Exception:
            self.handleError(record)


def qt_loaded() -> bool:
    return any(m.startswith(("PySide6", "shiboken6")) for m in sys.modules)


def worker_loop(conn: object) -> None:
    """The process body. ``conn`` is the child end of a duplex ``multiprocessing.Pipe``."""
    send: Send = conn.send  # type: ignore[attr-defined]
    recv: Callable[[], object] = conn.recv  # type: ignore[attr-defined]
    handler = _PipeHandler(send)
    root = logging.getLogger()
    root.handlers[:] = [handler]  # never a file handler in a worker (logs.py)
    root.setLevel(logging.INFO)
    log = logging.getLogger("morphwheel.engine.worker")

    converters = ConverterCache()
    plugins: dict[str, PluginSpec] = {}
    engines_dir: Path | None = None
    send(Ready(os.getpid(), sys.executable, qt_loaded()))
    while True:
        try:
            message = recv()
        except (EOFError, OSError):
            return  # the pool is gone
        if isinstance(message, Shutdown):
            return
        if isinstance(message, Configure):
            plugins = {spec.plugin_id: spec for spec in message.plugins}
            engines_dir = message.engines_dir
            root.setLevel(message.log_level)
            _warm_builtins(converters, plugins, log)
        elif isinstance(message, Task):
            _expose_engines(engines_dir)
            result = run_task(message, converters, plugins, send=send)
            try:
                send(result)
            except (OSError, ValueError):
                return
        else:
            log.warning("ignoring an unexpected message: %r", type(message).__name__)


def _warm_builtins(
    converters: ConverterCache, plugins: Mapping[str, PluginSpec], log: logging.Logger
) -> None:
    """Import the bundled converters while idle, so the first drop doesn't pay for Pillow."""
    for spec in plugins.values():
        if spec.directory is None:
            try:
                converters.get(spec)
            except PluginLoadError as e:  # reported again, per task, when a task needs it
                log.error("builtin converter failed to load: %s", e)
    log.debug("configured with %d plugin(s)", len(plugins))


def _expose_engines(engines_dir: Path | None) -> None:
    """Put an installed opt-in engine on ``sys.path``, also when it appeared after start-up."""
    if engines_dir is not None and (heic_dir(engines_dir) / "pillow_heif").is_dir():
        add_search_path(heic_dir(engines_dir))


if __name__ == "__main__":  # pragma: no cover - the worker exe's entry (A5a)
    multiprocessing.freeze_support()
    sys.exit("morphwheel-worker is started by Morphwheel, not by hand")
