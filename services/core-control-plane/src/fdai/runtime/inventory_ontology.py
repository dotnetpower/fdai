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

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from fdai.core.ontology_platform.inventory_projection import (
    DEFAULT_OBSERVED_STATE_FRESHNESS_CEILING_SECONDS,
    InventoryOntologyProjection,
    build_inventory_ontology_projection,
)
from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.shared.providers.ontology_instance import (
    OntologyInstanceStore,
    OntologyInstanceValidationError,
    OntologyObjectRecord,
)
from fdai.shared.providers.resource_lock import ResourceLock
from fdai.shared.providers.state_store import StateStore

INVENTORY_ONTOLOGY_MANIFEST_KEY = "inventory-ontology:manifest"
INVENTORY_ONTOLOGY_STATUS_KEY = "inventory-ontology:status"
_MANIFEST_SCHEMA_VERSION = "1.3.0"
_LEGACY_MANIFEST_SCHEMA_VERSION = "1.2.0"
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_PROJECTION_LOCK_ID = "inventory-ontology-projection"

_LOG = logging.getLogger(__name__)


class InventoryOntologyProjectionStatus(StrEnum):
    """Availability of the latest promoted inventory projection attempt."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class InventoryOntologyProjectionResult:
    """Counts and coverage for one applied generation."""

    generation: str
    ontology_release_digest: str
    status: InventoryOntologyProjectionStatus
    object_count: int
    link_count: int
    complete: bool
    relationship_complete: bool
    dropped_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _OwnedIdentities:
    """Identities the previous generation of this projection wrote."""

    object_ids: tuple[str, ...]
    link_keys: tuple[tuple[str, str, str], ...]
    generation: str | None = None
    manifest_digest: str | None = None


class InventoryOntologyProjector:
    """Apply one promoted observation as the provider-observed resource subgraph."""

    def __init__(
        self,
        *,
        store: OntologyInstanceStore,
        status_store: StateStore,
        ontology_release_digest: str,
        resource_type_mappings: Mapping[str, str] | None = None,
        freshness_ceiling_seconds: int = DEFAULT_OBSERVED_STATE_FRESHNESS_CEILING_SECONDS,
        projection_lock: ResourceLock | None = None,
    ) -> None:
        if _DIGEST_PATTERN.fullmatch(ontology_release_digest) is None:
            raise ValueError("inventory ontology release digest MUST be sha256:<64 lowercase hex>")
        if freshness_ceiling_seconds < 1:
            raise ValueError("inventory ontology freshness ceiling MUST be >= 1 second")
        self._store = store
        self._status_store = status_store
        self._ontology_release_digest = ontology_release_digest
        self._resource_type_mappings = resource_type_mappings
        self._freshness_ceiling_seconds = freshness_ceiling_seconds
        self._projection_lock = projection_lock
        self._local_lock = asyncio.Lock()

    async def apply(
        self,
        observation: PromotedInventoryObservation,
    ) -> InventoryOntologyProjectionResult:
        """Serialize and atomically replace the owned subgraph for one generation."""

        async with self._local_lock:
            if self._projection_lock is None:
                return await self._apply_locked(observation)
            async with self._projection_lock.acquire(_PROJECTION_LOCK_ID):
                return await self._apply_locked(observation)

    async def _apply_locked(
        self,
        observation: PromotedInventoryObservation,
    ) -> InventoryOntologyProjectionResult:
        """Build and commit one generation while the projection lock is held.

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
            resource_type_mappings=self._resource_type_mappings,
            seeded_resource_types=await self._seeded_resource_types(observation),
            freshness_ceiling_seconds=self._freshness_ceiling_seconds,
        )
        if not projection.complete:
            await self._write_status(
                projection,
                status=InventoryOntologyProjectionStatus.UNAVAILABLE,
            )
            return InventoryOntologyProjectionResult(
                generation=projection.generation,
                ontology_release_digest=self._ontology_release_digest,
                status=InventoryOntologyProjectionStatus.UNAVAILABLE,
                object_count=0,
                link_count=0,
                complete=False,
                relationship_complete=projection.relationship_complete,
                dropped_reasons=projection.dropped_reasons,
            )
        previous = await self._read_manifest()
        object_content, link_content = _projection_content(projection)
        current_manifest_digest = _manifest_digest(
            generation=projection.generation,
            ontology_release_digest=self._ontology_release_digest,
            complete=projection.complete,
            relationship_complete=projection.relationship_complete,
            dropped_reasons=projection.dropped_reasons,
            object_ids=tuple(record.id for record in projection.objects),
            link_keys=tuple(
                (record.from_id, record.link_type, record.to_id) for record in projection.links
            ),
            object_content=object_content,
            link_content=link_content,
        )
        if (
            previous.generation == projection.generation
            and previous.manifest_digest is not None
            and previous.manifest_digest != current_manifest_digest
        ):
            raise ValueError("inventory ontology generation content changed")
        pinned = await self._pin_owned_revisions(projection.objects, owned_ids=previous.object_ids)
        await self._store.replace_subgraph(
            objects=pinned,
            links=projection.links,
            previous_object_ids=previous.object_ids,
            previous_link_keys=previous.link_keys,
        )
        await self._write_manifest(projection)
        # Status is the commit marker. A crash after the manifest write leaves
        # generation mismatch visible and a retry safely replays the graph.
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
            ontology_release_digest=self._ontology_release_digest,
            status=InventoryOntologyProjectionStatus.AVAILABLE,
            object_count=len(projection.objects),
            link_count=len(projection.links),
            complete=projection.complete,
            relationship_complete=projection.relationship_complete,
            dropped_reasons=projection.dropped_reasons,
        )

    async def _seeded_resource_types(
        self,
        observation: PromotedInventoryObservation,
    ) -> frozenset[str] | None:
        """Return mapped ResourceType targets that exist in the current instance graph."""
        if self._resource_type_mappings is None:
            return None
        observed_types = sorted(
            {
                record.type.strip()
                for record in observation.resources
                if record.type.strip() in self._resource_type_mappings
            }
        )
        seeded: set[str] = set()
        for resource_type in observed_types:
            if await self._store.get_object(resource_type) is not None:
                seeded.add(resource_type)
        return frozenset(seeded)

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
        schema_version = raw.get("schema_version")
        if schema_version not in {_LEGACY_MANIFEST_SCHEMA_VERSION, _MANIFEST_SCHEMA_VERSION}:
            raise ValueError("inventory ontology manifest schema version is unsupported")
        if raw.get("ontology_release_digest") != self._ontology_release_digest:
            raise ValueError("inventory ontology manifest release digest does not match")
        if not isinstance(raw.get("generation"), str) or not raw["generation"].strip():
            raise ValueError("inventory ontology manifest generation is invalid")
        object_values = raw.get("object_ids")
        link_values = raw.get("link_keys")
        object_content = raw.get("object_content")
        link_content = raw.get("link_content")
        if not isinstance(object_values, list) or not isinstance(link_values, list):
            raise ValueError("inventory ontology manifest identities are invalid")
        object_ids = tuple(object_values)
        if any(not isinstance(item, str) or not item for item in object_ids) or object_ids != tuple(
            sorted(set(object_ids))
        ):
            raise ValueError("inventory ontology manifest object ids are invalid")
        link_keys = tuple(
            tuple(item)
            for item in link_values
            if isinstance(item, list)
            and len(item) == 3
            and all(isinstance(value, str) and value for value in item)
        )
        if len(link_keys) != len(link_values) or link_keys != tuple(sorted(set(link_keys))):
            raise ValueError("inventory ontology manifest link keys are invalid")
        if schema_version == _LEGACY_MANIFEST_SCHEMA_VERSION:
            return _OwnedIdentities(
                object_ids,
                link_keys,
                generation=raw["generation"],
            )
        if not isinstance(object_content, list) or not isinstance(link_content, list):
            raise ValueError("inventory ontology manifest content is invalid")
        if (
            tuple(item.get("id") for item in object_content if isinstance(item, dict)) != object_ids
            or len(object_content) != len(object_ids)
            or any(
                not isinstance(item, dict)
                or set(item) != {"id", "object_type", "properties"}
                or not isinstance(item["id"], str)
                or not isinstance(item["object_type"], str)
                or not isinstance(item["properties"], dict)
                for item in object_content
            )
        ):
            raise ValueError("inventory ontology manifest object content is invalid")
        manifest_link_keys = tuple(
            (item.get("from_id"), item.get("link_type"), item.get("to_id"))
            for item in link_content
            if isinstance(item, dict)
        )
        if (
            manifest_link_keys != link_keys
            or len(link_content) != len(link_keys)
            or any(
                not isinstance(item, dict)
                or set(item) != {"from_id", "link_type", "to_id", "properties"}
                or any(not isinstance(item[key], str) for key in ("from_id", "link_type", "to_id"))
                or not isinstance(item["properties"], dict)
                for item in link_content
            )
        ):
            raise ValueError("inventory ontology manifest link content is invalid")
        expected_digest = _manifest_digest(
            generation=raw["generation"],
            ontology_release_digest=self._ontology_release_digest,
            complete=raw.get("complete"),
            relationship_complete=raw.get("relationship_complete"),
            dropped_reasons=raw.get("dropped_reasons"),
            object_ids=object_ids,
            link_keys=link_keys,
            object_content=object_content,
            link_content=link_content,
        )
        if raw.get("manifest_digest") != expected_digest:
            raise ValueError("inventory ontology manifest digest does not match its contents")
        return _OwnedIdentities(
            object_ids,
            link_keys,
            generation=raw["generation"],
            manifest_digest=expected_digest,
        )

    async def _write_manifest(self, projection: InventoryOntologyProjection) -> None:
        object_content, link_content = _projection_content(projection)
        manifest_digest = _manifest_digest(
            generation=projection.generation,
            ontology_release_digest=self._ontology_release_digest,
            complete=projection.complete,
            relationship_complete=projection.relationship_complete,
            dropped_reasons=projection.dropped_reasons,
            object_ids=tuple(record.id for record in projection.objects),
            link_keys=tuple(
                (record.from_id, record.link_type, record.to_id) for record in projection.links
            ),
            object_content=object_content,
            link_content=link_content,
        )
        await self._status_store.write_state(
            INVENTORY_ONTOLOGY_MANIFEST_KEY,
            {
                "schema_version": _MANIFEST_SCHEMA_VERSION,
                "generation": projection.generation,
                "ontology_release_digest": self._ontology_release_digest,
                "manifest_digest": manifest_digest,
                "complete": projection.complete,
                "relationship_complete": projection.relationship_complete,
                "dropped_reasons": list(projection.dropped_reasons),
                "object_ids": [record.id for record in projection.objects],
                "link_keys": [
                    [record.from_id, record.link_type, record.to_id] for record in projection.links
                ],
                "object_content": list(object_content),
                "link_content": list(link_content),
            },
        )

    async def _write_status(
        self,
        projection: InventoryOntologyProjection,
        *,
        status: InventoryOntologyProjectionStatus,
    ) -> None:
        object_content, link_content = _projection_content(projection)
        manifest_digest = _manifest_digest(
            generation=projection.generation,
            ontology_release_digest=self._ontology_release_digest,
            complete=projection.complete,
            relationship_complete=projection.relationship_complete,
            dropped_reasons=projection.dropped_reasons,
            object_ids=tuple(record.id for record in projection.objects),
            link_keys=tuple(
                (record.from_id, record.link_type, record.to_id) for record in projection.links
            ),
            object_content=object_content,
            link_content=link_content,
        )
        await self._status_store.write_state(
            INVENTORY_ONTOLOGY_STATUS_KEY,
            {
                "schema_version": _MANIFEST_SCHEMA_VERSION,
                "generation": projection.generation,
                "ontology_release_digest": self._ontology_release_digest,
                "manifest_digest": manifest_digest,
                "status": status.value,
                "complete": projection.complete,
                "relationship_complete": projection.relationship_complete,
                "dropped_reasons": list(projection.dropped_reasons),
            },
        )


