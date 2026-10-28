"""Scripted drag run: rows C1-C8 and C12 of docs/testing/integration-checklist.md.

A developer diagnostic, not shipped. It drives real Explorer drags with ``SendInput`` while
``tools/drag_probe.py`` logs them, then checks each row's expected log lines. The results are
**synthetic** (decision S0-2): injected input goes through the same Explorer and OLE drag loop as a
real mouse, but it says nothing about hand timing, the physical console (C11) or a UAC prompt (C9).

Safety rules. Any failure stops the whole run.

- Only files this script generates are ever pressed: ``%TEMP%\\morphwheel-dragtest\\mw-test-*.png``,
  and with ``--with-c4`` a copy named ``morphwheel-dragtest.png`` on the Desktop.
- Before every press, UI Automation (``tools/uia_helper.ps1``) must find the item under the
  cursor's *actual* position, and the window under it must be this script's own Explorer window
  (or the desktop, for C4).
- If the cursor isn't where the script last put it, someone touched the mouse: stop.
- Shift goes down only after the probe logged this press with ``source_ok=True``.
- With Shift held, the button is released only after the probe logged SHOW, ENTER and the target
  region. Otherwise Esc comes first, so Explorer never completes a Shift (Move) drop. C8 runs
  first to prove that Esc cancels a drag started this way.
- On the way out, every key and button the script pressed is released, Esc first.
- Nothing is deleted. The test files stay where they are.

Usage. It needs a visible, active desktop session, and nobody may touch the mouse or keyboard
while it runs::

    .venv\\Scripts\\python.exe tools\\drag_driver.py --dry-run
    .venv\\Scripts\\python.exe tools\\drag_driver.py [--with-c4] [--rows C3,C12]

``--rows`` runs only those rows (C8 always runs first). ``--dry-run`` sends no input: it opens the
test window, finds every item and point, starts and stops both probes, and prints the plan.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from ctypes import wintypes as wt
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tools" / "drag_probe.py"
FROZEN_PROBE = ROOT / "packaging" / "output" / "dist" / "drag_probe" / "drag_probe.exe"
HELPER = ROOT / "tools" / "uia_helper.ps1"
LOG_DIR = Path(os.environ.get("LOCALAPPDATA", ".")) / "Morphwheel" / "logs"
TEST_DIR = Path(tempfile.gettempdir()) / "morphwheel-dragtest"
FILE_A, FILE_B, FILE_C = "mw-test-a.png", "mw-test-b.png", "mw-test-c.png"
DESKTOP_FILE = "morphwheel-dragtest.png"

# The probe's overlay (tools/drag_probe.py, drag mode), in logical px. JPG is due north.
# Physical px = logical px x dpr (system DPI / 96; the run checks it against the probe).
DIAM, R_HUB, R_LABEL = 300, 36, 78
# The slot the drops aim at. South (Compress) keeps every point the cursor visits inside the
# item list, so an echoed position can never put a press on the command bar above it.
SLOT, SLOT_DX, SLOT_DY = "Compress", 0, R_LABEL
WINDOW_SIZE = (900, 640)  # logical: room for all three test files

# --------------------------------------------------------------------------- Win32 (ctypes only)
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def _sig(fn: Any, res: Any, *args: Any) -> None:
    fn.restype, fn.argtypes = res, list(args)


_sig(user32.SendInput, wt.UINT, wt.UINT, ctypes.c_void_p, ctypes.c_int)
_sig(user32.GetCursorPos, wt.BOOL, ctypes.POINTER(wt.POINT))
_sig(user32.WindowFromPoint, wt.HWND, wt.POINT)
_sig(user32.GetAncestor, wt.HWND, wt.HWND, wt.UINT)
_sig(user32.GetForegroundWindow, wt.HWND)
_sig(
    user32.SetWindowPos,
    wt.BOOL,
    wt.HWND,
    wt.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wt.UINT,
)
_sig(user32.ShowWindow, wt.BOOL, wt.HWND, ctypes.c_int)
_sig(user32.IsIconic, wt.BOOL, wt.HWND)
_sig(user32.IsWindow, wt.BOOL, wt.HWND)
_sig(user32.GetWindowRect, wt.BOOL, wt.HWND, ctypes.POINTER(wt.RECT))
_sig(
    user32.SendMessageTimeoutW,
    ctypes.c_ssize_t,
    wt.HWND,
    wt.UINT,
    wt.WPARAM,
    wt.LPARAM,
    wt.UINT,
    wt.UINT,
    ctypes.POINTER(ctypes.c_size_t),
)
_sig(user32.PostMessageW, wt.BOOL, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
_sig(user32.GetClassNameW, ctypes.c_int, wt.HWND, wt.LPWSTR, ctypes.c_int)
_sig(user32.GetWindowThreadProcessId, wt.DWORD, wt.HWND, ctypes.POINTER(wt.DWORD))
_sig(user32.FindWindowW, wt.HWND, wt.LPCWSTR, wt.LPCWSTR)
_sig(user32.FindWindowExW, wt.HWND, wt.HWND, wt.HWND, wt.LPCWSTR, wt.LPCWSTR)
_sig(user32.EnumWindows, wt.BOOL, WNDENUMPROC, wt.LPARAM)
_sig(user32.GetSystemMetrics, ctypes.c_int, ctypes.c_int)
_sig(user32.SystemParametersInfoW, wt.BOOL, wt.UINT, wt.UINT, ctypes.c_void_p, wt.UINT)
_sig(user32.GetDpiForSystem, wt.UINT)
_sig(user32.SetProcessDpiAwarenessContext, wt.BOOL, wt.HANDLE)
_sig(user32.OpenInputDesktop, wt.HANDLE, wt.DWORD, wt.BOOL, wt.DWORD)
_sig(user32.CloseDesktop, wt.BOOL, wt.HANDLE)
_sig(
    user32.GetUserObjectInformationW,
    wt.BOOL,
    wt.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wt.DWORD,
    ctypes.POINTER(wt.DWORD),
)
_sig(user32.MapVirtualKeyW, wt.UINT, wt.UINT, wt.UINT)
_sig(shell32.SHGetFolderPathW, ctypes.c_long, wt.HWND, ctypes.c_int, wt.HANDLE, wt.DWORD, wt.LPWSTR)
_sig(kernel32.CreateToolhelp32Snapshot, wt.HANDLE, wt.DWORD, wt.DWORD)
_sig(kernel32.Process32FirstW, wt.BOOL, wt.HANDLE, ctypes.c_void_p)
_sig(kernel32.Process32NextW, wt.BOOL, wt.HANDLE, ctypes.c_void_p)
_sig(kernel32.CloseHandle, wt.BOOL, wt.HANDLE)

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_MOVE, MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0001, 0x0002, 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP = 0x0001, 0x0002
VK_SHIFT, VK_CONTROL, VK_ESCAPE, VK_LWIN, VK_C, VK_D = 0x10, 0x11, 0x1B, 0x5B, 0x43, 0x44
GA_ROOT = 2
SM_CXSCREEN, SM_CYSCREEN, SM_REMOTESESSION = 0, 1, 0x1000
SPI_GETWORKAREA = 0x0030
HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
SWP_NOSIZE, SWP_NOMOVE, SWP_SHOWWINDOW = 0x0001, 0x0002, 0x0040
SW_RESTORE, SW_SHOWMINNOACTIVE = 9, 7
WM_NCHITTEST, WM_CLOSE, HTCAPTION = 0x0084, 0x0010, 2
SMTO_ABORTIFHUNG = 0x0002
CSIDL_DESKTOPDIRECTORY = 0x0010


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wt.LONG),
        ("dy", wt.LONG),
        ("mouseData", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wt.WORD),
        ("wScan", wt.WORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


assert ctypes.sizeof(INPUT) == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)


def window_class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def root_of(x: int, y: int) -> int:
    """The top-level window under a screen point."""
    child = user32.WindowFromPoint(wt.POINT(x, y))
    return int(user32.GetAncestor(child, GA_ROOT) or 0) if child else 0


def window_pid(hwnd: int) -> int:
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", wt.LONG),
        ("dwFlags", wt.DWORD),
        ("szExeFile", wt.WCHAR * 260),
    ]


def process_tree(pid: int) -> set[int]:
    """``pid`` and its descendants. The venv's python.exe is a launcher: the real interpreter,
    which owns the probe's windows, is its child."""
    parents: dict[int, int] = {}
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if snapshot == wt.HANDLE(-1).value:
        return {pid}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            parents[entry.th32ProcessID] = entry.th32ParentProcessID
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    tree = {pid}
    while True:
        more = {p for p, parent in parents.items() if parent in tree and p not in tree}
        if not more:
            return tree
        tree |= more


