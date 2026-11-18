"""WORKER ONLY: import a plugin's converter from its manifest entry (phase-4 §2, §4.5).

The GUI process never calls ``load_converter`` (R5: it reads ``plugin.toml`` and nothing else).
Workers call it lazily, the first time a task needs a plugin, and cache the instance.

Rules:

- **Scoped ``sys.path``.** A third-party plugin's directory is appended to ``sys.path`` so that
  ``entry = "heic_pro:Converter"`` resolves to ``<plugin dir>/heic_pro.py`` or ``heic_pro/``.
  Appended, never prepended: a plugin can't shadow the app or the standard library. Plugins may
  use the standard library, what the app bundles (Pillow), and pure Python in their own folder;
  no pip (A4). The builtin plugin is a normal ``morphwheel`` module and needs no path.
- **A plugin is one module or one package, and it lives in its own folder (RD-28).** Every module
  the import brings in from a plugin folder must sit under *this* plugin's folder and under the
  entry's top name: helpers go inside the package and are imported relatively. Otherwise the load
  fails closed, before any code of the wrong plugin can run under this plugin's id: a name the
  app or another plugin already owns (the worker's ``sys.path`` starts with the app's own
  directory, and plugin folders come after it in load order), a sibling ``helpers.py`` that
  another plugin could resolve first, a folder without ``__init__.py``. What a refused load
  imported is dropped again, so a later plugin can't pick it up. The manifest refuses an entry
  named like the app, Pillow or the standard library, and the registry refuses two plugins whose
  entries share a top name, both before any worker sees them; this is the backstop, order-
  independent per worker.
- **Nothing is executed before the entry is imported**, and the import happens in a worker, where a
  crash costs a respawn and a ``WORKER_CRASHED`` result, not the GUI.
- A bad entry (module missing, attribute missing, not a converter, constructor raising) is a
  :class:`PluginLoadError`; the task fails with ``PLUGIN_ERROR`` and the message in the log.
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from morphwheel.plugins.api import Converter


class PluginLoadError(Exception):
    """The converter can't be loaded. The message names the plugin and the reason."""


@dataclass(frozen=True)
class PluginSpec:
    """What a worker needs to load one plugin. Built by the GUI from the manifest; picklable."""

    plugin_id: str
    entry: str  # "module.path:ClassName"
    directory: Path | None  # None for the builtin: it is imported from the package


class ConverterCache:
    """Per-worker cache of loaded converters, keyed by plugin id."""

    def __init__(self) -> None:
        self._loaded: dict[str, Converter] = {}

    def get(self, spec: PluginSpec) -> Converter:
        converter = self._loaded.get(spec.plugin_id)
        if converter is None:
            converter = load_converter(spec)
            self._loaded[spec.plugin_id] = converter
        return converter


def top_module(entry: str) -> str:
    """``"pkg.sub:Class"`` → ``"pkg"``: what an import of the entry claims in ``sys.modules``."""
    return entry.partition(":")[0].partition(".")[0]


_PLUGIN_DIRS: set[Path] = set()  # every plugin folder this worker put on sys.path (resolved)


def add_search_path(directory: Path) -> None:
    """Append ``directory`` to ``sys.path`` once; appended, it can't shadow the app or stdlib."""
    text = str(directory.resolve())
    if text not in sys.path:
        sys.path.append(text)


def load_converter(spec: PluginSpec) -> Converter:
    module_name, _, class_name = spec.entry.partition(":")
    if spec.directory is None:
        module = _import(spec, module_name)
    else:
        module = _load_third_party(spec, module_name, spec.directory.resolve())
    factory = getattr(module, class_name, None)
    if factory is None:
        raise PluginLoadError(f"{spec.plugin_id}: {module_name!r} has no {class_name!r}")
    try:
        converter = factory()
    except Exception as e:
        raise PluginLoadError(f"{spec.plugin_id}: {class_name}() raised {e!r}") from e
    if not isinstance(converter, Converter):
        raise PluginLoadError(f"{spec.plugin_id}: {class_name} has no convert() method")
    return converter


def _import(spec: PluginSpec, module_name: str) -> ModuleType:
    try:
        return importlib.import_module(module_name)
    except Exception as e:  # ImportError, or anything the module does at import time
        raise PluginLoadError(f"{spec.plugin_id}: can't import {module_name!r}: {e}") from e


# --------------------------------------------------------------------------- the folder rule
def _load_third_party(spec: PluginSpec, module_name: str, folder: Path) -> ModuleType:
    """Import the entry's module under the folder rule; a refused load leaves nothing behind."""
    top = top_module(spec.entry)
    cached = sys.modules.get(top)
    if cached is not None:  # the name is already taken: by this plugin (fine) or another
        _check_own(spec, top, cached, folder)
    add_search_path(folder)
    _PLUGIN_DIRS.add(folder)
    before = set(sys.modules)
    try:
        module = _import(spec, module_name)
        for name in sorted(set(sys.modules) - before):
            _check_new(spec, name, sys.modules[name], top, folder)
    except PluginLoadError:
        for name in set(sys.modules) - before:
            file = _module_file(sys.modules[name])
            if name.partition(".")[0] == top or _in_a_plugin_dir(file):
                del sys.modules[name]
        raise
    return module


def _module_file(module: ModuleType) -> Path | None:
    file = getattr(module, "__file__", None)
    return Path(file).resolve() if file else None


def _in_a_plugin_dir(file: Path | None) -> bool:
    return file is not None and any(file.is_relative_to(d) for d in _PLUGIN_DIRS)


def _check_own(spec: PluginSpec, name: str, module: ModuleType, folder: Path) -> None:
    """A module of the entry's own chain must be a file under this plugin's folder."""
    file = _module_file(module)
    if file is not None and file.is_relative_to(folder):
        return
    if file is None and hasattr(module, "__path__"):
        raise PluginLoadError(
            f"{spec.plugin_id}: {name!r} is a folder without __init__.py; add one to make it "
            f"a package"
        )
    raise PluginLoadError(
        f"{spec.plugin_id}: {name!r} resolves outside the plugin's folder (the name is taken by "
        f"the app or another plugin); rename the module (the plugin id is a safe name)"
    )


def _check_new(spec: PluginSpec, name: str, module: ModuleType, top: str, folder: Path) -> None:
    """A module the import brought in: the plugin's own under its top name, or not from a plugin."""
    if name.partition(".")[0] == top:
        _check_own(spec, name, module, folder)
        return
    file = _module_file(module)
    if file is None or not _in_a_plugin_dir(file):
        return  # the standard library, Pillow, an engine: not a plugin's code
    where = (
        f"a module of its own beside {top!r}"
        if file.is_relative_to(folder)
        else ("in another plugin's folder")
    )
    raise PluginLoadError(
        f"{spec.plugin_id}: {name!r} is {where}; put the plugin's helpers inside the package "
        f"{top!r} and import them relatively"
    )
