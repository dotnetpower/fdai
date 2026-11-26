"""Classify exact provider-schema relationship candidates without semantic promotion."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import StrEnum

from fdai.delivery.azure.provider_relationship_schema import (
    AzureProviderRelationshipSchemaSnapshot,
)
from fdai.delivery.provider_schema import ProviderSchemaError
from fdai.rule_catalog.schema.provider_relationship_mapping import (
    ProviderReferenceFormat,
    ProviderRelationshipMappingCatalog,
)

_MAX_PAIRS_PER_REFERENCE = 4_096
_MAX_UNIQUE_ENDPOINT_PAIRS = 100_000


class ProviderSchemaEndpointCoverage(StrEnum):
    """Modeled-provider coverage for one exact source-to-target endpoint pair."""

    BOTH_MODELED = "both_modeled"
    SOURCE_ONLY_MODELED = "source_only_modeled"
    TARGET_ONLY_MODELED = "target_only_modeled"
    NEITHER_MODELED = "neither_modeled"


@dataclass(frozen=True, slots=True)
class ProviderSchemaRelationshipCandidate:
    """One exact provider endpoint pair awaiting independent semantic review."""

    source_provider_type: str
    target_provider_type: str
    reference_count: int
    endpoint_coverage: ProviderSchemaEndpointCoverage
    matching_mapping_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for name, value in (
            ("source_provider_type", self.source_provider_type),
            ("target_provider_type", self.target_provider_type),
        ):
            if not value.strip():
                raise ProviderSchemaError(f"provider schema relationship candidate {name} is empty")
        if self.reference_count < 1:
            raise ProviderSchemaError(
                "provider schema relationship candidate reference count is invalid"
            )
        if self.matching_mapping_ids != tuple(sorted(set(self.matching_mapping_ids))):
            raise ProviderSchemaError(
                "provider schema relationship candidate mapping ids MUST be sorted and unique"
            )

    def to_mapping(self) -> dict[str, object]:
        return {
            "source_provider_type": self.source_provider_type,
            "target_provider_type": self.target_provider_type,
            "reference_count": self.reference_count,
            "endpoint_coverage": self.endpoint_coverage.value,
            "matching_mapping_ids": list(self.matching_mapping_ids),
        }


@dataclass(frozen=True, slots=True)
class ProviderSchemaRelationshipReview:
    """Content-addressed classification that grants no catalog or ontology authority."""

    source_revision: str
    provider_schema_digest: str
    relationship_evidence_digest: str
    mapping_catalog_digest: str
    exact_reference_count: int
    missing_source_reference_count: int
    target_only_type_count: int
    candidates: tuple[ProviderSchemaRelationshipCandidate, ...]
    review_digest: str

    def __post_init__(self) -> None:
        self.verify_digest()

    def verify_digest(self) -> None:
        """Recompute the digest after deserialization or before a trusted handoff."""

        if not self.review_digest.startswith("sha256:") or len(self.review_digest) != 71:
            raise ProviderSchemaError("provider schema relationship review digest is invalid")
        expected = (
            "sha256:"
            + hashlib.sha256(
                _canonical_json(
                    _review_material(
                        source_revision=self.source_revision,
                        provider_schema_digest=self.provider_schema_digest,
                        relationship_evidence_digest=self.relationship_evidence_digest,
                        mapping_catalog_digest=self.mapping_catalog_digest,
                        exact_reference_count=self.exact_reference_count,
                        missing_source_reference_count=self.missing_source_reference_count,
                        target_only_type_count=self.target_only_type_count,
                        candidates=self.candidates,
                    )
                )
            ).hexdigest()
        )
        if self.review_digest != expected:
            raise ProviderSchemaError("provider schema relationship review digest mismatch")

    @classmethod
    def build(
        cls,
        *,
        relationship_snapshot: AzureProviderRelationshipSchemaSnapshot,
        modeled_provider_types: frozenset[str],
        mapping_catalog: ProviderRelationshipMappingCatalog,
    ) -> ProviderSchemaRelationshipReview:
        """Classify exact endpoint pairs while leaving semantic meaning unresolved."""

        modeled = frozenset(item.casefold() for item in modeled_provider_types)
        pair_counts: Counter[tuple[str, str]] = Counter()
        target_only_types: set[str] = set()
        missing_source_count = 0
        exact_reference_count = 0
        for reference in relationship_snapshot.arm_id_references:
            if not reference.resolved:
                continue
            exact_reference_count += 1
            targets = tuple(item.casefold() for item in reference.allowed_resource_types)
            sources = tuple(item.casefold() for item in reference.source_resource_types)
            if not sources:
                missing_source_count += 1
                target_only_types.update(targets)
                continue
            if len(sources) * len(targets) > _MAX_PAIRS_PER_REFERENCE:
                raise ProviderSchemaError(
                    "provider schema relationship reference exceeds endpoint-pair bound"
                )
            pair_counts.update((source, target) for source in sources for target in targets)
            if len(pair_counts) > _MAX_UNIQUE_ENDPOINT_PAIRS:
                raise ProviderSchemaError(
                    "provider schema relationship review exceeds unique endpoint-pair bound"
                )

        mapping_ids_by_pair: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
        for mapping in mapping_catalog.mappings:
            sources = tuple(item.casefold() for item in mapping.source_provider_types)
            targets = tuple(item.casefold() for item in mapping.target_provider_types)
            if (
                mapping.provider.casefold() != "azure"
                or mapping.reference_format is not ProviderReferenceFormat.ARM_ID
                or "*" in sources
                or "*" in targets
            ):
                continue
            for source in sources:
                for target in targets:
                    mapping_ids_by_pair[(source, target)].add(mapping.mapping_id)

        candidates = tuple(
            ProviderSchemaRelationshipCandidate(
                source_provider_type=source,
                target_provider_type=target,
                reference_count=pair_counts[(source, target)],
                endpoint_coverage=_endpoint_coverage(
                    source=source,
                    target=target,
                    modeled_provider_types=modeled,
                ),
                matching_mapping_ids=tuple(sorted(mapping_ids_by_pair[(source, target)])),
            )
            for source, target in sorted(pair_counts)
        )
        material = _review_material(
            source_revision=relationship_snapshot.source_revision,
            provider_schema_digest=relationship_snapshot.provider_schema_digest,
            relationship_evidence_digest=relationship_snapshot.evidence_digest,
            mapping_catalog_digest=mapping_catalog.review.content_hash,
            exact_reference_count=exact_reference_count,
            missing_source_reference_count=missing_source_count,
            target_only_type_count=len(target_only_types),
            candidates=candidates,
        )
        review_digest = "sha256:" + hashlib.sha256(_canonical_json(material)).hexdigest()
        return cls(
            source_revision=relationship_snapshot.source_revision,
            provider_schema_digest=relationship_snapshot.provider_schema_digest,
            relationship_evidence_digest=relationship_snapshot.evidence_digest,
            mapping_catalog_digest=mapping_catalog.review.content_hash,
            exact_reference_count=exact_reference_count,
            missing_source_reference_count=missing_source_count,
            target_only_type_count=len(target_only_types),
            candidates=candidates,
            review_digest=review_digest,
        )

    def to_mapping(self) -> dict[str, object]:
        material = _review_material(
            source_revision=self.source_revision,
            provider_schema_digest=self.provider_schema_digest,
            relationship_evidence_digest=self.relationship_evidence_digest,
            mapping_catalog_digest=self.mapping_catalog_digest,
            exact_reference_count=self.exact_reference_count,
            missing_source_reference_count=self.missing_source_reference_count,
            target_only_type_count=self.target_only_type_count,
            candidates=self.candidates,
        )
        return {
            **material,
            "review_digest": self.review_digest,
        }


def _endpoint_coverage(
    *,
    source: str,
    target: str,
    modeled_provider_types: frozenset[str],
) -> ProviderSchemaEndpointCoverage:
    source_modeled = source in modeled_provider_types
    target_modeled = target in modeled_provider_types
    if source_modeled and target_modeled:
        return ProviderSchemaEndpointCoverage.BOTH_MODELED
    if source_modeled:
        return ProviderSchemaEndpointCoverage.SOURCE_ONLY_MODELED
    if target_modeled:
        return ProviderSchemaEndpointCoverage.TARGET_ONLY_MODELED
    return ProviderSchemaEndpointCoverage.NEITHER_MODELED


def _review_material(
    *,
    source_revision: str,
    provider_schema_digest: str,
    relationship_evidence_digest: str,
    mapping_catalog_digest: str,
    exact_reference_count: int,
    missing_source_reference_count: int,
    target_only_type_count: int,
    candidates: tuple[ProviderSchemaRelationshipCandidate, ...],
) -> dict[str, object]:
    coverage_counts = Counter(candidate.endpoint_coverage.value for candidate in candidates)
    matching_mapping_ids = sorted(
        {mapping_id for candidate in candidates for mapping_id in candidate.matching_mapping_ids}
    )
    return {
        "schema_version": "1.0.0",
        "kind": "provider-schema-relationship-candidate-review",
        "provider": "azure",
        "source_revision": source_revision,
        "provider_schema_digest": provider_schema_digest,
        "relationship_evidence_digest": relationship_evidence_digest,
        "mapping_catalog_digest": mapping_catalog_digest,
        "exact_reference_count": exact_reference_count,
        "missing_source_reference_count": missing_source_reference_count,
        "target_only_type_count": target_only_type_count,
        "unique_endpoint_pair_count": len(candidates),
        "endpoint_coverage_counts": dict(sorted(coverage_counts.items())),
        "reviewed_mapping_overlap_count": len(matching_mapping_ids),
        "reviewed_mapping_overlap_ids": matching_mapping_ids,
        "candidate_pairs": [candidate.to_mapping() for candidate in candidates],
        "semantic_review_status": "review_required",
        "automatic_promotion": False,
        "grants_authority": False,
    }


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


__all__ = [
    "ProviderSchemaEndpointCoverage",
    "ProviderSchemaRelationshipCandidate",
    "ProviderSchemaRelationshipReview",
]
