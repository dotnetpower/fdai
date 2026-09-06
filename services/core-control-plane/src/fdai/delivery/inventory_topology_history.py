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
from fdai.shared.providers.ontology_instance import OntologyObjectRecord
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
        "unknown",
    }
)
_STATE_PATHS = {
    "resource.operational_state": "state",
    "resource.availability_state": "availabilityState",
}


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


class InventoryCurrentStateReader(Protocol):
    """Read the exact prior inventory-owned ontology generation."""

    async def read_inventory_state_base(
        self,
        *,
        object_ids: tuple[str, ...],
        expected_generation: str | None,
    ) -> tuple[OntologyObjectRecord, ...]: ...


class InventoryTopologyHistoryPublisher:
    """Derive a retained complete baseline after authoritative promotion."""

    def __init__(
        self,
        *,
        writer: TopologyHistoryWriter,
        ontology_release_digest: str,
        history_reader: TopologyHistoryReader | None = None,
        transition_writer: StateTransitionStore | None = None,
        current_state_reader: InventoryCurrentStateReader | None = None,
    ) -> None:
        if not _is_digest(ontology_release_digest):
            raise ValueError("ontology_release_digest MUST be a canonical SHA-256 digest")
        self._writer = writer
        self._ontology_release_digest = ontology_release_digest
        self._history_reader = history_reader
        self._transition_writer = transition_writer
        self._current_state_reader = current_state_reader
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
        current_generation_retained = any(
            item.provider_generation_ref == observation.generation for item in previous_batches
        )
        if self._transition_writer is not None and not current_generation_retained:
            previous_objects = await self._previous_state_objects(
                projection.objects,
                observation=observation,
                previous_batches=previous_batches,
            )
            await self._publish_state_transitions(
                projection.objects,
                observation=observation,
                previous_objects=previous_objects,
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
        await self._writer.append(
            batch,
            ontology_release_digest=self._ontology_release_digest,
            source_receipt_digest=source_receipt_digest,
        )
        return batch

    async def _publish_state_transitions(
        self,
        objects: tuple[OntologyObjectRecord, ...],
        *,
        observation: PromotedInventoryObservation,
        previous_objects: Sequence[OntologyObjectRecord],
    ) -> None:
        if self._transition_writer is None or observation.recorded_at is None:
            return
        previous_states: dict[tuple[str, str], _ObservedState] = {}
        for item in previous_objects:
            item_id = item.id
            for state_type, state in _observed_states(item).items():
                previous_states[(item_id, state_type)] = state
        batches: dict[
            datetime,
            tuple[list[OperationalStateTransition], list[StateTransitionCoverage]],
        ] = {}
        for item in objects:
            subject_ref = item.id
            if item.object_type != "Resource":
                continue
            for state_type, current in _observed_states(item).items():
                prior = previous_states.get((subject_ref, state_type))
                if prior is not None and prior == current:
                    continue
                if prior is not None and (
                    current.metadata.effective_at < prior.metadata.effective_at
                    or (
                        current.metadata.effective_at == prior.metadata.effective_at
                        and current.value != prior.value
                    )
                ):
                    continue
                transitions, coverage = batches.setdefault(current.metadata.recorded_at, ([], []))
                subject_digest = hashlib.sha256(subject_ref.encode()).hexdigest()
                if prior is not None and prior.value != current.value:
                    transitions.append(
                        OperationalStateTransition.create(
                            idempotency_key=(
                                f"inventory-state:{subject_digest}:{state_type}:"
                                f"{current.metadata.source_revision}"
                            ),
                            subject_ref=subject_ref,
                            subject_type="Resource",
                            state_type=state_type,
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
                            producer_version="1.1.0",
                            freshness_ceiling_seconds=(current.metadata.freshness_ceiling_seconds),
                            completeness_basis_points=10_000,
                            evidence_refs=current.metadata.evidence_refs,
                        )
                    )
                coverage.append(
                    StateTransitionCoverage.create(
                        subject_ref=subject_ref,
                        state_type=state_type,
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

    async def _previous_state_objects(
        self,
        objects: Sequence[OntologyObjectRecord],
        *,
        observation: PromotedInventoryObservation,
        previous_batches: Sequence[TopologyRevisionBatch],
    ) -> tuple[OntologyObjectRecord, ...]:
        if self._current_state_reader is not None:
            object_ids = tuple(item.id for item in objects if item.object_type == "Resource")
            if observation.state_base_generation_checked:
                return await self._current_state_reader.read_inventory_state_base(
                    object_ids=object_ids,
                    expected_generation=observation.state_base_generation,
                )
        if not previous_batches or observation.recorded_at is None:
            return ()
        return tuple(
            graph_at(
                previous_batches,
                as_of=observation.recorded_at,
                known_at=observation.recorded_at,
            ).graph.objects
        )


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


def _observed_states(record: OntologyObjectRecord) -> dict[str, _ObservedState]:
    properties = record.properties
    provider = properties.get("properties") if isinstance(properties, dict) else None
    if not isinstance(provider, dict):
        return {}
    metadata_root = provider.get(STATE_FACT_METADATA_PROPERTY)
    if not isinstance(metadata_root, dict):
        return {}
    observed: dict[str, _ObservedState] = {}
    for state_type, path in _STATE_PATHS.items():
        state = provider.get(path)
        metadata_value = metadata_root.get(path)
        if state_type == "resource.operational_state" and not isinstance(metadata_value, dict):
            metadata_value = metadata_root
        if not isinstance(state, str) or not state.strip() or not isinstance(metadata_value, dict):
            continue
        try:
            metadata = StateFactMetadata.from_mapping(metadata_value)
        except (TypeError, ValueError):
            continue
        if (
            metadata.lane is not StateFactLane.OBSERVED
            or metadata.authority is not StateFactAuthority.PROVIDER
            or metadata.completeness < 1.0
            or metadata.synthetic
            or metadata.conflicts
        ):
            continue
        matched = _CANONICAL_STATES.intersection(re.findall(r"[a-z0-9]+", state.casefold()))
        if len(matched) == 1:
            observed[state_type] = _ObservedState(
                value=next(iter(matched)),
                metadata=metadata,
            )
    return observed


__all__ = ["InventoryTopologyHistoryPublisher", "TopologyHistoryWriter"]
