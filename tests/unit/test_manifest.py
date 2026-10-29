"""``plugins.manifest``: the schema table, the impostor builtin, API compatibility, the toml.

Traceability (phase-4 §6): "8 fixed slots, More, plugins only in the More arc", including a
third-party plugin that impersonates a builtin (id and slot) and stays in the arc.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from morphwheel.core.catalog import MORE_SLOT, SLOT_ORDER, Catalog, SlotPos, TargetKind
from morphwheel.core.formats import FileInfo, FormatId
from morphwheel.plugins.manifest import (
    Manifest,
    ManifestError,
    api_compatible,
    builtin_manifest,
    load_manifest,
    parse_manifest,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from builtin_targets import BUILTINS

GOOD = """
[plugin]
id = "com.example.heicpro"
name = "HEIC Pro"
version = "1.2.0"
api = "0.1"
entry = "heic_pro:Converter"

[[targets]]
id = "tiff"
label = "TIFF"
output = "tiff"
accepts = ["heic", "jpeg"]
slot = "N"
"""


def parse(text: str, *, builtin: bool = False) -> Manifest:
    return parse_manifest(text, directory=Path("C:/plugins/x"), is_builtin=builtin)


def test_good_third_party_manifest_is_namespaced_and_keeps_no_slot() -> None:
    m = parse(GOOD)
    assert m.plugin.id == "com.example.heicpro"
    assert m.plugin.api == (0, 1)
    assert m.plugin.entry == "heic_pro:Converter"
    assert not m.is_builtin
    (t,) = m.targets
    assert t.id == "com.example.heicpro:tiff"
    assert t.provider == "com.example.heicpro"
    assert t.kind is TargetKind.CONVERT
    assert t.output_format is FormatId.TIFF
    assert t.accepts == {FormatId.HEIC, FormatId.JPEG}
    assert t.slot is None
    assert not t.is_builtin


def test_impostor_builtin_stays_in_the_more_arc() -> None:
    """A third-party manifest claiming the builtin's id and the N slot gets neither."""
    impostor = GOOD.replace('id = "com.example.heicpro"', 'id = "pillow_images"').replace(
        'id = "tiff"', 'id = "jpeg"'
    )
    m = parse(impostor)
    (t,) = m.targets
    assert t.id == "pillow_images:jpeg"  # never the plain "jpeg"
    catalog = Catalog.of([*BUILTINS, t])
    plan = catalog.plan([FileInfo.from_path(Path("a.heic"))])
    assert plan.slots[SlotPos.N].target is not None
    assert plan.slots[SlotPos.N].target.id == "jpeg"  # the real builtin keeps N
    assert [s.target.id for s in plan.more if s.target] == ["pillow_images:jpeg"]


def test_builtin_location_grants_the_slot_and_the_plain_id() -> None:
    m = parse(GOOD, builtin=True)
    (t,) = m.targets
    assert t.is_builtin
    assert t.slot is SlotPos.N
    assert t.id == "tiff"


@pytest.mark.parametrize(
    ("declared", "current", "ok"),
    [
        ((0, 1), (0, 1), True),
        ((0, 2), (0, 1), False),
        ((0, 1), (0, 2), False),
        ((1, 0), (0, 1), False),
        ((1, 0), (1, 3), True),
        ((1, 9), (1, 0), True),
        ((2, 0), (1, 3), False),
    ],
)
def test_api_compatibility(declared: tuple[int, int], current: tuple[int, int], ok: bool) -> None:
    assert api_compatible(declared, current) is ok


@pytest.mark.parametrize(
    ("edit", "field"),
    [
        (("[plugin]", "[plugin\n"), "TOML"),
        (('id = "com.example.heicpro"', 'id = "Com Example"'), "plugin.id"),
        (('api = "0.1"', 'api = "0.2"'), "plugin.api"),
        (('api = "0.1"', 'api = "one"'), "plugin.api"),
        (('entry = "heic_pro:Converter"', 'entry = "heic_pro.Converter"'), "plugin.entry"),
        (('name = "HEIC Pro"', 'name = ""'), "plugin.name"),
        (('output = "tiff"', 'output = "tif"'), "targets[0].output"),
        (('output = "tiff"', ""), "targets[0].output"),
        (('accepts = ["heic", "jpeg"]', "accepts = []"), "targets[0].accepts"),
        (('accepts = ["heic", "jpeg"]', 'accepts = ["heic", "tiff"]'), "targets[0].accepts"),
        (('accepts = ["heic", "jpeg"]', 'accepts = "heic"'), "targets[0].accepts"),
        (('slot = "N"', 'slot = "center"'), "targets[0].slot"),
        (('label = "TIFF"', 'label = "A very long label indeed"'), "targets[0].label"),
        (('id = "tiff"', 'id = "TIFF:x"'), "targets[0].id"),
        (('output = "tiff"', 'kind = "compress"\noutput = "tiff"'), "targets[0].output"),
        (('output = "tiff"', 'kind = "shrink"\noutput = "tiff"'), "targets[0].kind"),
    ],
)
def test_invalid_manifests_name_the_field(edit: tuple[str, str], field: str) -> None:
    text = GOOD.replace(*edit)
    with pytest.raises(ManifestError, match=field.replace("[", r"\[").replace("]", r"\]")):
        parse(text)


def test_missing_targets_and_duplicate_ids() -> None:
    head = GOOD.split("[[targets]]")[0]
    with pytest.raises(ManifestError, match="targets"):
        parse(head)
    with pytest.raises(ManifestError, match="unique"):
        parse(GOOD + GOOD[GOOD.index("[[targets]]") :])


def test_compress_target_has_no_output() -> None:
    text = GOOD.replace('output = "tiff"', 'kind = "compress"')
    (t,) = parse(text).targets
    assert t.kind is TargetKind.COMPRESS
    assert t.output_format is None


def test_load_manifest_from_disk_and_missing_file(tmp_path: Path) -> None:
    (tmp_path / "plugin.toml").write_text(GOOD, encoding="utf-8")
    m = load_manifest(tmp_path / "plugin.toml", is_builtin=False)
    assert m.directory == tmp_path
    with pytest.raises(ManifestError, match="can't read"):
        load_manifest(tmp_path / "nope" / "plugin.toml", is_builtin=False)


def test_bundled_manifest_matches_the_slot_map() -> None:
    """Phase-3 §2.2: seven slotted targets, NW left to More, HEIC accepted everywhere."""
    m = builtin_manifest()
    assert m.is_builtin
    assert m.plugin.id == "pillow_images"
    assert m.plugin.entry.startswith("morphwheel.builtin.pillow_images.converter:")
    by_slot = {t.slot: t for t in m.targets}
    assert set(by_slot) == set(SLOT_ORDER) - {MORE_SLOT}
    assert by_slot[SlotPos.N].id == "jpeg"
    assert by_slot[SlotPos.S].kind is TargetKind.COMPRESS
    for t in m.targets:
        if t.kind is TargetKind.CONVERT:
            assert FormatId.HEIC in t.accepts
            assert t.output_format not in t.accepts
    assert by_slot[SlotPos.S].accepts == {FormatId.JPEG, FormatId.PNG, FormatId.WEBP, FormatId.AVIF}
    # The same plan the S1/S2 test builders produce.
    plan = Catalog.of(m.targets).plan([FileInfo.from_path(Path("photo.png"))])
    expected = Catalog.of(BUILTINS).plan([FileInfo.from_path(Path("photo.png"))])
    assert {p: (s.status, s.target and s.target.id) for p, s in plan.slots.items()} == {
        p: (s.status, s.target and s.target.id) for p, s in expected.slots.items()
    }
