"""Publish promoted inventory observations into append-only topology history."""

from __future__ import annotations

import hashlib
import json
from typing import Protocol

from fdai.core.ontology_platform.inventory_projection import (
    build_inventory_ontology_projection,
)
from fdai.core.ontology_platform.topology_history import (
    TopologyLinkRevision,
    TopologyObjectRevision,
    TopologyRevisionBatch,
)
from fdai.delivery.inventory_sync import PromotedInventoryObservation


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

    def __init__(self, *, writer: TopologyHistoryWriter, ontology_release_digest: str) -> None:
        if not _is_digest(ontology_release_digest):
            raise ValueError("ontology_release_digest MUST be a canonical SHA-256 digest")
        self._writer = writer
        self._ontology_release_digest = ontology_release_digest

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
        projection = build_inventory_ontology_projection(
            generation=observation.generation,
            resources=observation.resources,
            links=observation.links,
            observation_complete=observation.complete,
            relationship_drops=observation.relationship_drops,
        )
        if not projection.complete:
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
        )
        await self._writer.append(
            batch,
            ontology_release_digest=self._ontology_release_digest,
            source_receipt_digest=source_receipt_digest,
        )
        return batch


def _source_receipt_digest(
    *,
    generation: str,
    recorded_at: str,
    object_revisions: tuple[TopologyObjectRevision, ...],
    link_revisions: tuple[TopologyLinkRevision, ...],
) -> str:
    payload = {
        "generation": generation,
        "recorded_at": recorded_at,
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


__all__ = ["InventoryTopologyHistoryPublisher", "TopologyHistoryWriter"]
