"""Scripted drag run against the app itself: rows C13-C20 and C23 of the integration checklist.

A developer diagnostic, not shipped. It reuses ``tools/drag_driver.py`` (input, UI Automation, the
safety rules) but starts ``python -m morphwheel --debug`` instead of the probe and reads the app's
own log. Results are **synthetic** (S0-2), and they say nothing about hand timing, the UAC prompt
(C21) or swapped buttons (C22), which stay by hand.

The rules of ``drag_driver`` apply unchanged: only its own test files are pressed, every press
point is verified first, the button is released only over the wheel or the test window's item
list, anything unexpected ends the run with Esc, and nothing is deleted.

Since S3 every drop converts for real, so the run reads the engine's log lines too (``job …``,
``job … finished``, the toast). Outputs land beside the test files: the run lists the ones it
created (``outputs_created`` in the results) and leaves them where they are. C23 drops a PNG on
JPG, which sits north: the wheel is opened low enough in the item list that the JPG point is inside
the list, and the run stops (Esc) if the wheel came up anywhere else, so a release can never land
on the command bar or the address bar above it.

Usage (an active desktop session; hands off the mouse and keyboard)::

    .venv\\Scripts\\python.exe tools\\wheel_driver.py --dry-run
    .venv\\Scripts\\python.exe tools\\wheel_driver.py [--rows C13,C23]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import drag_driver as dd
from drag_driver import (
    LOG_DIR,
    ROOT,
    TEST_DIR,
    VK_ESCAPE,
    VK_SHIFT,
    Line,
    Row,
    Run,
    Stop,
    preflight,
    sha256,
    user32,
)

APP_LOG = LOG_DIR / "morphwheel.log"
FILE_PNG, FILE_PNG2, FILE_WEBP, FILE_TXT = (
    "mw-test-a.png",
    "mw-test-b.png",
    "mw-test-d.webp",
    "mw-test-e.txt",
)

# The app's wheel, size M, logical px from the centre (core/geometry.py).
SLOT_MID_R = (40.0 + 118.0) / 2  # 79
HALO_R = 190.0
SLOTS = {"n": (0, -1), "ne": (1, -1), "e": (1, 0), "s": (0, 1)}  # unit directions, y down

APP_LINE_RE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3}) (\w+)\s+\S+ (\S+): (.*)$")
PRESS_RE = re.compile(r"^press at \((-?\d+), (-?\d+)\), allowed=(\w+), chain=(.*)$")
SHOWN_RE = re.compile(r"center \((-?\d+), (-?\d+)\)")
# The engine's lines (engine/dispatcher.py) and the toast's (ui/toasts/manager.py), since S3.
JOB_START_RE = re.compile(r"^job (\w+): (\d+) file\(s\) -> (\S+) \((\d+) skipped\)$")
JOB_OUT_RE = re.compile(r"^job (\w+): (.+?) -> (.+) \((\d+) bytes, (\d+) ms(, fallback folder)?\)$")
JOB_FAIL_RE = re.compile(r"^job (\w+): (.+) failed with (\S+): (.*)$")
JOB_DONE_RE = re.compile(r"^job (\w+) finished: (\w+)$")
TOAST_RE = re.compile(r"""^toast: (\w+) (['"])(.*)\2$""")
SLOT_MARGIN = 32.0  # logical px: how far inside the item list the JPG point must stay (C23)


@dataclass(frozen=True)
class JobOutput:
    """One ``job <id>: <source> -> <output> (<n> bytes, <ms> ms)`` line."""

    job: str
    source: str
    output: str
    size: int
    ms: int
    fallback: bool  # written to Downloads\Morphwheel instead of beside the source


def job_outputs(lines: Iterable[Line]) -> list[JobOutput]:
    found = []
    for line in lines:
        if line.tag == "OUT" and (m := JOB_OUT_RE.match(line.msg)):
            found.append(JobOutput(m[1], m[2], m[3], int(m[4]), int(m[5]), m[6] is not None))
    return found


def job_started(lines: Iterable[Line], target: str) -> tuple[str, int, int] | None:
    """The first job onto ``target``: (job id, file count, skipped count)."""
    for line in lines:
        if line.tag == "JOB" and (m := JOB_START_RE.match(line.msg)) and m[3] == target:
            return m[1], int(m[2]), int(m[4])
    return None


def job_outcome(lines: Iterable[Line], job: str) -> str | None:
    for line in lines:
        if line.tag == "DONE" and (m := JOB_DONE_RE.match(line.msg)) and m[1] == job:
            return m[2]
    return None


def toasts(lines: Iterable[Line]) -> list[tuple[str, str]]:
    """(kind, title) of every toast shown."""
    return [(m[1], m[3]) for x in lines if x.tag == "toast" and (m := TOAST_RE.match(x.msg))]


def inside(rect: tuple[int, int, int, int], point: tuple[int, int], margin: int = 0) -> bool:
    left, top, right, bottom = rect
    x, y = point
    return left + margin <= x < right - margin and top + margin <= y < bottom - margin


def created_outputs(
    lines: Iterable[Line], folder: Path, before: set[str], sources: Iterable[Path]
) -> list[Path]:
    """The files this run's jobs wrote into ``folder``: new names only, never a source."""
    source_names = {p.name for p in sources}
    found: list[Path] = []
    for out in job_outputs(lines):
        name = out.output
        if out.fallback or Path(name).name != name or name in before or name in source_names:
            continue
        path = folder / name
        if path.is_file() and path not in found:
            found.append(path)
    return found


def conversion_checks(
    lines: list[Line],
    *,
    source: str,
    target: str,
    pil_format: str,
    folder: Path,
    before: set[str],
) -> tuple[dict[str, bool], JobOutput | None]:
    """C23's checks on the engine's side: one job, one new file beside the source, the toast.

    ``before`` holds the names that were in ``folder`` before the run, so an output left by an
    earlier run can't pass for this one.
    """
    started = job_started(lines, target)
    job = started[0] if started else None
    out = next((o for o in job_outputs(lines) if o.job == job and o.source == source), None)
    path = folder / out.output if out is not None else None
    new_beside = (
        out is not None
        and path is not None
        and not out.fallback
        and Path(out.output).name == out.output
        and out.output not in before
        and path.is_file()
    )
    real = False
    if new_beside and path is not None:
        from PIL import Image  # a dev dependency, as for the test files

        try:
            with Image.open(path) as image:
                real = image.format == pil_format
        except OSError:
            real = False
    checks = {
        f"job: 1 file(s) -> {target} (0 skipped)": started is not None and started[1:] == (1, 0),
        f"{source} -> a new file beside it": new_beside,
        "the output's size is the logged size": new_beside
        and out is not None
        and path is not None
        and path.stat().st_size == out.size,
        f"the output is a real {pil_format}": real,
        "job finished: success": job is not None and job_outcome(lines, job) == "success",
        # The kind, not the title: the title is translated (D3a); it stays in the row's log lines.
        "toast: success": any(kind == "success" for kind, _ in toasts(lines)),
    }
    return checks, out


def translate(logger: str, msg: str) -> tuple[str, str]:
    """Map an app log line onto the tags ``drag_driver``'s building blocks look for."""
    if m := PRESS_RE.match(msg):
        return "down", f"at {m[1]},{m[2]} source_ok={m[3]} chain={m[4]}"
    if JOB_DONE_RE.match(msg):
        return "DONE", msg
    if JOB_START_RE.match(msg):
        return "JOB", msg
    if JOB_OUT_RE.match(msg):
        return "OUT", msg
    if JOB_FAIL_RE.match(msg):
        return "FAIL", msg
    if msg.startswith("toast: "):
        return "toast", msg
    if msg.startswith("state pressed -> dragging"):
        return "thresh", msg
    if msg.startswith("state "):
        return "state", msg
    if msg.startswith("wheel shown"):
        return "SHOW", msg
    if msg.startswith("DragEnter"):
        return "ENTER", msg
    if msg.startswith("hover:"):
        return "move", msg
    if msg.startswith("DropRequest"):
        return "DROP", msg
    if msg.startswith("hide:"):
        return "hide", msg
    if msg.startswith("Esc pressed"):
        return "esc", msg
    return logger.rsplit(".", 1)[-1], msg


class AppLog(dd.ProbeLog):
    """Tails ``morphwheel.log`` and presents it with the probe's tags."""

    def poll(self) -> None:
        self._rest += self._file.read()
        *done, self._rest = self._rest.split("\n")
        for raw in done:
            if m := APP_LINE_RE.match(raw):
                stamp = datetime.strptime(m[1], "%Y-%m-%d %H:%M:%S.%f").timestamp() * 1000
                tag, msg = translate(m[3], m[4])
                self.lines.append(Line(stamp, tag, msg))


class WheelRun(Run):
    def __init__(self, dry_run: bool, rows: set[str] | None) -> None:
        super().__init__(dry_run, with_c4=False, rows=rows)
        self.timings: list[dict[str, float]] = []
        self.before: set[str] = set()  # the test folder's names before the run (C23)
        self.kept_lines: list[Line] = []  # the app's log, kept when teardown closes it

    # ------------------------------------------------------------- the app instead of the probe
    def make_test_files(self) -> None:
        from PIL import Image

        TEST_DIR.mkdir(exist_ok=True)
        self.before = {p.name for p in TEST_DIR.iterdir()}
        for i, name in enumerate((FILE_PNG, FILE_PNG2, FILE_WEBP)):
            path = TEST_DIR / name
            if not path.exists():
                Image.new("RGB", (64, 64), (40 + 80 * i, 120, 200)).save(path)
            self.hashes[path] = sha256(path)
        txt = TEST_DIR / FILE_TXT
        if not txt.exists():
            txt.write_text("throwaway test file for Morphwheel\n", encoding="utf-8")
        self.hashes[txt] = sha256(txt)

    def start_probe(self, frozen: bool) -> None:
        if frozen:
            raise Stop("the app has no frozen build in S2")
        if APP_LOG.exists():
            APP_LOG.unlink()  # the app rotates its own log; a fresh file keeps this run alone
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = dd.SW_SHOWMINNOACTIVE
        self.probe = subprocess.Popen(
            [sys.executable, "-m", "morphwheel", "--debug"],
            cwd=ROOT,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            startupinfo=startup,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        deadline = time.monotonic() + 30
        while not APP_LOG.exists():
            if time.monotonic() > deadline or self.probe.poll() is not None:
                raise Stop("the app didn't start a log")
            time.sleep(0.1)
        self.log = AppLog(APP_LOG)
        ready = self.log.wait_for(0, "raw_input", "raw input registered", timeout=30)
        if ready is None:
            raise Stop("the app never registered raw input")
        self.plan["app"] = ready.msg

    # ------------------------------------------------------------- building blocks
    def shift_drag(
        self, items: int, root: int, name: str, room_above: float | None = None
    ) -> tuple[int, tuple[int, int]]:
        """Press, cross the threshold, press Shift. Returns (log mark, wheel centre, physical).

        With ``room_above`` (logical px), the pointer first moves down inside the item list until
        that much list lies above it, so the wheel (centred on the pointer) opens there.
        """
        m, x, y = self.press_item(items, root, name)
        self.inp.glide(x + self.px(16), y)
        if not self.dry and self.wait(m, "thresh", timeout=1.0) is None:
            self.inp.glide(x, y)
            self.release("list", (x, y))
            raise Stop("the app saw no drag threshold")
        time.sleep(0.15)
        if room_above is not None:
            _left, top, _right, bottom = self.list_rect
            low = min(max(y, top + self.px(room_above)), bottom - self.px(SLOT_MARGIN))
            if low != y:
                self.inp.glide(x + self.px(16), low)
                time.sleep(0.15)
        shift_at = time.time()
        self.inp.key(VK_SHIFT, True)
        show = self.wait(m, "SHOW", timeout=1.5)
        if self.dry:
            return m, (x + self.px(16), y)
        if show is None:
            raise Stop("no 'wheel shown' after Shift")
        center = SHOWN_RE.search(show.msg)
        if center is None:
            raise Stop(f"can't read the centre from {show.msg!r}")
        self.timings.append({"shift_to_shown_ms": round(show.t_ms - shift_at * 1000, 1)})
        return m, (self.px(int(center[1])), self.px(int(center[2])))

    def slot_point(self, center: tuple[int, int], slot: str) -> tuple[int, int]:
        ux, uy = SLOTS[slot]
        norm = (ux * ux + uy * uy) ** 0.5
        return (
            round(center[0] + self.px(SLOT_MID_R) * ux / norm),
            round(center[1] + self.px(SLOT_MID_R) * uy / norm),
        )

    def hover(self, m: int, center: tuple[int, int], slot: str) -> Line | None:
        self.inp.glide(*self.slot_point(center, slot))
        return self.wait(m, "move", f"slot:{slot}", timeout=1.0)

    def enter_latency(self, m: int) -> float | None:
        assert self.log is not None
        show, enter = self.log.find(m, "SHOW"), self.log.find(m, "ENTER")
        if show is None or enter is None:
            return None
        ms = round(enter.t_ms - show.t_ms, 1)
        self.timings[-1]["shown_to_enter_ms"] = ms
        return ms

    def finish(self, m: int) -> None:
        """Let go of Shift and wait for the wheel to be gone."""
        self.inp.key(VK_SHIFT, False)
        self.wait(m, "hide", timeout=1.5)
        time.sleep(0.5)

    def job_lines(self, m: int, target: str) -> tuple[tuple[str, int, int] | None, str | None]:
        """Wait for the drop's job and its end. Returns (start, outcome).

        The first job may wait for a worker that is still starting, hence the long timeout.
        """
        assert self.log is not None
        self.wait(m, "JOB", f"-> {target} (", timeout=5.0)
        started = job_started(self.log.since(m), target)
        if started is None:
            return None, None
        self.wait(m, "DONE", f"job {started[0]} finished", timeout=15.0)
        return started, job_outcome(self.log.since(m), started[0])

    def stop_probe(self) -> None:
        """Stop the app, keeping its lines: the results list the outputs after teardown."""
        if self.log is not None:
            self.kept_lines = self.log.since(0)
        super().stop_probe()

    def outputs(self) -> list[Path]:
        """The files this run's conversions created beside the test files."""
        lines = self.log.since(0) if self.log is not None else self.kept_lines
        return created_outputs(lines, TEST_DIR, self.before, self.hashes)

    # ------------------------------------------------------------- the rows
    def c13_drop(self, row: str = "C13", name: str = FILE_PNG, slot: str = "s") -> None:
        m, center = self.shift_drag(self.window, self.window, name)
        enter = self.wait_enter(m, nudge=True)
        hovered = self.hover(m, center, slot)
        if not self.dry and hovered is None:
            raise Stop(f"the app never reported the pointer over slot {slot}")
        self.release("overlay")
        drop = self.wait(m, "DROP", timeout=1.5)
        self.finish(m)
        latency = self.enter_latency(m)
        started, outcome = self.job_lines(m, "compress")  # since S3 the drop really compresses
        assert self.log is not None
        self.record(
            row,
            m,
            {
                "wheel shown, then DragEnter with plan ok": enter is not None
                and "plan ok" in enter.msg,
                f"hub names the target over {slot}": hovered is not None
                and "hub=target" in hovered.msg,
                "DropRequest logged": drop is not None,
                "wheel hid (hide: dropped)": self.log.find(m, "hide", "dropped") is not None,
                "job: 1 file(s) -> compress": started is not None and started[1] == 1,
                "job finished: success or already_compact": outcome
                in {"success", "already_compact"},
                "files unchanged (sha256)": self.files_intact(),
            },
            drop=drop.msg if drop else "?",
            outcome=str(outcome),  # success, or already_compact for a tiny PNG: both fine
            shown_to_enter_ms=str(latency),
        )

    def c14_timing(self) -> None:
        for i in range(4):  # with C13's run: five samples
            self.c13_drop(f"C14.{i + 1}")
            time.sleep(0.6)
        shown = sorted(t["shift_to_shown_ms"] for t in self.timings)
        enter = sorted(t["shown_to_enter_ms"] for t in self.timings if "shown_to_enter_ms" in t)
        p95 = enter[min(len(enter) - 1, int(0.95 * len(enter)))] if enter else None
        self.rows.append(
            Row(
                "C14",
                "pass" if shown and max(shown) <= 50 and p95 is not None and p95 <= 100 else "fail",
                {
                    "wheel <= 50 ms after Shift (max)": bool(shown) and max(shown) <= 50,
                    "DragEnter <= 100 ms after shown (p95)": p95 is not None and p95 <= 100,
                },
                {"shift_to_shown_ms": str(shown), "shown_to_enter_ms": str(enter)},
            )
        )
        print(f"C14: shift->shown {shown} ms; shown->enter {enter} ms")

    def c15_hub(self) -> None:
        m, center = self.shift_drag(self.window, self.window, FILE_PNG)
        self.wait_enter(m, nudge=True)
        n = self.hover(m, center, "n")  # JPG: a target
        ne = self.hover(m, center, "ne")  # PNG onto a PNG: the source, disabled
        self.inp.glide(center[0] + self.px(4), center[1] + self.px(4))
        hub = self.wait(m, "move", "hover: hub", timeout=1.0)
        self.release("overlay")  # over the hub: rejected
        self.finish(m)
        assert self.log is not None
        self.record(
            "C15",
            m,
            {
                "JPG: hub=target jpeg": n is not None and "hub=target jpeg" in n.msg,
                "PNG: hub=disabled": ne is not None and "hub=disabled" in ne.msg,
                "centre: hub=cancel": hub is not None and "hub=cancel" in hub.msg,
                "no DropRequest": self.log.find(m, "DROP") is None,
                "files unchanged (sha256)": self.files_intact(),
            },
        )

    def c16_leave_and_reopen(self) -> None:
        m, center = self.shift_drag(self.window, self.window, FILE_PNG)
        self.wait_enter(m, nudge=True)
        self.inp.glide(center[0], center[1] + self.px(HALO_R + 60))  # well outside the ring
        left = self.wait(m, "hide", "left_halo", timeout=1.5)
        self.inp.key(VK_SHIFT, False)
        time.sleep(0.2)
        m2 = self.mark()
        self.inp.key(VK_SHIFT, True)
        shown = self.wait(m2, "SHOW", timeout=1.5)
        if not self.dry and shown is None:
            raise Stop("no second 'wheel shown' after Shift again")
        self.wait_enter(m2, nudge=True)
        self.release("overlay")  # the cursor is at the new wheel's centre: the hub
        self.finish(m2)
        assert self.log is not None
        self.record(
            "C16",
            m,
            {
                "leaving the halo hid the wheel (left_halo)": left is not None,
                "a new Shift press showed it again": shown is not None,
                "no DropRequest": self.log.find(m, "DROP") is None,
                "files unchanged (sha256)": self.files_intact(),
            },
        )

    def c17_release_over_hub(self) -> None:
        m, center = self.shift_drag(self.window, self.window, FILE_PNG)
        self.wait_enter(m, nudge=True)
        self.inp.glide(center[0] + self.px(5), center[1] + self.px(5))
        if not self.dry and self.wait(m, "move", "hover: hub", timeout=1.0) is None:
            raise Stop("the app never reported the pointer over the hub")
        self.release("overlay")
        hid = self.wait(m, "hide", timeout=1.5)
        self.finish(m)
        assert self.log is not None
        self.record(
            "C17",
            m,
            {
                "hid on release (hide: cancelled)": hid is not None and "cancelled" in hid.msg,
                "no DropRequest": self.log.find(m, "DROP") is None,
                "files unchanged (sha256)": self.files_intact(),
            },
        )

    def c18_esc(self) -> None:
        m, _ = self.shift_drag(self.window, self.window, FILE_PNG)
        self.wait_enter(m, nudge=True)
        self.inp.tap(VK_ESCAPE)
        esc = self.wait(m, "esc", timeout=1.0)
        hid = self.wait(m, "hide", timeout=1.5)
        self.inp.key(VK_SHIFT, False)
        # Esc made Explorer cancel the drag and the app hid the wheel, so the cursor is back over
        # the item list: a release there is a plain mouse-up.
        self.release("list")
        time.sleep(0.6)
        assert self.log is not None
        self.record(
            "C18",
            m,
            {
                "Esc logged": esc is not None,
                "Explorer cancelled the drag; the wheel hid": hid is not None,
                "no DropRequest": self.log.find(m, "DROP") is None,
                "files unchanged (sha256)": self.files_intact(),
            },
            hide=hid.msg if hid else "?",
        )

    def c19_mixed(self) -> None:
        """A PNG and a WebP together onto WebP (east): the WebP is skipped."""
        m0, x, y = self.press_item(self.window, self.window, FILE_PNG)
        self.release("list", (x, y))  # a click selects the PNG
        time.sleep(0.3)
        self.inp.key(dd.VK_CONTROL, True)
        _m1, bx, by = self.press_item(self.window, self.window, FILE_WEBP)
        self.release("list", (bx, by))  # Ctrl+click adds the WebP
        self.inp.key(dd.VK_CONTROL, False)
        time.sleep(0.3)
        m, center = self.shift_drag(self.window, self.window, FILE_WEBP)
        enter = self.wait_enter(m, nudge=True)
        hovered = self.hover(m, center, "e")
        self.release("overlay")
        drop = self.wait(m, "DROP", timeout=1.5)
        self.finish(m)
        started, outcome = self.job_lines(m, "webp")
        assert self.log is not None
        self.record(
            "C19",
            m0,
            {
                "DragEnter lists 2 urls": enter is not None and "2 url(s)" in enter.msg,
                "hub=target webp": hovered is not None and "hub=target webp" in hovered.msg,
                "DropRequest: 2 file(s) -> webp": drop is not None
                and "2 file(s) -> webp" in drop.msg,
                "job: 2 file(s) -> webp (1 skipped)": started is not None and started[1:] == (2, 1),
                "job finished: success": outcome == "success",
                "files unchanged (sha256)": self.files_intact(),
            },
        )
        # Leave a single selection behind for the next row.
        _m2, x, y = self.press_item(self.window, self.window, FILE_PNG)
        self.release("list", (x, y))
        time.sleep(0.3)

    def c20_unsupported(self) -> None:
        m, center = self.shift_drag(self.window, self.window, FILE_TXT)
        enter = self.wait_enter(m, nudge=True)
        hovered = self.hover(m, center, "s")
        self.inp.glide(center[0] + self.px(4), center[1] + self.px(4))
        self.wait(m, "move", "hover: hub", timeout=1.0)
        self.release("overlay")
        hid = self.wait(m, "hide", timeout=1.5)
        self.finish(m)
        assert self.log is not None
        self.record(
            "C20",
            m,
            {
                "DragEnter: plan not_supported": enter is not None and "not_supported" in enter.msg,
                "hub=not_supported over a slot": hovered is not None
                and "hub=not_supported" in hovered.msg,
                "no DropRequest": self.log.find(m, "DROP") is None,
                "hid on release": hid is not None,
                "files unchanged (sha256)": self.files_intact(),
            },
        )

    def c23_convert(self) -> None:
        """A real conversion: a PNG dropped on JPG (north) makes a JPG beside it (S3)."""
        m, center = self.shift_drag(
            self.window, self.window, FILE_PNG, room_above=SLOT_MID_R + SLOT_MARGIN
        )
        north = self.slot_point(center, "n")
        if not self.dry and not (
            inside(self.list_rect, center) and inside(self.list_rect, north, self.px(8))
        ):
            # Off the list, a release that misses the wheel could reach the command bar or the
            # address bar, where a Shift drop moves the file. Teardown presses Esc first.
            raise Stop(f"the JPG point {north} isn't inside the item list {self.list_rect}")
        enter = self.wait_enter(m, nudge=True)
        hovered = self.hover(m, center, "n")
        if not self.dry and hovered is None:
            raise Stop("the app never reported the pointer over JPG")
        self.release("overlay")
        drop = self.wait(m, "DROP", timeout=1.5)
        self.finish(m)
        self.job_lines(m, "jpeg")
        self.wait(m, "toast", "toast: success", timeout=3.0)
        assert self.log is not None
        checks, out = conversion_checks(
            self.log.since(m),
            source=FILE_PNG,
            target="jpeg",
            pil_format="JPEG",
            folder=TEST_DIR,
            before=self.before,
        )
        self.record(
            "C23",
            m,
            {
                "DragEnter with plan ok": enter is not None and "plan ok" in enter.msg,
                "hub=target jpeg over JPG": hovered is not None
                and "hub=target jpeg" in hovered.msg,
                "DropRequest: 1 file(s) -> jpeg": drop is not None
                and "1 file(s) -> jpeg" in drop.msg,
                **checks,
                "the source unchanged (sha256)": self.files_intact(),
            },
            output=out.output if out else "?",
            bytes=str(out.size) if out else "?",
            ms=str(out.ms) if out else "?",
        )

    # ------------------------------------------------------------- driver
    def go(self) -> None:
        self.uia = dd.Uia(LOG_DIR / "wheel_driver-helper.err.log")
        ping = self.uia.call("ping", timeout=60)
        self.plan["helper system dpi"] = ping.get("system_dpi")
        self.make_test_files()
        self.start_probe(frozen=False)
        self.open_window()
        self.plan["window"] = {"hwnd": self.window, "rect": dd.window_rect(self.window)}
        if self.dry:
            for name in (FILE_PNG, FILE_WEBP, FILE_TXT):
                self.plan[name] = self.uia.call("locate", hwnd=self.window, name=name)
            self.plan["dpr"] = self.dpr
            hashed = {p.name for p in self.hashes}
            self.plan["earlier outputs in the test folder"] = sorted(self.before - hashed)
            return
        self.park()
        steps: list[tuple[str, Callable[[], None]]] = [
            ("C18", self.c18_esc),  # first: every other row relies on Esc as the way out
            ("C13", self.c13_drop),
            ("C14", self.c14_timing),
            ("C15", self.c15_hub),
            ("C16", self.c16_leave_and_reopen),
            ("C17", self.c17_release_over_hub),
            ("C19", self.c19_mixed),
            ("C20", self.c20_unsupported),
            ("C23", self.c23_convert),
        ]
        for row, step in steps:
            if self.only is not None and row != "C18" and row not in self.only:
                continue
            step()
            time.sleep(0.8)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rows", help="only these rows, e.g. C13,C23 (C18 always runs first)")
    parser.add_argument("--countdown", type=int, default=10)
    args = parser.parse_args()

    user32.SetProcessDpiAwarenessContext(dd.ctypes.c_void_p(-4))
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    info = preflight()
    print("preflight:", json.dumps(info))
    if info["problems"] and not args.dry_run:
        print("NOT STARTED: " + "; ".join(info["problems"]))
        return 2
    if not args.dry_run:
        for left in range(args.countdown, 0, -1):
            print(f"first input in {left} s: hands off the mouse and keyboard", flush=True)
            time.sleep(1)
        if again := preflight()["problems"]:
            print("NOT STARTED: " + "; ".join(again))
            return 2

    rows = {r.strip().upper() for r in args.rows.split(",")} if args.rows else None
    run = WheelRun(args.dry_run, rows)
    error: str | None = None
    try:
        run.go()
    except Stop as e:
        error = str(e)
        print(f"STOPPED: {e}")
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        print(f"CRASHED: {error}")
        raise
    finally:
        run.teardown()
        created = run.outputs()  # after teardown: from the lines it kept
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out = LOG_DIR / f"wheel_driver-{'dry-' if args.dry_run else ''}{stamp}.json"
        result = {
            "synthetic": True,
            "dry_run": args.dry_run,
            "preflight": info,
            "plan": run.plan,
            "stopped": error,
            "rows": [asdict(r) for r in run.rows],
            "timings": run.timings,
            "files_intact": run.files_intact(),
            "test_files": [str(p) for p in run.hashes],
            "outputs_created": [str(p) for p in created],  # left in place
        }
        out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
        print(f"results: {out}")
        if created:
            names = ", ".join(p.name for p in created)
            print(f"outputs created, left in {TEST_DIR}: {names}")
        if args.dry_run:
            print(json.dumps(run.plan, indent=2, default=str))
    return 0 if error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
