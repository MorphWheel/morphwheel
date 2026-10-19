"""Drag probe: a developer diagnostic, not shipped. It replaces the Phase 1 spike.

Modes
-----
``drag`` (default)
    Shows a wheel-like overlay when you Shift-drag a file. Logs source window classes, timings
    (show → DragEnter), drop actions, whether the source survived, Esc presses and the screen.
    Every drag event goes through Morphwheel's real ``force_copy``. Used for
    docs/testing/integration-checklist.md.
``measure``
    Measures the runtime: GUI idle memory, worker cold start (spawn), worker memory and ping
    round trip. Run it from source and from the frozen build
    (packaging/pyinstaller/morphwheel.spec).

Nothing at module level imports Qt. Spawned workers re-run this module, and they must stay Qt-free,
just like ``morphwheel.__main__`` (phase-4 §3).

Usage::

    .venv\\Scripts\\python.exe tools\\drag_probe.py [drag] [--any-source] [--minutes 30]
    .venv\\Scripts\\python.exe tools\\drag_probe.py measure [--workers 2] [--import PIL.Image]

Stop the drag mode with Ctrl+C in its console, or wait for ``--minutes`` to run out.
"""

from __future__ import annotations

import argparse
import ctypes
import importlib
import json
import math
import multiprocessing
import os
import sys
import time
from ctypes import POINTER, byref
from ctypes import wintypes as wt
from pathlib import Path
from typing import Any

T0 = time.perf_counter()
_LOG: Any = None


def log(tag: str, msg: str) -> None:
    line = f"{(time.perf_counter() - T0) * 1000:10.1f} [{tag:<7}] {msg}"
    print(line, flush=True)
    if _LOG is not None:
        _LOG.write(line + "\n")
        _LOG.flush()


# --------------------------------------------------------------------------- Win32 (ctypes only)
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)


def _sig(fn: Any, res: Any, *args: Any) -> None:
    fn.restype, fn.argtypes = res, list(args)


_sig(user32.WindowFromPoint, wt.HWND, wt.POINT)
_sig(user32.GetAncestor, wt.HWND, wt.HWND, wt.UINT)
_sig(user32.GetDesktopWindow, wt.HWND)
_sig(user32.GetClassNameW, ctypes.c_int, wt.HWND, wt.LPWSTR, ctypes.c_int)
_sig(user32.GetCursorPos, wt.BOOL, POINTER(wt.POINT))
_sig(user32.GetAsyncKeyState, ctypes.c_short, ctypes.c_int)
_sig(user32.GetDpiForWindow, wt.UINT, wt.HWND)
_sig(user32.GetSystemMetricsForDpi, ctypes.c_int, ctypes.c_int, wt.UINT)
_sig(user32.GetForegroundWindow, wt.HWND)
_sig(user32.GetWindowThreadProcessId, wt.DWORD, wt.HWND, POINTER(wt.DWORD))
_sig(kernel32.GetCurrentProcess, wt.HANDLE)
_sig(kernel32.OpenProcess, wt.HANDLE, wt.DWORD, wt.BOOL, wt.DWORD)
_sig(kernel32.CloseHandle, wt.BOOL, wt.HANDLE)
_sig(
    user32.GetRawInputData,
    wt.UINT,
    ctypes.c_void_p,
    wt.UINT,
    ctypes.c_void_p,
    POINTER(wt.UINT),
    wt.UINT,
)
_sig(user32.RegisterRawInputDevices, wt.BOOL, ctypes.c_void_p, wt.UINT, wt.UINT)
_sig(advapi32.OpenProcessToken, wt.BOOL, wt.HANDLE, wt.DWORD, POINTER(wt.HANDLE))
_sig(
    advapi32.GetTokenInformation,
    wt.BOOL,
    wt.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wt.DWORD,
    POINTER(wt.DWORD),
)

