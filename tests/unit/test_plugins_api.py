"""``plugins.api``: stdlib-only (R3), runtime-checkable protocols, the error hierarchy."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from morphwheel.plugins import api
from morphwheel.plugins.api import (
    API_VERSION,
    ConversionContext,
    ConversionError,
    Converter,
    EngineMissingError,
    UnreadableInputError,
    UnsupportedAnimatedError,
)


def test_api_imports_only_the_standard_library() -> None:
    """R3, read from the source: every top-level import names a stdlib module."""
    tree = ast.parse(Path(api.__file__).read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert roots, "the module has imports"
    assert roots <= sys.stdlib_module_names, roots - sys.stdlib_module_names


def test_version_and_protocols() -> None:
    assert API_VERSION == (0, 1)

    class Good:
        def convert(self, ctx: ConversionContext) -> None:
            ctx.progress(1.0)

    class Bad:
        pass

    assert isinstance(Good(), Converter)
    assert not isinstance(Bad(), Converter)


def test_error_hierarchy() -> None:
    for cls in (UnreadableInputError, UnsupportedAnimatedError, EngineMissingError):
        assert issubclass(cls, ConversionError)
    assert issubclass(ConversionError, Exception)
    assert str(UnreadableInputError("damaged")) == "damaged"
