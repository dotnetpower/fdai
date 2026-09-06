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

Repeated observations of one identity inside a generation are adjudicated rather
than merged: agreement collapses to one object, and disagreement stays an explicit
conflict on the state fact. An empty conflict tuple records agreement between the
compared observations only; it is never evidence of independent corroboration.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fdai_service_contracts.recorded_resource_state import (
    availability_state_paths,
    is_recorded_state_value_valid,
    operational_state_paths,
)

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

from .observation_adjudication import (
    CONFLICT_PROVIDER_REF,
    CONFLICT_TRUNCATED,
    ObservationIdentityConflictError,
    ObservationVerdict,
    ObservedClaim,
    adjudicate_observations,
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
    "kubernetes_scheduled_on",
    "kubernetes_backed_by",
    "kubernetes_owned_by",
    "kubernetes_selects",
    "kubernetes_exposes_endpoints",
    "kubernetes_exposes_endpoint_slice",
    "runtime_calls",
)

_RESOURCE_OBJECT_TYPE = "Resource"
_MAX_RESOURCES = 50_000
_MAX_LINKS = 200_000
DEFAULT_OBSERVED_STATE_FRESHNESS_CEILING_SECONDS = 21_600
_DROP_OBSERVATION_INCOMPLETE = "observation_incomplete"
_DROP_UNREGISTERED_LINK_TYPE = "unregistered_link_type"
_DROP_MISSING_SOURCE_ENDPOINT = "missing_source_endpoint"
_DROP_MISSING_TARGET_ENDPOINT = "missing_target_endpoint"
_DROP_SELF_REFERENCE = "self_reference"
_DROP_UNVERIFIED_METADATA = "unverified_metadata"
_DROP_DUPLICATE_EDGE = "duplicate_edge"
_DROP_CONFLICTING_DUPLICATE = "conflicting_duplicate"
_DROP_UNMAPPED_RESOURCE_TYPE = "unmapped_resource_type"
_DROP_UNSEEDED_RESOURCE_TYPE = "unseeded_resource_type"
_NON_BLOCKING_DROPS = frozenset({_DROP_UNSEEDED_RESOURCE_TYPE})
_RECIPROCAL_LINK_TYPES = frozenset({"peered_with", "runtime_calls"})


class InventoryProjectionConflictError(RuntimeError):
    """One observed identity resolved to a contradictory type or endpoint meaning."""


@dataclass(frozen=True, slots=True)
class InventoryOntologyProjection:
    """One bounded observation restated as typed objects, links, and its coverage.

    ``generation`` is the inventory snapshot identity the observation came from.
    A pinned graph revision resolves that identity, so the caller supplies it and
    it is never derived from the projected content.

    ``complete`` is ``False`` whenever the observation was partial or an observed
    relationship was dropped. A missing catalog-owned classification target is a
    recorded non-blocking drop: it omits only derived classification enrichment and
    keeps the authoritative inventory generation writable.
    """

    generation: str
    objects: tuple[OntologyObjectRecord, ...]
    links: tuple[OntologyLinkRecord, ...]
    complete: bool
    relationship_complete: bool
    dropped_reasons: tuple[str, ...] = ()