VK_LBUTTON, VK_SHIFT, VK_ESCAPE = 0x01, 0x10, 0x1B
SM_CXDRAG, SM_CYDRAG = 68, 69
GA_PARENT = 1
PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_VM_READ = 0x1000, 0x0010
ALLOWED_CLASSES = {"SHELLDLL_DefView", "NamespaceTreeControl"}
REJECTED_CLASSES = {
    "TITLE_BAR_SCAFFOLDING_WINDOW_CLASS",
    "Microsoft.UI.Content.DesktopChildSiteBridge",
}


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD),
        ("PageFaultCount", wt.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


_sig(
    kernel32.K32GetProcessMemoryInfo, wt.BOOL, wt.HANDLE, POINTER(PROCESS_MEMORY_COUNTERS), wt.DWORD
)


def memory_mb(pid: int | None = None) -> dict[str, float]:
    """Working set and private bytes (PagefileUsage) of ``pid`` (default: this process), in MB."""
    own = pid is None
    handle = (
        kernel32.GetCurrentProcess()
        if own
        else kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, False, pid)
    )
    counters = PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(counters)
    try:
        if not kernel32.K32GetProcessMemoryInfo(handle, byref(counters), counters.cb):
            return {}
    finally:
        if not own:
            kernel32.CloseHandle(handle)
    mb = 1024 * 1024
    return {
        "working_set_mb": round(counters.WorkingSetSize / mb, 1),
        "private_mb": round(counters.PagefileUsage / mb, 1),
    }


def class_chain(hwnd: Any) -> list[str]:
    desktop, chain, buf = user32.GetDesktopWindow(), [], ctypes.create_unicode_buffer(256)
    while hwnd and hwnd != desktop and len(chain) < 24:
        user32.GetClassNameW(hwnd, buf, 256)
        chain.append(buf.value)
        hwnd = user32.GetAncestor(hwnd, GA_PARENT)
    return chain


def cursor() -> tuple[int, int]:
    pt = wt.POINT()
    user32.GetCursorPos(byref(pt))
    return pt.x, pt.y


def key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def is_elevated(pid: int | None = None) -> bool | None:
    proc = (
        kernel32.GetCurrentProcess()
        if pid is None
        else kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    )
    if not proc:
        return None  # typically: access denied to a higher-integrity process
    token = wt.HANDLE()
    try:
        if not advapi32.OpenProcessToken(proc, 0x0008, byref(token)):  # TOKEN_QUERY
            return None
        value, size = wt.DWORD(), wt.DWORD()
        ok = advapi32.GetTokenInformation(token, 20, byref(value), 4, byref(size))  # TokenElevation
        kernel32.CloseHandle(token)
        return bool(value.value) if ok else None
    finally:
        if pid is not None:
            kernel32.CloseHandle(proc)


def foreground_info() -> str:
    hwnd = user32.GetForegroundWindow()
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, byref(pid))
    chain = class_chain(hwnd)
    return f"fg={chain[-1] if chain else None} pid={pid.value} elevated={is_elevated(pid.value)}"


# --------------------------------------------------------------------------- measure mode
def _probe_worker(conn: Any, module: str | None) -> None:
    """Runs in a spawned worker. Reports readiness and whether Qt leaked into the process."""
    started = time.perf_counter()
    if module:
        importlib.import_module(module)
    conn.send(
        {
            "pid": os.getpid(),
            "import_s": time.perf_counter() - started,
            "qt_loaded": any(m.startswith("PySide6") for m in sys.modules),
            "qt_modules": sorted(m for m in sys.modules if m.startswith(("PySide6", "shiboken6"))),
        }
    )
    while (msg := conn.recv()) != "stop":
        conn.send(msg)


def measure(workers: int, module: str | None) -> dict[str, Any]:
    from PySide6.QtWidgets import QApplication, QWidget

    app = QApplication.instance() or QApplication(sys.argv)
    overlay = QWidget()
    overlay.winId()  # pre-create the native window like the real app
    deadline = time.perf_counter() + 2.0
    while time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.02)
    result: dict[str, Any] = {
        "frozen": bool(getattr(sys, "frozen", False)),
        "gui_idle": memory_mb(),
        "workers": [],
    }

    ctx = multiprocessing.get_context("spawn")
    for _ in range(workers):
        parent, child = ctx.Pipe()
        started = time.perf_counter()
        proc = ctx.Process(target=_probe_worker, args=(child, module), daemon=True)
        proc.start()
        ready = parent.recv()
        cold_start = time.perf_counter() - started
        ping_start = time.perf_counter_ns()
        parent.send("ping")
        parent.recv()
        rtt_ms = (time.perf_counter_ns() - ping_start) / 1e6
        result["workers"].append(
            {
                "cold_start_s": round(cold_start, 3),
                "import_s": round(ready["import_s"], 3),
                "ping_rtt_ms": round(rtt_ms, 3),
                "qt_loaded": ready["qt_loaded"],
                "qt_modules": ready["qt_modules"],
                "memory": memory_mb(ready["pid"]),
            }
        )
        parent.send("stop")
        proc.join(5)
    del overlay
    return result


