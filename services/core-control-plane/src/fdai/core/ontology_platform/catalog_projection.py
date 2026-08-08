"""Catalog-owned Rule and Rego projection into the ontology instance graph."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from fdai.rule_catalog.schema.rego_semantics import RegoSemantics, property_path
from fdai.rule_catalog.schema.resource_type import ResourceTypeRegistry
from fdai.rule_catalog.schema.signal_type import SignalTypeRegistry
from fdai.shared.contracts.models import OntologyActionType, Rule
from fdai.shared.providers.ontology_instance import (
    OntologyInstanceStore,
    OntologyLinkRecord,
    OntologyObjectRecord,
)

_OBJECT_TYPES = (
    "ActionType",
    "BenchmarkValidation",
    "DiagnosticMechanism",
    "PolicyArtifact",
    "Property",
    "ResourceType",
    "Rule",
    "SignalType",
)
_MAX_CATALOG_OBJECTS = 1000
_MAX_CATALOG_HISTORY_OBJECTS = 1000
_APPEND_ONLY_OBJECT_TYPES = frozenset({"BenchmarkValidation"})
_APPEND_ONLY_LINK_TYPES = frozenset({"mechanism_validated_by"})


@dataclass(frozen=True, slots=True)
class CatalogOntologyProjection:
    objects: tuple[OntologyObjectRecord, ...]
    links: tuple[OntologyLinkRecord, ...]


def merge_catalog_ontology_projections(
    *projections: CatalogOntologyProjection,
) -> CatalogOntologyProjection:
    """Merge catalog-owned projections and reject identity collisions."""

    objects: dict[str, OntologyObjectRecord] = {}
    links: dict[tuple[str, str, str], OntologyLinkRecord] = {}
    for projection in projections:
        for object_record in projection.objects:
            _add_object(objects, object_record)
        for link_record in projection.links:
            key = (link_record.from_id, link_record.link_type, link_record.to_id)
            previous = links.get(key)
            if previous is not None and previous != link_record:
                raise ValueError(f"catalog ontology link collision: {key!r}")
            links[key] = link_record
    if len(objects) > _MAX_CATALOG_OBJECTS:
        raise ValueError("catalog ontology projection exceeds its object limit")
    return CatalogOntologyProjection(
        objects=tuple(sorted(objects.values(), key=lambda item: item.id)),
        links=tuple(
            sorted(links.values(), key=lambda item: (item.from_id, item.link_type, item.to_id))
        ),
    )


def build_catalog_ontology_projection(
    *,
    rules: Sequence[Rule],
    action_types: Sequence[OntologyActionType],
    resource_types: ResourceTypeRegistry,
    signal_types: SignalTypeRegistry,
    policy_semantics: Mapping[str, RegoSemantics],
) -> CatalogOntologyProjection:
    """Build a deterministic catalog subgraph without writing external state."""

    objects: dict[str, OntologyObjectRecord] = {}
    links: dict[tuple[str, str, str], OntologyLinkRecord] = {}

    for resource_entry in resource_types:
        _add_object(
            objects,
            OntologyObjectRecord(
                id=_resource_type_id(resource_entry.id),
                object_type="ResourceType",
                properties={
                    "id": resource_entry.id,
                    "category": resource_entry.category.value,
                    **(
                        {"provider_type": resource_entry.azure_arm_type}
                        if resource_entry.azure_arm_type
                        else {}
                    ),
                },
            ),
        )
    for signal_entry in signal_types.types:
        _add_object(
            objects,
            OntologyObjectRecord(
                id=_signal_type_id(signal_entry.id),
                object_type="SignalType",
                properties={
                    "id": signal_entry.id,
                    "description": signal_entry.description,
                    "dispatch_mode": signal_entry.dispatch_mode.value,
                    "event_type_patterns": list(signal_entry.event_type_patterns),
                },
            ),
        )
    for action in action_types:
        category = action.category.value if action.category is not None else "remediation"
        _add_object(
            objects,
            OntologyObjectRecord(
                id=_action_type_id(action.name),
                object_type="ActionType",
                properties={
                    "id": action.name,
                    "version": str(action.version),
                    "category": category,
                    "operation": action.operation.value,
                },
            ),
        )

    for rule in sorted(rules, key=lambda item: item.id):
        reference = rule.check_logic.reference
        semantics = policy_semantics.get(reference)
        if semantics is None:
            raise ValueError(f"policy semantics unavailable for {reference!r}")
        if semantics.rule_id != rule.id:
            raise ValueError(f"policy semantics rule mismatch for {rule.id!r}")
        rule_id = _rule_id(rule.id)
        policy_id = _policy_id(reference)
        _add_object(
            objects,
            OntologyObjectRecord(
                id=rule_id,
                object_type="Rule",
                properties={
                    "id": rule.id,
                    "version": str(rule.version),
                    "severity": rule.severity.value,
                    "resource_type": rule.resource_type,
                    "remediates": rule.remediates,
                },
            ),
        )
        _add_object(
            objects,
            OntologyObjectRecord(
                id=policy_id,
                object_type="PolicyArtifact",
                properties={
                    "id": reference,
                    "reference": reference,
                    "package": semantics.package,
                    "title": semantics.title,
                    "description": semantics.description,
                    "content_digest": semantics.content_digest,
                },
            ),
        )
        _add_link(links, "implemented_by_policy", rule_id, policy_id)
        _add_link(links, "remediates", rule_id, _action_type_id(rule.remediates))
        for resource_type in sorted(rule.applies_to):
            _add_link(links, "applies_to", rule_id, _resource_type_id(resource_type))
        for signal_type in sorted(rule.triggered_by):
            _add_link(links, "triggered_by", rule_id, _signal_type_id(signal_type))
        for reference_id in sorted(rule.evaluates):
            path = property_path(rule.resource_type, reference_id)
            property_id = _property_id(reference_id)
            _add_object(
                objects,
                OntologyObjectRecord(
                    id=property_id,
                    object_type="Property",
                    properties={
                        "id": reference_id,
                        "resource_type": rule.resource_type,
                        "path": path,
                    },
                ),
            )
            _add_link(links, "evaluates", rule_id, property_id)

    if len(objects) > _MAX_CATALOG_OBJECTS:
        raise ValueError("catalog ontology projection exceeds its object limit")
    return CatalogOntologyProjection(
        objects=tuple(sorted(objects.values(), key=lambda item: item.id)),
        links=tuple(
            sorted(links.values(), key=lambda item: (item.from_id, item.link_type, item.to_id))
        ),
    )


class CatalogOntologyProjector:
    """Atomically replace only the catalog-owned ontology subgraph."""

    def __init__(self, store: OntologyInstanceStore) -> None:
        self._store = store

    async def replace(self, projection: CatalogOntologyProjection) -> None:
        previous = await self._store.query_objects(
            object_types=_OBJECT_TYPES,
            limit=_MAX_CATALOG_HISTORY_OBJECTS,
        )
        if previous.truncated:
            raise ValueError("existing catalog ontology subgraph is truncated")
        previous_objects = {item.id: item for item in previous.objects}
        projected_objects = {item.id: item for item in projection.objects}
        changed_objects: list[OntologyObjectRecord] = []
        for record in projection.objects:
            existing = previous_objects.get(record.id)
            if existing is None:
                changed_objects.append(record)
            elif existing.object_type != record.object_type or dict(existing.properties) != dict(
                record.properties
            ):
                if record.object_type in _APPEND_ONLY_OBJECT_TYPES:
                    raise ValueError("immutable catalog receipt content changed")
                changed_objects.append(replace(record, revision=existing.revision))
        stale_object_ids = tuple(
            record.id
            for record in previous.objects
            if record.object_type not in _APPEND_ONLY_OBJECT_TYPES
            and record.id not in projected_objects
        )

        previous_links = {
            (item.from_id, item.link_type, item.to_id): item for item in previous.links
        }
        projected_links = {
            (item.from_id, item.link_type, item.to_id): item for item in projection.links
        }
        changed_links = tuple(
            record for key, record in projected_links.items() if previous_links.get(key) != record
        )
        stale_link_keys = tuple(
            key
            for key, record in previous_links.items()
            if record.link_type not in _APPEND_ONLY_LINK_TYPES and key not in projected_links
        )
        if (
            not changed_objects
            and not stale_object_ids
            and not changed_links
            and not stale_link_keys
        ):
            return
        await self._store.replace_subgraph(
            objects=tuple(changed_objects),
            links=changed_links,
            previous_object_ids=stale_object_ids,
            previous_link_keys=stale_link_keys,
        )


def _add_object(
    objects: dict[str, OntologyObjectRecord],
    record: OntologyObjectRecord,
) -> None:
    previous = objects.get(record.id)
    if previous is not None and previous != record:
        raise ValueError(f"catalog ontology object collision: {record.id!r}")
    objects[record.id] = record


def _add_link(
    links: dict[tuple[str, str, str], OntologyLinkRecord],
    link_type: str,
    from_id: str,
    to_id: str,
) -> None:
    record = OntologyLinkRecord(link_type=link_type, from_id=from_id, to_id=to_id)
    links[(from_id, link_type, to_id)] = record


def _rule_id(value: str) -> str:
    return value


def _policy_id(value: str) -> str:
    return value


def _resource_type_id(value: str) -> str:
    return value


def _signal_type_id(value: str) -> str:
    return value


def _property_id(value: str) -> str:
    return value


def _action_type_id(value: str) -> str:
    return value


__all__ = [
    "CatalogOntologyProjection",
    "CatalogOntologyProjector",
    "build_catalog_ontology_projection",
    "merge_catalog_ontology_projections",
]