def build_inventory_ontology_projection(
    *,
    generation: str,
    resources: Sequence[ResourceRecord],
    links: Sequence[LinkRecord] = (),
    observation_complete: bool = True,
    relationship_drops: Sequence[RelationshipDrop] = (),
    resource_type_mappings: Mapping[str, str] | None = None,
    seeded_resource_types: Set[str] | None = None,
    freshness_ceiling_seconds: int = DEFAULT_OBSERVED_STATE_FRESHNESS_CEILING_SECONDS,
) -> InventoryOntologyProjection:
    """Restate one inventory observation as a typed resource subgraph.

    Resources are idempotent by ``resource_id`` and links by
    ``(from_id, link_type, to_id)``, matching the ``Inventory`` batch contract, so
    a caller may concatenate streamed batches. Repeating identical observed content
    is a no-op. Repeating one id with disagreeing content is adjudicated: the
    contested values are withheld and the object's state fact carries an explicit
    conflict that every downstream consumer demotes on. The disagreement is never
    averaged, and neither the newest nor the first observation wins.

    Raises:
        ValueError: ``generation`` is blank or the observation exceeds its bounds.
        InventoryProjectionConflictError: one ``resource_id`` was observed with a
            contradictory type, a contested ``resource_id`` reports no observation
            time to carry its conflict on, or a link endpoint type contradicts the
            observed resources.
    """
    if not generation.strip():
        raise ValueError("inventory projection generation MUST be non-empty")
    if len(resources) > _MAX_RESOURCES:
        raise ValueError("inventory projection resource count exceeds its bound")
    if len(links) > _MAX_LINKS:
        raise ValueError("inventory projection link count exceeds its bound")
    if freshness_ceiling_seconds < 1:
        raise ValueError("inventory projection freshness ceiling MUST be >= 1 second")

    objects = _build_objects(
        resources,
        generation=generation,
        freshness_ceiling_seconds=freshness_ceiling_seconds,
    )
    observed_types = {
        resource_id: str(record.properties["type"]) for resource_id, record in objects.items()
    }
    upstream_dropped = {item.reason.value for item in relationship_drops}
    blocking_dropped = {
        item.reason.value for item in relationship_drops if not item.classified_unavailable
    }
    projection_dropped: set[str] = set()
    if observation_complete:
        projected_links = _build_links(
            links,
            generation=generation,
            observed_types=observed_types,
            dropped=projection_dropped,
        )
        if resource_type_mappings is not None:
            projected_links += _build_classification_links(
                generation=generation,
                objects=objects,
                resource_type_mappings=resource_type_mappings,
                seeded_resource_types=seeded_resource_types,
                dropped=projection_dropped,
            )
            projected_links = tuple(
                sorted(
                    projected_links,
                    key=lambda item: (item.link_type, item.from_id, item.to_id),
                )
            )
    else:
        projected_links = ()
        projection_dropped.add(_DROP_OBSERVATION_INCOMPLETE)

    dropped = upstream_dropped | projection_dropped
    blocking_dropped.update(projection_dropped)

    return InventoryOntologyProjection(
        generation=generation,
        objects=tuple(objects[key] for key in sorted(objects)),
        links=projected_links,
        complete=observation_complete and not (blocking_dropped - _NON_BLOCKING_DROPS),
        relationship_complete=observation_complete and not dropped,
        dropped_reasons=tuple(sorted(dropped)),
    )


def _build_classification_links(
    *,
    generation: str,
    objects: Mapping[str, OntologyObjectRecord],
    resource_type_mappings: Mapping[str, str],
    seeded_resource_types: Set[str] | None,
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
        if seeded_resource_types is not None and resource_type not in seeded_resource_types:
            dropped.add(_DROP_UNSEEDED_RESOURCE_TYPE)
            continue
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
    freshness_ceiling_seconds: int,
) -> dict[str, OntologyObjectRecord]:
    """Return adjudicated ``Resource`` objects keyed by observed resource id.

    Repeated observations of one identity are adjudicated instead of deduplicated by
    first-writer or last-writer. Equal observed content collapses to one object; any
    disagreement stays an explicit conflict on the state fact and the contested values
    are withheld.
    """
    claims: dict[str, list[ObservedClaim]] = {}
    for record in resources:
        resource_id = record.resource_id.strip()
        if not resource_id or not record.type.strip():
            raise ValueError("inventory resource identity and type MUST be non-empty")
        props = normalize_json_value(dict(record.props), path=f"inventory.{resource_id}")
        claims.setdefault(resource_id, []).append(
            ObservedClaim(
                type=record.type.strip(),
                properties=dict(props) if isinstance(props, Mapping) else {},
                provider_ref=record.provider_ref,
                observed_at=_observed_at(record.last_seen),
            )
        )

    objects: dict[str, OntologyObjectRecord] = {}
    for resource_id, resource_claims in claims.items():
        try:
            verdict = adjudicate_observations(resource_claims)
        except ObservationIdentityConflictError as exc:
            raise InventoryProjectionConflictError(
                f"inventory resource {resource_id!r} observed with conflicting type"
            ) from exc
        objects[resource_id] = _resource_object(
            verdict,
            claims=resource_claims,
            resource_id=resource_id,
            generation=generation,
            freshness_ceiling_seconds=freshness_ceiling_seconds,
        )
    return objects


