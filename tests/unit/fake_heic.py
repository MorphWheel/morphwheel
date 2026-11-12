"""A fake pillow-heif wheel for tests, and a way to pin the engine spec's hash to it (A6)."""

from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import replace

import pytest

from morphwheel.engine import engines
from morphwheel.engine.engines import HEIC_WHEEL


def fake_wheel(*, extra: dict[str, bytes] | None = None, pyd: bool = True) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("pillow_heif/__init__.py", b"# fake\n")
        z.writestr("pillow_heif/heif.py", b"\n")
        if pyd:
            z.writestr("_pillow_heif.cp312-win_amd64.pyd", b"MZ fake")
        z.writestr("pillow_heif-1.8.1.data/platlib/libheif-abc.dll", b"MZ dll")
        z.writestr("pillow_heif-1.8.1.dist-info/METADATA", b"Name: pillow-heif\n")
        z.writestr("pillow_heif-1.8.1.dist-info/licenses/LICENSE.txt", b"GPL\n")
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


def pin(monkeypatch: pytest.MonkeyPatch, data: bytes) -> None:
    """Point the pinned spec's hash at ``data``, so a fake wheel passes verification."""
    spec = replace(HEIC_WHEEL, sha256=hashlib.sha256(data).hexdigest(), size=len(data))
    monkeypatch.setattr(engines, "HEIC_WHEEL", spec)
