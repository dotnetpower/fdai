"""Project reviewed Kubernetes Service relationships from one bounded snapshot."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from fdai.rule_catalog.schema.provider_relationship_mapping import (
    EndpointOrientation,
    ProviderReferenceFormat,
    ProviderRelationshipMapping,
    ProviderRelationshipMappingCatalog,
)
from fdai.shared.providers.inventory import (
    LinkRecord,
    ProviderRelationshipEvidence,
    RelationshipDrop,
    RelationshipDropReason,
    ResourceRecord,
)

KUBERNETES_RELATIONSHIP_SOURCE_SCHEMA_VERSION = "kubernetes-core-v1"
KUBERNETES_RELATIONSHIP_SOURCE_SCHEMA_DIGEST = (
    "sha256:7c1cf19f03f34c9ce451cf1918039839439f8430b33a9cb621bdadeca4cf7106"
)


@dataclass(frozen=True, slots=True)
class KubernetesRelationshipProjectionResult:
    """Raw Kubernetes links and stable reasons for suppressed candidates."""

    links: tuple[LinkRecord, ...] = ()
    dropped: tuple[RelationshipDrop, ...] = ()


@dataclass(frozen=True, slots=True)
class _Candidate:
    record: LinkRecord
    mapping: ProviderRelationshipMapping


def project_kubernetes_relationships(
    resources: Sequence[ResourceRecord],
    *,
    catalog: ProviderRelationshipMappingCatalog,
    complete: bool,
    observed_schema_digest: str = KUBERNETES_RELATIONSHIP_SOURCE_SCHEMA_DIGEST,
) -> KubernetesRelationshipProjectionResult:
    """Project reviewed Kubernetes links without asserting verification or authority.

    The caller must pass the result through complete-generation relationship
    verification before any link can enter the active ontology graph.
    """

    if not complete:
        return KubernetesRelationshipProjectionResult(
            dropped=(RelationshipDrop(reason=RelationshipDropReason.PARTIAL_GENERATION),)
        )

    mappings = tuple(
        mapping for mapping in catalog.mappings if mapping.provider.casefold() == "kubernetes"
    )
    candidates: list[_Candidate] = []
    dropped: list[RelationshipDrop] = []
    for owner in resources:
        owner_type = owner.type.casefold()
        for mapping in mappings:
            if owner_type not in mapping.source_provider_types:
                continue
            if mapping.source_schema.digest != observed_schema_digest:
                dropped.append(_drop(RelationshipDropReason.STALE_SOURCE_SCHEMA_DIGEST, mapping))
                continue
            targets = _mapping_targets(owner, resources=resources, mapping=mapping)
            if not targets:
                dropped.append(_drop(RelationshipDropReason.MISSING_TARGET_ENDPOINT, mapping))
                continue
            for target in targets:
                candidates.append(
                    _Candidate(
                        record=_oriented_link(
                            owner=owner,
                            target=target,
                            mapping=mapping,
                            catalog=catalog,
                            observed_schema_digest=observed_schema_digest,
                        ),
                        mapping=mapping,
                    )
                )

    grouped: dict[tuple[str, str, str], list[_Candidate]] = {}
    for candidate in candidates:
        record = candidate.record
        grouped.setdefault((record.from_id, record.link_type, record.to_id), []).append(candidate)

    links: list[LinkRecord] = []
    for key in sorted(grouped):
        group = grouped[key]
        if len(group) == 1:
            links.append(group[0].record)
            continue
        records = [candidate.record for candidate in group]
        reason = (
            RelationshipDropReason.DUPLICATE_EDGE
            if all(record == records[0] for record in records[1:])
            else RelationshipDropReason.CONFLICTING_DUPLICATE
        )
        dropped.append(_drop(reason, group[0].mapping))

    return KubernetesRelationshipProjectionResult(
        links=tuple(links),
        dropped=tuple(
            sorted(
                set(dropped),
                key=lambda item: (
                    item.reason.value,
                    item.mapping_id or "",
                    item.source_property_path or "",
                ),
            )
        ),
    )


def _mapping_targets(
    owner: ResourceRecord,
    *,
    resources: Sequence[ResourceRecord],
    mapping: ProviderRelationshipMapping,
) -> tuple[ResourceRecord, ...]:
    allowed_types = set(mapping.target_provider_types)
    scoped = tuple(
        resource
        for resource in resources
        if resource.type.casefold() in allowed_types and _same_scope(owner, resource)
    )
    if mapping.reference_format is ProviderReferenceFormat.LABEL_SELECTOR:
        selector = _string_mapping(owner.props.get(mapping.source_property_path))
        if not selector:
            return ()
        return tuple(
            resource
            for resource in scoped
            if all(
                _string_mapping(resource.props.get("labels")).get(key) == value
                for key, value in selector.items()
            )
        )
    if mapping.reference_format is ProviderReferenceFormat.RESOLVED_NAME:
        reference = owner.props.get(mapping.source_property_path)
        if not isinstance(reference, str) or not reference.strip():
            return ()
        return tuple(
            resource for resource in scoped if resource.props.get("name") == reference.strip()
        )
    return ()


def _same_scope(left: ResourceRecord, right: ResourceRecord) -> bool:
    return all(
        isinstance(left.props.get(key), str) and left.props.get(key) == right.props.get(key)
        for key in ("cluster_ref", "namespace")
    )


def _string_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    normalized: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            return {}
        if not isinstance(item, str) or not item.strip():
            return {}
        normalized[key.strip()] = item.strip()
    return normalized


def _oriented_link(
    *,
    owner: ResourceRecord,
    target: ResourceRecord,
    mapping: ProviderRelationshipMapping,
    catalog: ProviderRelationshipMappingCatalog,
    observed_schema_digest: str,
) -> LinkRecord:
    evidence = _mapping_evidence(
        owner=owner,
        target=target,
        mapping=mapping,
        catalog=catalog,
        observed_schema_digest=observed_schema_digest,
    )
    if mapping.endpoint_orientation is EndpointOrientation.OWNER_TO_REFERENCED:
        source, destination = owner, target
    else:
        source, destination = target, owner
    return LinkRecord(
        from_id=source.resource_id,
        from_type=source.type,
        link_type=mapping.link_type,
        to_id=destination.resource_id,
        to_type=destination.type,
        mapping_evidence=evidence,
    )


def _mapping_evidence(
    *,
    owner: ResourceRecord,
    target: ResourceRecord,
    mapping: ProviderRelationshipMapping,
    catalog: ProviderRelationshipMappingCatalog,
    observed_schema_digest: str,
) -> ProviderRelationshipEvidence:
    payload = json.dumps(
        {
            "mapping_id": mapping.mapping_id,
            "mapping_revision": catalog.review.content_hash,
            "owner_id": owner.resource_id,
            "target_id": target.resource_id,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return ProviderRelationshipEvidence(
        mapping_id=mapping.mapping_id,
        mapping_revision=catalog.review.content_hash,
        mapping_receipt_ref=catalog.review.immutable_receipt_ref,
        provider_identity=mapping.provider,
        source_identity=mapping.source_identity,
        source_property_path=mapping.source_property_path,
        source_schema_version=mapping.source_schema.version,
        source_schema_digest=mapping.source_schema.digest,
        observed_schema_digest=observed_schema_digest,
        evidence_method=mapping.evidence_method,
        freshness_ceiling_seconds=mapping.freshness.max_age_seconds,
        endpoint_orientation=mapping.endpoint_orientation.value,
        provider_owner_id=owner.resource_id,
        observation_receipt_ref="sha256:" + hashlib.sha256(payload).hexdigest(),
    )


def _drop(
    reason: RelationshipDropReason,
    mapping: ProviderRelationshipMapping,
) -> RelationshipDrop:
    return RelationshipDrop(
        reason=reason,
        mapping_id=mapping.mapping_id,
        source_property_path=mapping.source_property_path,
    )


__all__ = [
    "KUBERNETES_RELATIONSHIP_SOURCE_SCHEMA_DIGEST",
    "KUBERNETES_RELATIONSHIP_SOURCE_SCHEMA_VERSION",
    "KubernetesRelationshipProjectionResult",
    "project_kubernetes_relationships",
]
