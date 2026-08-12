"""Project one promoted inventory generation into the observed resource subgraph.

The inventory synchronization job owns snapshot promotion, so it also owns this
derived provider-observed subgraph. This module is that single writer: it pins
the current revision of every object it already owns, replaces its own subgraph
atomically, and retains the owned identities so a later generation deletes what
disappeared.

It never widens ownership. An object that exists but is absent from the retained
manifest belongs to another projection and stops the write instead of being
silently adopted.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from fdai.core.ontology_platform.inventory_projection import (
    InventoryOntologyProjection,
    build_inventory_ontology_projection,
)
from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.shared.providers.ontology_instance import (
    OntologyInstanceStore,
    OntologyInstanceValidationError,
    OntologyObjectRecord,
)
from fdai.shared.providers.state_store import StateStore

INVENTORY_ONTOLOGY_MANIFEST_KEY = "inventory-ontology:manifest"
INVENTORY_ONTOLOGY_STATUS_KEY = "inventory-ontology:status"
_MANIFEST_SCHEMA_VERSION = "1.0.0"

_LOG = logging.getLogger(__name__)


class InventoryOntologyProjectionStatus(StrEnum):
    """Availability of the latest promoted inventory projection attempt."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class InventoryOntologyProjectionResult:
    """Counts and coverage for one applied generation."""

    generation: str
    status: InventoryOntologyProjectionStatus
    object_count: int
    link_count: int
    complete: bool
    dropped_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _OwnedIdentities:
    """Identities the previous generation of this projection wrote."""

    object_ids: tuple[str, ...]
    link_keys: tuple[tuple[str, str, str], ...]


class InventoryOntologyProjector:
    """Apply one promoted observation as the provider-observed resource subgraph."""

    def __init__(self, *, store: OntologyInstanceStore, status_store: StateStore) -> None:
        self._store = store
        self._status_store = status_store

    async def apply(
        self,
        observation: PromotedInventoryObservation,
    ) -> InventoryOntologyProjectionResult:
        """Build and atomically replace the owned subgraph for one generation.

        Raises:
            OntologyInstanceValidationError: a projected object is already owned
                by a different projection.
        """
        projection = build_inventory_ontology_projection(
            generation=observation.generation,
            resources=observation.resources,
            links=observation.links,
            observation_complete=observation.complete,
            relationship_drops=observation.relationship_drops,
        )
        if not projection.complete:
            await self._write_status(
                projection,
                status=InventoryOntologyProjectionStatus.UNAVAILABLE,
            )
            return InventoryOntologyProjectionResult(
                generation=projection.generation,
                status=InventoryOntologyProjectionStatus.UNAVAILABLE,
                object_count=0,
                link_count=0,
                complete=False,
                dropped_reasons=projection.dropped_reasons,
            )
        previous = await self._read_manifest()
        pinned = await self._pin_owned_revisions(projection.objects, owned_ids=previous.object_ids)
        await self._store.replace_subgraph(
            objects=pinned,
            links=projection.links,
            previous_object_ids=previous.object_ids,
            previous_link_keys=previous.link_keys,
        )
        await self._write_manifest(projection)
        await self._write_status(
            projection,
            status=InventoryOntologyProjectionStatus.AVAILABLE,
        )
        _LOG.info(
            "inventory_ontology_projected",
            extra={
                "generation": projection.generation,
                "objects": len(projection.objects),
                "links": len(projection.links),
                "complete": projection.complete,
            },
        )
        return InventoryOntologyProjectionResult(
            generation=projection.generation,
            status=InventoryOntologyProjectionStatus.AVAILABLE,
            object_count=len(projection.objects),
            link_count=len(projection.links),
            complete=projection.complete,
            dropped_reasons=projection.dropped_reasons,
        )

    async def _pin_owned_revisions(
        self,
        objects: Sequence[OntologyObjectRecord],
        *,
        owned_ids: tuple[str, ...],
    ) -> tuple[OntologyObjectRecord, ...]:
        """Carry the stored revision so an owned update passes its CAS fence."""
        owned = set(owned_ids)
        pinned: list[OntologyObjectRecord] = []
        for record in objects:
            current = await self._store.get_object(record.id)
            if current is None:
                pinned.append(record)
                continue
            if record.id not in owned:
                raise OntologyInstanceValidationError(
                    f"inventory ontology object {record.id!r} is owned by another projection"
                )
            pinned.append(replace(record, revision=current.revision))
        return tuple(pinned)

    async def _read_manifest(self) -> _OwnedIdentities:
        raw = await self._status_store.read_state(INVENTORY_ONTOLOGY_MANIFEST_KEY)
        if not isinstance(raw, dict):
            return _OwnedIdentities((), ())
        object_ids = tuple(
            item for item in raw.get("object_ids", ()) if isinstance(item, str) and item
        )
        link_keys = tuple(
            (str(item[0]), str(item[1]), str(item[2]))
            for item in raw.get("link_keys", ())
            if isinstance(item, list | tuple) and len(item) == 3
        )
        return _OwnedIdentities(object_ids, link_keys)

    async def _write_manifest(self, projection: InventoryOntologyProjection) -> None:
        await self._status_store.write_state(
            INVENTORY_ONTOLOGY_MANIFEST_KEY,
            {
                "schema_version": _MANIFEST_SCHEMA_VERSION,
                "generation": projection.generation,
                "complete": projection.complete,
                "dropped_reasons": list(projection.dropped_reasons),
                "object_ids": [record.id for record in projection.objects],
                "link_keys": [
                    [record.from_id, record.link_type, record.to_id] for record in projection.links
                ],
            },
        )

    async def _write_status(
        self,
        projection: InventoryOntologyProjection,
        *,
        status: InventoryOntologyProjectionStatus,
    ) -> None:
        await self._status_store.write_state(
            INVENTORY_ONTOLOGY_STATUS_KEY,
            {
                "schema_version": _MANIFEST_SCHEMA_VERSION,
                "generation": projection.generation,
                "status": status.value,
                "dropped_reasons": list(projection.dropped_reasons),
            },
        )


__all__ = [
    "INVENTORY_ONTOLOGY_MANIFEST_KEY",
    "INVENTORY_ONTOLOGY_STATUS_KEY",
    "InventoryOntologyProjectionResult",
    "InventoryOntologyProjectionStatus",
    "InventoryOntologyProjector",
]
