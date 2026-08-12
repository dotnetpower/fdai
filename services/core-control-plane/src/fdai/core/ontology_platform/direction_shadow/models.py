"""Immutable contracts for graph-generation direction shadow comparison."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from fdai.shared.providers.inventory import LinkRecord
from fdai.shared.providers.state_evidence import LinkObservationMetadata

from .identity import content_digest

_DIGEST_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
_MAX_REF_LENGTH = 512


class ComparisonDisposition(StrEnum):
    """Evidence completeness classification without migration authority."""

    COMPLETE = "complete"
    REVIEW_REQUIRED = "review_required"


class ReviewReason(StrEnum):
    """Stable reasons that prevent a comparison from being complete evidence."""

    LEGACY_GENERATION_INCOMPLETE = "legacy_generation_incomplete"
    ALIGNED_GENERATION_INCOMPLETE = "aligned_generation_incomplete"
    LEGACY_GENERATION_TRUNCATED = "legacy_generation_truncated"
    ALIGNED_GENERATION_TRUNCATED = "aligned_generation_truncated"
    LEGACY_MISSING_ENDPOINT = "legacy_missing_endpoint"
    ALIGNED_MISSING_ENDPOINT = "aligned_missing_endpoint"
    LEGACY_LINK_EVIDENCE_UNVERIFIED = "legacy_link_evidence_unverified"
    ALIGNED_LINK_EVIDENCE_UNVERIFIED = "aligned_link_evidence_unverified"
    COMPARISON_TRUNCATED = "comparison_truncated"


@dataclass(frozen=True, slots=True)
class DirectionGraphLink:
    """One immutable directed link and its optional verified observation metadata."""

    link_type: str
    from_id: str
    to_id: str
    observation_metadata: LinkObservationMetadata | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("link_type", self.link_type),
            ("from_id", self.from_id),
            ("to_id", self.to_id),
        ):
            _bounded_ref(name, value)

    @classmethod
    def from_inventory_link(cls, record: LinkRecord) -> DirectionGraphLink:
        """Copy one provider-neutral inventory link into immutable comparison input."""

        return cls(
            link_type=record.link_type,
            from_id=record.from_id,
            to_id=record.to_id,
            observation_metadata=record.observation_metadata,
        )

    @property
    def key(self) -> tuple[str, str, str]:
        """Return the stored endpoint identity in canonical tuple order."""

        return self.link_type, self.from_id, self.to_id

    @property
    def evidence_verified(self) -> bool:
        """Return whether metadata proves a complete, non-synthetic verified link."""

        metadata = self.observation_metadata
        return bool(
            metadata is not None
            and metadata.verified
            and metadata.state_fact.completeness == 1.0
            and not metadata.state_fact.synthetic
            and not metadata.state_fact.conflicts
        )

    def to_mapping(self) -> dict[str, object]:
        """Return canonical JSON-compatible generation material."""

        return {
            "from_id": self.from_id,
            "link_type": self.link_type,
            "observation_metadata": (
                self.observation_metadata.to_mapping()
                if self.observation_metadata is not None
                else None
            ),
            "to_id": self.to_id,
        }


@dataclass(frozen=True, slots=True)
class DirectionGraphGeneration:
    """One immutable graph generation pinned to an exact ontology release."""

    generation_ref: str
    ontology_release_digest: str
    object_ids: tuple[str, ...]
    links: tuple[DirectionGraphLink, ...]
    complete: bool
    truncated: bool
    generation_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _bounded_ref("generation_ref", self.generation_ref)
        _digest_value("ontology_release_digest", self.ontology_release_digest)
        if self.object_ids != tuple(sorted(set(self.object_ids))):
            raise ValueError("direction graph object_ids MUST be unique and sorted")
        for object_id in self.object_ids:
            _bounded_ref("object_id", object_id)
        link_keys = tuple(link.key for link in self.links)
        if link_keys != tuple(sorted(set(link_keys))):
            raise ValueError("direction graph links MUST have unique sorted endpoint keys")
        object.__setattr__(self, "generation_digest", content_digest(self._digest_material()))

    @classmethod
    def create(
        cls,
        *,
        generation_ref: str,
        ontology_release_digest: str,
        object_ids: tuple[str, ...],
        links: tuple[DirectionGraphLink, ...],
        complete: bool,
        truncated: bool = False,
    ) -> DirectionGraphGeneration:
        """Canonicalize and content-address one immutable generation."""

        return cls(
            generation_ref=generation_ref,
            ontology_release_digest=ontology_release_digest,
            object_ids=tuple(sorted(object_ids)),
            links=tuple(sorted(links, key=lambda item: item.key)),
            complete=complete,
            truncated=truncated,
        )

    @property
    def missing_endpoint_ids(self) -> tuple[str, ...]:
        """Return link endpoints absent from this generation's object set."""

        known = set(self.object_ids)
        endpoints = {endpoint for link in self.links for endpoint in (link.from_id, link.to_id)}
        return tuple(sorted(endpoints - known))

    @property
    def link_evidence_verified(self) -> bool:
        """Return whether every retained link has complete verified observation evidence."""

        return all(link.evidence_verified for link in self.links)

    def _digest_material(self) -> dict[str, object]:
        return {
            "complete": self.complete,
            "generation_ref": self.generation_ref,
            "links": [link.to_mapping() for link in self.links],
            "object_ids": list(self.object_ids),
            "ontology_release_digest": self.ontology_release_digest,
            "truncated": self.truncated,
        }


