"""What a toast says (phase-3 §5): a ``JobResult`` or an undo outcome becomes a ``ToastModel``.

Pure data in, data plus translatable strings out. The strings live here, in the UI layer, so the
core never carries sentences (D3, D3a). Every string goes through ``ui.text.tr`` with the
context ``"Toast"``.

Timing rules (phase-3 §5): success and info disappear after 6 s, errors after 12 s, a critical
alert never by itself, and a working toast stays until its job's result replaces it. A working
toast for a single file appears only when the job runs longer than ``WORKING_DELAY_MS`` (§3).

Buttons (the §5 mockups), as ``ToastAction``s the widget turns into buttons:

- a success with outputs: *Show in folder* and *Undo* (*Undo all* for several outputs);
- a partial batch: *Details* and *Show in folder*; an error: *Details*;
- the critical alert: *Details* and *Show in folder* (the changed source);
- "Not undone": *Show in folder* for a file that is still there; everything else has none.

An action carries data, never a command: *Undo* carries the job id and the app asks the undo
registry (D5); *Show in folder* carries a path the app created or the user dragged; *Details*
carries the full text (every failed file, not only the three the body shows).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from morphwheel.core.catalog import TargetKind
from morphwheel.core.errors import ErrorCode
from morphwheel.core.jobs import JobOutcome, JobResult, TaskResult
from morphwheel.engine.undo import UndoOutcome, UndoStatus
from morphwheel.i18n import translate

SUCCESS_MS = 6_000
ERROR_MS = 12_000
STICKY = 0  # never disappears by itself
WORKING_DELAY_MS = 1_000  # a single file shows "working" only after about a second (phase-3 §3)
BODY_LINES = 3  # the body names at most this many files; Details has them all


class ToastKind(StrEnum):
    WORKING = "working"
    SUCCESS = "success"
    INFO = "info"  # an expected non-result: "Already compact", "Nothing to convert"
    WARNING = "warning"  # a partial batch, "Not undone"
    ERROR = "error"
    CRITICAL = "critical"  # the source changed: persistent (phase-3 §5)
    HINT = "hint"  # a how-to note: the first-run bubble (phase-3 §6.3)


class ActionKind(StrEnum):
    SHOW_IN_FOLDER = "show_in_folder"  # payload: the Path to select in Explorer
    UNDO = "undo"  # payload: the job id (D5: the registry decides what, if anything, goes)
    DETAILS = "details"  # payload: the full text
    DISMISS = "dismiss"  # "Got it": the toast just goes (every action dismisses its toast)
    SETTINGS = "settings"  # payload: the settings page to open
    INSTALL_HEIC = "install_heic"  # the offer's button (A6): the app asks for consent first


class EngineFailure(StrEnum):
    """Why an engine install failed, in the engine's words (``EngineInstallError.kind``) so the
    toast can say it in ours."""

    DOWNLOAD = "download"
    MISMATCH = "mismatch"
    ARCHIVE = "archive"
    WRITE = "write"  # the engines folder couldn't be written (an OSError)


@dataclass(frozen=True)
class ToastAction:
    kind: ActionKind
    label: str
    payload: Path | str = ""  # see ``ActionKind``; DISMISS has none


@dataclass(frozen=True)
class Progress:
    done: int
    total: int


@dataclass(frozen=True)
class ToastModel:
    kind: ToastKind
    title: str
    body: str = ""
    duration_ms: int = SUCCESS_MS  # 0 = sticky
    actions: tuple[ToastAction, ...] = ()
    progress: Progress | None = None  # a batch's bar; None for a single file or a result

    @property
    def sticky(self) -> bool:
        return self.duration_ms == STICKY


# --------------------------------------------------------------------------- actions
def show_in_folder(path: Path) -> ToastAction:
    return ToastAction(ActionKind.SHOW_IN_FOLDER, translate("Toast", "Show in folder"), path)


def undo_action(job_id: str, count: int) -> ToastAction:
    return ToastAction(
        ActionKind.UNDO,
        translate("Toast", "Undo all") if count > 1 else translate("Toast", "Undo"),
        job_id,
    )


def details_action(text: str) -> ToastAction:
    return ToastAction(ActionKind.DETAILS, translate("Toast", "Details"), text)


def _output_actions(result: JobResult) -> tuple[ToastAction, ...]:
    """Show in folder for the first output, and Undo when the registry kept something (D5)."""
    outputs = result.outputs
    if not outputs:
        return ()
    return (show_in_folder(outputs[0].path), undo_action(result.job_id, len(outputs)))


def _details_text(result: JobResult) -> str:
    """Every failed file with its reason, for the Details button (the body shows three). The
    tray's alert for a critical result takes the same payload from the model."""
    lines = [f"{r.source} — {reason_text(r.error)}" for r in result.failed]
    changed = [r for r in result.results if not r.source_intact]
    if changed:
        lines.append("")
        lines.append(
            translate(
                "Toast", "The source file changed while it was being read; nothing was written."
            )
        )
        lines.extend(str(r.source) for r in changed)
    return "\n".join(lines)


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
            translate("Toast", "Nothing to convert"),
            translate("Toast", "%n file(s) already %1", None, result.skipped_count).replace(
                "%1", result.target.label
            ),
        )
    if outcome is JobOutcome.ALREADY_COMPACT:
        names = ", ".join(r.source.name for r in result.already_compact[:BODY_LINES])
        return ToastModel(
            ToastKind.INFO,
            translate("Toast", "Already compact"),
            translate("Toast", "%1 — no smaller file was made").replace("%1", names),
        )
    return _success(result)


