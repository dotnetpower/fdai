"""Reconstruct an active inventory projection from its immutable journal."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from fdai.core.ontology_platform.inventory_projection import (
    DEFAULT_OBSERVED_STATE_FRESHNESS_CEILING_SECONDS,
)
from fdai.delivery.inventory_sync import (
    PromotedInventoryObservation,
    compute_relationship_coverage,
)
from fdai.shared.providers.inventory import (
    LinkRecord,
    RelationshipDrop,
    RelationshipDropReason,
    RelationshipUnavailableReason,
    ResourceRecord,
)
from fdai.shared.providers.inventory_observation import (
    InventoryObservationSubjectKind,
    NormalizedInventoryObservation,
)
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    STATE_FACT_METADATA_PROPERTY,
    LinkObservationMetadata,
    state_fact_metadata_values,
)

MAX_ACTIVE_PROJECTION_OBSERVATIONS: Final[int] = 250_000


@dataclass(frozen=True, slots=True)
class InventoryProjectionReplayInput:
    """Exact active-snapshot observation and its durable journal fence."""

    observation: PromotedInventoryObservation
    journal_high_watermark: int
    projection_high_watermark: int
    freshness_ceiling_seconds: int


def build_projection_replay_observation(
    *,
    generation: str,
    recorded_at: datetime,
    metadata: Mapping[str, Any],
    prior_manifest: Mapping[str, Any],
    records: Sequence[NormalizedInventoryObservation],
) -> PromotedInventoryObservation:
    if metadata.get("projection_complete") is not True:
        raise ValueError("active inventory snapshot is incomplete for projection replay")
    resources: list[ResourceRecord] = []
    links: list[LinkRecord] = []
    stateful_ids = _projection_stateful_object_ids(prior_manifest)
    for record in records:
        if record.subject_kind is InventoryObservationSubjectKind.OBJECT:
            resources.append(
                ResourceRecord(
                    resource_id=record.subject_ref,
                    type=record.subject_type,
                    props=record.properties,
                    provider_ref=record.provider_ref,
                    last_seen=(
                        record.observed_at.astimezone(UTC).isoformat()
                        if record.subject_ref in stateful_ids
                        else None
                    ),
                )
            )
            continue
        properties = dict(record.properties)
        raw_observation = properties.pop(LINK_OBSERVATION_METADATA_PROPERTY, None)
        properties.pop("provider_relationship_evidence", None)
        if not isinstance(raw_observation, Mapping):
            raise ValueError("inventory relationship replay has no observation metadata")
        links.append(
            LinkRecord(
                from_id=_required(record.from_id, "relationship from_id"),
                from_type=_required(record.from_type, "relationship from_type"),
                link_type=_required(record.link_type, "relationship link_type"),
                to_id=_required(record.to_id, "relationship to_id"),
                to_type=_required(record.to_type, "relationship to_type"),
                link_props=properties,
                observation_metadata=LinkObservationMetadata.from_mapping(raw_observation),
            )
        )
    observation = PromotedInventoryObservation(
        generation=generation,
        resources=tuple(resources),
        links=tuple(links),
        complete=True,
        relationship_drops=projection_replay_drops(metadata, prior_manifest),
        recorded_at=recorded_at,
        state_base_generation=(
            str(metadata["state_base_generation"])
            if metadata.get("state_base_generation") is not None
            else None
        ),
        state_base_generation_checked="state_base_generation" in metadata,
    )
    expected_coverage = _mapping(metadata.get("relationship_coverage"))
    if dict(compute_relationship_coverage(observation).to_metadata()) != dict(expected_coverage):
        raise ValueError("inventory projection replay relationship coverage changed")
    return observation


def projection_replay_drops(
    metadata: Mapping[str, Any],
    prior_manifest: Mapping[str, Any],
) -> tuple[RelationshipDrop, ...]:
    raw = metadata.get("relationship_drop_classifications", ())
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ValueError("inventory projection replay drop classifications are invalid")
    drops: list[RelationshipDrop] = []
    for value in raw:
        if not isinstance(value, Mapping):
            raise ValueError("inventory projection replay drop classification is invalid")
        count = value.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise ValueError("inventory projection replay drop count is invalid")
        drop = RelationshipDrop(
            reason=RelationshipDropReason(str(value.get("reason", ""))),
            mapping_id=_replay_optional(value.get("mapping_id"), "unattributed"),
            source_property_path=_replay_optional(
                value.get("source_property_path"), "unattributed"
            ),
            source_provider_type=_replay_optional(
                value.get("source_provider_type"), "unattributed"
            ),
            target_provider_type=_replay_optional(value.get("target_provider_type"), "unresolved"),
            unavailable_reason=(
                None
                if value.get("unavailable_reason") == "unclassified"
                else RelationshipUnavailableReason(str(value.get("unavailable_reason", "")))
            ),
        )
        if len(drops) + count > MAX_ACTIVE_PROJECTION_OBSERVATIONS:
            raise ValueError("inventory projection replay drop count exceeds its bound")
        drops.extend(drop for _ in range(count))
    coverage = _mapping(metadata.get("relationship_coverage"))
    expected_reviewed = _coverage_count(coverage, "reviewed_unavailable")
    expected_unclassified = _coverage_count(coverage, "unclassified")
    current_reviewed = sum(drop.classified_unavailable for drop in drops)
    current_unclassified = len(drops) - current_reviewed
    if current_reviewed > expected_reviewed or current_unclassified > expected_unclassified:
        raise ValueError("inventory projection replay drop classifications exceed coverage")
    prior_reasons = prior_manifest.get("dropped_reasons")
    if not isinstance(prior_reasons, list):
        raise ValueError("inventory projection replay manifest drop reasons are invalid")
    represented = {drop.reason for drop in drops}
    missing_reviewed = expected_reviewed - current_reviewed
    missing_unclassified = expected_unclassified - current_unclassified
    for value in prior_reasons:
        try:
            reason = RelationshipDropReason(str(value))
        except ValueError:
            continue
        if reason in represented:
            continue
        reviewed = _classified_replay_drop(reason)
        if reviewed is not None and missing_reviewed:
            drops.append(reviewed)
            missing_reviewed -= 1
            represented.add(reason)
        elif missing_unclassified:
            drops.append(RelationshipDrop(reason=reason))
            missing_unclassified -= 1
            represented.add(reason)
    unclassified_template = next((item for item in drops if not item.classified_unavailable), None)
    if missing_unclassified and unclassified_template is None:
        raise ValueError("inventory projection replay lacks unclassified drop evidence")
    if unclassified_template is not None:
        drops.extend(unclassified_template for _ in range(missing_unclassified))
    reviewed_template = next((item for item in drops if item.classified_unavailable), None)
    if missing_reviewed and reviewed_template is None:
        raise ValueError("inventory projection replay lacks reviewed drop evidence")
    if reviewed_template is not None:
        drops.extend(reviewed_template for _ in range(missing_reviewed))
    return tuple(drops)


def required_replay_watermark(manifest: Mapping[str, Any], field: str) -> int:
    value = manifest.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"inventory projection replay manifest {field} is invalid")
    return value


def projection_freshness_ceiling(manifest: Mapping[str, Any]) -> int:
    object_content = manifest.get("object_content")
    if not isinstance(object_content, list) or not object_content:
        raise ValueError("inventory projection replay manifest object content is unavailable")
    ceilings: set[int] = set()
    for item in object_content:
        if not isinstance(item, Mapping):
            raise ValueError("inventory projection replay manifest object is invalid")
        properties = item.get("properties")
        if not isinstance(properties, Mapping):
            raise ValueError("inventory projection replay manifest properties are invalid")
        provider_properties = properties.get("properties")
        if not isinstance(provider_properties, Mapping):
            raise ValueError("inventory projection replay provider properties are invalid")
        state_fact = provider_properties.get(STATE_FACT_METADATA_PROPERTY)
        if state_fact is None:
            continue
        if not isinstance(state_fact, Mapping):
            raise ValueError("inventory projection replay state fact is invalid")
        ceilings.update(
            fact.freshness_ceiling_seconds for fact in state_fact_metadata_values(state_fact)
        )
    if not ceilings:
        return DEFAULT_OBSERVED_STATE_FRESHNESS_CEILING_SECONDS
    if len(ceilings) != 1:
        raise ValueError("inventory projection replay freshness ceiling is inconsistent")
    return next(iter(ceilings))


def _classified_replay_drop(reason: RelationshipDropReason) -> RelationshipDrop | None:
    unavailable = {
        RelationshipDropReason.MISSING_SOURCE_ENDPOINT: (
            RelationshipUnavailableReason.SOURCE_OUTSIDE_ACTIVE_GENERATION
        ),
        RelationshipDropReason.MISSING_TARGET_ENDPOINT: (
            RelationshipUnavailableReason.TARGET_OUTSIDE_ACTIVE_GENERATION
        ),
        RelationshipDropReason.TARGET_TYPE_MISMATCH: (
            RelationshipUnavailableReason.TARGET_PROVIDER_TYPE_UNMODELED
        ),
        RelationshipDropReason.UNRESOLVED_REFERENCE: (
            RelationshipUnavailableReason.REFERENCE_NOT_OBSERVED
        ),
    }.get(reason)
    return (
        None
        if unavailable is None
        else RelationshipDrop(reason=reason, unavailable_reason=unavailable)
    )


def _projection_stateful_object_ids(manifest: Mapping[str, Any]) -> frozenset[str]:
    object_content = manifest.get("object_content")
    if not isinstance(object_content, list):
        raise ValueError("inventory projection replay manifest object content is unavailable")
    identifiers: set[str] = set()
    for item in object_content:
        if not isinstance(item, Mapping) or not isinstance(item.get("id"), str):
            raise ValueError("inventory projection replay manifest object identity is invalid")
        properties = item.get("properties")
        if not isinstance(properties, Mapping):
            raise ValueError("inventory projection replay manifest properties are invalid")
        provider_properties = properties.get("properties")
        if not isinstance(provider_properties, Mapping):
            raise ValueError("inventory projection replay provider properties are invalid")
        if STATE_FACT_METADATA_PROPERTY in provider_properties:
            identifiers.add(str(item["id"]))
    return frozenset(identifiers)


def _coverage_count(coverage: Mapping[str, Any], field: str) -> int:
    value = coverage.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"inventory projection replay coverage {field} is invalid")
    return value


def _replay_optional(value: object, placeholder: str) -> str | None:
    if not isinstance(value, str) or not value:
        raise ValueError("inventory projection replay classification text is invalid")
    return None if value == placeholder else value


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("inventory projection replay value is not an object")
    return value


def _required(value: str | None, field: str) -> str:
    if value is None:
        raise ValueError(f"inventory projection replay is missing {field}")
    return value


__all__ = [
    "MAX_ACTIVE_PROJECTION_OBSERVATIONS",
    "InventoryProjectionReplayInput",
    "build_projection_replay_observation",
    "projection_freshness_ceiling",
    "projection_replay_drops",
    "required_replay_watermark",
]