# --------------------------------------------------------------------------- drag mode
def drag(any_source: bool, minutes: float) -> None:
    from PySide6.QtCore import QAbstractNativeEventFilter, QPointF, QRectF, Qt, QTimer
    from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPainterPath
    from PySide6.QtWidgets import QApplication, QWidget

    from morphwheel.ui.wheel.drop_guard import assert_safe, force_copy, reject

    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    diam, r_out, r_hub = 300, 118, 36
    slots = ["JPG", "PNG", "WebP", "AVIF", "Compress", "PDF", "ICO", "More"]  # N, then clockwise

    def region(p: QPointF) -> str:
        dx, dy = p.x() - diam / 2, p.y() - diam / 2
        r = math.hypot(dx, dy)
        if r <= r_hub:
            return "hub"
        if r > r_out:
            return "halo"
        angle = (math.degrees(math.atan2(dx, -dy)) + 360 + 22.5) % 360  # 0° = north, clockwise
        return f"slot:{slots[int(angle // 45)]}"

    state: dict[str, Any] = {
        "phase": "idle",
        "down": (0, 0),
        "t_down": 0.0,
        "t_show": 0.0,
        "source_ok": False,
        "esc": False,
        "dropped": False,
    }

    class Overlay(QWidget):
        def __init__(self) -> None:
            super().__init__(
                None,
                Qt.WindowType.Tool
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.WindowDoesNotAcceptFocus,
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self.setAcceptDrops(True)
            self.setFixedSize(diam, diam)
            self.hover = ""

        def paintEvent(self, _: Any) -> None:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            c = QPointF(diam / 2, diam / 2)
            halo = QPainterPath()
            halo.addEllipse(c, diam / 2 - 1, diam / 2 - 1)
            p.fillPath(halo, QColor(0, 0, 0, 1))  # alpha floor: catches drops near the disc
            disc = QPainterPath()
            disc.addEllipse(c, r_out, r_out)
            p.fillPath(disc, QColor(32, 32, 32, 235))
            p.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
            for i, name in enumerate(slots):
                a = math.radians(i * 45 - 90)
                col = (
                    QColor(255, 140, 30) if self.hover == f"slot:{name}" else QColor(230, 230, 230)
                )
                p.setPen(col)
                p.drawText(
                    QRectF(c.x() + 78 * math.cos(a) - 35, c.y() + 78 * math.sin(a) - 10, 70, 20),
                    Qt.AlignmentFlag.AlignCenter,
                    name,
                )
            hub = QPainterPath()
            hub.addEllipse(c, r_hub, r_hub)
            p.fillPath(hub, QColor(60, 60, 64, 245))
            p.setPen(QColor(255, 255, 255))
            p.drawText(
                QRectF(c.x() - 34, c.y() - 10, 68, 20),
                Qt.AlignmentFlag.AlignCenter,
                self.hover.removeprefix("slot:") if self.hover.startswith("slot:") else "cancel",
            )

        def dragEnterEvent(self, e: Any) -> None:
            files = [u.toLocalFile() for u in e.mimeData().urls()]
            log(
                "ENTER",
                f"+{(time.perf_counter() - state['t_show']) * 1000:.1f} ms after show; "
                f"proposed={e.proposedAction()} files={[Path(f).name for f in files][:3]} "
                f"formats={len(e.mimeData().formats())}",
            )
            force_copy(e)  # always accept enter, or Qt sends no DragMove events

        def dragMoveEvent(self, e: Any) -> None:
            where = region(e.position())
            if where != self.hover:
                self.hover = where
                self.update()
                log("move", where)
            if where.startswith("slot:") and where != "slot:More":
                force_copy(e)
            else:
                reject(e)

        def dragLeaveEvent(self, _: Any) -> None:
            button_down = key_down(VK_LBUTTON)
            log("leave", f"DragLeave (button {'down' if button_down else 'up'})")
            self.hover = ""
            if not button_down:  # released over hub/halo: OLE sends DragLeave instead of Drop
                self.hide()

        def dropEvent(self, e: Any) -> None:
            where = region(e.position())
            files = [u.toLocalFile() for u in e.mimeData().urls()]
            action = force_copy(e) if where.startswith("slot:") and where != "slot:More" else None
            if action is None:
                reject(e)
            assert_safe(e)
            state["dropped"] = True
            log("DROP", f"{where} → {action} files={[Path(f).name for f in files][:3]}")
            QTimer.singleShot(100, self.hide)
            QTimer.singleShot(2500, lambda: check_sources(files))

    def check_sources(files: list[str]) -> None:
        gone = [f for f in files if f and not Path(f).exists()]
        log("SAFETY", f"SOURCE GONE: {gone}" if gone else f"source intact ({len(files)} file(s))")

    overlay = Overlay()
    overlay.winId()  # pre-create → RegisterDragDrop happens now

    def show_overlay(why: str) -> None:
        pos = QCursor.pos()
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        x = min(max(pos.x() - diam // 2, g.left()), g.right() - diam + 1)
        y = min(max(pos.y() - diam // 2, g.top()), g.bottom() - diam + 1)
        overlay.move(x, y)
        overlay.show()
        state["t_show"] = time.perf_counter()
        log(
            "SHOW",
            f"via {why} +{(state['t_show'] - state['t_down']) * 1000:.0f} ms after down; "
            f"screen={screen.name()} dpr={screen.devicePixelRatio()} {foreground_info()}",
        )

    def on_button(down: bool) -> None:
        if down:
            x, y = cursor()
            hwnd = user32.WindowFromPoint(wt.POINT(x, y))
            chain = class_chain(hwnd)
            if hwnd and int(hwnd) == int(overlay.winId()):
                return  # a click on our own overlay
            explorer = bool(ALLOWED_CLASSES & set(chain)) and not (REJECTED_CLASSES & set(chain))
            dpi = user32.GetDpiForWindow(hwnd) or 96
            state.update(
                phase="pressed",
                down=(x, y),
                t_down=time.perf_counter(),
                dropped=False,
                source_ok=explorer or any_source,
                esc=False,
                thr=(
                    user32.GetSystemMetricsForDpi(SM_CXDRAG, dpi),
                    user32.GetSystemMetricsForDpi(SM_CYDRAG, dpi),
                ),
            )
            log(
                "down",
                f"at {x},{y} source_ok={state['source_ok']} (explorer={explorer}) "
                f"chain={' > '.join(reversed(chain))}",
            )
        else:
            log("up", f"phase={state['phase']} dropped={state['dropped']}")
            if state["phase"] == "shown" and not state["dropped"]:
                # Raw L-up arrives 1-4 ms BEFORE OLE delivers Drop (spike log), so hiding now would
                # lose the drop. Wait for dropEvent / dragLeaveEvent, with a short grace fallback.
                QTimer.singleShot(150, hide_if_no_drop)
            state["phase"] = "idle"

    def hide_if_no_drop() -> None:
        if overlay.isVisible() and not state["dropped"]:
            log("hide", "released without a drop (grace period ended)")
            overlay.hide()

    def on_move() -> None:
        if state["phase"] == "pressed":
            x, y = cursor()
            dx, dy = abs(x - state["down"][0]), abs(y - state["down"][1])
            if dx > state["thr"][0] or dy > state["thr"][1]:
                state["phase"] = "dragging"
                log(
                    "thresh",
                    f"+{(time.perf_counter() - state['t_down']) * 1000:.0f} ms "
                    f"shift={key_down(VK_SHIFT)}",
                )
        maybe_trigger("raw-move")

    def maybe_trigger(why: str) -> None:
        if state["phase"] == "dragging" and state["source_ok"] and key_down(VK_SHIFT):
            state["phase"] = "shown"
            show_overlay(why)

    def poll() -> None:
        if state["phase"] in ("dragging", "shown"):
            maybe_trigger("poll")
            esc = key_down(VK_ESCAPE)
            if esc and not state["esc"]:
                log("esc", f"Esc pressed while {state['phase']}")
            state["esc"] = esc

    class RawFilter(QAbstractNativeEventFilter):
        class RAWINPUTHEADER(ctypes.Structure):
            _fields_ = [
                ("dwType", wt.DWORD),
                ("dwSize", wt.DWORD),
                ("hDevice", wt.HANDLE),
                ("wParam", wt.WPARAM),
            ]

        class RAWMOUSE(ctypes.Structure):
            # usButtonFlags/usButtonData sit in a 4-byte-aligned union after usFlags → explicit pad.
            _fields_ = [
                ("usFlags", wt.USHORT),
                ("_pad", wt.USHORT),
                ("usButtonFlags", wt.USHORT),
                ("usButtonData", wt.USHORT),
                ("ulRawButtons", wt.ULONG),
                ("lLastX", wt.LONG),
                ("lLastY", wt.LONG),
                ("ulExtraInformation", wt.ULONG),
            ]

        def __init__(self) -> None:
            super().__init__()

            class RAWINPUT(ctypes.Structure):
                _fields_ = [("header", RawFilter.RAWINPUTHEADER), ("mouse", RawFilter.RAWMOUSE)]

            self.buf = RAWINPUT()
            self.size = wt.UINT()
            self.failed = False

        def nativeEventFilter(self, _type: Any, message: Any) -> tuple[bool, int]:
            # Runs for every native message: a bug must surface as one log line, not a flood.
            try:
                self._handle(message)
            except Exception as exc:
                if not self.failed:
                    self.failed = True
                    log("ERROR", f"raw input filter failed (logged once): {exc!r}")
            return False, 0

        def _handle(self, message: Any) -> None:
            msg = wt.MSG.from_address(int(message))
            if msg.message == 0x00FF:  # WM_INPUT
                self.size.value = ctypes.sizeof(self.buf)
                if (
                    user32.GetRawInputData(
                        ctypes.c_void_p(msg.lParam),
                        0x10000003,
                        byref(self.buf),
                        byref(self.size),
                        ctypes.sizeof(RawFilter.RAWINPUTHEADER),
                    )
                    != 0xFFFFFFFF
                    and self.buf.header.dwType == 0
                ):
                    flags = self.buf.mouse.usButtonFlags
                    if flags & 0x0001:
                        on_button(True)
                    elif flags & 0x0002:
                        on_button(False)
                    elif state["phase"] != "idle":
                        on_move()

    class RAWINPUTDEVICE(ctypes.Structure):
        _fields_ = [
            ("usUsagePage", wt.USHORT),
            ("usUsage", wt.USHORT),
            ("dwFlags", wt.DWORD),
            ("hwndTarget", wt.HWND),
        ]

    sink = QWidget()
    raw = RawFilter()
    app.installNativeEventFilter(raw)
    device = RAWINPUTDEVICE(0x01, 0x02, 0x00000100, int(sink.winId()))  # mouse, RIDEV_INPUTSINK
    ok = user32.RegisterRawInputDevices(byref(device), 1, ctypes.sizeof(device))
    timer = QTimer(interval=8, timeout=poll)
    timer.start()
    QTimer.singleShot(int(minutes * 60_000), app.quit)
    log(
        "init",
        f"raw input ok={bool(ok)} elevated={is_elevated()} any_source={any_source} "
        f"screens={[(s.name(), s.devicePixelRatio()) for s in app.screens()]}",
    )
    log("init", "READY: start dragging a file in Explorer, then press Shift")
    app.exec()


def main() -> int:
    multiprocessing.freeze_support()  # FIRST: frozen workers take over here and never return
    global _LOG
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("mode", nargs="?", choices=["drag", "measure"], default="drag")
    parser.add_argument("--any-source", action="store_true")
    parser.add_argument("--minutes", type=float, default=30)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--import", dest="module", default="PIL.Image")
    args = parser.parse_args()

    log_dir = Path(os.environ.get("LOCALAPPDATA", ".")) / "Morphwheel" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    _LOG = (log_dir / f"drag_probe-{args.mode}-{time.strftime('%Y%m%d-%H%M%S')}.log").open(
        "w", encoding="utf-8"
    )
    log("init", f"log file: {_LOG.name}")
    if args.mode == "measure":
        log("measure", json.dumps(measure(args.workers, args.module or None)))
    else:
        drag(args.any_source, args.minutes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
