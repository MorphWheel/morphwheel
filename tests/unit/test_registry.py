"""``plugins.registry``: the enabled list is the trust record, the order list the arc order.

Traceability (phase-2 §3: every third-party plugin is disabled until enabled; phase-3 §2.3: the
arc holds enabled plugins' targets in the settings' order, at most six; S5 carry-over: ids in the
settings never become paths, and unknown ones are ignored).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from morphwheel.core.catalog import MORE_ARC_MAX, MORE_SLOT, Catalog, Reason
from morphwheel.core.formats import FileInfo
from morphwheel.plugins.discovery import BrokenKind, BrokenPlugin, Discovery
from morphwheel.plugins.manifest import builtin_manifest, parse_manifest
from morphwheel.plugins.registry import build_registry
from morphwheel.settings.model import PluginPrefs

BUILTIN = builtin_manifest()


def plugin(pid: str, *targets: str) -> object:
    """A third-party manifest with one PNG→<fmt> target per name."""
    rows = "".join(
        f'\n[[targets]]\nid = "{t}"\nlabel = "{t.upper()}"\noutput = "{t}"\naccepts = ["png"]\n'
        for t in targets
    )
    module = pid.replace(".", "_")  # one module name per plugin (RD-28)
    head = f'[plugin]\nid = "{pid}"\nname = "{pid}"\nversion = "1"\napi = "0.1"\n'
    text = head + f'entry = "{module}:C"\n{rows}'
    return parse_manifest(text, directory=Path("plugins") / pid, is_builtin=False)


def discovery(*manifests: object, broken: tuple[BrokenPlugin, ...] = ()) -> Discovery:
    return Discovery((BUILTIN, *manifests), broken, Path("plugins"))  # type: ignore[arg-type]


A = plugin("a.one", "tiff")
B = plugin("b.two", "bmp", "gif")
C = plugin("c.three", "ico")


def test_nothing_enabled_by_default_and_the_builtin_always_is() -> None:
    r = build_registry(discovery(A, B), PluginPrefs())
    assert r.prefs == PluginPrefs()
    assert [(e.id, e.enabled) for e in r.entries] == [
        ("pillow_images", True),
        ("a.one", False),
        ("b.two", False),
    ]
    assert r.targets == BUILTIN.targets
    assert r.arc_targets == ()
    assert [(s.plugin_id, s.directory) for s in r.specs] == [("pillow_images", None)]
    assert r.more_overflow == 0
    plan = Catalog.of(r.targets).plan([FileInfo.from_path(Path("x.png"))])
    assert plan.slots[MORE_SLOT].reason is Reason.NO_PLUGINS


def test_enabling_appends_the_targets_in_manifest_order_and_the_specs_carry_the_folder() -> None:
    r = build_registry(discovery(A, B), PluginPrefs(enabled=("b.two",)))
    assert [t.id for t in r.arc_targets] == ["b.two:bmp", "b.two:gif"]
    assert r.targets == BUILTIN.targets + r.arc_targets
    assert [(s.plugin_id, s.directory) for s in r.specs] == [
        ("pillow_images", None),
        ("b.two", Path("plugins") / "b.two"),
    ]
    assert r.entry("a.one") is not None
    assert not r.entry("a.one").enabled  # type: ignore[union-attr]
    assert r.entry("nope") is None


def test_the_order_list_comes_first_then_the_rest_by_folder_name() -> None:
    prefs = PluginPrefs(enabled=("a.one", "b.two", "c.three"), order=("c.three", "a.one"))
    r = build_registry(discovery(A, B, C), prefs)
    assert [e.id for e in r.third_party] == ["c.three", "a.one", "b.two"]
    assert [t.id for t in r.arc_targets] == ["c.three:ico", "a.one:tiff", "b.two:bmp", "b.two:gif"]


def test_a_disabled_plugin_keeps_its_row_and_leaves_the_arc() -> None:
    """One stable list for the page: a switch flips ``enabled`` without moving the row."""
    prefs = PluginPrefs(enabled=("a.one",), order=("c.three", "a.one", "b.two"))
    r = build_registry(discovery(A, B, C), prefs)
    assert [(e.id, e.enabled) for e in r.third_party] == [
        ("c.three", False),
        ("a.one", True),
        ("b.two", False),
    ]
    assert [t.id for t in r.arc_targets] == ["a.one:tiff"]


def test_unknown_ids_are_ignored_and_logged_and_a_repeated_id_counts_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    prefs = PluginPrefs(
        enabled=("a.one", "gone", "../../etc", "pillow_images"), order=("Bad Id", "a.one", "a.one")
    )
    with caplog.at_level(logging.WARNING, logger="morphwheel.plugins.registry"):
        r = build_registry(discovery(A), prefs)
    assert [e.id for e in r.third_party] == ["a.one"]  # once, although ordered twice
    assert [t.id for t in r.arc_targets] == ["a.one:tiff"]
    Catalog.of(r.targets)  # unique target ids: the catalog accepts it
    assert caplog.text.count("not an installed plugin") == 3
    assert "pillow_images" not in caplog.text  # the builtin's id is simply nothing
    # Negative control: valid, known ids log nothing.
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="morphwheel.plugins.registry"):
        build_registry(discovery(A), PluginPrefs(enabled=("a.one",), order=("a.one",)))
    assert caplog.text == ""


def test_an_enabled_plugin_that_is_broken_contributes_nothing() -> None:
    broken = (BrokenPlugin(Path("plugins/b.two"), BrokenKind.INVALID, "plugin.api: …", "b.two"),)
    r = build_registry(discovery(A, broken=broken), PluginPrefs(enabled=("a.one", "b.two")))
    assert r.broken == broken
    assert r.entry("b.two") is None
    assert [t.id for t in r.arc_targets] == ["a.one:tiff"]


def test_the_arc_shows_six_targets_and_the_registry_counts_the_rest() -> None:
    many = plugin("d.many", "tiff", "bmp", "gif", "ico", "pdf")  # 5 targets
    prefs = PluginPrefs(enabled=("d.many", "b.two"), order=("d.many", "b.two"))
    r = build_registry(discovery(B, many), prefs)
    assert len(r.arc_targets) == 7
    assert r.more_overflow == 1  # for the page, which has no files to plan with
    plan = Catalog.of(r.targets).plan([FileInfo.from_path(Path("x.png"))])
    assert len(plan.more) == MORE_ARC_MAX
    assert plan.more_overflow == r.more_overflow
    assert [s.target.id for s in plan.more if s.target][-1] == "b.two:bmp"  # cut mid-plugin


def with_entry(pid: str, entry: str, target: str) -> object:
    text = (
        f'[plugin]\nid = "{pid}"\nname = "{pid}"\nversion = "1"\napi = "0.1"\nentry = "{entry}"\n'
        f'\n[[targets]]\nid = "{target}"\nlabel = "T"\noutput = "{target}"\naccepts = ["png"]\n'
    )
    return parse_manifest(text, directory=Path("plugins") / pid, is_builtin=False)


def test_two_plugins_sharing_a_module_name_the_later_row_is_broken() -> None:
    """RD-28: a worker imports by module name; the registry refuses the clash deterministically."""
    first = with_entry("x.first", "plugin:C", "tiff")
    second = with_entry("y.second", "plugin.sub:C", "bmp")  # the same top-level name
    prefs = PluginPrefs(enabled=("x.first", "y.second"), order=("y.second", "x.first"))
    r = build_registry(discovery(first, second), prefs)
    assert [e.id for e in r.third_party] == ["y.second"]  # first in row order wins the name
    assert [t.id for t in r.arc_targets] == ["y.second:bmp"]
    (b,) = r.broken
    assert b.kind is BrokenKind.MODULE_CLASH
    assert b.plugin_id == "x.first"
    assert b.directory == Path("plugins/x.first")
    assert "'plugin' is also used by y.second" in b.reason
    # An enabled plugin claims first, whatever the row order: installing one never breaks one.
    prefs = PluginPrefs(enabled=("x.first",), order=("y.second", "x.first"))
    r = build_registry(discovery(first, second), prefs)
    assert [(e.id, e.enabled) for e in r.third_party] == [("x.first", True)]
    assert r.broken[0].plugin_id == "y.second"
    assert "also used by x.first" in r.broken[0].reason
    # An entry named like the app never gets this far: the manifest refuses it (test_manifest).
