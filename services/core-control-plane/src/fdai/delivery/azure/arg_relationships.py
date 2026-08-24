"""Catalog-driven Azure ARG relationship candidate projection."""

from __future__ import annotations

import hashlib
import ipaddress
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

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
    RelationshipUnavailableReason,
    ResourceRecord,
)

ARG_RELATIONSHIP_SOURCE_SCHEMA_VERSION = "azure-resource-graph-resources@2022-10-01"
ARG_RELATIONSHIP_SOURCE_SCHEMA_DIGEST = (
    "sha256:86b6fc0038f0492047c287e9bfc3c694ea9192658848ebdabee85ad4f8cb1340"
)

ArmIdToType = Callable[[str], str | None]
ToNeutralId = Callable[[str], str]
ExternalReferenceResolver = Callable[[str], str | None]
_OPEN_ENV_VALUE_PATH = "properties.template.containers[].env[].value"
_ROLE_ASSIGNMENT_PRINCIPAL_MAPPING_ID = "azure.role-assignment-attached-to-managed-identity"
_ROLE_ASSIGNMENT_SCOPE_MAPPING_ID = "azure.role-assignment-attached-to-scope"


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
    resolved_neutral_types: Mapping[str, str] | None = None,
    source_identity: str | None = None,
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
        if not _mapping_applies(
            mapping,
            source_provider_type=source_provider_type,
            source_identity=source_identity,
        ):
            continue
        if mapping.source_schema.digest != observed_schema_digest:
            dropped.append(
                _drop(
                    RelationshipDropReason.STALE_SOURCE_SCHEMA_DIGEST,
                    mapping,
                    source_provider_type=source_provider_type,
                )
            )
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
                    if not _is_unresolved_reference_candidate(mapping, provider_reference):
                        continue
                    dropped.append(
                        _drop(
                            RelationshipDropReason.UNRESOLVED_REFERENCE,
                            mapping,
                            source_provider_type=source_provider_type,
                            unavailable_reason=(
                                RelationshipUnavailableReason.REFERENCE_NOT_OBSERVED
                            ),
                        )
                    )
                    continue
                provider_reference = resolved_reference
            elif not _is_provider_reference_candidate(mapping, provider_reference):
                continue
            target_provider_type = _target_provider_type(
                mapping,
                provider_reference,
                arm_id_to_type=arm_id_to_type,
            )
            if target_provider_type is None or not _provider_type_allowed(
                target_provider_type,
                mapping.target_provider_types,
            ):
                if mapping.source_property_path == _OPEN_ENV_VALUE_PATH:
                    continue
                dropped.append(
                    _drop(
                        RelationshipDropReason.TARGET_TYPE_MISMATCH,
                        mapping,
                        source_provider_type=source_provider_type,
                        target_provider_type=target_provider_type,
                        unavailable_reason=_unmodeled_target_reason(mapping.mapping_id),
                    )
                )
                continue
            referenced_type = (
                resolved_neutral_types.get(provider_reference.casefold())
                if resolved_neutral_types is not None
                else None
            ) or arm_to_neutral.get(target_provider_type.casefold())
            if referenced_type is None and target_provider_type.casefold() == (
                "microsoft.resources/resourcegroups"
            ):
                referenced_type = "resource-group"
            if referenced_type is None:
                dropped.append(
                    _drop(
                        RelationshipDropReason.TARGET_TYPE_MISMATCH,
                        mapping,
                        source_provider_type=source_provider_type,
                        target_provider_type=target_provider_type,
                        unavailable_reason=_unmodeled_target_reason(mapping.mapping_id),
                    )
                )
                continue
            referenced_id = to_neutral_id(provider_reference)
            evidence = _mapping_evidence(
                catalog,
                mapping,
                owner_id=owner.resource_id,
                referenced_provider_id=provider_reference,
                source_provider_type=source_provider_type,
                target_provider_type=target_provider_type,
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

    shadowed = _shadowed_contains_candidate_ids(candidates)
    candidates = [candidate for index, candidate in enumerate(candidates) if index not in shadowed]
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
        if identical:
            links.append(records[0])
            continue
        dropped.append(
            _drop(RelationshipDropReason.CONFLICTING_DUPLICATE, candidates[indexes[0]].mapping)
        )

    return RelationshipProjectionResult(
        links=tuple(links),
        dropped=tuple(
            sorted(
                dropped,
                key=lambda item: (
                    item.reason.value,
                    item.mapping_id or "",
                    item.source_property_path or "",
                ),
            )
        ),
    )


def _unmodeled_target_reason(mapping_id: str) -> RelationshipUnavailableReason:
    if mapping_id == _ROLE_ASSIGNMENT_SCOPE_MAPPING_ID:
        return RelationshipUnavailableReason.AUTHORIZATION_CHILD_SCOPE_UNMODELED
    return RelationshipUnavailableReason.TARGET_PROVIDER_TYPE_UNMODELED


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
    source_identity: str | None,
) -> bool:
    return (
        mapping.provider.casefold() == "azure"
        and (
            source_identity is None
            or mapping.source_identity.casefold() == source_identity.casefold()
        )
        and (
            "*" in mapping.source_provider_types
            or source_provider_type in mapping.source_provider_types
        )
    )


