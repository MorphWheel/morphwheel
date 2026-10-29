"""``ui.wheel.sniffer``: headers win over extensions, the budget is honored, stale results drop.

Traceability (phase-4 §3): DragEnter does no I/O; the sniff runs on its own thread and updates the
slots; UNC paths aren't read.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from morphwheel.core.catalog import Catalog, SlotPos
from morphwheel.core.formats import FileInfo, FormatId
from morphwheel.ui.wheel.sniffer import Sniffer, should_sniff, sniff_files
from morphwheel.ui.wheel.window import WheelWindow

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
from builtin_targets import BUILTINS

pytestmark = pytest.mark.usefixtures("qapp")

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
GIF_ANIMATED = (
    b"GIF89a\x01\x00\x01\x00\x00\x00\x00"
    b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00"
    b"\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00"
    b"\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00\x3b"
)


@pytest.fixture
def files(tmp_path: Path) -> dict[str, Path]:
    out = {
        "real.png": PNG,
        "mislabeled.jpg": PNG,  # a PNG wearing a .jpg name
        "anim.gif": GIF_ANIMATED,
        "notes.txt": b"hello",
    }
    for name, data in out.items():
        (tmp_path / name).write_bytes(data)
    return {name: tmp_path / name for name in out}


def test_sniff_files_refines_by_bytes_and_skips_what_it_must(
    files: dict[str, Path], tmp_path: Path
) -> None:
    infos = [FileInfo.from_path(p) for p in files.values()]
    infos.append(FileInfo.from_path(tmp_path, is_dir=True))
    infos.append(FileInfo.from_path(Path(r"\\server\share\x.png")))
    infos.append(FileInfo.from_path(Path("http://x/y.png"), is_local=False))
    infos.append(FileInfo.from_path(tmp_path / "missing.png"))
    result = sniff_files(infos)
    by_name = {i.path.name: i for i in result}
    assert by_name["real.png"].format is FormatId.PNG
    assert by_name["real.png"].sniffed
    assert by_name["mislabeled.jpg"].format is FormatId.PNG  # the bytes win
    assert by_name["anim.gif"].animated is True
    assert by_name["notes.txt"].format is None  # unknown bytes: the extension (none) stands
    assert by_name["notes.txt"].sniffed
    for name in (tmp_path.name, "x.png", "y.png", "missing.png"):
        assert not by_name[name].sniffed
    assert not should_sniff(FileInfo.from_path(Path(r"\\server\share\x.png")))


def test_budget_is_checked_between_files(files: dict[str, Path]) -> None:
    infos = [FileInfo.from_path(files["real.png"]), FileInfo.from_path(files["anim.gif"])]
    ticks = iter([0, 0, 10**9, 10**9, 10**9])  # the second file arrives after the budget
    result = sniff_files(infos, budget_ns=50_000_000, clock=lambda: next(ticks))
    assert result[0].sniffed
    assert not result[1].sniffed  # kept as planned by extension


def test_sniffer_emits_on_the_gui_thread_and_skips_when_nothing_is_readable(
    qtbot: QtBot, files: dict[str, Path]
) -> None:
    sniffer = Sniffer()
    with qtbot.waitSignal(sniffer.finished, timeout=5000) as blocker:
        sniffer.sniff(7, [FileInfo.from_path(files["mislabeled.jpg"])])
    generation, infos = blocker.args
    assert generation == 7
    assert infos[0].format is FormatId.PNG
    # Nothing readable: no thread, no signal.
    with qtbot.assertNotEmitted(sniffer.finished, wait=200):
        sniffer.sniff(8, [FileInfo.from_path(Path(r"\\server\share\x.png"))])


# ----------------------------------------------------------------------------- in the window
def enter(window: WheelWindow, *paths: Path) -> None:
    m = QMimeData()
    m.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    offer = Qt.DropAction.CopyAction | Qt.DropAction.MoveAction
    center = QPointF(window.rect().center())
    e = QDragEnterEvent(
        center, offer, m, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier
    )
    QApplication.sendEvent(window, e)


def test_window_replans_after_the_sniff_and_ignores_stale_results(
    qtbot: QtBot, files: dict[str, Path]
) -> None:
    window = WheelWindow(Catalog.of(BUILTINS), cursor=lambda: QPoint(600, 400))
    window.show_at((0, 0), 1)
    assert window.session is not None
    enter(window, files["mislabeled.jpg"])
    first = window.session.plan
    assert first is not None
    assert first.slots[SlotPos.N].status.value == "source"  # by extension it is "already JPG"
    qtbot.waitUntil(
        lambda: window.session is not None and window.session.plan is not first, timeout=5000
    )
    second = window.session.plan
    assert second is not None
    assert second.slots[SlotPos.N].enabled  # the bytes say PNG: JPG is a real target now
    assert second.slots[SlotPos.NE].status.value == "source"
    assert window.view is not None
    assert window.view.plan is second
    assert [i.sniffed for i in window.drop_files()] == [True]

    # A result for an old generation never lands.
    window.on_sniffed(0, (FileInfo.from_path(files["anim.gif"]),))
    assert window.session.plan is second
    # Nor one that arrives after the wheel hid.
    window.hide_wheel()
    window.on_sniffed(window.generation, (FileInfo.from_path(files["anim.gif"]),))
    assert window.session is None
