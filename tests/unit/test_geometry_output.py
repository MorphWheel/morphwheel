"""Tests for ``core.geometry`` (regions, clamping, More arc) and ``core.output_policy``.

Traceability (phase-4 §6): "clamp by disc, More arc rotates inward"; "(n) on collision,
(compressed)"; "read-only fallback" (the pure decision).
"""

from __future__ import annotations

from itertools import islice
from pathlib import Path

import pytest

from morphwheel.core.catalog import SlotPos, Target, TargetKind
from morphwheel.core.formats import FormatId
from morphwheel.core.geometry import (
    MoreArc,
    Point,
    Rect,
    RegionKind,
    WheelGeometry,
    angle_delta,
    compass_angle,
    polar,
)
from morphwheel.core.output_policy import (
    MAX_COLLISION_SUFFIX,
    candidate_paths,
    output_directory,
)

M = WheelGeometry()
SCREEN = Rect(0, 0, 1707, 960)


def at(angle: float, radius: float) -> Point:
    return polar(angle, radius)


# --------------------------------------------------------------------------- regions


@pytest.mark.parametrize(
    ("angle", "radius", "kind", "slot"),
    [
        (0, 0, RegionKind.HUB, None),
        (0, 36, RegionKind.HUB, None),
        (0, 38, RegionKind.GAP, None),  # between hub and ring
        (0, 80, RegionKind.SLOT, SlotPos.N),
        (45, 80, RegionKind.SLOT, SlotPos.NE),
        (90, 80, RegionKind.SLOT, SlotPos.E),
        (135, 80, RegionKind.SLOT, SlotPos.SE),
        (180, 80, RegionKind.SLOT, SlotPos.S),
        (225, 80, RegionKind.SLOT, SlotPos.SW),
        (270, 80, RegionKind.SLOT, SlotPos.W),
        (315, 80, RegionKind.SLOT, SlotPos.NW),
        (22.5, 80, RegionKind.GAP, None),  # slot boundary
        (23.5, 80, RegionKind.GAP, None),  # inside the 3° gap
        (24.5, 80, RegionKind.SLOT, SlotPos.NE),
        (359, 118, RegionKind.SLOT, SlotPos.N),
        (0, 150, RegionKind.HALO, None),
        (0, 190, RegionKind.HALO, None),
        (0, 191, RegionKind.OUTSIDE, None),
    ],
)
def test_regions_size_m(
    angle: float, radius: float, kind: RegionKind, slot: SlotPos | None
) -> None:
    region = M.region(at(angle, radius))
    assert (region.kind, region.slot) == (kind, slot)


def test_scale_changes_every_radius() -> None:
    large = WheelGeometry.for_size("L")
    assert large.region(at(0, 200)).kind is RegionKind.HALO  # 190 * 1.2 = 228
    assert M.region(at(0, 200)).kind is RegionKind.OUTSIDE
    assert [WheelGeometry.for_size(s).window_size for s in "SML"] == [323, 380, 456]


def test_more_arc_regions() -> None:
    arc = MoreArc(center_deg=315, count=3)  # spans 270°..360°
    assert M.region(at(280, 150), arc).item == 0
    assert M.region(at(315, 150), arc).item == 1
    assert M.region(at(350, 150), arc).item == 2
    assert M.region(at(10, 150), arc).kind is RegionKind.HALO  # outside the arc's span
    assert M.region(at(315, 121), arc).kind is RegionKind.GAP  # between ring and arc
    assert M.region(at(315, 180), arc).kind is RegionKind.HALO
    assert arc.item_angle(1) == pytest.approx(315)


def test_push_outward_through_the_more_slot() -> None:
    assert M.is_outward_of_more_slot(at(315, 130))
    assert not M.is_outward_of_more_slot(at(315, 100))
    assert not M.is_outward_of_more_slot(at(0, 130))


def test_angles_round_trip() -> None:
    for angle in (0, 33, 90, 181, 359):
        assert compass_angle(polar(angle, 50)) == pytest.approx(angle % 360, abs=1e-9)
    assert angle_delta(10, 350) == pytest.approx(20)
    assert angle_delta(350, 10) == pytest.approx(-20)


# --------------------------------------------------------------------------- clamping and the arc


