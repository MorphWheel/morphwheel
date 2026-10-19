"""Tests for ``core.catalog`` (U2, U3, builtin privilege) and ``core.jobs``.

Traceability (phase-4 §6): "source disabled, mixed-drag skip, incompatible" → U2 tests;
"8 fixed slots, More, plugins only in the More arc" → arc and impersonation tests.
"""

from __future__ import annotations

import pickle
from pathlib import Path

import pytest
from builtin_targets import BUILTINS, convert, file, plugin

from morphwheel.core.catalog import (
    MORE_ARC_MAX,
    Catalog,
    PlanStatus,
    Reason,
    SlotPos,
    SlotStatus,
    Target,
    TargetKind,
    Verdict,
)
from morphwheel.core.errors import ErrorCode
from morphwheel.core.formats import FileInfo, FormatId
from morphwheel.core.jobs import (
    CreatedFile,
    JobOutcome,
    JobResult,
    Task,
    TaskResult,
    TaskStatus,
)

F = FormatId
f = file


@pytest.fixture
def catalog() -> Catalog:
    return Catalog.of(BUILTINS)


# --------------------------------------------------------------------------- U2: slot states


@pytest.mark.parametrize(
    ("files", "pos", "status", "skips", "reason"),
    [
        (["a.png"], SlotPos.N, SlotStatus.ENABLED, 0, None),
        (["a.png"], SlotPos.NE, SlotStatus.SOURCE, 1, Reason.IS_SOURCE),
        (["a.png"], SlotPos.S, SlotStatus.ENABLED, 0, None),
        (["a.jpg"], SlotPos.N, SlotStatus.SOURCE, 1, Reason.IS_SOURCE),
        (["a.heic"], SlotPos.S, SlotStatus.INCOMPATIBLE, 0, Reason.CONVERT_FIRST),
        (["a.heic"], SlotPos.N, SlotStatus.ENABLED, 0, None),
        (["a.png", "b.jpg"], SlotPos.N, SlotStatus.ENABLED, 1, None),  # mixed: skip the JPG
        (["a.png", "b.jpg"], SlotPos.NE, SlotStatus.ENABLED, 1, None),
        (["a.jpg", "b.jpeg"], SlotPos.N, SlotStatus.SOURCE, 2, Reason.IS_SOURCE),
        (["a.png", "b.heic"], SlotPos.S, SlotStatus.INCOMPATIBLE, 0, Reason.CONVERT_FIRST),
        (["a.png"], SlotPos.NW, SlotStatus.EMPTY, 0, Reason.NO_PLUGINS),
    ],
)
def test_slot_states(
    catalog: Catalog,
    files: list[str],
    pos: SlotPos,
    status: SlotStatus,
    skips: int,
    reason: Reason | None,
) -> None:
    plan = catalog.plan([f(n) for n in files])
    assert plan.status is PlanStatus.OK
    state = plan.slots[pos]
    assert (state.status, state.skip_count, state.reason) == (status, skips, reason)


def test_plan_always_has_all_eight_slots(catalog: Catalog) -> None:
    for files in ([f("a.png")], [f("a.txt")], []):
        assert set(catalog.plan(files).slots) == set(SlotPos)


# --------------------------------------------------------------------------- whole-drag reasons


@pytest.mark.parametrize(
    ("files", "reason"),
    [
        ([], Reason.NO_FILES),
        ([f("photos", is_dir=True)], Reason.FOLDER),
        ([f("a.png", is_local=False)], Reason.NOT_LOCAL),
        ([f("a.gif", animated=True)], Reason.ANIMATED),
        ([f("notes.txt")], Reason.UNKNOWN_FORMAT),
        ([f("doc.pdf")], Reason.UNSUPPORTED_FORMAT),  # PDF/ICO are outputs only in the MVP
        ([f("icon.ico")], Reason.UNSUPPORTED_FORMAT),
        ([f("a.png"), f("a.gif", animated=True)], Reason.ANIMATED),  # one bad file blocks the drag
        ([f("a.gif", animated=True), f("dir", is_dir=True)], Reason.FOLDER),  # precedence
    ],
)
def test_not_supported(catalog: Catalog, files: list[FileInfo], reason: Reason) -> None:
    plan = catalog.plan(files)
    assert plan.status is PlanStatus.NOT_SUPPORTED
    assert plan.reason is reason
    assert not any(s.enabled for s in plan.slots.values())


def test_static_gif_and_unknown_animation_are_convertible(catalog: Catalog) -> None:
    assert catalog.plan([f("a.gif", animated=False)]).ok
    assert catalog.plan([f("a.gif")]).ok  # animated=None: the worker validates


def test_heic_without_engine_is_not_supported_a6() -> None:
    plan = Catalog.of(BUILTINS, missing_engines=[F.HEIC]).plan([f("a.heic")])
    assert (plan.status, plan.reason) == (PlanStatus.NOT_SUPPORTED, Reason.ENGINE_MISSING)


def test_no_common_format() -> None:
    only_png = Target(
        "x", "X", TargetKind.CONVERT, F.TIFF, frozenset({F.PNG}), "p", True, SlotPos.N
    )
    only_jpg = Target(
        "y", "Y", TargetKind.CONVERT, F.BMP, frozenset({F.JPEG}), "p", True, SlotPos.E
    )
    plan = Catalog.of([only_png, only_jpg]).plan([f("a.png"), f("b.jpg")])
    assert (plan.status, plan.reason) == (PlanStatus.NO_COMMON_FORMAT, Reason.NO_COMMON_FORMAT)


