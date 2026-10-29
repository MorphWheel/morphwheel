"""What a toast says (phase-3 §5): a ``JobResult`` or an undo outcome becomes a ``ToastModel``.

Pure data in, data plus translatable strings out. The strings live here, in the UI layer, so the
core never carries sentences (D3, D3a). Every string goes through ``QCoreApplication.translate``
with the context ``"Toast"``.

Timing rules (phase-3 §5): success and info disappear after 6 s, errors after 12 s, a critical
alert never by itself, and a working toast stays until its job's result replaces it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from morphwheel.core.catalog import TargetKind
from morphwheel.core.errors import ErrorCode
from morphwheel.core.jobs import JobOutcome, JobResult, TaskResult
from morphwheel.engine.undo import UndoOutcome, UndoStatus

SUCCESS_MS = 6_000
ERROR_MS = 12_000
STICKY = 0  # never disappears by itself


class ToastKind(StrEnum):
    WORKING = "working"
    SUCCESS = "success"
    INFO = "info"  # an expected non-result: "Already compact", "Nothing to convert"
    WARNING = "warning"  # a partial batch, "Not undone"
    ERROR = "error"
    CRITICAL = "critical"  # the source changed: persistent (phase-3 §5)


@dataclass(frozen=True)
class ToastModel:
    kind: ToastKind
    title: str
    body: str = ""
    duration_ms: int = SUCCESS_MS  # 0 = sticky

    @property
    def sticky(self) -> bool:
        return self.duration_ms == STICKY


def _tr(text: str, n: int = -1) -> str:
    """Translate with the context ``Toast``. ``n`` drives plural forms (``%n file(s)``).

    Qt substitutes ``%n`` and lets a translation pick the plural form. English ships without a
    translation file, so the source convention ``(s)`` is resolved here for the source language.
    """
    out = QCoreApplication.translate("Toast", text, None, n)
    if n >= 0 and out == text.replace("%n", str(n)):  # untranslated: English source rules
        out = out.replace("(s)", "" if n == 1 else "s")
    return out


# --------------------------------------------------------------------------- results
def toast_for(result: JobResult) -> ToastModel:
    outcome = result.outcome
    if outcome is JobOutcome.SOURCE_CHANGED:
        return _source_changed(result)
    if outcome is JobOutcome.FAILED:
        return _failed(result)
    if outcome is JobOutcome.PARTIAL:
        return _partial(result)
    if outcome is JobOutcome.NOTHING_TO_DO:
        return ToastModel(
            ToastKind.INFO,
            _tr("Nothing to convert"),
            _tr("%n file(s) already %1", result.skipped_count).replace("%1", result.target.label),
        )
    if outcome is JobOutcome.ALREADY_COMPACT:
        names = ", ".join(r.source.name for r in result.already_compact[:3])
        return ToastModel(
            ToastKind.INFO,
            _tr("Already compact"),
            _tr("%1 — no smaller file was made").replace("%1", names),
        )
    return _success(result)


def _success(result: JobResult) -> ToastModel:
    outputs = result.outputs
    compress = result.target.kind is TargetKind.COMPRESS
    if len(outputs) == 1 and not result.skipped_count and not result.already_compact:
        out = outputs[0]
        title = (
            _tr("Compressed")
            if compress
            else _tr("Converted to %1").replace("%1", result.target.label)
        )
        before = human_size(_file_size(out.source))
        body = f"{out.path.name} · {before} → {human_size(out.size)}"
    else:
        if compress:
            title = _tr("%n file(s) compressed", len(outputs))
            if result.already_compact:
                title += " · " + _tr("%n already compact", len(result.already_compact))
        else:
            title = _tr("%n file(s) converted to %1", len(outputs)).replace(
                "%1", result.target.label
            )
        body = ""
        if result.skipped_count:
            body = _tr("%n skipped — already %1", result.skipped_count).replace(
                "%1", result.target.label
            )
    if any(r.used_fallback for r in result.results):
        folder = next(r.output.path.parent for r in result.results if r.used_fallback and r.output)
        note = _tr("Saved to %1 — the source folder is read-only").replace(
            "%1", _short_folder(folder)
        )
        body = f"{body}\n{note}" if body else note
    return ToastModel(ToastKind.SUCCESS, title, body)


def _partial(result: JobResult) -> ToastModel:
    total = result.ok_count + len(result.failed)
    title = _tr("%1 of %2 converted").replace("%1", str(result.ok_count)).replace("%2", str(total))
    return ToastModel(ToastKind.WARNING, title, _failure_lines(result.failed), ERROR_MS)


def _failed(result: JobResult) -> ToastModel:
    failed = result.failed
    if len(failed) == 1:
        title = _tr("Couldn't convert %1").replace("%1", failed[0].source.name)
        body = reason_text(failed[0].error)
    else:
        title = _tr("Couldn't convert %n file(s)", len(failed))
        body = _failure_lines(failed)
    return ToastModel(ToastKind.ERROR, title, body, ERROR_MS)


def _source_changed(result: JobResult) -> ToastModel:
    changed = [r for r in result.results if not r.source_intact]
    names = ", ".join(r.source.name for r in changed[:3])
    body = _tr("%1 — size or date differs.").replace("%1", names)
    body += "\n" + _tr("This should never happen. Please report it. Nothing was written.")
    return ToastModel(
        ToastKind.CRITICAL, _tr("Source file changed during conversion"), body, STICKY
    )


def _failure_lines(failed: tuple[TaskResult, ...]) -> str:
    lines = [f"{r.source.name} — {reason_text(r.error)}" for r in failed[:3]]
    if len(failed) > 3:
        lines.append(_tr("and %n more", len(failed) - 3))
    return "\n".join(lines)


def reason_text(code: ErrorCode | None) -> str:
    texts = {
        ErrorCode.UNREADABLE: _tr("The file couldn't be read."),
        ErrorCode.UNSUPPORTED_ANIMATED: _tr("Animated images aren't supported."),
        ErrorCode.ENGINE_MISSING: _tr("HEIC support isn't installed."),
        ErrorCode.NOT_SMALLER: _tr("No smaller file was made."),
        ErrorCode.WRITE_FAILED: _tr("The file couldn't be written."),
        ErrorCode.NO_SPACE: _tr("There isn't enough disk space."),
        ErrorCode.TIMEOUT: _tr("The conversion took too long and was stopped."),
        ErrorCode.WORKER_CRASHED: _tr("The converter stopped unexpectedly."),
        ErrorCode.PLUGIN_ERROR: _tr("The converter reported an error."),
        ErrorCode.SOURCE_CHANGED: _tr("The source file changed during the conversion."),
    }
    return texts.get(code, _tr("Unknown error."))  # type: ignore[arg-type]


# --------------------------------------------------------------------------- working and undo
def working_toast(count: int, target_label: str, done: int = 0) -> ToastModel:
    title = _tr("Converting %n file(s) to %1…", count).replace("%1", target_label)
    body = f"{done} / {count}" if count > 1 else ""
    return ToastModel(ToastKind.WORKING, title, body, STICKY)


def undo_toast(outcome: UndoOutcome) -> ToastModel:
    if outcome.complete:
        names = ", ".join(p.name for p in outcome.recycled[:3])
        return ToastModel(ToastKind.SUCCESS, _tr("Moved to Recycle Bin"), names)
    changed = [i.path.name for i in outcome.items if i.status is UndoStatus.CHANGED]
    missing = [i.path.name for i in outcome.items if i.status is UndoStatus.MISSING]
    refused = [i.path.name for i in outcome.items if i.status is UndoStatus.REFUSED]
    lines = []
    if changed:
        lines.append(_tr("%1 changed after conversion.").replace("%1", ", ".join(changed[:3])))
    if missing:
        lines.append(_tr("%1 is no longer there.").replace("%1", ", ".join(missing[:3])))
    if refused:
        lines.append(_tr("%1 has no Recycle Bin here.").replace("%1", ", ".join(refused[:3])))
    if outcome.recycled:
        lines.append(_tr("%n file(s) moved to Recycle Bin", len(outcome.recycled)))
    return ToastModel(ToastKind.WARNING, _tr("Not undone"), "\n".join(lines), ERROR_MS)


# --------------------------------------------------------------------------- helpers
def human_size(size: int) -> str:
    """``840 KB``, ``3.1 MB``: one decimal above KB, none below (phase-3 §5 mockups)."""
    if size < 1024:
        return f"{size} B"
    if size < 1024**2:
        return f"{size / 1024:.0f} KB"
    if size < 1024**3:
        return f"{size / 1024**2:.1f} MB"
    return f"{size / 1024**3:.1f} GB"


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _short_folder(folder: Path) -> str:
    """``Downloads\\Morphwheel`` rather than the whole path."""
    return "\\".join(folder.parts[-2:])
