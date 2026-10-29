"""``engine.file_ops``: never overwrite, even in a race (phase-4 §6 row 2).

The race is simulated with a candidate generator that creates a file just before yielding its
name: another process won that name first. The "name taken at commit" case is the one that must
never end in a replace: the stranger's bytes stay, and ours get the next name. The placeholder is
held open with delete-on-close, so a killed worker leaves no empty "result" behind; that is proven
with a real child process that is terminated mid-reservation.
"""

from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from morphwheel.core.catalog import Target, TargetKind
from morphwheel.core.formats import FormatId
from morphwheel.core.output_policy import candidate_paths
from morphwheel.engine.file_ops import (
    TEMP_SUFFIX,
    EmptyOutputError,
    NoCandidateError,
    abort,
    commit,
    remove_quietly,
    reserve_unique,
)

JPEG = Target(
    "jpeg", "JPG", TargetKind.CONVERT, FormatId.JPEG, frozenset({FormatId.PNG}), "b", True
)


def names(directory: Path) -> Iterator[Path]:
    return candidate_paths(directory / "photo.png", JPEG, source_format=FormatId.PNG)


def test_reserve_claims_the_first_free_name_and_a_temp_beside_it(tmp_path: Path) -> None:
    res = reserve_unique(names(tmp_path))
    assert res.final == tmp_path / "photo.jpg"
    assert res.held
    assert res.final.exists()
    assert res.final.stat().st_size == 0
    assert res.temp.parent == tmp_path
    assert res.temp.name.startswith("photo.jpg.")
    assert res.temp.name.endswith(TEMP_SUFFIX)
    second = reserve_unique(names(tmp_path))
    assert second.final == tmp_path / "photo (1).jpg"  # the placeholder holds the name
    abort(res)
    abort(second)


def test_commit_gives_the_temp_the_final_name_and_reports_the_file(tmp_path: Path) -> None:
    res = reserve_unique(names(tmp_path))
    res.temp.write_bytes(b"jpeg bytes")
    created = commit(res, source=tmp_path / "photo.png")
    assert created.path == tmp_path / "photo.jpg"
    assert created.size == 10
    assert created.source == tmp_path / "photo.png"
    assert created.path.read_bytes() == b"jpeg bytes"
    assert not res.held
    assert sorted(p.name for p in tmp_path.iterdir()) == ["photo.jpg"]


def test_race_another_process_takes_the_name_first(tmp_path: Path) -> None:
    def racing() -> Iterator[Path]:
        for candidate in names(tmp_path):
            if candidate.name == "photo.jpg":
                candidate.write_bytes(b"theirs")  # created between our check and our claim
            yield candidate

    res = reserve_unique(racing())
    assert res.final == tmp_path / "photo (1).jpg"
    assert (tmp_path / "photo.jpg").read_bytes() == b"theirs"
    abort(res)


def test_commit_never_replaces_a_stranger_who_took_the_name(tmp_path: Path) -> None:
    """Between the placeholder's close and the rename, someone creates ``photo.jpg``."""
    res = reserve_unique(names(tmp_path))
    res.temp.write_bytes(b"ours")
    res.release()  # the placeholder is gone now
    (tmp_path / "photo.jpg").write_bytes(b"a stranger's file")
    created = commit(res, source=tmp_path / "photo.png")
    assert created.path == tmp_path / "photo (1).jpg"
    assert (tmp_path / "photo.jpg").read_bytes() == b"a stranger's file"
    assert created.path.read_bytes() == b"ours"


def test_commit_refuses_an_empty_output(tmp_path: Path) -> None:
    res = reserve_unique(names(tmp_path))
    with pytest.raises(EmptyOutputError):
        commit(res, source=tmp_path / "photo.png")
    assert list(tmp_path.iterdir()) == []


def test_commit_fails_cleanly_when_the_temp_is_gone(tmp_path: Path) -> None:
    res = reserve_unique(names(tmp_path))
    res.temp.unlink()
    with pytest.raises(FileNotFoundError):
        commit(res, source=tmp_path / "photo.png")
    assert list(tmp_path.iterdir()) == []  # the placeholder went with its handle


def test_commit_runs_out_of_names(tmp_path: Path) -> None:
    res = reserve_unique(names(tmp_path))
    res.temp.write_bytes(b"ours")
    res.release()
    (tmp_path / "photo.jpg").write_bytes(b"x")
    res._more = iter(())  # no names left after the first
    with pytest.raises(NoCandidateError):
        commit(res, source=tmp_path / "photo.png")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["photo.jpg"]


def test_abort_leaves_nothing_and_tolerates_missing_files(tmp_path: Path) -> None:
    res = reserve_unique(names(tmp_path))
    res.temp.write_bytes(b"partial")
    abort(res)
    assert list(tmp_path.iterdir()) == []
    abort(res)  # idempotent
    remove_quietly(tmp_path / "never-there")


def test_no_candidate_left() -> None:
    with pytest.raises(NoCandidateError):
        reserve_unique(iter(()))


def test_missing_directory_raises_a_plain_oserror(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        reserve_unique(names(tmp_path / "nope"))


CHILD = """
import sys, time
from pathlib import Path
from morphwheel.engine.file_ops import reserve_unique
d = Path(sys.argv[1])
res = reserve_unique([d / "photo.jpg"])
res.temp.write_bytes(b"half")
print("reserved", flush=True)
time.sleep(60)
"""


def test_a_killed_worker_leaves_no_placeholder(tmp_path: Path) -> None:
    """The placeholder is delete-on-close: TerminateProcess removes it. The temp is swept later."""
    proc = subprocess.Popen(
        [sys.executable, "-c", CHILD, str(tmp_path)],
        stdout=subprocess.PIPE,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2] / "src"),
    )
    try:
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "reserved"
        assert (tmp_path / "photo.jpg").exists()
        proc.kill()
        proc.wait(10)
    finally:
        if proc.poll() is None:
            proc.kill()
    deadline = time.monotonic() + 5.0  # a scanner may hold the dying handle open for a moment
    while (tmp_path / "photo.jpg").exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    left = sorted(p.name for p in tmp_path.iterdir())
    assert "photo.jpg" not in left
    assert len(left) == 1
    assert left[0].endswith(TEMP_SUFFIX)
    remove_quietly(tmp_path / left[0])  # what the pool does after a kill
    assert list(tmp_path.iterdir()) == []


def test_read_only_directory_refuses_a_reservation(read_only_dir: Path) -> None:
    with pytest.raises(PermissionError):
        reserve_unique(names(read_only_dir))
