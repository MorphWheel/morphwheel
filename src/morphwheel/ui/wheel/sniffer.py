"""The sniffer thread (phase-4 §3): read each dragged file's header off the GUI thread.

``WheelWindow.dragEnterEvent`` plans by extension and does no I/O. Right after, it hands the
``FileInfo``s to the ``Sniffer``, which reads up to ``SNIFF_BYTES`` of each local file on one
long-lived daemon thread and reports refined infos (the real format, animated or not) through a
queued signal. The window then calls ``set_plan`` a second time (``WheelSession`` keeps arming,
hover and the More state across it).

Rules:

- **Budget.** ``budget_ms`` (50 ms, phase-4 §3) is checked between files: when it is spent, the
  remaining files keep their extension-based info. A single slow file can't be interrupted, so
  files that would block are skipped up front:
- **Skipped without reading:** non-local items, folders, UNC paths (network: not sniffed, §3),
  and cloud placeholders that would trigger a download (``FILE_ATTRIBUTE_OFFLINE`` or
  ``RECALL_ON_DATA_ACCESS``, OneDrive "Files On-Demand"). The placeholder check stats the file,
  so it runs on the thread; the GUI thread only applies the pure part (``worth_a_look``).
- **Stale results are dropped** twice: the thread skips any request older than the newest one in
  its queue (OLE re-sends DragEnter every time the pointer re-crosses the window edge), and the
  window ignores a result whose generation isn't the current one, or that arrives after it hid.
- The thread never touches Qt objects: it computes a tuple and emits one signal. ``sniff_files``
  is a plain function, so the logic is tested without threads.
"""

from __future__ import annotations

import logging
import queue
import stat
import threading
import time
from collections.abc import Callable, Sequence

from PySide6.QtCore import QObject, Signal

from morphwheel.core.formats import SNIFF_BYTES, FileInfo, sniff
from morphwheel.logs import elapsed_ms

log = logging.getLogger("morphwheel.ui.wheel.sniffer")

DEFAULT_BUDGET_MS = 50.0
_FILE_ATTRIBUTE_OFFLINE = getattr(stat, "FILE_ATTRIBUTE_OFFLINE", 0x1000)
_FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000
_PLACEHOLDER = _FILE_ATTRIBUTE_OFFLINE | _FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS

Request = tuple[int, tuple[FileInfo, ...]]


def worth_a_look(info: FileInfo) -> bool:
    """The pure part of the filter: local, a file, not on a network path. No I/O."""
    if not info.is_local or info.is_dir:
        return False
    drive = info.path.drive
    return bool(drive) and not drive.startswith("\\\\")


def should_sniff(info: FileInfo) -> bool:
    """``worth_a_look`` and not a cloud placeholder. Stats the file: thread only."""
    if not worth_a_look(info):
        return False
    try:
        st = info.path.stat()
    except OSError:
        return False
    if not stat.S_ISREG(st.st_mode):
        return False
    attributes = getattr(st, "st_file_attributes", 0)
    return not attributes & _PLACEHOLDER


def sniff_files(
    infos: Sequence[FileInfo],
    *,
    budget_ns: int = int(DEFAULT_BUDGET_MS * 1_000_000),
    clock: Callable[[], int] = time.perf_counter_ns,
) -> tuple[FileInfo, ...]:
    """Refine what can be read within the budget; the rest come back unchanged."""
    start = clock()
    out: list[FileInfo] = []
    budget_left = True
    for info in infos:
        if budget_left and clock() - start >= budget_ns:
            budget_left = False
        if not budget_left or not should_sniff(info):
            out.append(info)
            continue
        try:
            with info.path.open("rb") as f:
                header = f.read(SNIFF_BYTES)
        except OSError:
            out.append(info)
            continue
        out.append(info.with_sniff(sniff(header)))
    return tuple(out)


class Sniffer(QObject):
    finished = Signal(int, object)  # generation, tuple[FileInfo, ...]

    def __init__(
        self, parent: QObject | None = None, *, budget_ms: float = DEFAULT_BUDGET_MS
    ) -> None:
        super().__init__(parent)
        self._budget_ns = int(budget_ms * 1_000_000)
        self._requests: queue.Queue[Request] = queue.Queue()
        self._thread: threading.Thread | None = None

    def sniff(self, generation: int, infos: Sequence[FileInfo]) -> None:
        """Queue a sniff; the result arrives as ``finished`` (GUI thread) unless superseded."""
        if not any(worth_a_look(i) for i in infos):
            return  # nothing could be read: the extension plan stands (no I/O decided this)
        self._requests.put((generation, tuple(infos)))
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, name="mw-sniffer", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        while True:
            try:
                generation, infos = self._requests.get(timeout=30.0)
            except queue.Empty:
                return  # idle: the thread ends; the next drag starts a new one
            while not self._requests.empty():  # a newer DragEnter superseded this one
                generation, infos = self._requests.get_nowait()
            started = time.perf_counter_ns()
            result = sniff_files(infos, budget_ns=self._budget_ns)
            try:
                self.finished.emit(generation, result)
            except RuntimeError:  # the sniffer was deleted while the thread ran (app shutting down)
                return
            log.debug(
                "sniffed %d/%d file(s) in %.1f ms",
                sum(1 for i in result if i.sniffed),
                len(result),
                elapsed_ms(started),
            )