def top_windows(cls: str) -> set[int]:
    found: set[int] = set()

    @WNDENUMPROC
    def visit(hwnd: Any, _: Any) -> bool:
        if hwnd and window_class(hwnd) == cls:
            found.add(int(hwnd))
        return True

    user32.EnumWindows(visit, 0)
    return found


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def work_area() -> tuple[int, int, int, int]:
    r = wt.RECT()
    user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(r), 0)
    return r.left, r.top, r.right, r.bottom


def nc_hit_test(hwnd: int, x: int, y: int) -> int:
    result = ctypes.c_size_t()
    lparam = ((y & 0xFFFF) << 16) | (x & 0xFFFF)
    if not user32.SendMessageTimeoutW(
        hwnd, WM_NCHITTEST, 0, lparam, SMTO_ABORTIFHUNG, 500, ctypes.byref(result)
    ):
        return -1
    return result.value


def place(hwnd: int, x: int, y: int, w: int, h: int) -> None:
    """Restore, move and raise a window (TOPMOST then NOTOPMOST lifts it without stealing focus)."""
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetWindowPos(hwnd, HWND_TOPMOST, x, y, w, h, SWP_SHOWWINDOW)
    user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
    time.sleep(0.6)


def desktop_dir() -> Path:
    buf = ctypes.create_unicode_buffer(260)
    if shell32.SHGetFolderPathW(None, CSIDL_DESKTOPDIRECTORY, None, 0, buf) != 0:
        raise Stop("can't find the Desktop folder")
    return Path(buf.value)


def desktop_list_view() -> int:
    """The desktop's icon view (SysListView32 inside SHELLDLL_DefView, under Progman or WorkerW)."""
    hosts = [int(user32.FindWindowW("Progman", None) or 0), *sorted(top_windows("WorkerW"))]
    for host in hosts:
        defview = user32.FindWindowExW(host, None, "SHELLDLL_DefView", None) if host else None
        if defview:
            view = user32.FindWindowExW(defview, None, "SysListView32", None)
            if view:
                return int(view)
    raise Stop("can't find the desktop icon view")


# --------------------------------------------------------------------------- pure helpers
LINE_RE = re.compile(r"^\s*([\d.]+) \[(\w+)\s*\] (.*)$")
ENTER_MS_RE = re.compile(r"\+([\d.]+) ms after show")