def test_clamp_keeps_the_disc_on_screen_but_not_the_halo() -> None:
    assert M.clamp_center(Point(10, 10), SCREEN) == Point(118, 118)
    assert M.clamp_center(Point(800, 400), SCREEN) == Point(800, 400)
    assert M.clamp_center(Point(1700, 955), SCREEN) == Point(1707 - 118, 960 - 118)
    assert M.clamp_center(Point(5, 5), Rect(0, 0, 100, 100)) == Point(50, 50)  # tiny screen


def test_more_arc_prefers_nw_and_rotates_inward_at_edges() -> None:
    middle = M.more_arc(Point(800, 480), SCREEN, 4)
    assert middle == MoreArc(315, 4)

    corner = Point(118, 118)  # clamped to the top-left corner: NW would leave the screen
    rotated = M.more_arc(corner, SCREEN, 4)
    assert rotated is not None
    toward_center = compass_angle(Point(SCREEN.center.x - corner.x, SCREEN.center.y - corner.y))
    assert rotated.center_deg == pytest.approx(toward_center)
    assert M.more_arc(corner, SCREEN, 0) is None


# --------------------------------------------------------------------------- output names

JPEG = Target(
    "jpeg", "JPG", TargetKind.CONVERT, FormatId.JPEG, frozenset({FormatId.PNG}), "b", True
)
COMPRESS = Target(
    "compress", "Compress", TargetKind.COMPRESS, None, frozenset({FormatId.JPEG}), "b", True
)


def test_convert_candidates() -> None:
    src = Path(r"C:\x\photo.png")
    names = [p.name for p in islice(candidate_paths(src, JPEG, source_format=FormatId.PNG), 3)]
    assert names == ["photo.jpg", "photo (1).jpg", "photo (2).jpg"]
    everything = list(candidate_paths(src, JPEG, source_format=FormatId.PNG))
    assert len(everything) == MAX_COLLISION_SUFFIX + 1


@pytest.mark.parametrize(
    ("name", "detected", "expected"),
    [
        ("Photo.JPG", FormatId.JPEG, "Photo (compressed).JPG"),  # the source's own spelling
        ("photo.jpeg", FormatId.JPEG, "photo (compressed).jpeg"),
        ("photo", FormatId.JPEG, "photo (compressed).jpg"),  # RF-3: no extension
        ("a.png", FormatId.JPEG, "a (compressed).jpg"),  # RF-3: mislabeled, the bytes decide
        ("Photo.JPG", None, "Photo (compressed).JPG"),  # not sniffed: the name is all we have
    ],
)
def test_compress_extension_follows_the_detected_format(
    name: str, detected: FormatId | None, expected: str
) -> None:
    first = next(candidate_paths(Path(r"C:\x") / name, COMPRESS, source_format=detected))
    assert first == Path(r"C:\x") / expected


def test_a_dot_that_is_not_an_extension_stays_in_the_name() -> None:
    src = Path(r"C:\x\Dr. Who")  # a PNG with no extension: ". Who" is part of the name
    assert next(candidate_paths(src, COMPRESS, source_format=FormatId.PNG)).name == (
        "Dr. Who (compressed).png"
    )
    assert next(candidate_paths(src, JPEG, source_format=FormatId.PNG)).name == "Dr. Who.jpg"


def test_never_proposes_the_source_itself() -> None:
    really_png = Path(r"C:\x\A.JPG")  # extension says JPEG, bytes say PNG; target is JPEG
    first = next(candidate_paths(really_png, JPEG, source_format=FormatId.PNG))
    assert first == Path(r"C:\x\A (1).jpg")


def test_candidates_in_another_directory() -> None:
    src, elsewhere = Path(r"C:\ro\photo.png"), Path(r"C:\dl\Morphwheel")
    first = next(candidate_paths(src, JPEG, elsewhere, source_format=FormatId.PNG))
    assert first == Path(r"C:\dl\Morphwheel\photo.jpg")


def test_output_directory_fallback() -> None:
    src, fallback = Path(r"C:\ro\photo.png"), Path(r"C:\dl\Morphwheel")
    assert output_directory(src, writable=lambda _: True, fallback_dir=fallback) == (
        src.parent,
        False,
    )
    assert output_directory(src, writable=lambda _: False, fallback_dir=fallback) == (
        fallback,
        True,
    )
