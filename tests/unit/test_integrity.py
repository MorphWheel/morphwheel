"""``engine.integrity``: what counts as a change, and when the hash is skipped."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from morphwheel.engine.integrity import Fingerprint, fingerprint, unchanged


@pytest.fixture
def source(tmp_path: Path) -> Path:
    p = tmp_path / "photo.png"
    p.write_bytes(b"\x89PNG" + bytes(range(256)) * 10)
    return p


def test_unchanged_file_matches_and_is_hashed(source: Path) -> None:
    a = fingerprint(source)
    b = fingerprint(source)
    assert a == b
    assert unchanged(a, b)
    assert a.hashed
    assert a.size == source.stat().st_size


def test_appended_bytes_are_a_change(source: Path) -> None:
    before = fingerprint(source)
    with source.open("ab") as f:
        f.write(b"x")
    assert not unchanged(before, fingerprint(source))


def test_same_size_different_bytes_is_a_change_even_with_the_same_mtime(source: Path) -> None:
    before = fingerprint(source)
    st = source.stat()
    data = bytearray(source.read_bytes())
    data[10] ^= 0xFF
    source.write_bytes(bytes(data))
    os.utime(source, ns=(st.st_atime_ns, st.st_mtime_ns))  # a tamperer restoring the timestamp
    after = fingerprint(source)
    assert after.size == before.size
    assert after.mtime_ns == before.mtime_ns
    assert not unchanged(before, after)  # the hash catches it


def test_touch_alone_is_a_change(source: Path) -> None:
    before = fingerprint(source)
    st = source.stat()
    os.utime(source, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    assert not unchanged(before, fingerprint(source))


def test_large_files_skip_the_hash_and_never_match_a_hashed_print(source: Path) -> None:
    small_limit = fingerprint(source, hash_limit=10)
    assert not small_limit.hashed
    assert small_limit.sha256 is None
    assert unchanged(small_limit, fingerprint(source, hash_limit=10))
    assert not unchanged(small_limit, fingerprint(source))  # policies differ: no false "intact"


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        fingerprint(tmp_path / "gone.png")


def test_replaced_file_with_the_same_size_and_time_is_a_change(source: Path) -> None:
    before = fingerprint(source, hash_limit=0)  # no hash: only the stat protects us
    st = source.stat()
    data = source.read_bytes()
    source.unlink()
    source.write_bytes(data)
    os.utime(source, ns=(st.st_atime_ns, st.st_mtime_ns))
    after = fingerprint(source, hash_limit=0)
    assert (after.size, after.mtime_ns) == (before.size, before.mtime_ns)
    assert after.file_id != before.file_id  # a new NTFS file reference
    assert not unchanged(before, after)


def test_fingerprint_is_a_plain_value() -> None:
    assert Fingerprint(1, 2, 3, None) == Fingerprint(1, 2, 3, None)
    assert Fingerprint(1, 2, 3, "a") != Fingerprint(1, 2, 3, "b")
