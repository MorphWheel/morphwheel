"""Wheel targets, and the plan for one drag: which slots are enabled, disabled, or skip files.

Rules (approved):

- **U2 — 8 fixed slots.** A slot keeps its position whether or not it applies to the dragged
  files. A slot is *disabled* when every dragged file is already in its format (``SOURCE``), or
  when any file can't be converted to it (``INCOMPATIBLE``). In a mixed drag, files already in the
  target format are *skipped*, and the slot stays enabled.
- **U3 — the More arc.** NW is reserved for "More". Targets without a slot, i.e. all plugin targets,
  go to an outer arc in the given order. At most ``MORE_ARC_MAX`` items are shown.
- **Builtin privilege comes from discovery.** ``Target.is_builtin`` is set by plugin discovery
  from the directory a manifest was found in (phase-4 §4.5). It is never inferred from an id or a
  provider name. Only builtin targets may claim a fixed slot; a slot on any other target is
  ignored.
- **Animated inputs, and formats whose engine isn't installed (HEIC, A6), make the drag
  unsupported** (MVP).

Reasons are keys (``Reason``), not sentences. The UI translates them for the hub.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from morphwheel.core.formats import FileInfo, FormatId


class SlotPos(StrEnum):
    """Compass positions, clockwise from north (phase-3 §2.2)."""

    N = "n"
    NE = "ne"
    E = "e"
    SE = "se"
    S = "s"
    SW = "sw"
    W = "w"
    NW = "nw"


SLOT_ORDER: tuple[SlotPos, ...] = tuple(SlotPos)
MORE_SLOT = SlotPos.NW
MORE_ARC_MAX = 6


class TargetKind(StrEnum):
    CONVERT = "convert"
    COMPRESS = "compress"  # same format in, same format out, smaller


@dataclass(frozen=True)
class Target:
    id: str  # unique: "jpeg", "compress", "com.jdoe.heicpro:tiff"
    label: str  # shown on the wheel: "JPG"
    kind: TargetKind
    output_format: FormatId | None  # None for COMPRESS (keeps the input format)
    accepts: frozenset[FormatId]
    provider: str  # id of the plugin that provides it
    is_builtin: bool = False  # set by discovery from the manifest's location, never by the manifest
    slot: SlotPos | None = None  # honored only when is_builtin

    def __post_init__(self) -> None:
        # Manifests (S3) deliver plain strings, and the core compares enums with ``is``: coerce
        # first, which also rejects unknown values (ValueError).
        coerce = object.__setattr__
        coerce(self, "kind", TargetKind(self.kind))
        if self.output_format is not None:
            coerce(self, "output_format", FormatId(self.output_format))
        coerce(self, "accepts", frozenset(FormatId(f) for f in self.accepts))
        if self.slot is not None:
            coerce(self, "slot", SlotPos(self.slot))
        if self.kind is TargetKind.CONVERT and self.output_format is None:
            raise ValueError(f"convert target {self.id!r} needs an output format")
        if self.kind is TargetKind.COMPRESS and self.output_format is not None:
            raise ValueError(f"compress target {self.id!r} must keep the input format")


class Verdict(StrEnum):
    CONVERT = "convert"
    SKIP = "skip"  # already in the target format
    INCOMPATIBLE = "incompatible"


class SlotStatus(StrEnum):
    ENABLED = "enabled"
    SOURCE = "source"  # every file is already in this format
    INCOMPATIBLE = "incompatible"
    EMPTY = "empty"  # no target here (or More with no plugins)


class PlanStatus(StrEnum):
    OK = "ok"
    NOT_SUPPORTED = "not_supported"
    NO_COMMON_FORMAT = "no_common_format"


class Reason(StrEnum):
    # Whole-drag reasons, in precedence order (the first one that applies is shown).
    NO_FILES = "no_files"
    FOLDER = "folder"
    NOT_LOCAL = "not_local"
    ENGINE_MISSING = "engine_missing"
    ANIMATED = "animated"
    UNKNOWN_FORMAT = "unknown_format"
    UNSUPPORTED_FORMAT = "unsupported_format"  # known, but no target converts it (e.g. PDF input)
    NO_COMMON_FORMAT = "no_common_format"
    # Per-slot reasons, shown in the hub while hovering a disabled slot.
    IS_SOURCE = "is_source"
    CONVERT_FIRST = "convert_first"  # Compress on a format it can't re-encode (e.g. HEIC)
    NOT_FOR_THESE_FILES = "not_for_these_files"
    NO_PLUGINS = "no_plugins"


_DRAG_REASON_ORDER = (
    Reason.FOLDER,
    Reason.NOT_LOCAL,
    Reason.ENGINE_MISSING,
    Reason.ANIMATED,
    Reason.UNKNOWN_FORMAT,
    Reason.UNSUPPORTED_FORMAT,
)


@dataclass(frozen=True)
class SlotState:
    status: SlotStatus
    target: Target | None = None
    skip_count: int = 0
    reason: Reason | None = None

    @property
    def enabled(self) -> bool:
        return self.status is SlotStatus.ENABLED


@dataclass(frozen=True)
class WheelPlan:
    status: PlanStatus
    file_count: int
    slots: Mapping[SlotPos, SlotState]  # always all 8 positions
    more: tuple[SlotState, ...] = ()
    more_overflow: int = 0  # plugin targets that didn't fit in the arc
    reason: Reason | None = None

    @property
    def ok(self) -> bool:
        return self.status is PlanStatus.OK


@dataclass
class Catalog:
    """The targets on offer, validated once. ``plan()`` is called per drag."""

    targets: Sequence[Target]
    missing_engines: frozenset[FormatId] = frozenset()
    _slotted: dict[SlotPos, Target] = field(init=False, repr=False)
    _arc: tuple[Target, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        ids = [t.id for t in self.targets]
        if len(ids) != len(set(ids)):
            raise ValueError("target ids must be unique")
        slotted: dict[SlotPos, Target] = {}
        arc: list[Target] = []
        for target in self.targets:
            if target.is_builtin and target.slot is not None:
                if target.slot is MORE_SLOT:
                    raise ValueError(f"{target.id!r}: the NW slot is reserved for More")
                if target.slot in slotted:
                    raise ValueError(f"slot {target.slot} claimed twice")
                slotted[target.slot] = target
            else:
                arc.append(target)  # third-party slots are ignored on purpose
        self._slotted = slotted
        self._arc = tuple(arc)

    @classmethod
    def of(cls, targets: Iterable[Target], *, missing_engines: Iterable[FormatId] = ()) -> Catalog:
        return cls(tuple(targets), frozenset(missing_engines))

    @property
    def arc_targets(self) -> tuple[Target, ...]:
        return self._arc

    def target(self, target_id: str) -> Target | None:
        return next((t for t in self.targets if t.id == target_id), None)

    # ----------------------------------------------------------------- per file
    @staticmethod
    def classify(info: FileInfo, target: Target) -> Verdict:
        if info.format is None:
            return Verdict.INCOMPATIBLE
        if target.kind is TargetKind.CONVERT and info.format is target.output_format:
            return Verdict.SKIP
        return Verdict.CONVERT if info.format in target.accepts else Verdict.INCOMPATIBLE

    def file_problem(self, info: FileInfo) -> Reason | None:
        """Why this file can't take part in any conversion, or ``None`` if it can."""
        if info.is_dir:
            return Reason.FOLDER
        if not info.is_local:
            return Reason.NOT_LOCAL
        if info.format is None:
            return Reason.UNKNOWN_FORMAT
        if info.format in self.missing_engines:
            return Reason.ENGINE_MISSING
        if info.animated:
            return Reason.ANIMATED
        if not any(self.classify(info, t) is Verdict.CONVERT for t in self.targets):
            return Reason.UNSUPPORTED_FORMAT
        return None

    # ----------------------------------------------------------------- per drag
    def plan(self, files: Sequence[FileInfo]) -> WheelPlan:
        if not files:
            return self._blocked(0, Reason.NO_FILES)
        problems = {p for p in (self.file_problem(f) for f in files) if p is not None}
        if problems:
            reason = next(r for r in _DRAG_REASON_ORDER if r in problems)
            return self._blocked(len(files), reason)

        slots = {pos: self._slot_state(pos, files) for pos in SLOT_ORDER}
        more = tuple(self._state(t, files) for t in self._arc[:MORE_ARC_MAX])
        usable = any(s.enabled for p, s in slots.items() if p is not MORE_SLOT) or any(
            s.enabled for s in more
        )
        return WheelPlan(
            status=PlanStatus.OK if usable else PlanStatus.NO_COMMON_FORMAT,
            file_count=len(files),
            slots=MappingProxyType(slots),
            more=more,
            more_overflow=max(0, len(self._arc) - MORE_ARC_MAX),
            reason=None if usable else Reason.NO_COMMON_FORMAT,
        )

    def _slot_state(self, pos: SlotPos, files: Sequence[FileInfo]) -> SlotState:
        if pos is MORE_SLOT:
            if not self._arc:
                return SlotState(SlotStatus.EMPTY, reason=Reason.NO_PLUGINS)
            return SlotState(SlotStatus.ENABLED)
        target = self._slotted.get(pos)
        return SlotState(SlotStatus.EMPTY) if target is None else self._state(target, files)

    def _state(self, target: Target, files: Sequence[FileInfo]) -> SlotState:
        verdicts = [self.classify(f, target) for f in files]
        if Verdict.INCOMPATIBLE in verdicts:
            reason = (
                Reason.CONVERT_FIRST
                if target.kind is TargetKind.COMPRESS
                else Reason.NOT_FOR_THESE_FILES
            )
            return SlotState(SlotStatus.INCOMPATIBLE, target, reason=reason)
        skips = verdicts.count(Verdict.SKIP)
        if skips == len(verdicts):
            return SlotState(SlotStatus.SOURCE, target, skip_count=skips, reason=Reason.IS_SOURCE)
        return SlotState(SlotStatus.ENABLED, target, skip_count=skips)

    def _blocked(self, count: int, reason: Reason) -> WheelPlan:
        """A plan where nothing can be selected: every slot shown dimmed (phase-3 §3.1)."""
        slots = {
            pos: SlotState(
                SlotStatus.INCOMPATIBLE if pos in self._slotted else SlotStatus.EMPTY,
                self._slotted.get(pos),
                reason=reason,
            )
            for pos in SLOT_ORDER
        }
        return WheelPlan(
            status=PlanStatus.NOT_SUPPORTED,
            file_count=count,
            slots=MappingProxyType(slots),
            reason=reason,
        )
