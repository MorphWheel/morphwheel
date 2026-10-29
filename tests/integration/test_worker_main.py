"""``engine.worker_main.run_task`` in-process, on real files: the §4.4 sequence and its guards.

Traceability (phase-4 §6): "a Compress output that isn't smaller is removed"; "fallback location
for a read-only folder"; "source integrity check: a malicious plugin that modifies the source gives
SOURCE_CHANGED and a critical alert". Also RD-3 (names follow the sniffed format).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from morphwheel.core.catalog import Target, TargetKind
from morphwheel.core.errors import ErrorCode, Severity, severity
from morphwheel.core.formats import FormatId
from morphwheel.core.jobs import Task, TaskStatus
from morphwheel.engine.worker_main import Progress, Reserved, run_task
from morphwheel.plugins.loader import ConverterCache, PluginSpec
from morphwheel.plugins.manifest import MANIFEST_NAME, builtin_manifest, load_manifest

from .conftest import plugin_dir

pytestmark = pytest.mark.integration

BUILTIN = builtin_manifest()
TARGETS = {t.id: t for t in BUILTIN.targets}
PLUGINS: dict[str, PluginSpec] = {
    BUILTIN.plugin.id: PluginSpec(BUILTIN.plugin.id, BUILTIN.plugin.entry, None)
}
for _name in ("echo", "tamper", "broken"):
    _m = load_manifest(plugin_dir(_name) / MANIFEST_NAME, is_builtin=False)
    PLUGINS[_m.plugin.id] = PluginSpec(_m.plugin.id, _m.plugin.entry, _m.directory)
    TARGETS[_m.targets[0].id] = _m.targets[0]


def task(
    source: Path,
    target: str,
    fallback: Path,
    *,
    source_format: FormatId | None = None,
    **options: object,
) -> Task:
    return Task("job", 1, source, TARGETS[target], fallback, options, source_format=source_format)


def run(t: Task, sent: list[object] | None = None) -> object:
    return run_task(t, ConverterCache(), PLUGINS, send=sent.append if sent is not None else None)


def listing(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


def alone(images: Mapping[str, Path], name: str, tmp_path: Path) -> Path:
    """A copy of one fixture in an otherwise empty folder, so the expected names are free."""
    folder = tmp_path / "alone"
    folder.mkdir()
    dest = folder / name
    dest.write_bytes(images[name].read_bytes())
    return dest


def test_jpeg_from_png_lands_beside_the_source(images: Mapping[str, Path], tmp_path: Path) -> None:
    src = alone(images, "photo.png", tmp_path)
    sent: list[object] = []
    result = run(task(src, "jpeg", tmp_path / "fallback"), sent)
    assert result.status is TaskStatus.OK  # type: ignore[attr-defined]
    created = result.output  # type: ignore[attr-defined]
    assert created.path == src.parent / "photo.jpg"
    assert created.size > 0
    assert created.source == src
    assert not result.used_fallback  # type: ignore[attr-defined]
    assert result.source_intact  # type: ignore[attr-defined]
    assert result.duration_ms > 0  # type: ignore[attr-defined]
    assert listing(src.parent) == ["photo.jpg", "photo.png"]  # no temp
    assert not (tmp_path / "fallback").exists()
    assert isinstance(sent[0], Reserved)
    assert sent[0].temp.parent == src.parent
    assert [m.fraction for m in sent if isinstance(m, Progress)][-1] == 1.0


def test_collision_gets_a_suffix_and_never_overwrites(images: Mapping[str, Path]) -> None:
    folder = images["photo.png"].parent
    existing = folder / "photo.jpg"  # the fixture copy: a real JPEG that must survive
    original = existing.read_bytes()
    result = run(task(images["photo.png"], "jpeg", folder / "fallback"))
    assert result.output.path == folder / "photo (1).jpg"  # type: ignore[attr-defined]
    assert existing.read_bytes() == original


def test_output_name_follows_the_sniffed_format(images: Mapping[str, Path], tmp_path: Path) -> None:
    """RD-3: ``actually-jpeg.png`` compressed is ``actually-jpeg (compressed).jpg``."""
    src = alone(images, "actually-jpeg.png", tmp_path)
    result = run(task(src, "compress", tmp_path / "fb"))
    assert result.status is TaskStatus.OK  # type: ignore[attr-defined]
    assert result.output.path.name == "actually-jpeg (compressed).jpg"  # type: ignore[attr-defined]
    # With the hint from the wheel's sniff, the worker doesn't read the header again.
    hinted = run(task(src, "compress", tmp_path / "fb", source_format=FormatId.JPEG))
    assert hinted.output.path.name == "actually-jpeg (compressed) (1).jpg"  # type: ignore[attr-defined]


def test_compress_not_smaller_leaves_nothing(images: Mapping[str, Path], tmp_path: Path) -> None:
    src = images["compact.jpg"]  # quality 10: re-encoding at 80 can only grow it
    before = listing(src.parent)
    result = run(task(src, "compress", tmp_path / "fb"))
    assert result.status is TaskStatus.FAILED  # type: ignore[attr-defined]
    assert result.error is ErrorCode.NOT_SMALLER  # type: ignore[attr-defined]
    assert severity(ErrorCode.NOT_SMALLER) is Severity.INFO
    assert listing(src.parent) == before


def test_tampering_plugin_is_caught_and_its_output_discarded(
    images: Mapping[str, Path], tmp_path: Path
) -> None:
    src = images["photo.jpg"]
    before = listing(src.parent)
    result = run(task(src, "test.tamper:copy", tmp_path / "fb"))
    assert result.status is TaskStatus.FAILED  # type: ignore[attr-defined]
    assert result.error is ErrorCode.SOURCE_CHANGED  # type: ignore[attr-defined]
    assert not result.source_intact  # type: ignore[attr-defined]
    assert severity(ErrorCode.SOURCE_CHANGED) is Severity.CRITICAL
    assert "source changed" in (result.detail or "")  # type: ignore[attr-defined]
    assert listing(src.parent) == before  # the plugin's output never got its final name


def test_well_behaved_plugin_passes_the_guard(images: Mapping[str, Path], tmp_path: Path) -> None:
    result = run(task(alone(images, "photo.jpg", tmp_path), "test.echo:copy", tmp_path / "fb"))
    assert result.status is TaskStatus.OK  # type: ignore[attr-defined]
    assert result.output.path.name == "photo.png"  # type: ignore[attr-defined]


def test_broken_plugin_is_a_plugin_error_not_a_crash(
    images: Mapping[str, Path], tmp_path: Path
) -> None:
    result = run(task(images["photo.jpg"], "test.broken:copy", tmp_path / "fb"))
    assert result.error is ErrorCode.PLUGIN_ERROR  # type: ignore[attr-defined]
    assert "broken on purpose" in (result.detail or "")  # type: ignore[attr-defined]


def test_unknown_provider(images: Mapping[str, Path], tmp_path: Path) -> None:
    rogue = Target("x:y", "Y", TargetKind.CONVERT, FormatId.PNG, frozenset({FormatId.JPEG}), "x")
    result = run_task(Task("j", 1, images["photo.jpg"], rogue, tmp_path), ConverterCache(), PLUGINS)
    assert result.error is ErrorCode.PLUGIN_ERROR


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("anim.gif", ErrorCode.UNSUPPORTED_ANIMATED),
        ("corrupt.jpg", ErrorCode.UNREADABLE),
        ("notes.txt", ErrorCode.UNREADABLE),
    ],
)
def test_refusals_leave_nothing(
    images: Mapping[str, Path], tmp_path: Path, name: str, code: ErrorCode
) -> None:
    src = images[name]
    before = listing(src.parent)
    result = run(task(src, "png" if name != "anim.gif" else "jpeg", tmp_path / "fb"))
    assert result.status is TaskStatus.FAILED  # type: ignore[attr-defined]
    assert result.error is code  # type: ignore[attr-defined]
    assert listing(src.parent) == before


def test_missing_source_is_unreadable(tmp_path: Path) -> None:
    result = run(task(tmp_path / "gone.png", "jpeg", tmp_path / "fb"))
    assert result.error is ErrorCode.UNREADABLE  # type: ignore[attr-defined]
    assert not (tmp_path / "fb").exists()


@pytest.fixture
def locked_source(
    images: Mapping[str, Path], tmp_path: Path, lock_directory: Callable[[Path], None]
) -> Path:
    """A copy of the PNG in a folder this user can't add files to. Written before the ACE lands."""
    d = tmp_path / "locked"
    d.mkdir()
    src = d / "photo.png"
    src.write_bytes(images["photo.png"].read_bytes())
    lock_directory(d)
    return src


def test_read_only_folder_falls_back_to_downloads(locked_source: Path, tmp_path: Path) -> None:
    fallback = tmp_path / "Downloads" / "Morphwheel"  # doesn't exist yet
    result = run(task(locked_source, "jpeg", fallback))
    assert result.status is TaskStatus.OK  # type: ignore[attr-defined]
    assert result.used_fallback  # type: ignore[attr-defined]
    assert result.output.path == fallback / "photo.jpg"  # type: ignore[attr-defined]
    assert listing(locked_source.parent) == ["photo.png"]