def _projection_content(
    projection: InventoryOntologyProjection,
) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    """Return canonical object and link content for the projection receipt."""

    objects: tuple[dict[str, object], ...] = tuple(
        {
            "id": record.id,
            "object_type": record.object_type,
            "properties": _content_properties(record.properties),
        }
        for record in projection.objects
    )
    links: tuple[dict[str, object], ...] = tuple(
        {
            "from_id": record.from_id,
            "link_type": record.link_type,
            "to_id": record.to_id,
            "properties": _content_properties(record.properties),
        }
        for record in projection.links
    )
    return objects, links


def _content_properties(properties: Mapping[str, object]) -> dict[str, object]:
    """Copy one normalized property mapping into the manifest content envelope."""

    return dict(properties)


def _manifest_digest(
    *,
    generation: str,
    ontology_release_digest: str,
    complete: object,
    relationship_complete: object,
    dropped_reasons: object,
    object_ids: tuple[str, ...],
    link_keys: tuple[tuple[str, str, str], ...],
    object_content: Sequence[Mapping[str, object]],
    link_content: Sequence[Mapping[str, object]],
) -> str:
    """Hash the shared manifest payload used by status and reader reload checks."""

    payload = {
        "schema_version": _MANIFEST_SCHEMA_VERSION,
        "generation": generation,
        "ontology_release_digest": ontology_release_digest,
        "complete": complete,
        "relationship_complete": relationship_complete,
        "dropped_reasons": dropped_reasons,
        "object_ids": list(object_ids),
        "link_keys": [list(key) for key in link_keys],
        "object_content": list(object_content),
        "link_content": list(link_content),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "INVENTORY_ONTOLOGY_MANIFEST_KEY",
    "INVENTORY_ONTOLOGY_STATUS_KEY",
    "InventoryOntologyProjectionResult",
    "InventoryOntologyProjectionStatus",
    "InventoryOntologyProjector",
]