def _resource_object(
    verdict: ObservationVerdict,
    *,
    claims: Sequence[ObservedClaim],
    resource_id: str,
    generation: str,
    freshness_ceiling_seconds: int,
) -> OntologyObjectRecord:
    """Map one adjudicated resource onto the declared ``Resource`` property shape."""
    global_conflicts = tuple(
        conflict
        for conflict in verdict.conflicts
        if conflict in {CONFLICT_PROVIDER_REF, CONFLICT_TRUNCATED}
    )
    if global_conflicts and not operational_state_paths(verdict.type):
        raise InventoryProjectionConflictError(
            f"inventory resource {resource_id!r} has a global observation conflict "
            "but no applicable operational state fact can carry it"
        )
    if verdict.contested and verdict.observed_at is None:
        # The conflict can only travel on the state fact, and the state fact needs an
        # observation time. Projecting the object anyway would publish a contested
        # resource that reads as clean, so no consumer would demote on it.
        raise InventoryProjectionConflictError(
            f"inventory resource {resource_id!r} is contested but reports no observation "
            "time, so the conflict cannot be projected"
        )
    properties: dict[str, Any] = {"id": resource_id, "type": verdict.type}
    provider_properties = dict(verdict.agreed_properties)
    _add_observed_state(
        provider_properties,
        resource_type=verdict.type,
        claims=claims,
        generation=generation,
        observed_at=verdict.observed_at,
        conflicts=verdict.conflicts,
        freshness_ceiling_seconds=freshness_ceiling_seconds,
    )
    for lifted in ("name", "parent_id"):
        value = verdict.agreed_properties.get(lifted)
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
    resource_type: str,
    claims: Sequence[ObservedClaim],
    generation: str,
    observed_at: datetime | None,
    conflicts: tuple[str, ...],
    freshness_ceiling_seconds: int,
) -> None:
    """Add the observed state fact, carrying any adjudicated conflict explicitly.

    An empty ``conflicts`` tuple records that the compared observations agreed. It is
    not evidence that the fact was independently corroborated.
    """

    _filter_state_metadata_owners(properties, resource_type=resource_type)
    paths = operational_state_paths(resource_type)
    if not paths:
        _remove_operational_state(properties, resource_type=resource_type)
        return
    state, conflicts = _adjudicate_operational_state(
        claims,
        resource_type=resource_type,
        conflicts=conflicts,
    )
    has_state = state is not None
    if observed_at is None or not (has_state or conflicts):
        return
    if has_state:
        properties["state"] = state
    state_metadata = StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=StateFactAuthority.PROVIDER,
        source_identity="inventory-provider",
        source_revision=generation,
        effective_at=observed_at,
        recorded_at=observed_at,
        evidence_cutoff=observed_at,
        freshness_ceiling_seconds=freshness_ceiling_seconds,
        completeness=0.0 if conflicts else 1.0,
        synthetic=False,
        conflicts=conflicts,
        evidence_refs=(f"inventory-generation:{generation}",),
    ).to_mapping()
    existing_metadata = properties.get(STATE_FACT_METADATA_PROPERTY)
    if isinstance(existing_metadata, Mapping) and "lane" not in existing_metadata:
        properties[STATE_FACT_METADATA_PROPERTY] = {
            **_allowlisted_state_metadata(existing_metadata, resource_type=resource_type),
            "state": state_metadata,
        }
    else:
        properties[STATE_FACT_METADATA_PROPERTY] = state_metadata


