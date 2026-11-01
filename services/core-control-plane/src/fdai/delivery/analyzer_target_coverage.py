"""Per-resource-type candidate, selection, and hold accounting for analyzer targets."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from fdai.delivery.analyzer_tick import AnalyzerTarget
from fdai.shared.providers.ontology_instance import OntologyObjectRecord

HOLD_DUPLICATE_CANDIDATE = "duplicate_candidate"
HOLD_NOT_SELECTED = "not_selected"
HOLD_SELECTION_LIMIT = "selection_limit"


@dataclass(frozen=True, slots=True)
class AnalyzerResourceTypeResolution:
    """Candidate, selected, and held counts for one canonical resource type."""

    resource_type: str
    candidate_count: int
    selected_count: int
    held_count: int
    held_reason_counts: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        if not self.resource_type.strip() or len(self.resource_type) > 128:
            raise ValueError("analyzer coverage resource_type MUST be bounded text")
        if (
            type(self.candidate_count) is not int
            or type(self.selected_count) is not int
            or type(self.held_count) is not int
            or min(self.candidate_count, self.selected_count, self.held_count) < 0
        ):
            raise ValueError("analyzer coverage counts MUST be non-negative")
        if self.candidate_count != self.selected_count + self.held_count:
            raise ValueError("analyzer coverage candidate totals MUST reconcile")
        if (
            sum(count for _reason, count in self.held_reason_counts if type(count) is int)
            != self.held_count
            or len({reason for reason, _count in self.held_reason_counts})
            != len(self.held_reason_counts)
            or any(
                not reason.strip() or len(reason) > 128 or type(count) is not int or count <= 0
                for reason, count in self.held_reason_counts
            )
        ):
            raise ValueError("analyzer coverage held reasons MUST reconcile")

    def to_dict(self) -> dict[str, object]:
        return {
            "resource_type": self.resource_type,
            "candidate_count": self.candidate_count,
            "selected_count": self.selected_count,
            "held_count": self.held_count,
            "held_reason_counts": dict(self.held_reason_counts),
        }


def configured_resource_type_resolution(
    targets: Sequence[AnalyzerTarget],
) -> tuple[AnalyzerResourceTypeResolution, ...]:
    if any(target.resource_type is None for target in targets):
        return ()
    selected = Counter(str(target.resource_type) for target in targets)
    return tuple(
        AnalyzerResourceTypeResolution(
            resource_type=resource_type,
            candidate_count=count,
            selected_count=count,
            held_count=0,
        )
        for resource_type, count in sorted(selected.items())
    )


def inventory_resource_type_resolution(
    *,
    records: Sequence[OntologyObjectRecord],
    candidate_hold_reasons: Sequence[str | None],
    withheld_refs: set[str],
    targets: Sequence[AnalyzerTarget],
    analyzer_kinds: Mapping[str, str],
) -> tuple[tuple[AnalyzerResourceTypeResolution, ...], str | None]:
    if any(target.resource_type is None for target in targets):
        return (), "selected_resource_type_absent"

    if len(candidate_hold_reasons) != len(records):
        return (), "candidate_hold_reason_count_mismatch"

    candidates: list[tuple[str | None, str, str | None]] = []
    candidate_refs: set[str] = set()
    candidate_types_by_ref: dict[str, set[str]] = defaultdict(set)
    for record, hold_reason in zip(records, candidate_hold_reasons, strict=True):
        resource_ref = record.properties.get("id")
        resource_type = record.properties.get("type")
        normalized_ref = (
            resource_ref.strip() if isinstance(resource_ref, str) and resource_ref.strip() else None
        )
        normalized_type = (
            resource_type.strip()
            if isinstance(resource_type, str) and resource_type.strip() in analyzer_kinds
            else "unclassified"
        )
        candidates.append((normalized_ref, normalized_type, hold_reason))
        if normalized_ref is not None:
            candidate_refs.add(normalized_ref)
            candidate_types_by_ref[normalized_ref].add(normalized_type)

    if any(len(resource_types) > 1 for resource_types in candidate_types_by_ref.values()):
        return (), "candidate_resource_type_conflict"

    for target in targets:
        if target.resource_ref not in candidate_refs:
            candidates.append((target.resource_ref, str(target.resource_type), None))

    selected_refs = {target.resource_ref for target in targets}
    matched_selected: set[str] = set()
    candidate_counts: Counter[str] = Counter()
    selected_counts: Counter[str] = Counter(str(target.resource_type) for target in targets)
    held_counts: Counter[str] = Counter()
    held_reasons: dict[str, Counter[str]] = defaultdict(Counter)
    for resource_ref, resource_type, hold_reason in candidates:
        candidate_counts[resource_type] += 1
        if (
            resource_ref is not None
            and resource_ref in selected_refs
            and resource_ref not in matched_selected
        ):
            matched_selected.add(resource_ref)
        else:
            held_counts[resource_type] += 1
            if hold_reason is not None:
                reason = hold_reason
            elif resource_ref in withheld_refs:
                reason = HOLD_SELECTION_LIMIT
            elif resource_ref in matched_selected:
                reason = HOLD_DUPLICATE_CANDIDATE
            else:
                reason = HOLD_NOT_SELECTED
            held_reasons[resource_type][reason] += 1

    if matched_selected != selected_refs:
        return (), "selected_resource_identity_absent"
    resource_types = set(candidate_counts) | set(selected_counts) | set(held_counts)
    try:
        resolution = tuple(
            AnalyzerResourceTypeResolution(
                resource_type=resource_type,
                candidate_count=candidate_counts[resource_type],
                selected_count=selected_counts[resource_type],
                held_count=held_counts[resource_type],
                held_reason_counts=tuple(sorted(held_reasons[resource_type].items())),
            )
            for resource_type in sorted(resource_types)
        )
    except ValueError:
        return (), "resource_type_totals_unreconciled"
    return resolution, None
