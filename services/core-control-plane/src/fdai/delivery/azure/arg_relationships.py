"""Catalog-driven Azure ARG relationship candidate projection."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fdai.rule_catalog.schema.provider_relationship_mapping import (
    EndpointOrientation,
    ProviderReferenceFormat,
    ProviderRelationshipMapping,
    ProviderRelationshipMappingCatalog,
    RelationshipPredicate,
)
from fdai.shared.providers.inventory import (
    LinkRecord,
    ProviderRelationshipEvidence,
    RelationshipDrop,
    RelationshipDropReason,
    ResourceRecord,
)

ARG_RELATIONSHIP_SOURCE_SCHEMA_VERSION = "azure-resource-graph-resources@2022-10-01"
ARG_RELATIONSHIP_SOURCE_SCHEMA_DIGEST = (
    "sha256:86b6fc0038f0492047c287e9bfc3c694ea9192658848ebdabee85ad4f8cb1340"
)

ArmIdToType = Callable[[str], str | None]
ToNeutralId = Callable[[str], str]
ExternalReferenceResolver = Callable[[str], str | None]


@dataclass(frozen=True, slots=True)
class RelationshipProjectionResult:
    """Raw mapped links and stable reasons for candidates suppressed before verification."""

    links: tuple[LinkRecord, ...] = ()
    dropped: tuple[RelationshipDrop, ...] = ()


@dataclass(frozen=True, slots=True)
class _PathMatch:
    value: object
    indexes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _Candidate:
    record: LinkRecord
    mapping: ProviderRelationshipMapping
    referenced_provider_id: str


def project_provider_relationships(
    row: Mapping[str, Any],
    *,
    owner: ResourceRecord,
    arm_to_neutral: Mapping[str, str],
    catalog: ProviderRelationshipMappingCatalog,
    arm_id_to_type: ArmIdToType,
    to_neutral_id: ToNeutralId,
    external_reference_resolver: ExternalReferenceResolver | None = None,
    observed_schema_digest: str = ARG_RELATIONSHIP_SOURCE_SCHEMA_DIGEST,
) -> RelationshipProjectionResult:
    """Project provider references using only reviewed mapping direction and paths.

    Returned links remain unverified raw observations. A complete-generation verifier
    must observe both endpoints and attach ``LinkObservationMetadata`` before the
    ontology projection may activate them.
    """

    source_provider_type = _source_provider_type(row, owner, arm_id_to_type=arm_id_to_type)
    if source_provider_type is None:
        return RelationshipProjectionResult()

    candidates: list[_Candidate] = []
    dropped: list[RelationshipDrop] = []
    for mapping in catalog.mappings:
        if not _mapping_applies(mapping, source_provider_type=source_provider_type):
            continue
        if mapping.source_schema.digest != observed_schema_digest:
            dropped.append(_drop(RelationshipDropReason.STALE_SOURCE_SCHEMA_DIGEST, mapping))
            continue
        for match in _path_matches(row, mapping.source_property_path):
            if not isinstance(match.value, str) or not match.value.strip():
                continue
            if mapping.predicate is not None and not _predicate_matches(
                row,
                mapping.predicate,
                indexes=match.indexes,
            ):
                continue
            provider_reference = match.value.strip()
            if mapping.reference_format is ProviderReferenceFormat.RESOLVED_NAME:
                resolved_reference = (
                    external_reference_resolver(provider_reference)
                    if external_reference_resolver is not None
                    else None
                )
                if resolved_reference is None:
                    continue
                provider_reference = resolved_reference
            target_provider_type = _target_provider_type(
                mapping,
                provider_reference,
                arm_id_to_type=arm_id_to_type,
            )
            if target_provider_type is None or not _provider_type_allowed(
                target_provider_type,
                mapping.target_provider_types,
            ):
                continue
            referenced_type = arm_to_neutral.get(target_provider_type.casefold())
            if referenced_type is None and target_provider_type.casefold() == (
                "microsoft.resources/resourcegroups"
            ):
                referenced_type = "resource-group"
            if referenced_type is None:
                continue
            referenced_id = to_neutral_id(provider_reference)
            evidence = _mapping_evidence(
                catalog,
                mapping,
                owner_id=owner.resource_id,
                referenced_provider_id=provider_reference,
                observed_schema_digest=observed_schema_digest,
            )
            record = _oriented_link(
                owner=owner,
                referenced_id=referenced_id,
                referenced_type=referenced_type,
                mapping=mapping,
                evidence=evidence,
            )
            candidates.append(
                _Candidate(
                    record=record,
                    mapping=mapping,
                    referenced_provider_id=provider_reference,
                )
            )

    ambiguous = _ambiguous_candidate_ids(candidates)
    for candidate_id in sorted(ambiguous):
        mapping = candidates[candidate_id].mapping
        dropped.append(_drop(RelationshipDropReason.AMBIGUOUS_ORIENTATION, mapping))

    by_key: dict[tuple[str, str, str], list[int]] = {}
    for index, candidate in enumerate(candidates):
        if index in ambiguous:
            continue
        record = candidate.record
        by_key.setdefault((record.from_id, record.link_type, record.to_id), []).append(index)

    links: list[LinkRecord] = []
    for key in sorted(by_key):
        indexes = by_key[key]
        if len(indexes) == 1:
            links.append(candidates[indexes[0]].record)
            continue
        records = [candidates[index].record for index in indexes]
        identical = all(record == records[0] for record in records[1:])
        reason = (
            RelationshipDropReason.DUPLICATE_EDGE
            if identical
            else RelationshipDropReason.CONFLICTING_DUPLICATE
        )
        dropped.append(_drop(reason, candidates[indexes[0]].mapping))

    return RelationshipProjectionResult(
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


def _source_provider_type(
    row: Mapping[str, Any],
    owner: ResourceRecord,
    *,
    arm_id_to_type: ArmIdToType,
) -> str | None:
    raw_type = row.get("type")
    if isinstance(raw_type, str) and raw_type.strip():
        return raw_type.strip().casefold()
    if owner.provider_ref:
        inferred = arm_id_to_type(owner.provider_ref)
        return inferred.casefold() if inferred is not None else None
    return None


def _mapping_applies(
    mapping: ProviderRelationshipMapping,
    *,
    source_provider_type: str,
) -> bool:
    return mapping.provider.casefold() == "azure" and (
        "*" in mapping.source_provider_types
        or source_provider_type in mapping.source_provider_types
    )


def _target_provider_type(
    mapping: ProviderRelationshipMapping,
    provider_reference: str,
    *,
    arm_id_to_type: ArmIdToType,
) -> str | None:
    if mapping.source_property_path == "id.resourceGroup":
        return "microsoft.resources/resourcegroups"
    return arm_id_to_type(provider_reference)


def _provider_type_allowed(provider_type: str, allowed: Sequence[str]) -> bool:
    canonical = provider_type.casefold()
    return "*" in allowed or canonical in allowed


def _oriented_link(
    *,
    owner: ResourceRecord,
    referenced_id: str,
    referenced_type: str,
    mapping: ProviderRelationshipMapping,
    evidence: ProviderRelationshipEvidence,
) -> LinkRecord:
    if mapping.endpoint_orientation is EndpointOrientation.OWNER_TO_REFERENCED:
        from_id, from_type = owner.resource_id, owner.type
        to_id, to_type = referenced_id, referenced_type
    else:
        from_id, from_type = referenced_id, referenced_type
        to_id, to_type = owner.resource_id, owner.type
    return LinkRecord(
        from_id=from_id,
        from_type=from_type,
        link_type=mapping.link_type,
        to_id=to_id,
        to_type=to_type,
        mapping_evidence=evidence,
    )


def _mapping_evidence(
    catalog: ProviderRelationshipMappingCatalog,
    mapping: ProviderRelationshipMapping,
    *,
    owner_id: str,
    referenced_provider_id: str,
    observed_schema_digest: str,
) -> ProviderRelationshipEvidence:
    receipt_payload = json.dumps(
        {
            "mapping_id": mapping.mapping_id,
            "mapping_revision": catalog.review.content_hash,
            "owner_id": owner_id,
            "provider_reference": referenced_provider_id,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    observation_receipt = "sha256:" + hashlib.sha256(receipt_payload).hexdigest()
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
        provider_owner_id=owner_id,
        observation_receipt_ref=observation_receipt,
    )


def _ambiguous_candidate_ids(candidates: Sequence[_Candidate]) -> set[int]:
    grouped: dict[tuple[str, str, str], list[int]] = {}
    for index, candidate in enumerate(candidates):
        grouped.setdefault(
            (
                candidate.record.link_type,
                candidate.record.mapping_evidence.provider_owner_id
                if candidate.record.mapping_evidence is not None
                else "",
                candidate.referenced_provider_id.casefold(),
            ),
            [],
        ).append(index)
    ambiguous: set[int] = set()
    for indexes in grouped.values():
        orientations = {candidates[index].mapping.endpoint_orientation for index in indexes}
        if len(orientations) > 1:
            ambiguous.update(indexes)
    return ambiguous


def _drop(
    reason: RelationshipDropReason,
    mapping: ProviderRelationshipMapping,
) -> RelationshipDrop:
    return RelationshipDrop(
        reason=reason,
        mapping_id=mapping.mapping_id,
        source_property_path=mapping.source_property_path,
    )


def _predicate_matches(
    row: Mapping[str, Any],
    predicate: RelationshipPredicate,
    *,
    indexes: tuple[int, ...],
) -> bool:
    return any(
        match.indexes == indexes
        and isinstance(match.value, str)
        and match.value.casefold() == predicate.equals.casefold()
        for match in _path_matches(row, predicate.property_path)
    )


def _path_matches(row: Mapping[str, Any], path: str) -> tuple[_PathMatch, ...]:
    if path == "id.resourceGroup":
        raw_id = row.get("id")
        parent = _resource_group_parent(raw_id) if isinstance(raw_id, str) else None
        return (_PathMatch(parent, ()),) if parent is not None else ()
    matches = [_PathMatch(row, ())]
    for segment in path.split("."):
        collection = segment.endswith("[]")
        key = segment[:-2] if collection else segment
        next_matches: list[_PathMatch] = []
        for match in matches:
            if not isinstance(match.value, Mapping):
                continue
            child = match.value.get(key)
            if collection:
                if not isinstance(child, Sequence) or isinstance(child, (str, bytes)):
                    continue
                next_matches.extend(
                    _PathMatch(item, (*match.indexes, index)) for index, item in enumerate(child)
                )
            else:
                next_matches.append(_PathMatch(child, match.indexes))
        matches = next_matches
    return tuple(matches)


def _resource_group_parent(arm_id: str) -> str | None:
    marker = "/resourcegroups/"
    lowered = arm_id.casefold()
    marker_index = lowered.find(marker)
    if marker_index == -1:
        return None
    next_slash = arm_id.find("/", marker_index + len(marker))
    return None if next_slash == -1 else arm_id[:next_slash]


__all__ = [
    "ARG_RELATIONSHIP_SOURCE_SCHEMA_DIGEST",
    "ARG_RELATIONSHIP_SOURCE_SCHEMA_VERSION",
    "RelationshipProjectionResult",
    "project_provider_relationships",
]
