"""``engine.undo`` (D5): only recorded paths, only unchanged files, one shot per job.

Traceability (phase-4 §6): "limited Undo, session only": a changed file is refused (unit); the
Recycle Bin itself is a manual check.
"""

from __future__ import annotations

import os
from pathlib import Path

from morphwheel.core.jobs import CreatedFile
from morphwheel.engine.undo import UndoRegistry, UndoStatus


class FakeBin:
    def __init__(self, refuse: set[str] = frozenset()) -> None:  # type: ignore[assignment]
        self.recycled: list[Path] = []
        self.refuse = refuse

    def __call__(self, path: Path) -> bool:
        if path.name in self.refuse:
            return False
        path.unlink()
        self.recycled.append(path)
        return True


def created(path: Path, source: Path) -> CreatedFile:
    st = path.stat()
    return CreatedFile(path, st.st_size, st.st_mtime_ns, source, st.st_ino)


def test_undo_recycles_only_the_recorded_unchanged_files(tmp_path: Path) -> None:
    src = tmp_path / "photo.png"
    src.write_bytes(b"source")
    good = tmp_path / "photo.jpg"
    good.write_bytes(b"jpeg")
    edited = tmp_path / "photo (1).jpg"
    edited.write_bytes(b"jpeg")
    gone = tmp_path / "photo (2).jpg"
    gone.write_bytes(b"jpeg")
    files = [created(good, src), created(edited, src), created(gone, src)]
    edited.write_bytes(b"edited by the user")
    gone.unlink()
    bin_ = FakeBin()
    registry = UndoRegistry(bin_)
    registry.record("j1", files)
    assert registry.can_undo("j1")

    outcome = registry.undo("j1")
    assert [i.status for i in outcome.items] == [
        UndoStatus.RECYCLED,
        UndoStatus.CHANGED,
        UndoStatus.MISSING,
    ]
    assert outcome.recycled == (good,)
    assert not outcome.complete
    assert bin_.recycled == [good]
    assert edited.read_bytes() == b"edited by the user"
    assert src.read_bytes() == b"source"  # never touched
    assert not registry.can_undo("j1")  # one shot
    assert registry.undo("j1").items[0].status is UndoStatus.UNKNOWN_JOB


def test_touch_alone_counts_as_changed(tmp_path: Path) -> None:
    src = tmp_path / "a.png"
    src.write_bytes(b"s")
    out = tmp_path / "a.jpg"
    out.write_bytes(b"o")
    file = created(out, src)
    st = out.stat()
    os.utime(out, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    registry = UndoRegistry(FakeBin())
    registry.record("j", [file])
    assert registry.undo("j").items[0].status is UndoStatus.CHANGED
    assert out.exists()


def test_replaced_file_with_the_same_size_and_time_is_changed(tmp_path: Path) -> None:
    src = tmp_path / "a.png"
    src.write_bytes(b"s")
    out = tmp_path / "a.jpg"
    out.write_bytes(b"o")
    file = created(out, src)
    st = out.stat()
    out.unlink()
    out.write_bytes(b"x")  # same size, and the timestamp put back
    os.utime(out, ns=(st.st_atime_ns, st.st_mtime_ns))
    registry = UndoRegistry(FakeBin())
    registry.record("j", [file])
    assert registry.undo("j").items[0].status is UndoStatus.CHANGED
    assert out.exists()


def test_refusals_and_errors_leave_the_file(tmp_path: Path) -> None:
    src = tmp_path / "a.png"
    src.write_bytes(b"s")
    out = tmp_path / "a.jpg"
    out.write_bytes(b"o")
    registry = UndoRegistry(FakeBin(refuse={"a.jpg"}))
    registry.record("j", [created(out, src)])
    assert registry.undo("j").items[0].status is UndoStatus.REFUSED
    assert out.exists()

    def boom(path: Path) -> bool:
        raise OSError("shell says no")

    registry = UndoRegistry(boom)
    registry.record("j", [created(out, src)])
    assert registry.undo("j").items[0].status is UndoStatus.REFUSED
    assert out.exists()


def test_a_source_path_is_never_recycled(tmp_path: Path) -> None:
    src = tmp_path / "a.png"
    src.write_bytes(b"s")
    bin_ = FakeBin()
    registry = UndoRegistry(bin_)
    registry.record("j", [created(src, src)])  # a corrupt record: output == source
    assert registry.undo("j").items[0].status is UndoStatus.REFUSED
    assert src.exists()
    assert bin_.recycled == []


def test_jobs_without_outputs_are_not_kept() -> None:
    registry = UndoRegistry(FakeBin())
    registry.record("empty", [])
    assert not registry.can_undo("empty")
    outcome = registry.undo("empty")
    assert outcome.items[0].status is UndoStatus.UNKNOWN_JOB
    assert not outcome.complete