# --------------------------------------------------------------------------- U3: More arc


def test_plugins_go_to_the_more_arc_in_order() -> None:
    plugins = [plugin(f"p{i}") for i in range(MORE_ARC_MAX + 2)]
    plan = Catalog.of([*BUILTINS, *plugins]).plan([f("a.heic")])
    assert plan.slots[SlotPos.NW].status is SlotStatus.ENABLED
    assert [s.target.id for s in plan.more if s.target] == [p.id for p in plugins[:MORE_ARC_MAX]]
    assert plan.more_overflow == 2
    assert all(s.enabled for s in plan.more)


def test_more_arc_items_get_their_own_states() -> None:
    plan = Catalog.of([*BUILTINS, plugin("heicpro")]).plan([f("a.png")])
    assert plan.more[0].status is SlotStatus.INCOMPATIBLE
    assert plan.ok  # the builtin slots still work


def test_third_party_cannot_claim_a_fixed_slot() -> None:
    """Impersonation: id/provider/slot all look builtin, but discovery didn't mark it builtin."""
    fake = plugin("jpeg2", slot=SlotPos.N, provider="builtin", accepts={F.PNG})
    catalog = Catalog.of([*BUILTINS, fake])
    plan = catalog.plan([f("a.png")])
    assert plan.slots[SlotPos.N].target is BUILTINS[0]
    assert catalog.arc_targets == (fake,)


@pytest.mark.parametrize(
    "targets",
    [
        [BUILTINS[0], BUILTINS[0]],  # duplicate id
        [BUILTINS[0], convert("jpeg-b", "JPG2", F.JPEG, SlotPos.N)],  # slot claimed twice
        [convert("bad", "BAD", F.PNG, SlotPos.NW)],  # NW is reserved for More
    ],
)
def test_catalog_validation(targets: list[Target]) -> None:
    with pytest.raises(ValueError, match=r"unique|twice|reserved"):
        Catalog.of(targets)


def test_target_validation() -> None:
    with pytest.raises(ValueError, match="output format"):
        Target("a", "A", TargetKind.CONVERT, None, frozenset(), "p")
    with pytest.raises(ValueError, match="keep the input"):
        Target("a", "A", TargetKind.COMPRESS, F.PNG, frozenset(), "p")


def test_classify(catalog: Catalog) -> None:
    jpeg, compress = BUILTINS[0], BUILTINS[4]
    assert catalog.classify(f("a.png"), jpeg) is Verdict.CONVERT
    assert catalog.classify(f("a.jpg"), jpeg) is Verdict.SKIP
    assert catalog.classify(f("a.pdf"), jpeg) is Verdict.INCOMPATIBLE
    assert catalog.classify(f("a.jpg"), compress) is Verdict.CONVERT  # compress never skips
    assert catalog.classify(f("a.txt"), compress) is Verdict.INCOMPATIBLE
    assert catalog.target("pdf") is BUILTINS[5]
    assert catalog.target("nope") is None


# --------------------------------------------------------------------------- jobs


def _result(status: TaskStatus, error: ErrorCode | None = None, intact: bool = True) -> TaskResult:
    return TaskResult("j", 0, Path("a.png"), status, error=error, source_intact=intact)


@pytest.mark.parametrize(
    ("statuses", "outcome"),
    [
        ([_result(TaskStatus.OK)], JobOutcome.SUCCESS),
        ([_result(TaskStatus.OK), _result(TaskStatus.SKIPPED)], JobOutcome.SUCCESS),
        ([_result(TaskStatus.SKIPPED)], JobOutcome.NOTHING_TO_DO),
        (
            [_result(TaskStatus.OK), _result(TaskStatus.FAILED, ErrorCode.UNREADABLE)],
            JobOutcome.PARTIAL,
        ),
        ([_result(TaskStatus.FAILED, ErrorCode.UNREADABLE)], JobOutcome.FAILED),
        ([_result(TaskStatus.FAILED, ErrorCode.NOT_SMALLER)], JobOutcome.ALREADY_COMPACT),
        (
            [
                _result(TaskStatus.FAILED, ErrorCode.NOT_SMALLER),
                _result(TaskStatus.FAILED, ErrorCode.TIMEOUT),
            ],
            JobOutcome.FAILED,
        ),
        ([_result(TaskStatus.OK), _result(TaskStatus.OK, intact=False)], JobOutcome.SOURCE_CHANGED),
    ],
)
def test_job_outcome(statuses: list[TaskResult], outcome: JobOutcome) -> None:
    assert JobResult("j", BUILTINS[0], tuple(statuses)).outcome is outcome


def test_job_types_survive_pickling() -> None:
    """They cross a spawn boundary (A5)."""
    task = Task("j", 1, Path(r"C:\x\a.png"), BUILTINS[4], Path(r"C:\dl"), {"quality": 80})
    created = CreatedFile(Path(r"C:\x\a (compressed).png"), 10, 123, task.source)
    result = TaskResult("j", 1, task.source, TaskStatus.OK, output=created, duration_ms=1.5)
    job = JobResult("j", task.target, (result,))
    for obj in (task, result, job):
        assert pickle.loads(pickle.dumps(obj)) == obj
    assert job.outputs == (created,)
    assert job.ok_count == 1
    assert job.skipped_count == 0