def _operational_state_candidates(
    properties: Mapping[str, object],
    *,
    paths: tuple[str, ...],
) -> tuple[tuple[str, str], ...]:
    candidates: list[tuple[str, str]] = []
    for prefix in ("", "properties.", "properties.properties."):
        for path in paths:
            current: object = properties
            for part in (prefix + path).split("."):
                if not isinstance(current, Mapping):
                    current = None
                    break
                current = current.get(part)
            if is_recorded_state_value_valid(
                current,
                allow_unknown=path == "ready_status",
            ) and isinstance(current, str):
                candidate = (path, current.strip())
                if candidate not in candidates:
                    candidates.append(candidate)
    return tuple(candidates)


def _adjudicate_operational_state(
    claims: Sequence[ObservedClaim],
    *,
    resource_type: str,
    conflicts: tuple[str, ...],
) -> tuple[str | None, tuple[str, ...]]:
    """Adjudicate only reviewed operational paths across repeated observations."""

    paths = operational_state_paths(resource_type)
    if not paths:
        return None, ()
    global_conflicts = tuple(
        conflict
        for conflict in conflicts
        if conflict in {CONFLICT_PROVIDER_REF, CONFLICT_TRUNCATED}
    )
    candidates_by_claim = tuple(
        _operational_state_candidates(claim.properties, paths=paths) for claim in claims
    )
    supplied = tuple(candidate for candidates in candidates_by_claim for candidate in candidates)
    if not supplied:
        return None, global_conflicts
    values = {candidate[1] for candidate in supplied}
    if all(candidates_by_claim) and len(values) == 1:
        return supplied[0][1], global_conflicts
    property_conflicts = tuple(
        f"observed_property_conflict:{root}"
        for root in sorted({candidate[0].split(".", 1)[0] for candidate in supplied})
    )
    return None, tuple(dict.fromkeys((*global_conflicts, *property_conflicts)))


def _remove_operational_state(
    properties: dict[str, Any],
    *,
    resource_type: str,
) -> None:
    properties.pop("state", None)
    metadata = properties.get(STATE_FACT_METADATA_PROPERTY)
    if not isinstance(metadata, Mapping):
        return
    if "lane" in metadata:
        properties.pop(STATE_FACT_METADATA_PROPERTY, None)
        return
    retained = _allowlisted_state_metadata(metadata, resource_type=resource_type)
    if retained:
        properties[STATE_FACT_METADATA_PROPERTY] = retained
    else:
        properties.pop(STATE_FACT_METADATA_PROPERTY, None)


def _allowlisted_state_metadata(
    metadata: Mapping[str, object],
    *,
    resource_type: str,
) -> dict[str, object]:
    allowed_paths = (
        *operational_state_paths(resource_type),
        *availability_state_paths(resource_type),
    )
    allowed_keys = {
        prefix + path
        for prefix in ("", "properties.", "properties.properties.")
        for path in allowed_paths
    }
    return {key: value for key, value in metadata.items() if key in allowed_keys}


def _filter_state_metadata_owners(
    properties: dict[str, Any],
    *,
    resource_type: str,
) -> None:
    owner = properties
    for depth in range(3):
        metadata = owner.get(STATE_FACT_METADATA_PROPERTY)
        if isinstance(metadata, Mapping):
            retained = (
                dict(metadata)
                if "lane" in metadata and _flat_state_metadata_allowed(owner, resource_type)
                else _allowlisted_state_metadata(metadata, resource_type=resource_type)
                if "lane" not in metadata
                else {}
            )
            if retained:
                owner[STATE_FACT_METADATA_PROPERTY] = retained
            else:
                owner.pop(STATE_FACT_METADATA_PROPERTY, None)
        if depth == 2:
            return
        nested = owner.get("properties")
        if not isinstance(nested, Mapping):
            return
        nested_owner = dict(nested)
        owner["properties"] = nested_owner
        owner = nested_owner


def _flat_state_metadata_allowed(
    owner: Mapping[str, object],
    resource_type: str,
) -> bool:
    paths = operational_state_paths(resource_type)
    return any(
        path in paths
        and is_recorded_state_value_valid(
            owner.get(path),
            allow_unknown=path == "ready_status",
        )
        for path in ("status", "state", "ready_status")
    )


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
        properties.pop("provider_relationship_evidence", None)
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
        if link_type not in _RECIPROCAL_LINK_TYPES and reverse_key in keyed:
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