def _success(result: JobResult) -> ToastModel:
    outputs = result.outputs
    compress = result.target.kind is TargetKind.COMPRESS
    if len(outputs) == 1 and not result.skipped_count and not result.already_compact:
        out = outputs[0]
        title = (
            translate("Toast", "Compressed")
            if compress
            else translate("Toast", "Converted to %1").replace("%1", result.target.label)
        )
        before = human_size(_file_size(out.source))
        body = f"{out.path.name} · {before} → {human_size(out.size)}"
    else:
        if compress:
            title = translate("Toast", "%n file(s) compressed", None, len(outputs))
            if result.already_compact:
                title += " · " + translate(
                    "Toast", "%n already compact", None, len(result.already_compact)
                )
        else:
            title = translate("Toast", "%n file(s) converted to %1", None, len(outputs)).replace(
                "%1", result.target.label
            )
        body = ""
        if result.skipped_count:
            body = translate(
                "Toast", "%n skipped — already %1", None, result.skipped_count
            ).replace("%1", result.target.label)
    if any(r.used_fallback for r in result.results):
        folder = next(r.output.path.parent for r in result.results if r.used_fallback and r.output)
        note = translate("Toast", "Saved to %1 — the source folder is read-only").replace(
            "%1", _short_folder(folder)
        )
        body = f"{body}\n{note}" if body else note
    return ToastModel(ToastKind.SUCCESS, title, body, actions=_output_actions(result))


def _partial(result: JobResult) -> ToastModel:
    total = result.ok_count + len(result.failed)
    title = (
        translate("Toast", "%1 of %2 converted")
        .replace("%1", str(result.ok_count))
        .replace("%2", str(total))
    )
    actions: tuple[ToastAction, ...] = (details_action(_details_text(result)),)
    if result.outputs:
        actions += (show_in_folder(result.outputs[0].path),)
    return ToastModel(ToastKind.WARNING, title, _failure_lines(result.failed), ERROR_MS, actions)


def _failed(result: JobResult) -> ToastModel:
    failed = result.failed
    if len(failed) == 1:
        title = translate("Toast", "Couldn't convert %1").replace("%1", failed[0].source.name)
        body = reason_text(failed[0].error)
    else:
        title = translate("Toast", "Couldn't convert %n file(s)", None, len(failed))
        body = _failure_lines(failed)
    actions = (details_action(_details_text(result)),)
    return ToastModel(ToastKind.ERROR, title, body, ERROR_MS, actions)


def _source_changed(result: JobResult) -> ToastModel:
    changed = [r for r in result.results if not r.source_intact]
    names = ", ".join(r.source.name for r in changed[:BODY_LINES])
    body = translate("Toast", "%1 — size or date differs.").replace("%1", names)
    body += "\n" + translate(
        "Toast", "This should never happen. Please report it. Nothing was written."
    )
    actions = (details_action(_details_text(result)), show_in_folder(changed[0].source))
    return ToastModel(
        ToastKind.CRITICAL,
        translate("Toast", "Source file changed during conversion"),
        body,
        STICKY,
        actions,
    )


def _failure_lines(failed: tuple[TaskResult, ...]) -> str:
    lines = [f"{r.source.name} — {reason_text(r.error)}" for r in failed[:BODY_LINES]]
    if len(failed) > BODY_LINES:
        lines.append(translate("Toast", "and %n more", None, len(failed) - BODY_LINES))
    return "\n".join(lines)


def reason_text(code: ErrorCode | None) -> str:
    texts = {
        ErrorCode.UNREADABLE: translate("Toast", "The file couldn't be read."),
        ErrorCode.UNSUPPORTED_ANIMATED: translate("Toast", "Animated images aren't supported."),
        ErrorCode.ENGINE_MISSING: translate("Toast", "HEIC support isn't installed."),
        ErrorCode.NOT_SMALLER: translate("Toast", "No smaller file was made."),
        ErrorCode.WRITE_FAILED: translate("Toast", "The file couldn't be written."),
        ErrorCode.NO_SPACE: translate("Toast", "There isn't enough disk space."),
        ErrorCode.TIMEOUT: translate("Toast", "The conversion took too long and was stopped."),
        ErrorCode.WORKER_CRASHED: translate("Toast", "The converter stopped unexpectedly."),
        ErrorCode.PLUGIN_ERROR: translate("Toast", "The converter reported an error."),
        ErrorCode.SOURCE_CHANGED: translate(
            "Toast", "The source file changed during the conversion."
        ),
    }
    return texts.get(code, translate("Toast", "Unknown error."))  # type: ignore[arg-type]


