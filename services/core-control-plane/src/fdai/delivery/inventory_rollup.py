"""Adapt immutable inventory observations to semantic retention inputs."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal

from fdai.core.ontology_platform.archive_manifest import ArchiveSourcePartition
from fdai.core.ontology_platform.semantic_rollup import (
    EvidenceHealth,
    RelationshipChange,
    RollupFactKind,
    RollupObservation,
    SemanticRollup,
    SemanticRollupPolicy,
)
from fdai.delivery.inventory_convergence import (
    InventoryMutationKind,
    InventoryObservedRevision,
)


def inventory_revision_to_rollup_observation(
    revision: InventoryObservedRevision,
    policy: SemanticRollupPolicy,
    *,
    generation_ref: str,
    interval_start: datetime,
    interval_end: datetime,
    complete: bool,
    conflict_count: int,
) -> RollupObservation:
    """Bind collection provenance explicitly without changing cursor or promotion behavior."""

    _canonical_digest(revision.payload_digest, "inventory payload_digest")
    value: Decimal | str | RelationshipChange | EvidenceHealth
    if policy.fact_kind is RollupFactKind.RELATIONSHIP_CHANGE:
        value = (
            RelationshipChange.ADDED
            if revision.mutation is InventoryMutationKind.UPSERT
            else RelationshipChange.REMOVED
        )
    elif policy.fact_kind is RollupFactKind.CATEGORICAL_STATE:
        value = revision.mutation.value
    elif policy.fact_kind is RollupFactKind.EVIDENCE_HEALTH:
        value = (
            EvidenceHealth.CONFLICTING
            if conflict_count
            else EvidenceHealth.HEALTHY
            if complete
            else EvidenceHealth.INCOMPLETE
        )
    else:
        raise ValueError("inventory revisions cannot supply numeric rollup facts")
    identity = {
        "logical_key": revision.logical_key,
        "mutation": revision.mutation.value,
        "source_id": revision.source_id,
        "payload_digest": revision.payload_digest,
        "observed_at": revision.observed_at.astimezone(UTC).isoformat(),
        "ontology_release_digest": policy.ontology_release_digest,
        "semantic_id": policy.semantic_id,
    }
    return RollupObservation(
        observation_id=_sha256(identity),
        semantic_id=policy.semantic_id,
        fact_kind=policy.fact_kind,
        source_id=revision.source_id,
        source_revision=revision.source_revision,
        source_partition_digest=revision.payload_digest,
        generation_ref=generation_ref,
        ontology_release_digest=policy.ontology_release_digest,
        interval_start=interval_start,
        interval_end=interval_end,
        effective_at=revision.observed_at,
        event_at=revision.observed_at,
        recorded_at=revision.recorded_at,
        value=value,
        complete=complete,
        conflict_count=conflict_count,
    )


def semantic_rollup_to_archive_partition(
    rollup: SemanticRollup,
    *,
    partition_id: str,
    schema_version: str,
) -> ArchiveSourcePartition:
    """Preserve rollup completeness and conflict state in archive coverage."""

    relationship_count = (
        rollup.observation_count if rollup.fact_kind is RollupFactKind.RELATIONSHIP_CHANGE else 0
    )
    object_count = 0 if relationship_count else rollup.observation_count
    return ArchiveSourcePartition(
        partition_id=partition_id,
        content_digest=rollup.digest,
        interval_start=rollup.window_start,
        interval_end=rollup.window_end,
        object_count=object_count,
        relationship_count=relationship_count,
        schema_version=schema_version,
        ontology_release_digest=rollup.ontology_release_digest,
        complete=rollup.complete,
        conflict_count=rollup.conflict_count,
    )


def _canonical_digest(value: str, name: str) -> None:
    if (
        len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ValueError(f"{name} MUST be a canonical SHA-256 digest")


def _sha256(value: object) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
    )


__all__ = [
    "inventory_revision_to_rollup_observation",
    "semantic_rollup_to_archive_partition",
]
