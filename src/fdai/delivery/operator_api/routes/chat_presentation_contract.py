"""Bounded value-free presentation planning contract for operator chat."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

PresentationComponent = Literal[
    "summary_band",
    "status_table",
    "data_table",
    "bar_chart",
    "line_chart",
    "coverage_bar",
    "threshold_table",
    "detail_list",
    "callout",
    "evidence_footer",
]
PresentationEmphasis = Literal["primary", "secondary", "supporting"]
PresentationRationale = Literal[
    "summary",
    "attention",
    "comparison",
    "distribution",
    "trend",
    "coverage",
    "limitation",
    "detail",
    "provenance",
]

PRESENTATION_COMPONENTS: Final[tuple[PresentationComponent, ...]] = (
    "summary_band",
    "status_table",
    "data_table",
    "bar_chart",
    "line_chart",
    "coverage_bar",
    "threshold_table",
    "detail_list",
    "callout",
    "evidence_footer",
)
PRESENTATION_EMPHASES: Final[tuple[PresentationEmphasis, ...]] = (
    "primary",
    "secondary",
    "supporting",
)
PRESENTATION_RATIONALES: Final[tuple[PresentationRationale, ...]] = (
    "summary",
    "attention",
    "comparison",
    "distribution",
    "trend",
    "coverage",
    "limitation",
    "detail",
    "provenance",
)
MAX_PRESENTATION_SLOTS: Final = 8


@dataclass(frozen=True, slots=True)
class PresentationSlot:
    """One server-declared evidence slot the model may only arrange."""

    slot_id: str
    role: PresentationRationale
    allowed_components: tuple[PresentationComponent, ...]
    default_component: PresentationComponent
    default_emphasis: PresentationEmphasis
    default_collapsed: bool
    can_collapse: bool
    record_count_bucket: Literal["none", "one", "few", "many"]
    coverage_state: Literal["complete", "limited", "unknown"]

    def __post_init__(self) -> None:
        if not self.slot_id or len(self.slot_id) > 64:
            raise ValueError("presentation slot id must contain 1-64 characters")
        if not self.allowed_components or self.default_component not in self.allowed_components:
            raise ValueError("presentation slot default component must be allowed")
        if len(set(self.allowed_components)) != len(self.allowed_components):
            raise ValueError("presentation slot components must be unique")
        if self.default_collapsed and not self.can_collapse:
            raise ValueError("non-collapsible presentation slot cannot default to collapsed")

    def to_profile_dict(self) -> dict[str, object]:
        return {
            "slot_id": self.slot_id,
            "role": self.role,
            "allowed_components": list(self.allowed_components),
            "can_collapse": self.can_collapse,
            "record_count_bucket": self.record_count_bucket,
            "coverage_state": self.coverage_state,
        }


@dataclass(frozen=True, slots=True)
class PresentationProfile:
    """Value-free result shape supplied to the presentation model."""

    kind: Literal["inventory", "subscription_health"]
    slots: tuple[PresentationSlot, ...]

    def __post_init__(self) -> None:
        if not self.slots or len(self.slots) > MAX_PRESENTATION_SLOTS:
            raise ValueError("presentation profile must contain 1-8 slots")
        slot_ids = [slot.slot_id for slot in self.slots]
        if len(set(slot_ids)) != len(slot_ids):
            raise ValueError("presentation profile slot ids must be unique")

    def to_model_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "slots": [slot.to_profile_dict() for slot in self.slots],
        }


@dataclass(frozen=True, slots=True)
class PresentationPlacement:
    """One validated component placement selected for a declared slot."""

    slot_id: str
    component: PresentationComponent
    emphasis: PresentationEmphasis
    collapsed: bool
    rationale: PresentationRationale

    def to_dict(self) -> dict[str, object]:
        return {
            "slot_id": self.slot_id,
            "component": self.component,
            "emphasis": self.emphasis,
            "collapsed": self.collapsed,
            "rationale": self.rationale,
        }


@dataclass(frozen=True, slots=True)
class PresentationPlan:
    """Validated ordering and component choices without evidence content."""

    placements: tuple[PresentationPlacement, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "layout": "stack",
            "placements": [placement.to_dict() for placement in self.placements],
        }


def presentation_plan_schema(profile: PresentationProfile) -> dict[str, object]:
    """Return an Azure Structured Outputs compatible schema for one profile."""

    return {
        "type": "object",
        "properties": {
            "schema_version": {"type": "integer", "enum": [1]},
            "layout": {"type": "string", "enum": ["stack"]},
            "placements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "slot_id": {
                            "type": "string",
                            "enum": [slot.slot_id for slot in profile.slots],
                        },
                        "component": {
                            "type": "string",
                            "enum": list(PRESENTATION_COMPONENTS),
                        },
                        "emphasis": {
                            "type": "string",
                            "enum": list(PRESENTATION_EMPHASES),
                        },
                        "collapsed": {"type": "boolean"},
                        "rationale": {
                            "type": "string",
                            "enum": list(PRESENTATION_RATIONALES),
                        },
                    },
                    "required": [
                        "slot_id",
                        "component",
                        "emphasis",
                        "collapsed",
                        "rationale",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["schema_version", "layout", "placements"],
        "additionalProperties": False,
    }


def default_presentation_plan(profile: PresentationProfile) -> PresentationPlan:
    """Build the complete deterministic plan used on every planner failure."""

    return PresentationPlan(
        placements=tuple(
            PresentationPlacement(
                slot_id=slot.slot_id,
                component=slot.default_component,
                emphasis=slot.default_emphasis,
                collapsed=slot.default_collapsed,
                rationale=slot.role,
            )
            for slot in profile.slots
        )
    )


def parse_presentation_plan(
    raw: Mapping[str, object],
    profile: PresentationProfile,
) -> PresentationPlan | None:
    """Validate untrusted model output against exact profile pairings and bounds."""

    if set(raw) != {"schema_version", "layout", "placements"}:
        return None
    if raw.get("schema_version") != 1 or raw.get("layout") != "stack":
        return None
    raw_placements = raw.get("placements")
    if not isinstance(raw_placements, Sequence) or isinstance(raw_placements, (str, bytes)):
        return None
    if len(raw_placements) != len(profile.slots):
        return None
    slots_by_id = {slot.slot_id: slot for slot in profile.slots}
    placements: list[PresentationPlacement] = []
    seen: set[str] = set()
    for raw_placement in raw_placements:
        if not isinstance(raw_placement, Mapping):
            return None
        if set(raw_placement) != {
            "slot_id",
            "component",
            "emphasis",
            "collapsed",
            "rationale",
        }:
            return None
        slot_id = raw_placement.get("slot_id")
        component = raw_placement.get("component")
        emphasis = raw_placement.get("emphasis")
        collapsed = raw_placement.get("collapsed")
        rationale = raw_placement.get("rationale")
        if not isinstance(slot_id, str) or slot_id in seen:
            return None
        slot = slots_by_id.get(slot_id)
        if slot is None or component not in slot.allowed_components:
            return None
        if emphasis not in PRESENTATION_EMPHASES or rationale != slot.role:
            return None
        if not isinstance(collapsed, bool) or collapsed and not slot.can_collapse:
            return None
        seen.add(slot_id)
        placements.append(
            PresentationPlacement(
                slot_id=slot_id,
                component=component,
                emphasis=emphasis,
                collapsed=collapsed,
                rationale=rationale,
            )
        )
    if seen != set(slots_by_id):
        return None
    return PresentationPlan(placements=tuple(placements))


def record_count_bucket(count: int) -> Literal["none", "one", "few", "many"]:
    if count <= 0:
        return "none"
    if count == 1:
        return "one"
    if count <= 5:
        return "few"
    return "many"


__all__ = [
    "PresentationPlan",
    "PresentationPlacement",
    "PresentationProfile",
    "PresentationSlot",
    "default_presentation_plan",
    "parse_presentation_plan",
    "presentation_plan_schema",
    "record_count_bucket",
]
