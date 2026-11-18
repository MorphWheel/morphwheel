"""``plugins.loader``: entries resolve from the plugin directory; bad plugins fail as load errors.

Traceability (phase-4 §6, R5): the GUI never imports plugin code. The ``broken`` fixture raises at
import; its manifest parses, and only ``load_converter`` trips over it.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from morphwheel.plugins import loader
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


# --------------------------------------------------------------------------- RD-28
CONVERTER = "class Converter:\n    def convert(self, ctx):\n        pass\n"


@pytest.fixture
def isolated(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """sys.path, sys.modules and the loader's folder set are put back after the test."""
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(loader, "_PLUGIN_DIRS", set())
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        del sys.modules[name]


def write_module(folder: Path, name: str, text: str = CONVERTER, *, package: bool = False) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    if package:
        (folder / name).mkdir()
        (folder / name / "__init__.py").write_text(text, encoding="utf-8")
    else:
        (folder / f"{name}.py").write_text(text, encoding="utf-8")
    importlib.invalidate_caches()
    return folder


def loaded_from(converter: Converter) -> Path:
    module = sys.modules[type(converter).__module__]
    return Path(module.__file__).resolve()  # type: ignore[arg-type]


@pytest.mark.usefixtures("isolated")
def test_two_plugins_sharing_a_module_name_the_second_is_refused(tmp_path: Path) -> None:
    a = write_module(tmp_path / "a", "zz_shared")
    b = write_module(tmp_path / "b", "zz_shared")
    first = load_converter(PluginSpec("a", "zz_shared:Converter", a))
    assert loaded_from(first).is_relative_to(a.resolve())
    with pytest.raises(PluginLoadError, match="'zz_shared' resolves outside the plugin's folder"):
        load_converter(PluginSpec("b", "zz_shared:Converter", b))
    again = load_converter(PluginSpec("a", "zz_shared:Converter", a))
    assert loaded_from(again) == loaded_from(first)


@pytest.mark.usefixtures("isolated")
def test_a_module_found_earlier_on_sys_path_is_refused(tmp_path: Path) -> None:
    """The worker's sys.path starts with the app's own directory: a plugin never wins against it."""
    shadow = write_module(tmp_path / "shadow", "zz_shadow")  # a working converter, elsewhere
    plugin = write_module(tmp_path / "plugin", "zz_shadow")
    sys.path.insert(0, str(shadow))
    with pytest.raises(PluginLoadError, match="resolves outside the plugin's folder"):
        load_converter(PluginSpec("p", "zz_shadow:Converter", plugin))
    assert "zz_shadow" not in sys.modules  # nothing of the wrong file is kept
    # Negative control: without the shadow, the same spec loads from its own folder.
    sys.path.remove(str(shadow))
    converter = load_converter(PluginSpec("p", "zz_shadow:Converter", plugin))
    assert loaded_from(converter) == (plugin / "zz_shadow.py").resolve()


@pytest.mark.usefixtures("isolated")
def test_a_stdlib_or_app_name_is_refused_for_a_third_party_entry(tmp_path: Path) -> None:
    with pytest.raises(PluginLoadError, match="'json' resolves outside the plugin's folder"):
        load_converter(PluginSpec("p", "json:JSONDecoder", tmp_path))
    with pytest.raises(PluginLoadError, match="'morphwheel' resolves outside"):
        load_converter(PluginSpec("p", "morphwheel.plugins.api:Converter", tmp_path))


@pytest.mark.usefixtures("isolated")
def test_a_sibling_helper_is_refused_dropped_and_never_found_by_another_plugin(
    tmp_path: Path,
) -> None:
    a = write_module(tmp_path / "a", "zz_helper")
    write_module(a, "zz_main", "import zz_helper\n" + CONVERTER)
    with pytest.raises(PluginLoadError, match="'zz_helper' is a module of its own beside"):
        load_converter(PluginSpec("a", "zz_main:Converter", a))
    assert "zz_helper" not in sys.modules
    assert "zz_main" not in sys.modules
    # Plugin b has its own zz_helper.py, but a's folder comes first on sys.path now.
    b = write_module(tmp_path / "b", "zz_helper")
    write_module(b, "zz_other", "import zz_helper\n" + CONVERTER)
    with pytest.raises(PluginLoadError, match="'zz_helper' is in another plugin's folder"):
        load_converter(PluginSpec("b", "zz_other:Converter", b))


@pytest.mark.usefixtures("isolated")
def test_a_package_with_relative_helpers_loads_and_a_folder_without_init_does_not(
    tmp_path: Path,
) -> None:
    pkg = write_module(tmp_path / "ok", "zz_pkg", "from .helpers import Converter\n", package=True)
    (pkg / "zz_pkg" / "helpers.py").write_text(CONVERTER, encoding="utf-8")
    importlib.invalidate_caches()
    converter = load_converter(PluginSpec("ok", "zz_pkg:Converter", pkg))
    assert type(converter).__module__ == "zz_pkg.helpers"
    assert loaded_from(converter).is_relative_to(pkg.resolve())
    ns = tmp_path / "ns"
    (ns / "zz_ns").mkdir(parents=True)  # no __init__.py: a namespace package
    (ns / "zz_ns" / "mod.py").write_text(CONVERTER, encoding="utf-8")
    importlib.invalidate_caches()
    with pytest.raises(PluginLoadError, match=r"'zz_ns' is a folder without __init__\.py"):
        load_converter(PluginSpec("ns", "zz_ns.mod:Converter", ns))