@dataclass(frozen=True, slots=True)
class ComparisonBounds:
    """Replay-stable traversal ceilings for one comparison."""

    traversal_depth: int = 5
    blast_radius_depth: int = 2
    max_roots: int = 1_000

    def __post_init__(self) -> None:
        if not 1 <= self.traversal_depth <= 5:
            raise ValueError("traversal_depth MUST be between 1 and 5")
        if not 1 <= self.blast_radius_depth <= 5:
            raise ValueError("blast_radius_depth MUST be between 1 and 5")
        if not 1 <= self.max_roots <= 10_000:
            raise ValueError("max_roots MUST be between 1 and 10000")


@dataclass(frozen=True, slots=True)
class RebuildPointer:
    """Safe rollback pointer that rebuilds current state from authoritative inventory."""

    authoritative_generation_ref: str
    rebuild_procedure_ref: str
    strategy: Literal["rebuild_current_state_from_authoritative_inventory"] = (
        "rebuild_current_state_from_authoritative_inventory"
    )
    restores_deleted_rows: Literal[False] = False
    mutation_authority: Literal[False] = False

    def __post_init__(self) -> None:
        _bounded_ref("authoritative_generation_ref", self.authoritative_generation_ref)
        _bounded_ref("rebuild_procedure_ref", self.rebuild_procedure_ref)


@dataclass(frozen=True, slots=True)
class LinkRef:
    """Stable stored identity for one directed link."""

    link_type: str
    from_id: str
    to_id: str


@dataclass(frozen=True, slots=True)
class LinkReversal:
    """One removed stored direction paired with its aligned reverse."""

    legacy: LinkRef
    aligned: LinkRef


@dataclass(frozen=True, slots=True)
class QueryResultDelta:
    """Changed result set for one replayable bounded graph query."""

    query: str
    root_id: str
    legacy_ids: tuple[str, ...]
    aligned_ids: tuple[str, ...]
    added_ids: tuple[str, ...]
    removed_ids: tuple[str, ...]
    legacy_truncated: bool = False
    aligned_truncated: bool = False

    def __post_init__(self) -> None:
        for values in (self.legacy_ids, self.aligned_ids, self.added_ids, self.removed_ids):
            if values != tuple(sorted(set(values))):
                raise ValueError("query result ids MUST be unique and sorted")
        if self.added_ids != tuple(sorted(set(self.aligned_ids) - set(self.legacy_ids))):
            raise ValueError("query added_ids do not match result sets")
        if self.removed_ids != tuple(sorted(set(self.legacy_ids) - set(self.aligned_ids))):
            raise ValueError("query removed_ids do not match result sets")