def overlay_center(
    px: int, py: int, work: tuple[int, int, int, int], dpr: float = 1.0
) -> tuple[int, int]:
    """Where the probe centres its overlay for a cursor at physical (px, py).

    The same clamp as the probe, which works in logical px (physical / dpr).
    """
    left, top, right, bottom = (round(v / dpr) for v in work)
    x = min(max(round(px / dpr) - DIAM // 2, left), right - DIAM)
    y = min(max(round(py / dpr) - DIAM // 2, top), bottom - DIAM)
    return round((x + DIAM // 2) * dpr), round((y + DIAM // 2) * dpr)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Stop(Exception):  # noqa: N818 - it stops the run; it isn't only an error
    """Stop the whole run: something isn't as the safety rules require."""


@dataclass
class Line:
    t_ms: float
    tag: str
    msg: str

    def __str__(self) -> str:
        return f"{self.t_ms:10.1f} [{self.tag:<7}] {self.msg}"


class ProbeLog:
    """Tails the probe's UTF-8 log file. The probe's console isn't used: it may not be UTF-8."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._file = path.open(encoding="utf-8")
        self._rest = ""
        self.lines: list[Line] = []

    def poll(self) -> None:
        self._rest += self._file.read()
        *done, self._rest = self._rest.split("\n")
        for raw in done:
            if m := LINE_RE.match(raw):
                self.lines.append(Line(float(m[1]), m[2], m[3]))

    def mark(self) -> int:
        self.poll()
        return len(self.lines)

    def since(self, mark: int) -> list[Line]:
        self.poll()
        return self.lines[mark:]

    def find(self, mark: int, tag: str, contains: str = "") -> Line | None:
        return next((x for x in self.since(mark) if x.tag == tag and contains in x.msg), None)

    def wait_for(
        self, mark: int, tag: str, contains: str = "", timeout: float = 1.5
    ) -> Line | None:
        deadline = time.monotonic() + timeout
        while (found := self.find(mark, tag, contains)) is None and time.monotonic() < deadline:
            time.sleep(0.01)
        return found

    def close(self) -> None:
        self._file.close()


# --------------------------------------------------------------------------- input
def _mouse(flags: int, dx: int = 0, dy: int = 0) -> INPUT:
    return INPUT(INPUT_MOUSE, _INPUTUNION(mi=MOUSEINPUT(dx, dy, 0, flags, 0, 0)))


def _key(vk: int, down: bool) -> INPUT:
    flags = (0 if down else KEYEVENTF_KEYUP) | (KEYEVENTF_EXTENDEDKEY if vk == VK_LWIN else 0)
    scan = user32.MapVirtualKeyW(vk, 0)
    return INPUT(INPUT_KEYBOARD, _INPUTUNION(ki=KEYBDINPUT(vk, scan, flags, 0, 0)))


class Input:
    """SendInput with bookkeeping: what is held, and where the cursor should be."""

    def __init__(self, dry_run: bool) -> None:
        self.dry = dry_run
        self.sw = user32.GetSystemMetrics(SM_CXSCREEN)
        self.sh = user32.GetSystemMetrics(SM_CYSCREEN)
        self.last: tuple[int, int] | None = None
        self.paths: list[tuple[tuple[int, int], tuple[int, int]]] = []  # recent moves
        self.button = False
        self.held: list[int] = []

    def _send(self, *inputs: INPUT) -> None:
        if self.dry:
            return
        array = (INPUT * len(inputs))(*inputs)
        sent = user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT))
        if sent != len(inputs):
            raise Stop(f"SendInput sent {sent} of {len(inputs)} (error {ctypes.get_last_error()})")

    def cursor(self) -> tuple[int, int]:
        pt = wt.POINT()
        if not user32.GetCursorPos(ctypes.byref(pt)):
            raise Stop(
                f"GetCursorPos failed (error {ctypes.get_last_error()}): desktop not visible"
            )
        return pt.x, pt.y

    def near_recent(self, x: int, y: int, tol: float = 4.0) -> bool:
        """Within ``tol`` px of somewhere this script moved the cursor through recently."""
        for (ax, ay), (bx, by) in self.paths:
            dx, dy = bx - ax, by - ay
            along = 0.0 if dx == dy == 0 else ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)
            t = min(1.0, max(0.0, along))
            if math.hypot(x - (ax + t * dx), y - (ay + t * dy)) <= tol:
                return True
        return False

    def hands_off(self) -> None:
        """Stop if the cursor is somewhere this script never put it.

        Over RDP, the client echoes earlier cursor positions back to the server a moment after
        injected moves, so any point along the last few moves counts. A hand on the mouse lands
        somewhere else.
        """
        if self.dry or self.last is None:
            return
        for _ in range(3):  # a transient lag settles within a few reads
            x, y = self.cursor()
            if self.near_recent(x, y):
                self.last = (x, y)  # the next move starts from where the cursor really is
                return
            time.sleep(0.03)
        raise Stop(f"the mouse moved to {x},{y} (expected {self.last}): hands off during the run")

    def at(self, target: tuple[int, int]) -> bool:
        x, y = self.cursor()
        return abs(x - target[0]) <= 3 and abs(y - target[1]) <= 3

    def _settle(self, x: int, y: int, hold: float = 0.35, timeout: float = 3.0) -> tuple[int, int]:
        """Wait until the cursor reports the target and stays there for ``hold`` seconds.

        Over RDP the position lags the injected input, and the client echoes earlier positions
        back for a while. An off-target read puts the cursor back and restarts the hold.
        """
        deadline = time.monotonic() + timeout
        stable_since: float | None = None
        while True:
            cx, cy = self.cursor()
            now = time.monotonic()
            if abs(cx - x) <= 2 and abs(cy - y) <= 2:
                stable_since = stable_since or now
                if now - stable_since >= hold:
                    return cx, cy
            else:
                stable_since = None
                self._move(x, y)
            if now > deadline:
                raise Stop(f"the cursor won't stay at {x},{y} (last read {cx},{cy})")
            time.sleep(0.02)

    def reassert(self, target: tuple[int, int]) -> tuple[int, int]:
        """Put the cursor back on ``target`` after an echo moved it, and wait until it's there."""
        if self.dry:
            return target
        self._move(*target)
        self.last = self._settle(*target)
        return self.last

    def _move(self, x: int, y: int) -> None:
        self._send(
            _mouse(
                MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE,
                round(x * 65535 / (self.sw - 1)),
                round(y * 65535 / (self.sh - 1)),
            )
        )

    def glide(self, x: int, y: int, step: float = 24.0, pause: float = 0.012) -> tuple[int, int]:
        """Move in steps, so raw input and OLE see a movement, not a jump.

        Few steps: over RDP every intermediate position comes back as an echo later.
        """
        if self.dry:
            self.last = (x, y)
            return x, y
        self.hands_off()
        sx, sy = self.last or self.cursor()
        self.paths = [*self.paths[-3:], ((sx, sy), (x, y))]
        steps = max(1, math.ceil(math.hypot(x - sx, y - sy) / step))
        for i in range(1, steps + 1):
            self._move(round(sx + (x - sx) * i / steps), round(sy + (y - sy) * i / steps))
            time.sleep(pause)
        self.last = self._settle(x, y)
        return self.last

    def down(self, target: tuple[int, int]) -> None:
        """Press at ``target``, which the caller has verified; an echo in between is corrected."""
        self.hands_off()
        if not self.dry and not self.at(target):
            self.reassert(target)
        self._send(_mouse(MOUSEEVENTF_LEFTDOWN))
        self.button = True

    def up(self) -> None:
        """The bare release. Callers go through ``Run.release``, which verifies the point first."""
        self._send(_mouse(MOUSEEVENTF_LEFTUP))
        self.button = False

    def key(self, vk: int, down: bool) -> None:
        self._send(_key(vk, down))
        if down and vk not in self.held:
            self.held.append(vk)
        elif not down and vk in self.held:
            self.held.remove(vk)

    def tap(self, *vks: int) -> None:
        """Press in order, hold, release in reverse. The hold lets the probe's 8 ms poll see it."""
        for vk in vks:
            self.key(vk, True)
        time.sleep(0.06)
        for vk in reversed(vks):
            self.key(vk, False)
        time.sleep(0.05)

    def release_all(self) -> None:
        """The way out. Esc first, so a drag in flight is cancelled rather than dropped."""
        if self.dry:
            return
        try:
            if self.button:
                self.tap(VK_ESCAPE)
                time.sleep(0.25)
            for vk in reversed(list(self.held)):
                self.key(vk, False)
            if self.button:
                self._send(_mouse(MOUSEEVENTF_LEFTUP))
                self.button = False
        except Stop as e:
            print(f"!! cleanup could not send input: {e}")


# --------------------------------------------------------------------------- helper process
class Uia:
    """The UI Automation helper (tools/uia_helper.ps1), one JSON line each way."""

    def __init__(self, stderr_path: Path) -> None:
        self._stderr = stderr_path.open("w", encoding="utf-8")
        self._proc = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(HELPER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
            text=True,
            encoding="utf-8",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self._answers: queue.Queue[str] = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            self._answers.put(line)

    def call(self, cmd: str, timeout: float = 30.0, **args: Any) -> dict[str, Any]:
        text = json.dumps({"cmd": cmd, **args})
        if not text.isascii():
            raise Stop(f"refusing to send non-ASCII to the helper: {cmd}")
        assert self._proc.stdin is not None
        self._proc.stdin.write(text + "\n")
        self._proc.stdin.flush()
        try:
            answer: dict[str, Any] = json.loads(self._answers.get(timeout=timeout))
        except queue.Empty:
            raise Stop(f"the UI Automation helper didn't answer {cmd!r}") from None
        return answer

    def close(self) -> None:
        if self._proc.stdin is not None:
            self._proc.stdin.close()
        try:
            self._proc.wait(5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        self._stderr.close()


# --------------------------------------------------------------------------- the run
@dataclass
class Row:
    row: str
    status: str  # "pass" | "fail" | "not run"
    checks: dict[str, bool] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)


class Run:
    def __init__(self, dry_run: bool, with_c4: bool, rows: set[str] | None = None) -> None:
        self.dry = dry_run
        self.with_c4 = with_c4
        self.only = rows  # None: every row; otherwise these rows, with C8 always first
        self.inp = Input(dry_run)
        self.work = work_area()
        self.dpr = user32.GetDpiForSystem() / 96
        self.uia: Uia | None = None
        self.probe: subprocess.Popen[bytes] | None = None
        self.log: ProbeLog | None = None
        self.window = 0
        self.window_pos = (0, 0)
        self.list_rect = (0, 0, 0, 0)  # the items view: a release there can't move a file
        self.hashes: dict[Path, str] = {}
        self.desktop_shown = False
        self.rows: list[Row] = []
        self.plan: dict[str, Any] = {}

    # ------------------------------------------------------------- setup and teardown
    def make_test_files(self) -> None:
        from PIL import Image  # a dev dependency; only the driver's own test files use it

        TEST_DIR.mkdir(exist_ok=True)
        for i, name in enumerate((FILE_A, FILE_B, FILE_C)):
            path = TEST_DIR / name
            if not path.exists():
                Image.new("RGB", (64, 64), (40 + 80 * i, 120, 200)).save(path)
            self.hashes[path] = sha256(path)

    def files_intact(self) -> bool:
        return all(p.exists() and sha256(p) == h for p, h in self.hashes.items())

    def start_probe(self, frozen: bool) -> None:
        before = set(LOG_DIR.glob("drag_probe-drag-*.log"))
        cmd = (
            [str(FROZEN_PROBE), "drag", "--minutes", "10"]
            if frozen
            else [sys.executable, str(PROBE), "drag", "--minutes", "10"]
        )
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = SW_SHOWMINNOACTIVE
        self.probe = subprocess.Popen(
            cmd, cwd=ROOT, creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=startup
        )
        deadline = time.monotonic() + 30
        while not (new := set(LOG_DIR.glob("drag_probe-drag-*.log")) - before):
            if time.monotonic() > deadline or self.probe.poll() is not None:
                raise Stop(f"the {'frozen ' if frozen else ''}probe didn't start a log")
            time.sleep(0.1)
        self.log = ProbeLog(max(new, key=lambda p: p.stat().st_mtime))
        ready = self.log.wait_for(0, "init", "READY", timeout=30)
        if ready is None:
            raise Stop("the probe never logged READY")
        raw = self.log.find(0, "init", "raw input ok=")
        self.plan[f"probe ({'frozen' if frozen else 'source'})"] = raw.msg if raw else "?"

    def stop_probe(self) -> None:
        if self.log is not None:
            self.log.close()
            self.log = None
        if self.probe is not None and self.probe.poll() is None:
            self.probe.terminate()
            self.probe.wait(10)
        self.probe = None

    def open_window(self) -> None:
        assert self.uia is not None
        before = top_windows("CabinetWClass")
        subprocess.Popen(["explorer.exe", f"/n,{TEST_DIR}"])
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            answer = self.uia.call("find_window", path=str(TEST_DIR))["hwnds"]
            # PowerShell may hand a one-item list back as a bare number.
            hwnds = [
                int(h) for h in (answer if isinstance(answer, list) else [answer] if answer else [])
            ]
            new = [h for h in hwnds if h not in before]
            if new:
                self.window = new[0]
                break
            if hwnds:
                raise Stop("the test folder opened as a tab in an existing Explorer window")
            time.sleep(0.3)
        else:
            raise Stop("the test folder's Explorer window didn't appear")
        w, h = self.window_size
        left, top, right, bottom = self.work
        self.window_pos = (left + (right - left - w) // 2, top + (bottom - top - h) // 2)
        place(self.window, *self.window_pos, w, h)
        time.sleep(1.5)  # Explorer finishes laying the view out after the resize
        self.read_list_rect()
        self.plan["list_rect"] = self.list_rect

    @property
    def window_size(self) -> tuple[int, int]:
        return self.px(WINDOW_SIZE[0]), self.px(WINDOW_SIZE[1])

    def px(self, logical: float) -> int:
        return round(logical * self.dpr)

    def restore_window(self) -> None:
        place(self.window, *self.window_pos, *self.window_size)

    def read_list_rect(self) -> None:
        assert self.uia is not None
        answer = self.uia.call("list_rect", hwnd=self.window)
        if not answer.get("ok"):
            raise Stop(f"the items view wasn't found: {answer.get('error')}")
        r = answer["rect"]
        self.list_rect = (r["left"], r["top"], r["right"], r["bottom"])

    def park(self) -> None:
        """Rest the cursor on the list's empty background, so echoes of it are harmless."""
        left, top, right, bottom = self.list_rect
        self.inp.glide((left + right) // 2, (top + bottom) // 2)

    def safe_release_point(self, where: str, x: int, y: int) -> bool:
        root = root_of(x, y)
        if where == "overlay":  # the probe's wheel: it accepts a Copy or rejects, never a Move
            return self.probe is not None and window_pid(root) in process_tree(self.probe.pid)
        if root != self.window:
            return False
        if where == "caption":
            return self.is_caption(x, y)
        left, top, right, bottom = self.list_rect
        return left <= x < right and top <= y < bottom

    def release(self, where: str, target: tuple[int, int] | None = None) -> None:
        """Let go of the button only where a drop can't move a file.

        ``where`` is "overlay" (the probe's wheel), "list" (our window's item list) or "caption"
        (our window's title bar). Over RDP an echo can move the cursor between the last move and
        the release, so the point is verified first and put back if needed. If that fails, Esc
        cancels the drag before the button goes up.
        """
        if self.dry:
            return
        target = target or self.inp.last
        assert target is not None
        seen: list[str] = []
        for _ in range(3):
            time.sleep(0.25)  # let echoes of earlier positions settle
            x, y = self.inp.cursor()
            if self.inp.at(target) and self.safe_release_point(where, x, y):
                self.inp.up()
                return
            root = root_of(x, y)
            seen.append(f"{x},{y} over {window_class(root)!r} pid={window_pid(root)}")
            self.inp.reassert(target)
        self.inp.tap(VK_ESCAPE)
        time.sleep(0.25)
        self.inp.up()
        probe_pid = self.probe.pid if self.probe else None
        raise Stop(
            f"couldn't verify a release over the {where} at {target} (probe pid {probe_pid}); "
            f"saw {seen}; cancelled with Esc"
        )

    def teardown(self) -> None:
        self.inp.release_all()
        if self.desktop_shown and not self.dry:
            try:
                self.inp.tap(VK_LWIN, VK_D)  # Win+D again brings the windows back
            except Stop as e:
                print(f"!! couldn't restore the windows after Win+D: {e}")
            self.desktop_shown = False
        self.stop_probe()
        if self.window and user32.IsWindow(self.window):
            user32.PostMessageW(self.window, WM_CLOSE, 0, 0)  # our own window only
        if self.uia is not None:
            self.uia.close()

    # ------------------------------------------------------------- building blocks
    def aim(self, items: int, root: int, name: str) -> tuple[int, int]:
        """Put the cursor on an item, then prove it is there before anything presses."""
        assert self.uia is not None
        # The view can still be laying out: the point must be the same twice, 0.3 s apart.
        for _ in range(4):
            found = self.uia.call("locate", hwnd=items, name=name)
            if not found["ok"]:
                raise Stop(f"{name}: {found['error']}")
            time.sleep(0.3)
            again = self.uia.call("locate", hwnd=items, name=name)
            if again.get("ok") and (again["x"], again["y"]) == (found["x"], found["y"]):
                break
        else:
            raise Stop(f"{name}: the item keeps moving")
        left, top, right, bottom = window_rect(root)
        if not (left <= found["x"] < right and top <= found["y"] < bottom):
            raise Stop(f"{name}: UI Automation and Win32 disagree on coordinates (DPI?)")
        x, y = self.inp.glide(found["x"], found["y"])
        time.sleep(0.15)  # hover effects (checkbox) settle before the check
        settled = self.uia.call("locate", hwnd=items, name=name)
        if settled.get("ok") and (abs(settled["x"] - x) > 2 or abs(settled["y"] - y) > 2):
            raise Stop(f"{name}: the item moved to {settled['x']},{settled['y']} under the cursor")
        self.plan[f"press {name}"] = (x, y, found.get("item"))
        check = self.uia.call("check", hwnd=items, name=name, x=x, y=y)
        if not check["ok"]:
            raise Stop(f"{name}: under the cursor is {check.get('hit')}, not the item")
        if root_of(x, y) != root:
            raise Stop(f"{name}: the window under {x},{y} isn't the expected one")
        return x, y

    def wait(self, mark: int, tag: str, contains: str = "", timeout: float = 1.5) -> Line | None:
        assert self.log is not None
        return None if self.dry else self.log.wait_for(mark, tag, contains, timeout)

    def mark(self) -> int:
        assert self.log is not None
        return self.log.mark()

    def press_item(self, items: int, root: int, name: str) -> tuple[int, int, int]:
        """Aim at the item and press on it. Returns (log mark, x, y).

        The probe logs where the press really landed. If an echo moved the cursor in the last
        instant, the press missed the item (Explorer starts a rubber band instead of a drag): let
        go where nothing can happen, and try again.
        """
        for _ in range(3):
            m = self.mark()
            x, y = self.aim(items, root, name)
            self.inp.down((x, y))
            down = self.wait(m, "down", timeout=1.0)
            if self.dry:
                return m, x, y
            if down is None or "source_ok=True" not in down.msg:
                self.release("list" if root == self.window else "overlay", (x, y))
                raise Stop(f"the probe didn't log the press as an allowed source: {down}")
            at = re.match(r"at (-?\d+),(-?\d+)", down.msg)
            if at and abs(int(at[1]) - x) <= 3 and abs(int(at[2]) - y) <= 3:
                return m, x, y
            print(f"    press landed at {at[0] if at else '?'} instead of {x},{y}: retrying")
            self.release("list" if root == self.window else "overlay", (x, y))
            time.sleep(0.8)
        raise Stop(f"{name}: three presses missed the item")

    def shift_drag(self, items: int, root: int, name: str) -> tuple[int, tuple[int, int]]:
        """Press, cross the threshold, press Shift. Returns (log mark, overlay centre)."""
        m, x, y = self.press_item(items, root, name)
        self.inp.glide(x + self.px(16), y)
        if not self.dry and self.wait(m, "thresh", timeout=1.0) is None:
            self.inp.glide(x, y)  # back on the item itself: a drop on itself does nothing
            self.release("list", (x, y))
            raise Stop("the probe saw no drag threshold")
        time.sleep(0.15)
        at_show = self.inp.last or (x + self.px(16), y)
        self.inp.key(VK_SHIFT, True)
        show = self.wait(m, "SHOW", timeout=1.5)
        if not self.dry and show is None:
            raise Stop("no SHOW after Shift")  # teardown presses Esc before letting go
        if show is not None and f"dpr={self.dpr}" not in show.msg:
            raise Stop(f"the probe's scale differs from {self.dpr}: {show.msg}")
        return m, overlay_center(*at_show, self.work, self.dpr)

    def wait_enter(self, m: int, nudge: bool) -> Line | None:
        """DragEnter needs OLE to notice the pointer over the new window: nudge, then wiggle."""
        if not nudge or self.inp.last is None:
            enter = self.wait(m, "ENTER", timeout=2.0)
        else:
            x, y = self.inp.last
            enter = None
            for dx in (3, -6, 9, -3):  # logical px, all within the hub
                self.inp.glide(x + self.px(dx), y)
                enter = self.wait(m, "ENTER", timeout=0.8)
                if enter is not None:
                    break
        if not self.dry and enter is None:
            raise Stop("no ENTER (DragEnter) on the overlay")
        return enter

    def drop_on_slot(self, m: int, center: tuple[int, int]) -> tuple[Line | None, Line | None]:
        self.inp.glide(center[0] + self.px(SLOT_DX), center[1] + self.px(SLOT_DY))
        if not self.dry and self.wait(m, "move", f"slot:{SLOT}", timeout=1.0) is None:
            raise Stop(f"the probe never reported the pointer over {SLOT}")
        self.release("overlay")
        drop = self.wait(m, "DROP", timeout=1.5)
        self.inp.key(VK_SHIFT, False)
        if not self.dry and drop is None:
            raise Stop(f"no DROP on {SLOT}")
        return drop, self.wait(m, "SAFETY", timeout=4.0)

    def record(self, row: str, m: int, checks: dict[str, bool], **notes: str) -> None:
        assert self.log is not None
        status = "pass" if all(checks.values()) else "fail"
        if self.dry:
            status, checks = "dry run", {}
        lines = [str(x) for x in self.log.since(m)]
        self.rows.append(Row(row, status, checks, notes, lines))
        print(f"{row}: {status.upper()} {notes or ''}")
        for name, ok in checks.items():
            print(f"    [{'x' if ok else ' '}] {name}")
        if status == "fail":
            raise Stop(f"{row} failed")

    def c1_like(self, row: str, items: int, root: int, name: str) -> dict[str, bool]:
        m, center = self.shift_drag(items, root, name)
        enter = self.wait_enter(m, nudge=True)
        drop, safety = self.drop_on_slot(m, center)
        assert self.log is not None
        down = self.log.find(m, "down")
        checks = {
            "SHOW, then ENTER": enter is not None,
            f"DROP slot:{SLOT} -> CopyAction": drop is not None
            and f"slot:{SLOT}" in drop.msg
            and "CopyAction" in drop.msg,
            f"the drop carries {name} only": drop is not None and f"files=['{name}']" in drop.msg,
            "probe: source intact": safety is not None and "source intact" in safety.msg,
            "files unchanged (sha256)": self.files_intact(),
        }
        latency = ENTER_MS_RE.search(enter.msg) if enter else None
        self.record(
            row,
            m,
            checks,
            enter_after_show_ms=latency[1] if latency else "?",
            source_chain=down.msg.split("chain=")[-1] if down else "?",
        )
        return checks

    # ------------------------------------------------------------- the rows
    def c8_esc(self) -> None:
        """Esc over the hub: if Esc didn't cancel, the release lands on the hub and is rejected."""
        m, _ = self.shift_drag(self.window, self.window, FILE_A)
        self.wait_enter(m, nudge=True)  # the cursor sits at the centre: the hub
        self.inp.tap(VK_ESCAPE)
        esc = self.wait(m, "esc", timeout=1.0)
        cancelled = self.wait(m, "leave", "button down", timeout=1.5)
        self.inp.key(VK_SHIFT, False)
        self.release("overlay")
        time.sleep(0.6)
        assert self.log is not None
        self.record(
            "C8",
            m,
            {
                "esc logged": esc is not None,
                "Esc cancelled the drag (DragLeave with the button down)": cancelled is not None,
                "no DROP": self.log.find(m, "DROP") is None,
                "files unchanged (sha256)": self.files_intact(),
            },
        )

    def c1(self) -> None:
        self.c1_like("C1", self.window, self.window, FILE_A)

    def c2_still(self) -> None:
        m, center = self.shift_drag(self.window, self.window, FILE_A)
        enter = self.wait(m, "ENTER", timeout=2.0)  # no input at all for 2 s
        time.sleep(0.2)
        if not self.dry and enter is None:
            self.wait_enter(m, nudge=True)
        drop, _ = self.drop_on_slot(m, center)
        self.record(
            "C2",
            m,
            {
                "ENTER arrived with the mouse still": enter is not None,
                f"DROP slot:{SLOT} -> CopyAction": drop is not None and "CopyAction" in drop.msg,
                "files unchanged (sha256)": self.files_intact(),
            },
        )

    def c3_hub(self) -> None:
        m, center = self.shift_drag(self.window, self.window, FILE_A)
        self.wait_enter(m, nudge=True)
        self.inp.glide(center[0] + self.px(5), center[1] + self.px(5))
        if not self.dry and self.wait(m, "move", "hub", timeout=1.0) is None:
            raise Stop("the probe never reported the pointer over the hub")
        self.release("overlay")
        time.sleep(0.6)
        self.inp.key(VK_SHIFT, False)
        assert self.log is not None
        hid = self.log.find(m, "leave", "button up") or self.log.find(m, "hide")
        self.record(
            "C3",
            m,
            {
                "no DROP": self.log.find(m, "DROP") is None,
                "overlay hid on release (leave/hide)": hid is not None,
                "files unchanged (sha256)": self.files_intact(),
            },
        )

    def c5_clipboard(self) -> None:
        m, bx, by = self.press_item(self.window, self.window, FILE_B)
        time.sleep(0.05)
        self.release("list", (bx, by))  # a click: selects B
        time.sleep(0.4)
        if not self.dry and int(user32.GetForegroundWindow() or 0) != self.window:
            raise Stop("our Explorer window isn't in front, so Ctrl+C would go elsewhere")
        self.inp.tap(VK_CONTROL, VK_C)
        time.sleep(0.4)
        m2, center = self.shift_drag(self.window, self.window, FILE_A)
        enter = self.wait_enter(m2, nudge=True)
        drop, _ = self.drop_on_slot(m2, center)
        self.record(
            "C5",
            m,
            {
                f"ENTER lists {FILE_A} only": enter is not None
                and f"files=['{FILE_A}']" in enter.msg,
                f"DROP lists {FILE_A} only": drop is not None and f"files=['{FILE_A}']" in drop.msg,
                "files unchanged (sha256)": self.files_intact(),
            },
            clipboard=f"now holds {FILE_B} (Ctrl+C)",
        )

    def c7_no_shift(self) -> None:
        m, x, y = self.press_item(self.window, self.window, FILE_A)
        self.inp.glide(x + self.px(20), y)
        thresh = self.wait(m, "thresh", timeout=1.0)
        time.sleep(0.3)
        self.inp.glide(x, y)  # back onto the item itself: dropping a file on itself does nothing
        self.release("list", (x, y))
        time.sleep(0.8)
        assert self.log is not None
        self.record(
            "C7",
            m,
            {
                "the drag started (threshold)": thresh is not None,
                "no SHOW": self.log.find(m, "SHOW") is None,
                "files unchanged (sha256)": self.files_intact(),
            },
        )

    def is_caption(self, x: int, y: int) -> bool:
        """Title bar of our window. Win11 Explorer answers from a child window, so ask both."""
        if root_of(x, y) != self.window:
            return False
        child = int(user32.WindowFromPoint(wt.POINT(x, y)) or 0)
        return HTCAPTION in {nc_hit_test(self.window, x, y), nc_hit_test(child, x, y)}

    def caption_point(self) -> tuple[int, int] | None:
        left, top, right, _ = window_rect(self.window)
        for dy in (10, 16, 22):
            for x in range(right - 170, left + 200, -12):
                if self.is_caption(x, top + dy):
                    return x, top + dy
        return None

    def c6_title_bar(self) -> None:
        point = self.caption_point()
        self.plan["C6 caption point"] = point
        if point is None:
            self.rows.append(Row("C6", "not run", notes={"why": "no title-bar point found"}))
            print("C6: NOT RUN (no title-bar point found)")
            return
        m = self.mark()
        x, y = self.inp.glide(*point)
        if not self.dry and not self.is_caption(x, y):
            raise Stop("the cursor isn't on our window's title bar")
        self.inp.down((x, y))
        down = self.wait(m, "down", timeout=1.0)
        if not self.dry and down is not None and "source_ok=True" in down.msg:
            self.release("caption", (x, y))
            raise Stop("the probe took the title bar for an allowed source")
        self.inp.glide(x + self.px(20), y)  # the window comes along: it's a window move
        self.inp.key(VK_SHIFT, True)
        time.sleep(0.8)
        self.release("caption")
        self.inp.key(VK_SHIFT, False)
        time.sleep(0.3)
        self.restore_window()
        assert self.log is not None
        self.record(
            "C6",
            m,
            {
                "down: source_ok=False": down is not None and "source_ok=False" in down.msg,
                "no SHOW": self.log.find(m, "SHOW") is None,
            },
            source_chain=down.msg.split("chain=")[-1] if down else "?",
        )

    def c4_desktop(self) -> None:
        desktop_copy = desktop_dir() / DESKTOP_FILE
        if not desktop_copy.exists():
            shutil.copy2(TEST_DIR / FILE_A, desktop_copy)
        self.hashes[desktop_copy] = sha256(desktop_copy)
        if not self.dry:
            self.inp.tap(VK_LWIN, VK_D)
            self.desktop_shown = True
            time.sleep(1.2)
        view = desktop_list_view()
        root = int(user32.GetAncestor(view, GA_ROOT) or 0)
        self.plan["C4 desktop view"] = f"{window_class(root)} > SysListView32"
        self.c1_like("C4", view, root, DESKTOP_FILE)
        if not self.dry:
            self.inp.tap(VK_LWIN, VK_D)
            self.desktop_shown = False
            time.sleep(1.2)
        self.restore_window()

    def c12_frozen(self) -> None:
        self.stop_probe()
        self.start_probe(frozen=True)
        self.c1_like("C12", self.window, self.window, FILE_A)

    # ------------------------------------------------------------- driver
    def go(self) -> None:
        self.uia = Uia(LOG_DIR / "drag_driver-helper.err.log")
        ping = self.uia.call("ping", timeout=60)
        self.plan["helper system dpi"] = ping.get("system_dpi")
        self.make_test_files()
        self.start_probe(frozen=False)
        self.open_window()
        self.plan["window"] = {"hwnd": self.window, "rect": window_rect(self.window)}
        if self.dry:
            self.dry_plan()
            return
        self.park()
        steps: list[tuple[str, Callable[[], None]]] = [
            ("C8", self.c8_esc),  # always first: every other row relies on Esc as the way out
            ("C1", self.c1),
            ("C2", self.c2_still),
            ("C3", self.c3_hub),
            ("C5", self.c5_clipboard),
            ("C7", self.c7_no_shift),
            ("C6", self.c6_title_bar),
        ]
        if self.with_c4:
            steps.append(("C4", self.c4_desktop))
        steps.append(("C12", self.c12_frozen))
        for row, step in steps:
            if self.only is not None and row != "C8" and row not in self.only:
                continue
            step()
            time.sleep(0.8)

    def dry_plan(self) -> None:
        """Everything but input: find each item and point, check them, try the frozen probe."""
        assert self.uia is not None
        for name in (FILE_A, FILE_B, FILE_C):
            found = self.uia.call("locate", hwnd=self.window, name=name)
            if found.get("ok"):
                x, y = found["x"], found["y"]
                shift_at = (x + self.px(16), y)
                center = overlay_center(*shift_at, self.work, self.dpr)
                left, top, right, bottom = window_rect(self.window)
                found["inside_window"] = left <= x < right and top <= y < bottom
                found["root_ok"] = root_of(x, y) == self.window
                found["overlay_center"] = center
                found["jpg_point"] = (center[0], center[1] - self.px(R_LABEL))
                found["center_clamped"] = (
                    abs(center[0] - shift_at[0]) > 2 or abs(center[1] - shift_at[1]) > 2
                )
            self.plan[name] = found
        self.plan["dpr"] = self.dpr
        self.plan["C6 caption point"] = self.caption_point()
        try:
            view = desktop_list_view()
            self.plan["C4 desktop view"] = window_class(int(user32.GetAncestor(view, GA_ROOT)))
        except Stop as e:
            self.plan["C4 desktop view"] = str(e)
        self.plan["desktop is under OneDrive"] = "OneDrive" in str(desktop_dir())
        self.stop_probe()
        self.start_probe(frozen=True)


def preflight() -> dict[str, Any]:
    info: dict[str, Any] = {
        "system_dpi": user32.GetDpiForSystem(),
        "screen": (user32.GetSystemMetrics(SM_CXSCREEN), user32.GetSystemMetrics(SM_CYSCREEN)),
        "work_area": work_area(),
        "remote_session": bool(user32.GetSystemMetrics(SM_REMOTESESSION)),
        "test_dir_ascii": str(TEST_DIR).isascii(),
    }
    desk = user32.OpenInputDesktop(0, False, 0x0001)
    name = ctypes.create_unicode_buffer(64)
    if desk:
        user32.GetUserObjectInformationW(desk, 2, name, ctypes.sizeof(name), None)
        user32.CloseDesktop(desk)
    info["input_desktop"] = name.value or None
    pt = wt.POINT()
    info["cursor_readable"] = bool(user32.GetCursorPos(ctypes.byref(pt)))
    info["foreground_window"] = bool(user32.GetForegroundWindow())
    problems = [
        k
        for k, bad in (
            ("the test folder path isn't ASCII", not info["test_dir_ascii"]),
            ("the input desktop isn't Default (locked?)", info["input_desktop"] != "Default"),
            ("the cursor can't be read (RDP window minimized?)", not info["cursor_readable"]),
            ("no foreground window", not info["foreground_window"]),
        )
        if bad
    ]
    info["problems"] = problems
    return info


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--dry-run", action="store_true", help="send no input; print the plan")
    parser.add_argument("--with-c4", action="store_true", help="also C4 (a copy on the Desktop)")
    parser.add_argument("--rows", help="only these rows, e.g. C3,C12 (C8 always runs first)")
    parser.add_argument("--countdown", type=int, default=10, help="seconds before the first input")
    args = parser.parse_args()

    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor v2: physical px
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
    run = Run(args.dry_run, args.with_c4, rows)
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
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out = LOG_DIR / f"drag_driver-{'dry-' if args.dry_run else ''}{stamp}.json"
        result = {
            "synthetic": True,
            "dry_run": args.dry_run,
            "preflight": info,
            "plan": run.plan,
            "stopped": error,
            "rows": [asdict(r) for r in run.rows],
            "files_intact": run.files_intact(),
            "test_files": [str(p) for p in run.hashes],
        }
        out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
        print(f"results: {out}")
        if args.dry_run:
            print(json.dumps(run.plan, indent=2, default=str))
    return 0 if error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