# --------------------------------------------------------------------------- working and undo
def working_toast(count: int, target_label: str, done: int = 0, *, name: str = "") -> ToastModel:
    """A batch shows its bar and "5 / 12"; a single file (``name``) only its title."""
    if count > 1:
        title = translate("Toast", "Converting %n file(s) to %1…", None, count).replace(
            "%1", target_label
        )
        return ToastModel(
            ToastKind.WORKING, title, f"{done} / {count}", STICKY, progress=Progress(done, count)
        )
    title = (
        translate("Toast", "Converting %1 to %2…").replace("%1", name).replace("%2", target_label)
    )
    return ToastModel(ToastKind.WORKING, title, "", STICKY)


def undo_toast(outcome: UndoOutcome) -> ToastModel:
    if outcome.complete:
        names = ", ".join(p.name for p in outcome.recycled[:BODY_LINES])
        return ToastModel(ToastKind.SUCCESS, translate("Toast", "Moved to Recycle Bin"), names)
    changed = [i.path.name for i in outcome.items if i.status is UndoStatus.CHANGED]
    missing = [i.path.name for i in outcome.items if i.status is UndoStatus.MISSING]
    refused = [i.path.name for i in outcome.items if i.status is UndoStatus.REFUSED]
    lines = []
    if changed:
        lines.append(
            translate("Toast", "%1 changed after conversion.").replace(
                "%1", ", ".join(changed[:BODY_LINES])
            )
        )
    if missing:
        lines.append(
            translate("Toast", "%1 is no longer there.").replace(
                "%1", ", ".join(missing[:BODY_LINES])
            )
        )
    if refused:
        lines.append(
            translate("Toast", "%1 has no Recycle Bin here.").replace(
                "%1", ", ".join(refused[:BODY_LINES])
            )
        )
    if outcome.recycled:
        lines.append(
            translate("Toast", "%n file(s) moved to Recycle Bin", None, len(outcome.recycled))
        )
    still_there = [
        i.path
        for i in outcome.items
        if i.status in (UndoStatus.CHANGED, UndoStatus.REFUSED) and i.path.name
    ]
    actions = (show_in_folder(still_there[0]),) if still_there else ()
    return ToastModel(
        ToastKind.WARNING, translate("Toast", "Not undone"), "\n".join(lines), ERROR_MS, actions
    )


# --------------------------------------------------------------------------- the HEIC engine (A6)
def heic_offer_toast(size: int) -> ToastModel:
    body = translate(
        "Toast", "Install it to convert HEIC photos. The download is %1 from PyPI."
    ).replace("%1", human_size(size))
    action = ToastAction(ActionKind.INSTALL_HEIC, translate("Toast", "Install"))
    return ToastModel(
        ToastKind.INFO,
        translate("Toast", "HEIC support isn't installed."),
        body,
        ERROR_MS,
        (action,),
    )


def heic_working_toast() -> ToastModel:
    return ToastModel(ToastKind.WORKING, translate("Toast", "Installing HEIC support…"), "", STICKY)


def heic_installed_toast() -> ToastModel:
    return ToastModel(
        ToastKind.SUCCESS,
        translate("Toast", "HEIC support installed"),
        translate("Toast", "Drag a HEIC photo to try it."),
    )


def heic_removed_toast(leftover: bool) -> ToastModel:
    body = translate("Toast", "The files still in use go at the next start.") if leftover else ""
    return ToastModel(ToastKind.INFO, translate("Toast", "HEIC support removed"), body)


def heic_failed_toast(failure: EngineFailure, details: str) -> ToastModel:
    texts = {
        EngineFailure.DOWNLOAD: translate(
            "Toast", "The download failed. Check the connection and try again."
        ),
        EngineFailure.MISMATCH: translate(
            "Toast", "The download didn't match the expected file. Nothing was installed."
        ),
        EngineFailure.ARCHIVE: translate(
            "Toast", "The downloaded file couldn't be unpacked. Nothing was installed."
        ),
        EngineFailure.WRITE: translate("Toast", "The engine folder couldn't be written."),
    }
    actions = (details_action(details),)
    return ToastModel(
        ToastKind.ERROR,
        translate("Toast", "Couldn't install HEIC support"),
        texts[failure],
        ERROR_MS,
        actions,
    )


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
