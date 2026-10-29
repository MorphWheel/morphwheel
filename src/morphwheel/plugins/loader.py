"""WORKER ONLY: import a plugin's converter from its manifest entry (phase-4 §2, §4.5).

The GUI process never calls this module (R5: it reads ``plugin.toml`` and nothing else). Workers
call ``load_converter`` lazily, the first time a task needs a plugin, and cache the instance.

Rules:

- **Scoped ``sys.path``.** A third-party plugin's directory is put on ``sys.path`` so that
  ``entry = "heic_pro:Converter"`` resolves to ``<plugin dir>/heic_pro.py`` or ``heic_pro/``.
  Plugins may use the standard library, what the app bundles (Pillow), and pure Python in their
  own folder; no pip (A4). The builtin plugin is a normal ``morphwheel`` module and needs no path.
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


def add_search_path(directory: Path) -> None:
    """Append ``directory`` to ``sys.path`` once; appended, it can't shadow the app or stdlib."""
    text = str(directory)
    if text not in sys.path:
        sys.path.append(text)


def load_converter(spec: PluginSpec) -> Converter:
    module_name, _, class_name = spec.entry.partition(":")
    if spec.directory is not None:
        add_search_path(spec.directory)
    try:
        module = importlib.import_module(module_name)
    except Exception as e:  # ImportError, or anything the module does at import time
        raise PluginLoadError(f"{spec.plugin_id}: can't import {module_name!r}: {e}") from e
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
