"""Canonical manifest, status, and digest records for inventory ontology projection."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

from fdai.core.ontology_platform.inventory_projection import InventoryOntologyProjection
from fdai.runtime.inventory_ontology_state import InventoryOntologyProjectionStatus

MANIFEST_SCHEMA_VERSION = "1.3.0"
LEGACY_MANIFEST_SCHEMA_VERSION = "1.2.0"
IDENTITY_ONLY_MANIFEST_SCHEMA_VERSION = "1.1.0"
MAX_MANIFEST_BYTES = 32 * 1024 * 1024


def projection_content(
    projection: InventoryOntologyProjection,
) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    """Return canonical object and link content for the projection receipt."""

    objects: tuple[dict[str, object], ...] = tuple(
        {
            "id": record.id,
            "object_type": record.object_type,
            "properties": dict(record.properties),
        }
        for record in projection.objects
    )
    links: tuple[dict[str, object], ...] = tuple(
        {
            "from_id": record.from_id,
            "link_type": record.link_type,
            "to_id": record.to_id,
            "properties": dict(record.properties),
        }
        for record in projection.links
    )
    return objects, links


def manifest_state(
    projection: InventoryOntologyProjection,
    *,
    ontology_release_digest: str,
    manifest_digest: str,
    journal_high_watermark: int | None = None,
    projection_high_watermark: int | None = None,
) -> dict[str, object]:
    object_content, link_content = projection_content(projection)
    state: dict[str, object] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generation": projection.generation,
        "ontology_release_digest": ontology_release_digest,
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
    }
    if journal_high_watermark is not None:
        state["journal_high_watermark"] = journal_high_watermark
        state["projection_high_watermark"] = projection_high_watermark
    return state


def status_state(
    projection: InventoryOntologyProjection,
    *,
    ontology_release_digest: str,
    manifest_digest: str,
    status: InventoryOntologyProjectionStatus,
    journal_high_watermark: int | None = None,
    projection_high_watermark: int | None = None,
) -> dict[str, object]:
    state: dict[str, object] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generation": projection.generation,
        "ontology_release_digest": ontology_release_digest,
        "manifest_digest": manifest_digest,
        "status": status.value,
        "complete": projection.complete,
        "relationship_complete": projection.relationship_complete,
        "dropped_reasons": list(projection.dropped_reasons),
    }
    if journal_high_watermark is not None:
        state["journal_high_watermark"] = journal_high_watermark
        state["projection_high_watermark"] = projection_high_watermark
    return state


def projection_status_state(
    projection: InventoryOntologyProjection,
    *,
    ontology_release_digest: str,
    status: InventoryOntologyProjectionStatus,
    journal_high_watermark: int | None = None,
    projection_high_watermark: int | None = None,
) -> dict[str, object]:
    object_content, link_content = projection_content(projection)
    digest = manifest_digest(
        generation=projection.generation,
        ontology_release_digest=ontology_release_digest,
        complete=projection.complete,
        relationship_complete=projection.relationship_complete,
        dropped_reasons=projection.dropped_reasons,
        object_ids=tuple(record.id for record in projection.objects),
        link_keys=tuple(
            (record.from_id, record.link_type, record.to_id) for record in projection.links
        ),
        object_content=object_content,
        link_content=link_content,
        journal_high_watermark=journal_high_watermark,
        projection_high_watermark=projection_high_watermark,
    )
    return status_state(
        projection,
        ontology_release_digest=ontology_release_digest,
        manifest_digest=digest,
        status=status,
        journal_high_watermark=journal_high_watermark,
        projection_high_watermark=projection_high_watermark,
    )


def manifest_digest(
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
    journal_high_watermark: int | None = None,
    projection_high_watermark: int | None = None,
) -> str:
    """Hash the shared manifest payload used by status and reader reload checks."""

    payload = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
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
    if journal_high_watermark is not None:
        payload["journal_high_watermark"] = journal_high_watermark
        payload["projection_high_watermark"] = projection_high_watermark
    return _bounded_digest(payload)


def manifest_content_digest(
    *,
    generation: str,
    complete: object,
    relationship_complete: object,
    dropped_reasons: object,
    object_ids: tuple[str, ...],
    link_keys: tuple[tuple[str, str, str], ...],
    object_content: Sequence[Mapping[str, object]],
    link_content: Sequence[Mapping[str, object]],
    journal_high_watermark: int | None = None,
    projection_high_watermark: int | None = None,
) -> str:
    """Hash release-independent observed content for safe release transitions."""

    payload = {
        "generation": generation,
        "complete": complete,
        "relationship_complete": relationship_complete,
        "dropped_reasons": dropped_reasons,
        "object_ids": list(object_ids),
        "link_keys": [list(key) for key in link_keys],
        "object_content": list(object_content),
        "link_content": list(link_content),
    }
    return _bounded_digest(payload)


def _bounded_digest(payload: Mapping[str, object]) -> str:
    digest = hashlib.sha256()
    byte_count = 0
    encoder = json.JSONEncoder(
        sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )
    for chunk in encoder.iterencode(payload):
        encoded = chunk.encode("utf-8")
        byte_count += len(encoded)
        if byte_count > MAX_MANIFEST_BYTES:
            raise ValueError("inventory ontology manifest exceeds its encoded byte bound")
        digest.update(encoded)
    return "sha256:" + digest.hexdigest()


def manifest_watermark(value: Mapping[str, object], key: str) -> int | None:
    if key not in value:
        return None
    watermark = value.get(key)
    if not isinstance(watermark, int) or isinstance(watermark, bool) or watermark < 0:
        raise ValueError(f"inventory ontology manifest {key} is invalid")
    return watermark
