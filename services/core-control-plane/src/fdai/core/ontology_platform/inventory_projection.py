"""Project CSP-neutral inventory observations into the semantic resource subgraph.

The authoritative inventory owns observed cloud state. This builder restates one
bounded observation as typed ``Resource`` objects and registered topology links so
decision paths traverse relationships without reading a provider SDK. It is pure:
the caller supplies the observation and persists the result under one writer.

The projection never claims a relationship it did not observe. An incomplete
observation yields objects without links, an unregistered link type is dropped,
and a link whose endpoint was not observed is dropped. Every drop is reported in
``dropped_reasons`` so a consumer can distinguish an empty result from an
unobserved one instead of reading absence as health.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fdai.shared.providers.inventory import LinkRecord, RelationshipDrop, ResourceRecord
from fdai.shared.providers.ontology_instance import (
    OntologyLinkRecord,
    OntologyObjectRecord,
    normalize_json_value,
)
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    STATE_FACT_METADATA_PROPERTY,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

#: Registered ``Resource -> Resource`` observation links. A new topology link type
#: enters the catalog vocabulary first, then this tuple; an unlisted type is
#: dropped rather than written under a name the catalog cannot validate.
TOPOLOGY_LINK_TYPES: tuple[str, ...] = (
    "contains",
    "attached_to",
    "depends_on",
    "routes_to",
    "peered_with",
)

_RESOURCE_OBJECT_TYPE = "Resource"
_MAX_RESOURCES = 50_000
_MAX_LINKS = 200_000

_DROP_OBSERVATION_INCOMPLETE = "observation_incomplete"
_DROP_UNREGISTERED_LINK_TYPE = "unregistered_link_type"
_DROP_MISSING_SOURCE_ENDPOINT = "missing_source_endpoint"
_DROP_MISSING_TARGET_ENDPOINT = "missing_target_endpoint"
_DROP_SELF_REFERENCE = "self_reference"
_DROP_UNVERIFIED_METADATA = "unverified_metadata"
_DROP_DUPLICATE_EDGE = "duplicate_edge"
_DROP_CONFLICTING_DUPLICATE = "conflicting_duplicate"
_DROP_UNMAPPED_RESOURCE_TYPE = "unmapped_resource_type"


class InventoryProjectionConflictError(RuntimeError):
    """One observed resource id resolved to conflicting content in the same batch."""


@dataclass(frozen=True, slots=True)
class InventoryOntologyProjection:
    """One bounded observation restated as typed objects, links, and its coverage.

    ``generation`` is the inventory snapshot identity the observation came from.
    A pinned graph revision resolves that identity, so the caller supplies it and
    it is never derived from the projected content.

    ``complete`` is ``False`` whenever the observation was partial or any link was
    dropped. A consumer MUST NOT read an absence claim from an incomplete
    projection.
    """

    generation: str
    objects: tuple[OntologyObjectRecord, ...]
    links: tuple[OntologyLinkRecord, ...]
    complete: bool
    dropped_reasons: tuple[str, ...] = ()


def build_inventory_ontology_projection(
    *,
    generation: str,
    resources: Sequence[ResourceRecord],
    links: Sequence[LinkRecord] = (),
    observation_complete: bool = True,
    relationship_drops: Sequence[RelationshipDrop] = (),
    resource_type_mappings: Mapping[str, str] | None = None,
) -> InventoryOntologyProjection:
    """Restate one inventory observation as a typed resource subgraph.

    Resources are idempotent by ``resource_id`` and links by
    ``(from_id, link_type, to_id)``, matching the ``Inventory`` batch contract, so
    a caller may concatenate streamed batches. Repeating identical content is a
    no-op; repeating one id with different content is a defect and raises.

    Raises:
        ValueError: ``generation`` is blank or the observation exceeds its bounds.
        InventoryProjectionConflictError: one ``resource_id`` carries conflicting
            observed content within the same observation.
    """
    if not generation.strip():
        raise ValueError("inventory projection generation MUST be non-empty")
    if len(resources) > _MAX_RESOURCES:
        raise ValueError("inventory projection resource count exceeds its bound")
    if len(links) > _MAX_LINKS:
        raise ValueError("inventory projection link count exceeds its bound")

    objects = _build_objects(resources, generation=generation)
    observed_types = {
        resource_id: str(record.properties["type"]) for resource_id, record in objects.items()
    }
    dropped = {item.reason.value for item in relationship_drops}
    if observation_complete:
        projected_links = _build_links(
            links,
            generation=generation,
            observed_types=observed_types,
            dropped=dropped,
        )
        if resource_type_mappings is not None:
            projected_links += _build_classification_links(
                generation=generation,
                objects=objects,
                resource_type_mappings=resource_type_mappings,
                dropped=dropped,
            )
            projected_links = tuple(
                sorted(
                    projected_links,
                    key=lambda item: (item.link_type, item.from_id, item.to_id),
                )
            )
    else:
        projected_links = ()
        dropped.add(_DROP_OBSERVATION_INCOMPLETE)

    return InventoryOntologyProjection(
        generation=generation,
        objects=tuple(objects[key] for key in sorted(objects)),
        links=projected_links,
        complete=observation_complete and not dropped,
        dropped_reasons=tuple(sorted(dropped)),
    )


def _build_classification_links(
    *,
    generation: str,
    objects: Mapping[str, OntologyObjectRecord],
    resource_type_mappings: Mapping[str, str],
    dropped: set[str],
) -> tuple[OntologyLinkRecord, ...]:
    """Classify every observed Resource through one reviewed type mapping."""

    links: list[OntologyLinkRecord] = []
    for resource_id, record in sorted(objects.items()):
        resource_type = record.properties.get("type")
        if not isinstance(resource_type, str):  # pragma: no cover - object builder invariant
            raise InventoryProjectionConflictError(
                f"inventory resource {resource_id!r} has no projected type"
            )
        mapping_digest = resource_type_mappings.get(resource_type)
        if mapping_digest is None:
            dropped.add(_DROP_UNMAPPED_RESOURCE_TYPE)
            continue
        if not mapping_digest.startswith("sha256:") or len(mapping_digest) != 71:
            raise ValueError("resource type mapping digest MUST be a canonical SHA-256 value")
        links.append(
            OntologyLinkRecord(
                link_type="resource_classified_as",
                from_id=resource_id,
                to_id=resource_type,
                properties={
                    "inventory_generation": generation,
                    "mapping_digest": mapping_digest,
                    "mapping_id": resource_type,
                    "verified": True,
                },
            )
        )
    return tuple(links)


def _build_objects(
    resources: Sequence[ResourceRecord],
    *,
    generation: str,
) -> dict[str, OntologyObjectRecord]:
    """Return deduplicated ``Resource`` objects keyed by observed resource id."""
    objects: dict[str, OntologyObjectRecord] = {}
    for record in resources:
        resource_id = record.resource_id.strip()
        if not resource_id or not record.type.strip():
            raise ValueError("inventory resource identity and type MUST be non-empty")
        projected = _resource_object(record, resource_id=resource_id, generation=generation)
        existing = objects.get(resource_id)
        if existing is None:
            objects[resource_id] = projected
        elif existing.properties != projected.properties:
            raise InventoryProjectionConflictError(
                f"inventory resource {resource_id!r} observed with conflicting content"
            )
    return objects


def _resource_object(
    record: ResourceRecord,
    *,
    resource_id: str,
    generation: str,
) -> OntologyObjectRecord:
    """Map one observed resource onto the declared ``Resource`` property shape."""
    props = normalize_json_value(dict(record.props), path=f"inventory.{resource_id}")
    properties: dict[str, Any] = {"id": resource_id, "type": record.type.strip()}
    if isinstance(props, Mapping):
        provider_properties = dict(props)
        _add_observed_state(
            provider_properties,
            generation=generation,
            observed_at=_observed_at(record.last_seen),
        )
        for lifted in ("name", "parent_id"):
            value = props.get(lifted)
            if isinstance(value, str) and value.strip():
                properties[lifted] = value
        properties["properties"] = provider_properties
    return OntologyObjectRecord(
        id=resource_id,
        object_type=_RESOURCE_OBJECT_TYPE,
        properties=properties,
    )


def _add_observed_state(
    properties: dict[str, Any],
    *,
    generation: str,
    observed_at: datetime | None,
) -> None:
    """Add canonical observed state only when provider time and state are complete."""

    state = properties.get("status")
    if not isinstance(state, str) or not state.strip() or observed_at is None:
        return
    properties["state"] = state.strip()
    properties[STATE_FACT_METADATA_PROPERTY] = StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="inventory-provider",
        source_revision=generation,
        effective_at=observed_at,
        recorded_at=observed_at,
        evidence_cutoff=observed_at,
        freshness_ceiling_seconds=300,
        completeness=1.0,
        synthetic=False,
        evidence_refs=(f"inventory-generation:{generation}",),
    ).to_mapping()


def _observed_at(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _build_links(
    links: Sequence[LinkRecord],
    *,
    generation: str,
    observed_types: Mapping[str, str],
    dropped: set[str],
) -> tuple[OntologyLinkRecord, ...]:
    """Return deduplicated topology links whose endpoints were both observed."""
    keyed: dict[tuple[str, str, str], OntologyLinkRecord] = {}
    endpoint_types: dict[tuple[str, str, str], tuple[str, str]] = {}
    blocked_keys: set[tuple[str, str, str]] = set()
    for record in links:
        link_type = record.link_type.strip()
        from_id = record.from_id.strip()
        to_id = record.to_id.strip()
        if not link_type or not from_id or not to_id:
            raise ValueError("inventory link identity fields MUST be non-empty")
        if link_type not in TOPOLOGY_LINK_TYPES:
            dropped.add(_DROP_UNREGISTERED_LINK_TYPE)
            continue
        if from_id == to_id:
            dropped.add(_DROP_SELF_REFERENCE)
            continue
        if from_id not in observed_types:
            dropped.add(_DROP_MISSING_SOURCE_ENDPOINT)
            continue
        if to_id not in observed_types:
            dropped.add(_DROP_MISSING_TARGET_ENDPOINT)
            continue
        current_endpoint_types = (record.from_type.strip(), record.to_type.strip())
        observed_endpoint_types = (observed_types[from_id], observed_types[to_id])
        if current_endpoint_types != observed_endpoint_types:
            raise InventoryProjectionConflictError(
                f"inventory link {(link_type, from_id, to_id)!r} endpoint type conflicts "
                "with observed resources"
            )
        metadata = record.observation_metadata
        if (
            metadata is None
            or not metadata.verified
            or metadata.inventory_generation != generation
            or metadata.state_fact.completeness < 1.0
            or metadata.state_fact.synthetic
            or metadata.state_fact.conflicts
        ):
            dropped.add(_DROP_UNVERIFIED_METADATA)
            continue
        key = (link_type, from_id, to_id)
        if key in blocked_keys:
            continue
        link_props = normalize_json_value(dict(record.link_props), path=f"inventory.{link_type}")
        properties = dict(link_props) if isinstance(link_props, Mapping) else {}
        properties[LINK_OBSERVATION_METADATA_PROPERTY] = normalize_json_value(
            metadata.to_mapping(),
            path=f"inventory.{link_type}.{LINK_OBSERVATION_METADATA_PROPERTY}",
        )
        projected = OntologyLinkRecord(
            link_type=link_type,
            from_id=from_id,
            to_id=to_id,
            properties=properties,
        )
        existing = keyed.get(key)
        if existing is not None:
            conflicting = (
                existing.properties != projected.properties
                or endpoint_types[key] != current_endpoint_types
            )
            dropped.add(_DROP_CONFLICTING_DUPLICATE if conflicting else _DROP_DUPLICATE_EDGE)
            keyed.pop(key)
            endpoint_types.pop(key)
            blocked_keys.add(key)
            continue
        keyed[key] = projected
        endpoint_types[key] = current_endpoint_types
    for key in tuple(keyed):
        link_type, from_id, to_id = key
        reverse_key = (link_type, to_id, from_id)
        if link_type != "peered_with" and reverse_key in keyed:
            dropped.add(_DROP_CONFLICTING_DUPLICATE)
            keyed.pop(key, None)
            keyed.pop(reverse_key, None)
    return tuple(keyed[key] for key in sorted(keyed))


__all__ = [
    "TOPOLOGY_LINK_TYPES",
    "InventoryOntologyProjection",
    "InventoryProjectionConflictError",
    "build_inventory_ontology_projection",
]
