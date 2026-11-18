"""``examples/sample_plugin``: the M3 exit criterion (phase-2 criterion 7).

A third-party plugin, copied into the plugins folder as a user would, is discovered, obeys the
rules (RD-25, RD-28), reaches the More arc once enabled, and converts through a real worker,
without a line of the app changed.
"""

from __future__ import annotations

import ast
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest
from PIL import Image

from morphwheel.core.catalog import Catalog
from morphwheel.core.formats import FileInfo
from morphwheel.core.jobs import Task, TaskStatus
from morphwheel.engine.worker_pool import WorkerPool
from morphwheel.plugins import loader
from morphwheel.plugins.discovery import discover
from morphwheel.plugins.loader import load_converter
from morphwheel.plugins.registry import Registry, build_registry
from morphwheel.settings.model import PluginPrefs

from .conftest import Collector

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "sample_plugin"
PLUGIN_ID = "sample_plugin"


def install(tmp_path: Path) -> Registry:
    """The example copied under its id into a plugins folder, discovered and enabled."""
    plugins_dir = tmp_path / "plugins"
    shutil.copytree(EXAMPLE, plugins_dir / PLUGIN_ID)
    discovery = discover(plugins_dir)
    assert discovery.broken == (), [b.reason for b in discovery.broken]
    return build_registry(discovery, PluginPrefs(enabled=(PLUGIN_ID,)))


def test_the_sample_plugin_follows_the_rules_and_reaches_the_more_arc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = install(tmp_path)
    entry = registry.entry(PLUGIN_ID)
    assert entry is not None
    assert entry.enabled
    assert entry.manifest.plugin.entry == f"{PLUGIN_ID}:Converter"  # one module, named after the id
    (target,) = registry.arc_targets
    assert target.id == f"{PLUGIN_ID}:bmp"
    assert target.label == "BMP"
    assert target.slot is None  # a third-party target: the More arc, never a fixed slot
    plan = Catalog.of(registry.targets).plan([FileInfo.from_path(Path("photo.png"))])
    assert [s.target.id for s in plan.more if s.target] == [target.id]
    # The loader accepts it under the folder rule (RD-28), in this process.
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(loader, "_PLUGIN_DIRS", set())
    monkeypatch.delitem(sys.modules, PLUGIN_ID, raising=False)
    spec = next(s for s in registry.specs if s.plugin_id == PLUGIN_ID)
    assert spec.directory == entry.manifest.directory
    converter = load_converter(spec)
    module_file = Path(sys.modules[type(converter).__module__].__file__ or "").resolve()
    assert module_file == (tmp_path / "plugins" / PLUGIN_ID / f"{PLUGIN_ID}.py").resolve()
    monkeypatch.delitem(sys.modules, PLUGIN_ID, raising=False)


@pytest.mark.integration
def test_the_sample_plugin_converts_through_a_worker(
    tmp_path: Path, images: Mapping[str, Path]
) -> None:
    registry = install(tmp_path)
    (target,) = registry.arc_targets
    folder = tmp_path / "pictures"
    folder.mkdir()
    src = folder / "alpha.png"  # transparency: the plugin's own code, not a plain re-encode
    shutil.copyfile(images["alpha.png"], src)
    collector = Collector()
    pool = WorkerPool(
        size=1, task_timeout_s=30.0, plugins=registry.specs, on_log=collector.records.append
    )
    pool.start()
    try:
        collector.expect(1)
        pool.run(Task("job", 1, src, target, tmp_path / "fallback"), collector.done)
        (result,) = collector.wait()
    finally:
        pool.shutdown()
    assert result.status is TaskStatus.OK, result.detail
    out = folder / "alpha.bmp"
    assert out.exists()
    with Image.open(src) as source:
        size = source.size
        alpha = source.convert("RGBA").getchannel("A")
        pixels = ((x, y) for y in range(size[1]) for x in range(size[0]))
        hole = next(p for p in pixels if alpha.getpixel(p) == 0)
    with Image.open(out) as im:
        assert im.format == "BMP"
        assert im.size == size
        assert im.mode == "RGB"
        assert im.getpixel(hole) == (255, 255, 255)  # transparency landed on white
    assert src.read_bytes() == images["alpha.png"].read_bytes()  # the source is untouched


def test_the_example_is_a_self_contained_folder() -> None:
    """What a user copies: the manifest and one module, importing only what a plugin may (A4)."""
    names = sorted(p.name for p in EXAMPLE.iterdir() if p.name != "__pycache__")
    assert names == ["plugin.toml", f"{PLUGIN_ID}.py"]
    tree = ast.parse((EXAMPLE / f"{PLUGIN_ID}.py").read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert imported == {"__future__", "PIL", "morphwheel.plugins.api"}