@dataclass(frozen=True, slots=True)
class DirectionShadowReceipt:
    """Content-addressed comparison evidence with no mutation or migration authority."""

    schema_version: Literal["1.0.0"]
    comparator_version: Literal["direction-shadow-comparator.v1"]
    disposition: ComparisonDisposition
    review_reasons: tuple[ReviewReason, ...]
    migration_revision: str
    prior_release_digest: str
    aligned_release_digest: str
    legacy_generation_digest: str
    aligned_generation_digest: str
    bounds: ComparisonBounds
    added_links: tuple[LinkRef, ...]
    removed_links: tuple[LinkRef, ...]
    reversed_links: tuple[LinkReversal, ...]
    directional_query_deltas: tuple[QueryResultDelta, ...]
    contains_descendant_deltas: tuple[QueryResultDelta, ...]
    attached_anchor_deltas: tuple[QueryResultDelta, ...]
    depends_prerequisite_deltas: tuple[QueryResultDelta, ...]
    blast_radius_deltas: tuple[QueryResultDelta, ...]
    blast_radius_policy: Literal["contains_outgoing+depends_on_incoming.v1"]
    rebuild_pointer: RebuildPointer
    migration_ready: Literal[False]
    graph_mutation_authority: Literal[False]
    migration_execution_authority: Literal[False]
    receipt_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _bounded_ref("migration_revision", self.migration_revision)
        for name, value in (
            ("prior_release_digest", self.prior_release_digest),
            ("aligned_release_digest", self.aligned_release_digest),
            ("legacy_generation_digest", self.legacy_generation_digest),
            ("aligned_generation_digest", self.aligned_generation_digest),
        ):
            _digest_value(name, value)
        canonical_reasons = tuple(sorted(set(self.review_reasons), key=str))
        if canonical_reasons != self.review_reasons:
            raise ValueError("direction shadow review reasons MUST be unique and sorted")
        expected = (
            ComparisonDisposition.REVIEW_REQUIRED
            if self.review_reasons
            else ComparisonDisposition.COMPLETE
        )
        if self.disposition is not expected:
            raise ValueError("direction shadow disposition does not match review reasons")
        object.__setattr__(
            self,
            "receipt_digest",
            content_digest(self.to_mapping(include_digest=False)),
        )

    def to_mapping(self, *, include_digest: bool = True) -> dict[str, object]:
        """Return the canonical replay and review representation."""

        value: dict[str, object] = {
            "added_links": [_link_mapping(item) for item in self.added_links],
            "aligned_generation_digest": self.aligned_generation_digest,
            "aligned_release_digest": self.aligned_release_digest,
            "attached_anchor_deltas": [
                _query_mapping(item) for item in self.attached_anchor_deltas
            ],
            "blast_radius_deltas": [_query_mapping(item) for item in self.blast_radius_deltas],
            "blast_radius_policy": self.blast_radius_policy,
            "bounds": {
                "blast_radius_depth": self.bounds.blast_radius_depth,
                "max_roots": self.bounds.max_roots,
                "traversal_depth": self.bounds.traversal_depth,
            },
            "comparator_version": self.comparator_version,
            "contains_descendant_deltas": [
                _query_mapping(item) for item in self.contains_descendant_deltas
            ],
            "depends_prerequisite_deltas": [
                _query_mapping(item) for item in self.depends_prerequisite_deltas
            ],
            "directional_query_deltas": [
                _query_mapping(item) for item in self.directional_query_deltas
            ],
            "disposition": self.disposition.value,
            "graph_mutation_authority": self.graph_mutation_authority,
            "legacy_generation_digest": self.legacy_generation_digest,
            "migration_execution_authority": self.migration_execution_authority,
            "migration_ready": self.migration_ready,
            "migration_revision": self.migration_revision,
            "prior_release_digest": self.prior_release_digest,
            "rebuild_pointer": {
                "authoritative_generation_ref": (self.rebuild_pointer.authoritative_generation_ref),
                "mutation_authority": self.rebuild_pointer.mutation_authority,
                "rebuild_procedure_ref": self.rebuild_pointer.rebuild_procedure_ref,
                "restores_deleted_rows": self.rebuild_pointer.restores_deleted_rows,
                "strategy": self.rebuild_pointer.strategy,
            },
            "removed_links": [_link_mapping(item) for item in self.removed_links],
            "reversed_links": [
                {"aligned": _link_mapping(item.aligned), "legacy": _link_mapping(item.legacy)}
                for item in self.reversed_links
            ],
            "review_reasons": [reason.value for reason in self.review_reasons],
            "schema_version": self.schema_version,
        }
        if include_digest:
            value["receipt_digest"] = self.receipt_digest
        return value


def _link_mapping(link: LinkRef) -> dict[str, str]:
    return {"from_id": link.from_id, "link_type": link.link_type, "to_id": link.to_id}


def _query_mapping(delta: QueryResultDelta) -> dict[str, object]:
    return {
        "added_ids": list(delta.added_ids),
        "aligned_ids": list(delta.aligned_ids),
        "aligned_truncated": delta.aligned_truncated,
        "legacy_ids": list(delta.legacy_ids),
        "legacy_truncated": delta.legacy_truncated,
        "query": delta.query,
        "removed_ids": list(delta.removed_ids),
        "root_id": delta.root_id,
    }


def _bounded_ref(name: str, value: str) -> None:
    if not value or len(value) > _MAX_REF_LENGTH or any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} MUST be a bounded non-empty reference")


def _digest_value(name: str, value: str) -> None:
    if _DIGEST_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} MUST be a sha256 digest")


__all__ = [
    "ComparisonBounds",
    "ComparisonDisposition",
    "DirectionGraphGeneration",
    "DirectionGraphLink",
    "DirectionShadowReceipt",
    "LinkRef",
    "LinkReversal",
    "QueryResultDelta",
    "RebuildPointer",
    "ReviewReason",
]