def _target_provider_type(
    mapping: ProviderRelationshipMapping,
    provider_reference: str,
    *,
    arm_id_to_type: ArmIdToType,
) -> str | None:
    if mapping.source_property_path == "id.resourceGroup":
        return "microsoft.resources/resourcegroups"
    scope_parts = [part for part in provider_reference.split("/") if part]
    if len(scope_parts) == 2 and scope_parts[0].casefold() == "subscriptions":
        return "microsoft.resources/subscriptions"
    if (
        len(scope_parts) == 4
        and scope_parts[0].casefold() == "subscriptions"
        and scope_parts[2].casefold() == "resourcegroups"
    ):
        return "microsoft.resources/resourcegroups"
    return arm_id_to_type(provider_reference)


def _provider_type_allowed(provider_type: str, allowed: Sequence[str]) -> bool:
    canonical = provider_type.casefold()
    return "*" in allowed or canonical in allowed


def _is_provider_reference_candidate(
    mapping: ProviderRelationshipMapping,
    reference: str,
) -> bool:
    if mapping.source_property_path != _OPEN_ENV_VALUE_PATH:
        return True
    return reference.casefold().startswith("/subscriptions/")


def _is_unresolved_reference_candidate(
    mapping: ProviderRelationshipMapping,
    reference: str,
) -> bool:
    if mapping.mapping_id == _ROLE_ASSIGNMENT_PRINCIPAL_MAPPING_ID:
        return False
    if mapping.source_property_path != _OPEN_ENV_VALUE_PATH:
        return True
    text = reference.strip()
    if "://" not in text or "," in text or any(char.isspace() for char in text):
        return False
    try:
        parsed = urlparse(text)
        hostname = parsed.hostname
    except ValueError:
        return False
    if not parsed.scheme.isalpha() or hostname is None:
        return False
    canonical_hostname = hostname.casefold().rstrip(".")
    if canonical_hostname == "localhost":
        return False
    try:
        ipaddress.ip_address(canonical_hostname)
    except ValueError:
        return "." in canonical_hostname
    return False


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
    source_provider_type: str,
    target_provider_type: str,
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
        source_provider_type=source_provider_type,
        target_provider_type=target_provider_type,
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


def _shadowed_contains_candidate_ids(candidates: Sequence[_Candidate]) -> set[int]:
    """Suppress wildcard containment when an exact mapping owns the same child."""
    grouped: dict[str, list[int]] = {}
    for index, candidate in enumerate(candidates):
        if candidate.record.link_type == "contains":
            grouped.setdefault(candidate.record.to_id, []).append(index)
    shadowed: set[int] = set()
    for indexes in grouped.values():
        if not any("*" not in candidates[index].mapping.source_provider_types for index in indexes):
            continue
        shadowed.update(
            index for index in indexes if "*" in candidates[index].mapping.source_provider_types
        )
    return shadowed


def _drop(
    reason: RelationshipDropReason,
    mapping: ProviderRelationshipMapping,
    *,
    source_provider_type: str | None = None,
    target_provider_type: str | None = None,
    unavailable_reason: RelationshipUnavailableReason | None = None,
) -> RelationshipDrop:
    return RelationshipDrop(
        reason=reason,
        mapping_id=mapping.mapping_id,
        source_property_path=mapping.source_property_path,
        source_provider_type=source_provider_type,
        target_provider_type=target_provider_type,
        unavailable_reason=unavailable_reason,
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
    if path == "id.providerParent":
        raw_id = row.get("id")
        parent = provider_parent_id(raw_id) if isinstance(raw_id, str) else None
        return (_PathMatch(parent, ()),) if parent is not None else ()
    matches = [_PathMatch(row, ())]
    for segment in path.split("."):
        mapping_keys = segment.endswith("{keys}")
        mapping_values = segment.endswith("{values}")
        collection = segment.endswith("[]")
        key = (
            segment[:-6]
            if mapping_keys
            else segment[:-8]
            if mapping_values
            else segment[:-2]
            if collection
            else segment
        )
        next_matches: list[_PathMatch] = []
        for match in matches:
            if not isinstance(match.value, Mapping):
                continue
            child = match.value.get(key)
            if mapping_keys or mapping_values:
                if not isinstance(child, Mapping):
                    continue
                next_matches.extend(
                    _PathMatch(item, (*match.indexes, index))
                    for index, item in enumerate(child.keys() if mapping_keys else child.values())
                )
            elif collection:
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


def provider_parent_id(arm_id: str) -> str | None:
    """Return the immediate parent for a structurally valid nested provider id."""
    marker = "/providers/"
    marker_index = arm_id.casefold().find(marker)
    if marker_index == -1:
        return None
    provider_path = arm_id[marker_index + len(marker) :].split("/")
    if len(provider_path) < 5 or len(provider_path) % 2 == 0:
        return None
    return arm_id.rsplit("/", maxsplit=2)[0]


__all__ = [
    "ARG_RELATIONSHIP_SOURCE_SCHEMA_DIGEST",
    "ARG_RELATIONSHIP_SOURCE_SCHEMA_VERSION",
    "RelationshipProjectionResult",
    "provider_parent_id",
    "project_provider_relationships",
]
