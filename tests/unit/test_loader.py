"""``plugins.loader``: entries resolve from the plugin directory; bad plugins fail as load errors.

Traceability (phase-4 §6, R5): the GUI never imports plugin code. The ``broken`` fixture raises at
import; its manifest parses, and only ``load_converter`` trips over it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from morphwheel.plugins.api import Converter
from morphwheel.plugins.loader import ConverterCache, PluginLoadError, PluginSpec, load_converter
from morphwheel.plugins.manifest import MANIFEST_NAME, load_manifest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "plugins"


def spec(name: str) -> PluginSpec:
    m = load_manifest(FIXTURES / name / MANIFEST_NAME, is_builtin=False)
    return PluginSpec(m.plugin.id, m.plugin.entry, m.directory)


def test_fixture_manifests_parse_without_importing_any_plugin_code() -> None:
    before = set(sys.modules)
    for name in ("echo", "crash", "sleep", "tamper", "broken"):
        m = load_manifest(FIXTURES / name / MANIFEST_NAME, is_builtin=False)
        assert m.plugin.id == f"test.{name}"
        assert not m.is_builtin
    assert not {m for m in set(sys.modules) - before if m.endswith("_plugin")}


def test_echo_loads_from_its_directory_and_is_cached(tmp_path: Path) -> None:
    cache = ConverterCache()
    converter = cache.get(spec("echo"))
    assert isinstance(converter, Converter)
    assert cache.get(spec("echo")) is converter
    assert str(FIXTURES / "echo") in sys.path
    assert sys.path.index(str(FIXTURES / "echo")) > 0  # appended, never shadowing the app


def test_broken_module_is_a_load_error() -> None:
    with pytest.raises(PluginLoadError, match=r"test\.broken: can't import"):
        load_converter(spec("broken"))


def test_missing_class_and_non_converter() -> None:
    with pytest.raises(PluginLoadError, match="has no 'Nope'"):
        load_converter(PluginSpec("x", "echo_plugin:Nope", FIXTURES / "echo"))
    with pytest.raises(PluginLoadError, match="has no convert"):
        load_converter(PluginSpec("x", "pathlib:Path", None))
    with pytest.raises(PluginLoadError, match="raised"):
        load_converter(PluginSpec("x", "re:Pattern", None))  # re.Pattern() can't be instantiated


def test_builtin_entry_loads_without_a_directory() -> None:
    from morphwheel.plugins.manifest import builtin_manifest

    m = builtin_manifest()
    converter = load_converter(PluginSpec(m.plugin.id, m.plugin.entry, None))
    assert isinstance(converter, Converter)
