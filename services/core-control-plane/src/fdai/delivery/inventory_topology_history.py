"""Publish promoted inventory observations into append-only topology history."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fdai.core.ontology_platform.inventory_projection import (
    build_inventory_ontology_projection,
)
from fdai.core.ontology_platform.state_transitions import (
    OperationalStateTransition,
    StateTransitionAuthority,
    StateTransitionBatch,
    StateTransitionCoverage,
    StateTransitionLane,
    StateTransitionStore,
)
from fdai.core.ontology_platform.topology_history import (
    TopologyHistoryReader,
    TopologyLinkRevision,
    TopologyObjectRevision,
    TopologyRevisionBatch,
    graph_at,
)
from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.shared.providers.state_evidence import (
    STATE_FACT_METADATA_PROPERTY,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

_CANONICAL_STATES = frozenset(
    {
        "available",
        "deallocated",
        "degraded",
        "failed",
        "online",
        "paused",
        "ready",
        "running",
        "stopped",
        "succeeded",
        "unavailable",
    }
)


@dataclass(frozen=True, slots=True)
class _ObservedState:
    value: str
    metadata: StateFactMetadata


class TopologyHistoryWriter(Protocol):
    """Append one immutable topology revision batch."""

    async def append(
        self,
        batch: TopologyRevisionBatch,
        *,
        ontology_release_digest: str,
        source_receipt_digest: str,
    ) -> None: ...


class InventoryTopologyHistoryPublisher:
    """Derive a retained complete baseline after authoritative promotion."""

    def __init__(
        self,
        *,
        writer: TopologyHistoryWriter,
        ontology_release_digest: str,
        history_reader: TopologyHistoryReader | None = None,
        transition_writer: StateTransitionStore | None = None,
    ) -> None:
        if not _is_digest(ontology_release_digest):
            raise ValueError("ontology_release_digest MUST be a canonical SHA-256 digest")
        self._writer = writer
        self._ontology_release_digest = ontology_release_digest
        self._history_reader = history_reader
        self._transition_writer = transition_writer
        if (history_reader is None) != (transition_writer is None):
            raise ValueError(
                "inventory state-transition history reader and writer MUST be bound together"
            )

    async def __call__(self, observation: PromotedInventoryObservation) -> None:
        await self.publish(observation)

    async def publish(
        self,
        observation: PromotedInventoryObservation,
    ) -> TopologyRevisionBatch | None:
        """Append one complete baseline, or abstain from a truncated observation."""

        if not observation.complete:
            return None
        if observation.recorded_at is None:
            raise ValueError("promoted inventory observation recorded_at MUST be supplied")
        previous_batches = (
            await self._history_reader.read(
                as_of=observation.recorded_at,
                known_at=observation.recorded_at,
            )
            if self._history_reader is not None
            else ()
        )
        projection = build_inventory_ontology_projection(
            generation=observation.generation,
            resources=observation.resources,
            links=observation.links,
            observation_complete=observation.complete,
            relationship_drops=observation.relationship_drops,
        )
        if not projection.complete or not projection.relationship_complete:
            return None

        evidence_ref = f"inventory-generation:{observation.generation}"
        object_revisions = tuple(
            TopologyObjectRevision.upsert(
                record,
                effective_at=observation.recorded_at,
                recorded_at=observation.recorded_at,
                evidence_ref=evidence_ref,
            )
            for record in projection.objects
        )
        object_types = {record.id: record.object_type for record in projection.objects}
        link_revisions = tuple(
            TopologyLinkRevision(
                from_id=record.from_id,
                from_type=object_types[record.from_id],
                link_type=record.link_type,
                to_id=record.to_id,
                to_type=object_types[record.to_id],
                properties_json=_canonical_json(record.properties),
                effective_at=observation.recorded_at,
                recorded_at=observation.recorded_at,
                deleted=False,
                evidence_ref=evidence_ref,
            )
            for record in projection.links
        )
        source_receipt_digest = _source_receipt_digest(
            generation=observation.generation,
            recorded_at=observation.recorded_at.isoformat(),
            ontology_release_digest=self._ontology_release_digest,
            object_revisions=object_revisions,
            link_revisions=link_revisions,
        )
        batch = TopologyRevisionBatch(
            revision_id=f"inventory-topology:{source_receipt_digest.removeprefix('sha256:')}",
            provider_generation_ref=observation.generation,
            effective_at=observation.recorded_at,
            recorded_at=observation.recorded_at,
            complete_snapshot=True,
            object_revisions=object_revisions,
            link_revisions=link_revisions,
            ontology_release_digest=self._ontology_release_digest,
            source_receipt_digest=source_receipt_digest,
        )
        current_generation_retained = any(
            item.provider_generation_ref == observation.generation for item in previous_batches
        )
        if self._transition_writer is not None and not current_generation_retained:
            await self._publish_state_transitions(
                projection.objects,
                observation=observation,
                previous_batches=previous_batches,
            )
        await self._writer.append(
            batch,
            ontology_release_digest=self._ontology_release_digest,
            source_receipt_digest=source_receipt_digest,
        )
        return batch

    async def _publish_state_transitions(
        self,
        objects: tuple[object, ...],
        *,
        observation: PromotedInventoryObservation,
        previous_batches: Sequence[TopologyRevisionBatch],
    ) -> None:
        if self._transition_writer is None or observation.recorded_at is None:
            return
        previous = (
            graph_at(
                previous_batches,
                as_of=observation.recorded_at,
                known_at=observation.recorded_at,
            )
            if previous_batches
            else None
        )
        previous_states = (
            {
                item.id: state
                for item in previous.graph.objects
                if (state := _observed_state(item)) is not None
            }
            if previous is not None
            else {}
        )
        batches: dict[
            datetime,
            tuple[list[OperationalStateTransition], list[StateTransitionCoverage]],
        ] = {}
        for item in objects:
            subject_ref = getattr(item, "id", None)
            subject_type = getattr(item, "object_type", None)
            current = _observed_state(item)
            if not isinstance(subject_ref, str) or subject_type != "Resource" or current is None:
                continue
            transitions, coverage = batches.setdefault(current.metadata.recorded_at, ([], []))
            prior = previous_states.get(subject_ref)
            subject_digest = hashlib.sha256(subject_ref.encode()).hexdigest()
            if prior is not None and prior.value != current.value:
                transitions.append(
                    OperationalStateTransition.create(
                        idempotency_key=(
                            f"inventory-state:{subject_digest}:{current.metadata.source_revision}"
                        ),
                        subject_ref=subject_ref,
                        subject_type="Resource",
                        state_type="resource.operational_state",
                        from_state=prior.value,
                        to_state=current.value,
                        lane=StateTransitionLane.OBSERVED,
                        authority=StateTransitionAuthority.PROVIDER,
                        effective_at=current.metadata.effective_at,
                        evidence_cutoff=current.metadata.evidence_cutoff,
                        recorded_at=current.metadata.recorded_at,
                        source_identity=current.metadata.source_identity,
                        source_revision=current.metadata.source_revision,
                        producer_id="huginn.inventory-state-transition",
                        producer_version="1.0.0",
                        freshness_ceiling_seconds=(current.metadata.freshness_ceiling_seconds),
                        completeness_basis_points=10_000,
                        evidence_refs=current.metadata.evidence_refs,
                    )
                )
            coverage.append(
                StateTransitionCoverage.create(
                    subject_ref=subject_ref,
                    state_type="resource.operational_state",
                    coverage_start_at=(
                        prior.metadata.evidence_cutoff
                        if prior is not None
                        else current.metadata.effective_at
                    ),
                    coverage_end_at=current.metadata.evidence_cutoff,
                    recorded_at=current.metadata.recorded_at,
                    source_identity=current.metadata.source_identity,
                    source_revision=current.metadata.source_revision,
                    watermark=current.metadata.source_revision,
                    evidence_ref=current.metadata.evidence_refs[0],
                    complete=False,
                    limitation=(
                        "initial_state_only" if prior is None else "snapshot_interval_only"
                    ),
                )
            )
        if not batches:
            return
        for recorded_at, (transitions, coverage) in sorted(batches.items()):
            ordered_transitions = tuple(sorted(transitions, key=lambda item: item.idempotency_key))
            ordered_coverage = tuple(
                sorted(coverage, key=lambda item: (item.subject_ref, item.state_type))
            )
            transitions_by_subject = {
                (item.subject_ref, item.state_type): item for item in ordered_transitions
            }
            for start in range(0, len(ordered_coverage), 512):
                coverage_chunk = ordered_coverage[start : start + 512]
                transition_chunk = tuple(
                    transitions_by_subject[key]
                    for item in coverage_chunk
                    if (key := (item.subject_ref, item.state_type)) in transitions_by_subject
                )
                batch = StateTransitionBatch.create(
                    transitions=transition_chunk,
                    coverage=coverage_chunk,
                    recorded_at=recorded_at,
                )
                await self._transition_writer.append(batch)


def _source_receipt_digest(
    *,
    generation: str,
    recorded_at: str,
    ontology_release_digest: str,
    object_revisions: tuple[TopologyObjectRevision, ...],
    link_revisions: tuple[TopologyLinkRevision, ...],
) -> str:
    payload = {
        "generation": generation,
        "recorded_at": recorded_at,
        "ontology_release_digest": ontology_release_digest,
        "objects": [
            {
                "id": item.object_id,
                "type": item.object_type,
                "properties": json.loads(item.properties_json),
            }
            for item in object_revisions
        ],
        "links": [
            {
                "from_id": item.from_id,
                "from_type": item.from_type,
                "link_type": item.link_type,
                "to_id": item.to_id,
                "to_type": item.to_type,
                "properties": json.loads(item.properties_json),
            }
            for item in link_revisions
        ],
    }
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _is_digest(value: str) -> bool:
    return (
        len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _observed_state(record: object) -> _ObservedState | None:
    properties = getattr(record, "properties", None)
    provider = properties.get("properties") if isinstance(properties, dict) else None
    state = provider.get("state") if isinstance(provider, dict) else None
    metadata_value = (
        provider.get(STATE_FACT_METADATA_PROPERTY) if isinstance(provider, dict) else None
    )
    if not isinstance(state, str) or not state.strip() or not isinstance(metadata_value, dict):
        return None
    try:
        metadata = StateFactMetadata.from_mapping(metadata_value)
    except (TypeError, ValueError):
        return None
    if (
        metadata.lane is not StateFactLane.OBSERVED
        or metadata.authority is not StateFactAuthority.PROVIDER
        or metadata.completeness < 1.0
        or metadata.synthetic
        or metadata.conflicts
    ):
        return None
    matched = _CANONICAL_STATES.intersection(re.findall(r"[a-z0-9]+", state.casefold()))
    if len(matched) != 1:
        return None
    return _ObservedState(value=next(iter(matched)), metadata=metadata)


__all__ = ["InventoryTopologyHistoryPublisher", "TopologyHistoryWriter"]
