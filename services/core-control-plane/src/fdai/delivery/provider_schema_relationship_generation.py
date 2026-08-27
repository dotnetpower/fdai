"""Build replayable, proposal-only relationship candidates for one schema release.

The provider-schema and REST evidence ledgers remain authoritative for their own
inputs.  This module only materializes a bounded candidate generation.  It does
not update the ontology graph or the catalog; semantic promotion continues
through the separately reviewed catalog GitOps path.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from fdai.delivery.azure.provider_relationship_schema import (
    AzureProviderRelationshipSchemaSnapshot,
)
from fdai.delivery.provider_schema import ProviderSchemaError, ProviderSchemaSnapshot
from fdai.delivery.provider_schema_relationship_review import (
    ProviderSchemaRelationshipReview,
)
from fdai.rule_catalog.schema.provider_relationship_mapping import (
    EndpointOrientation,
    ProviderRelationshipMapping,
    ProviderRelationshipMappingCatalog,
)

_DIGEST_PREFIX = "sha256:"
_DIGEST_LENGTH = 71
_MAX_CANDIDATES = 100_000
_MAX_TEXT = 512
_CARDINALITIES = frozenset({"one_to_one", "one_to_many", "many_to_one", "many_to_many"})


class RelationshipGenerationDropReason(StrEnum):
    """Reasons a schema pair cannot enter a candidate generation."""

    MISSING_LINK_METADATA = "missing_link_metadata"
    STALE_LINK_METADATA = "stale_link_metadata"
    AMBIGUOUS_LINK_METADATA = "ambiguous_link_metadata"


@dataclass(frozen=True, slots=True)
class RelationshipLinkMetadata:
    """Explicit semantic metadata required before a pair becomes a candidate."""

    mapping_id: str
    source_provider_type: str
    target_provider_type: str
    link_type: str
    endpoint_orientation: EndpointOrientation
    cardinality: str
    source_property_path: str
    source_schema_version: str
    source_schema_digest: str
    projection_manifest_digest: str

    def __post_init__(self) -> None:
        for name, value in (
            ("mapping_id", self.mapping_id),
            ("source_provider_type", self.source_provider_type),
            ("target_provider_type", self.target_provider_type),
            ("link_type", self.link_type),
            ("cardinality", self.cardinality),
            ("source_property_path", self.source_property_path),
            ("source_schema_version", self.source_schema_version),
            ("source_schema_digest", self.source_schema_digest),
            ("projection_manifest_digest", self.projection_manifest_digest),
        ):
            if not value.strip() or len(value) > _MAX_TEXT:
                raise ValueError(f"relationship link metadata {name} MUST be bounded")
        if self.cardinality not in _CARDINALITIES:
            raise ValueError("relationship link metadata cardinality is invalid")
        _require_digest(self.source_schema_digest, "source schema digest")
        _require_digest(self.projection_manifest_digest, "projection manifest digest")
        object.__setattr__(self, "source_provider_type", self.source_provider_type.casefold())
        object.__setattr__(self, "target_provider_type", self.target_provider_type.casefold())

    def to_mapping(self) -> dict[str, str]:
        return {
            "cardinality": self.cardinality,
            "endpoint_orientation": self.endpoint_orientation.value,
            "link_type": self.link_type,
            "mapping_id": self.mapping_id,
            "projection_manifest_digest": self.projection_manifest_digest,
            "source_property_path": self.source_property_path,
            "source_provider_type": self.source_provider_type,
            "source_schema_digest": self.source_schema_digest,
            "source_schema_version": self.source_schema_version,
            "target_provider_type": self.target_provider_type,
        }


@dataclass(frozen=True, slots=True)
class ProviderSchemaRelationshipCandidate:
    """One exact pair with explicit direction, cardinality, and provenance."""

    source_provider_type: str
    target_provider_type: str
    source_provider_versions: tuple[str, ...]
    target_provider_versions: tuple[str, ...]
    reference_count: int
    metadata: RelationshipLinkMetadata

    def __post_init__(self) -> None:
        if self.reference_count < 1:
            raise ValueError("relationship candidate reference_count MUST be positive")
        for name, versions in (
            ("source_provider_versions", self.source_provider_versions),
            ("target_provider_versions", self.target_provider_versions),
        ):
            if not versions or versions != tuple(sorted(set(versions))):
                raise ValueError(f"relationship candidate {name} MUST be sorted and non-empty")
        if (
            self.source_provider_type.casefold() != self.metadata.source_provider_type
            or self.target_provider_type.casefold() != self.metadata.target_provider_type
        ):
            raise ValueError("relationship candidate endpoint metadata does not match the pair")

    def to_mapping(self) -> dict[str, object]:
        return {
            "reference_count": self.reference_count,
            "source_provider_type": self.source_provider_type,
            "source_provider_versions": list(self.source_provider_versions),
            "target_provider_type": self.target_provider_type,
            "target_provider_versions": list(self.target_provider_versions),
            **self.metadata.to_mapping(),
        }


@dataclass(frozen=True, slots=True)
class ProviderSchemaRelationshipGeneration:
    """Immutable candidate materialization bound to exact provider and mapping releases."""

    provider: str
    generation_ref: str
    provider_schema_digest: str
    relationship_evidence_digest: str
    mapping_revision: str
    projection_manifest_digest: str
    candidates: tuple[ProviderSchemaRelationshipCandidate, ...]
    drops: tuple[RelationshipGenerationDropReason, ...]
    complete: bool
    semantic_promotion: Literal["proposal_only"] = "proposal_only"
    graph_mutation_authority: Literal[False] = False
    migration_execution_authority: Literal[False] = False
    generation_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("provider_schema_digest", self.provider_schema_digest),
            ("relationship_evidence_digest", self.relationship_evidence_digest),
            ("projection_manifest_digest", self.projection_manifest_digest),
        ):
            _require_digest(value, name)
        if not self.provider.strip() or not self.generation_ref.strip():
            raise ValueError("relationship generation identity MUST be non-empty")
        if (
            self.semantic_promotion != "proposal_only"
            or self.graph_mutation_authority is not False
            or self.migration_execution_authority is not False
        ):
            raise ValueError("relationship generation cannot grant promotion or mutation authority")
        if self.drops != tuple(sorted(set(self.drops), key=str)):
            raise ValueError("relationship generation drops MUST be unique and sorted")
        keys = tuple(
            (item.source_provider_type, item.target_provider_type, item.metadata.mapping_id)
            for item in self.candidates
        )
        if keys != tuple(sorted(set(keys))):
            raise ValueError("relationship generation candidates MUST be unique and sorted")
        material = self.to_mapping(include_digest=False)
        object.__setattr__(
            self,
            "generation_digest",
            _digest(_canonical_json(material)),
        )

    def to_mapping(self, *, include_digest: bool = True) -> dict[str, object]:
        """Return stable material suitable for a ledger or a review package."""

        value: dict[str, object] = {
            "complete": self.complete,
            "candidates": [candidate.to_mapping() for candidate in self.candidates],
            "drops": [drop.value for drop in self.drops],
            "generation_ref": self.generation_ref,
            "mapping_revision": self.mapping_revision,
            "migration_execution_authority": self.migration_execution_authority,
            "provider": self.provider,
            "provider_schema_digest": self.provider_schema_digest,
            "projection_manifest_digest": self.projection_manifest_digest,
            "relationship_evidence_digest": self.relationship_evidence_digest,
            "semantic_promotion": self.semantic_promotion,
            "graph_mutation_authority": self.graph_mutation_authority,
            "schema_version": "1.0.0",
        }
        if include_digest:
            value["generation_digest"] = self.generation_digest
        return value


def generate_provider_schema_relationship_generation(
    *,
    provider_schema: ProviderSchemaSnapshot,
    relationship_snapshot: AzureProviderRelationshipSchemaSnapshot,
    review: ProviderSchemaRelationshipReview,
    mapping_catalog: ProviderRelationshipMappingCatalog,
    link_metadata: Mapping[str, RelationshipLinkMetadata],
    generation_ref: str,
    projection_manifest_digest: str,
    max_candidates: int = _MAX_CANDIDATES,
) -> ProviderSchemaRelationshipGeneration:
    """Materialize exact pairs with reviewed metadata, failing closed on mixed releases."""

    if provider_schema.provider != "azure" or relationship_snapshot.source_revision != (
        relationship_snapshot.source_revision.strip()
    ):
        raise ProviderSchemaError("provider relationship generation provider identity is invalid")
    review.verify_digest()
    if relationship_snapshot.provider_schema_digest != provider_schema.schema_digest:
        raise ProviderSchemaError("provider relationship generation schema release is stale")
    if review.provider_schema_digest != provider_schema.schema_digest:
        raise ProviderSchemaError("provider relationship review schema release is stale")
    if review.relationship_evidence_digest != relationship_snapshot.evidence_digest:
        raise ProviderSchemaError("provider relationship review evidence release is stale")
    if not 1 <= max_candidates <= _MAX_CANDIDATES:
        raise ValueError("provider relationship candidate bound is invalid")
    _require_digest(projection_manifest_digest, "projection manifest digest")
    if mapping_catalog.review.content_hash != review.mapping_catalog_digest:
        raise ProviderSchemaError("provider relationship mapping catalog release is stale")
    schema_types = {item.resource_type: item for item in provider_schema.types}

    metadata_by_pair: dict[tuple[str, str], list[RelationshipLinkMetadata]] = {}
    for metadata in link_metadata.values():
        metadata_by_pair.setdefault(
            (metadata.source_provider_type, metadata.target_provider_type), []
        ).append(metadata)

    candidates: list[ProviderSchemaRelationshipCandidate] = []
    drops: set[RelationshipGenerationDropReason] = set()
    for pair in review.candidates:
        key = (pair.source_provider_type, pair.target_provider_type)
        source_schema_type = schema_types.get(pair.source_provider_type.casefold())
        target_schema_type = schema_types.get(pair.target_provider_type.casefold())
        if source_schema_type is None or target_schema_type is None:
            raise ProviderSchemaError(
                "provider relationship review candidate endpoint is not in schema snapshot"
            )
        matching = [
            item
            for item in metadata_by_pair.get(key, ())
            if item.mapping_id in pair.matching_mapping_ids
            and item.projection_manifest_digest == projection_manifest_digest
        ]
        if not matching:
            drops.add(RelationshipGenerationDropReason.MISSING_LINK_METADATA)
            continue
        if len(matching) > 1:
            orientations = {item.endpoint_orientation for item in matching}
            metadata_values = {json.dumps(item.to_mapping(), sort_keys=True) for item in matching}
            if len(orientations) > 1 or len(metadata_values) > 1:
                drops.add(RelationshipGenerationDropReason.AMBIGUOUS_LINK_METADATA)
                continue
            matching = [sorted(matching, key=lambda item: item.mapping_id)[0]]
        metadata = matching[0]
        mapping = _mapping_for_id(metadata.mapping_id, mapping_catalog)
        if not _metadata_matches_mapping(metadata, mapping):
            drops.add(RelationshipGenerationDropReason.STALE_LINK_METADATA)
            continue
        candidates.append(
            ProviderSchemaRelationshipCandidate(
                source_provider_type=pair.source_provider_type,
                target_provider_type=pair.target_provider_type,
                source_provider_versions=(
                    *source_schema_type.stable_api_versions,
                    *source_schema_type.preview_api_versions,
                ),
                target_provider_versions=(
                    *target_schema_type.stable_api_versions,
                    *target_schema_type.preview_api_versions,
                ),
                reference_count=pair.reference_count,
                metadata=metadata,
            )
        )
        if len(candidates) > max_candidates:
            raise ProviderSchemaError("provider relationship candidate generation exceeds bound")

    return ProviderSchemaRelationshipGeneration(
        provider=provider_schema.provider,
        generation_ref=generation_ref,
        provider_schema_digest=provider_schema.schema_digest,
        relationship_evidence_digest=relationship_snapshot.evidence_digest,
        mapping_revision=mapping_catalog.review.content_hash,
        projection_manifest_digest=projection_manifest_digest,
        candidates=tuple(sorted(candidates, key=_candidate_key)),
        drops=tuple(sorted(drops, key=str)),
        complete=not drops,
    )


def replay_provider_schema_relationship_generation(
    generation: ProviderSchemaRelationshipGeneration,
    *,
    provider_schema: ProviderSchemaSnapshot,
    relationship_snapshot: AzureProviderRelationshipSchemaSnapshot,
    review: ProviderSchemaRelationshipReview,
    mapping_catalog: ProviderRelationshipMappingCatalog,
    link_metadata: Mapping[str, RelationshipLinkMetadata],
    generation_ref: str,
    projection_manifest_digest: str,
    max_candidates: int = _MAX_CANDIDATES,
) -> bool:
    """Rebuild a generation from pinned inputs and compare its content identity."""

    replayed = generate_provider_schema_relationship_generation(
        provider_schema=provider_schema,
        relationship_snapshot=relationship_snapshot,
        review=review,
        mapping_catalog=mapping_catalog,
        link_metadata=link_metadata,
        generation_ref=generation_ref,
        projection_manifest_digest=projection_manifest_digest,
        max_candidates=max_candidates,
    )
    return replayed == generation


def changed_provider_type_versions(
    baseline: ProviderSchemaSnapshot,
    observed: ProviderSchemaSnapshot,
) -> frozenset[str]:
    """Return only provider type/version identities whose mapping inputs changed."""

    if baseline.provider != observed.provider:
        raise ProviderSchemaError("provider schema snapshots MUST have the same provider")
    before = {item.resource_type: item for item in baseline.types}
    after = {item.resource_type: item for item in observed.types}
    changed: set[str] = set()
    for resource_type in sorted(set(before) | set(after)):
        old = before.get(resource_type)
        new = after.get(resource_type)
        old_versions = () if old is None else (*old.stable_api_versions, *old.preview_api_versions)
        new_versions = () if new is None else (*new.stable_api_versions, *new.preview_api_versions)
        if old_versions != new_versions:
            changed.add(resource_type)
            changed.update(
                f"{resource_type}@{version}" for version in (*old_versions, *new_versions)
            )
    return frozenset(changed)


def invalidate_changed_relationship_candidates(
    generation: ProviderSchemaRelationshipGeneration,
    changed_identities: Sequence[str],
) -> ProviderSchemaRelationshipGeneration:
    """Drop candidates touching changed types so an incremental rebuild cannot reuse stale links."""

    changed = {value.casefold() for value in changed_identities}
    retained = tuple(
        candidate
        for candidate in generation.candidates
        if not _candidate_is_changed(candidate, changed)
    )
    invalidated = len(retained) != len(generation.candidates)
    drops = set(generation.drops)
    if invalidated:
        drops.add(RelationshipGenerationDropReason.STALE_LINK_METADATA)
    return ProviderSchemaRelationshipGeneration(
        provider=generation.provider,
        generation_ref=generation.generation_ref,
        provider_schema_digest=generation.provider_schema_digest,
        relationship_evidence_digest=generation.relationship_evidence_digest,
        mapping_revision=generation.mapping_revision,
        projection_manifest_digest=generation.projection_manifest_digest,
        candidates=retained,
        drops=tuple(sorted(drops, key=str)),
        complete=False if invalidated else generation.complete,
    )


def _mapping_for_id(
    mapping_id: str,
    catalog: ProviderRelationshipMappingCatalog,
) -> ProviderRelationshipMapping:
    for mapping in catalog.mappings:
        if mapping.mapping_id == mapping_id:
            return mapping
    raise ProviderSchemaError("provider relationship metadata references an unknown mapping")


def _metadata_matches_mapping(
    metadata: RelationshipLinkMetadata,
    mapping: ProviderRelationshipMapping,
) -> bool:
    """Require every semantic field to match the reviewed catalog entry."""

    return (
        metadata.mapping_id == mapping.mapping_id
        and metadata.source_provider_type in mapping.source_provider_types
        and metadata.target_provider_type in mapping.target_provider_types
        and metadata.link_type == mapping.link_type
        and metadata.endpoint_orientation is mapping.endpoint_orientation
        and metadata.cardinality == mapping.cardinality
        and metadata.source_property_path == mapping.source_property_path
        and metadata.source_schema_version == mapping.source_schema.version
        and metadata.source_schema_digest == mapping.source_schema.digest
    )


def _candidate_key(item: ProviderSchemaRelationshipCandidate) -> tuple[str, str, str]:
    return (
        item.source_provider_type,
        item.target_provider_type,
        item.metadata.mapping_id,
    )


def _candidate_is_changed(
    candidate: ProviderSchemaRelationshipCandidate,
    changed: set[str],
) -> bool:
    identities = {
        candidate.source_provider_type,
        candidate.target_provider_type,
        *(
            f"{candidate.source_provider_type}@{version}"
            for version in candidate.source_provider_versions
        ),
        *(
            f"{candidate.target_provider_type}@{version}"
            for version in candidate.target_provider_versions
        ),
    }
    return bool(identities & changed)


def _require_digest(value: str, name: str) -> None:
    if len(value) != _DIGEST_LENGTH or not value.startswith(_DIGEST_PREFIX):
        raise ValueError(f"{name} MUST be sha256:<64 lowercase hex>")
    if any(character not in "0123456789abcdef" for character in value[7:]):
        raise ValueError(f"{name} MUST be sha256:<64 lowercase hex>")


def _digest(payload: bytes) -> str:
    return _DIGEST_PREFIX + hashlib.sha256(payload).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


__all__ = [
    "ProviderSchemaRelationshipCandidate",
    "ProviderSchemaRelationshipGeneration",
    "RelationshipGenerationDropReason",
    "RelationshipLinkMetadata",
    "changed_provider_type_versions",
    "generate_provider_schema_relationship_generation",
    "invalidate_changed_relationship_candidates",
    "replay_provider_schema_relationship_generation",
]
