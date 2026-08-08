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
from typing import Any

from fdai.shared.providers.inventory import LinkRecord, ResourceRecord
from fdai.shared.providers.ontology_instance import (
    OntologyLinkRecord,
    OntologyObjectRecord,
    normalize_json_value,
)
from fdai.shared.providers.state_evidence import LINK_OBSERVATION_METADATA_PROPERTY

#: Registered ``Resource -> Resource`` observation links. A new topology link type
#: enters the catalog vocabulary first, then this tuple; an unlisted type is
#: dropped rather than written under a name the catalog cannot validate.
TOPOLOGY_LINK_TYPES: tuple[str, ...] = ("contains", "attached_to", "depends_on")

_RESOURCE_OBJECT_TYPE = "Resource"
_MAX_RESOURCES = 50_000
_MAX_LINKS = 200_000

_DROP_OBSERVATION_INCOMPLETE = "observation_incomplete"
_DROP_UNREGISTERED_LINK_TYPE = "unregistered_link_type"
_DROP_UNOBSERVED_ENDPOINT = "unobserved_endpoint"
_DROP_SELF_REFERENCE = "self_reference"


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

    objects = _build_objects(resources)
    dropped: set[str] = set()
    if observation_complete:
        projected_links = _build_links(links, observed_ids=set(objects), dropped=dropped)
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


def _build_objects(resources: Sequence[ResourceRecord]) -> dict[str, OntologyObjectRecord]:
    """Return deduplicated ``Resource`` objects keyed by observed resource id."""
    objects: dict[str, OntologyObjectRecord] = {}
    for record in resources:
        resource_id = record.resource_id.strip()
        if not resource_id or not record.type.strip():
            raise ValueError("inventory resource identity and type MUST be non-empty")
        projected = _resource_object(record, resource_id=resource_id)
        existing = objects.get(resource_id)
        if existing is None:
            objects[resource_id] = projected
        elif existing.properties != projected.properties:
            raise InventoryProjectionConflictError(
                f"inventory resource {resource_id!r} observed with conflicting content"
            )
    return objects


def _resource_object(record: ResourceRecord, *, resource_id: str) -> OntologyObjectRecord:
    """Map one observed resource onto the declared ``Resource`` property shape."""
    props = normalize_json_value(dict(record.props), path=f"inventory.{resource_id}")
    properties: dict[str, Any] = {"id": resource_id, "type": record.type.strip()}
    if isinstance(props, Mapping):
        for lifted in ("name", "parent_id"):
            value = props.get(lifted)
            if isinstance(value, str) and value.strip():
                properties[lifted] = value
        properties["properties"] = props
    return OntologyObjectRecord(
        id=resource_id,
        object_type=_RESOURCE_OBJECT_TYPE,
        properties=properties,
    )


def _build_links(
    links: Sequence[LinkRecord],
    *,
    observed_ids: set[str],
    dropped: set[str],
) -> tuple[OntologyLinkRecord, ...]:
    """Return deduplicated topology links whose endpoints were both observed."""
    keyed: dict[tuple[str, str, str], OntologyLinkRecord] = {}
    endpoint_types: dict[tuple[str, str, str], tuple[str, str]] = {}
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
        if from_id not in observed_ids or to_id not in observed_ids:
            dropped.add(_DROP_UNOBSERVED_ENDPOINT)
            continue
        key = (link_type, from_id, to_id)
        link_props = normalize_json_value(dict(record.link_props), path=f"inventory.{link_type}")
        properties = dict(link_props) if isinstance(link_props, Mapping) else {}
        if record.observation_metadata is not None:
            properties[LINK_OBSERVATION_METADATA_PROPERTY] = normalize_json_value(
                record.observation_metadata.to_mapping(),
                path=f"inventory.{link_type}.{LINK_OBSERVATION_METADATA_PROPERTY}",
            )
        projected = OntologyLinkRecord(
            link_type=link_type,
            from_id=from_id,
            to_id=to_id,
            properties=properties,
        )
        existing = keyed.get(key)
        current_endpoint_types = (record.from_type.strip(), record.to_type.strip())
        if existing is not None and (
            existing.properties != projected.properties
            or endpoint_types[key] != current_endpoint_types
        ):
            raise InventoryProjectionConflictError(
                f"inventory link {key!r} observed with conflicting content"
            )
        keyed[key] = projected
        endpoint_types[key] = current_endpoint_types
    return tuple(keyed[key] for key in sorted(keyed))


__all__ = [
    "TOPOLOGY_LINK_TYPES",
    "InventoryOntologyProjection",
    "InventoryProjectionConflictError",
    "build_inventory_ontology_projection",
]
