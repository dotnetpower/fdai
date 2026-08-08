"""Immutable contracts for graph, state, catalog, and document evidence bundles."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from fdai.shared.contracts.models import Autonomy
from fdai.shared.providers.state_evidence import StateFactMetadata

from .evidence_bundle_sources import EvidenceTemporalScope, VerifiedEvidenceSourceReceipt
from .models import OperationalContextEvidencePath

_MAX_REF_LENGTH = 512
_MAX_CLAIM_VALUE_BYTES = 65_536
_MAX_CITATIONS_PER_CLAIM = 64
_MAX_DOCUMENT_TEXT_BYTES = 65_536


class EvidenceLane(StrEnum):
    """Authority-separated evidence lane in a materialized bundle."""

    ONTOLOGY = "ontology"
    STATE = "state"
    CATALOG = "catalog"
    DOCUMENT = "document"


@dataclass(frozen=True, slots=True)
class CitationBinding:
    """Exact evidence item identity bound into a claim digest."""

    evidence_ref: str
    item_digest: str
    source_revision: str

    def __post_init__(self) -> None:
        require_ref(self.evidence_ref)
        require_ref(self.source_revision)
        if not self.item_digest.startswith("sha256:") or len(self.item_digest) != 71:
            raise ValueError("CitationBinding.item_digest MUST be a SHA-256 digest")

    def to_mapping(self) -> dict[str, str]:
        """Return the canonical citation identity."""

        return {
            "evidence_ref": self.evidence_ref,
            "item_digest": self.item_digest,
            "source_revision": self.source_revision,
        }


@dataclass(frozen=True, slots=True)
class ClaimRecord:
    """One exact typed claim with canonical value and cited evidence references."""

    claim_id: str
    subject: str
    predicate: str
    temporal_scope: EvidenceTemporalScope
    canonical_value: str
    citations: tuple[CitationBinding, ...]

    def __post_init__(self) -> None:
        for field_name, value in (
            ("claim_id", self.claim_id),
            ("subject", self.subject),
            ("predicate", self.predicate),
        ):
            if not value.strip() or len(value) > _MAX_REF_LENGTH:
                raise ValueError(f"ClaimRecord.{field_name} MUST be non-empty")
        canonical = canonical_json(json.loads(self.canonical_value))
        if canonical != self.canonical_value:
            raise ValueError("ClaimRecord.canonical_value MUST use canonical JSON")
        if len(self.canonical_value.encode()) > _MAX_CLAIM_VALUE_BYTES:
            raise ValueError("ClaimRecord.canonical_value exceeds byte limit")
        citations = tuple(
            sorted(
                set(self.citations),
                key=lambda item: (item.evidence_ref, item.item_digest, item.source_revision),
            )
        )
        if len(citations) > _MAX_CITATIONS_PER_CLAIM:
            raise ValueError("ClaimRecord.citations exceeds item limit")
        object.__setattr__(self, "citations", citations)
        if self.claim_id != self.expected_id():
            raise ValueError("ClaimRecord.claim_id MUST match the canonical claim digest")

    @classmethod
    def create(
        cls,
        *,
        subject: str,
        predicate: str,
        value: Any,
        temporal_scope: EvidenceTemporalScope,
        citations: tuple[CitationBinding, ...],
    ) -> ClaimRecord:
        """Create a content-addressed claim from a JSON-compatible typed value."""

        canonical_value = canonical_json(value)
        canonical_citations = tuple(
            sorted(
                set(citations),
                key=lambda item: (item.evidence_ref, item.item_digest, item.source_revision),
            )
        )
        payload = (
            subject,
            predicate,
            temporal_scope.to_mapping(),
            canonical_value,
            tuple(item.to_mapping() for item in canonical_citations),
        )
        claim_id = f"claim:sha256:{digest_json(payload)}"
        return cls(
            claim_id=claim_id,
            subject=subject,
            predicate=predicate,
            temporal_scope=temporal_scope,
            canonical_value=canonical_value,
            citations=canonical_citations,
        )

    @property
    def citation_refs(self) -> tuple[str, ...]:
        """Return cited references for diagnostics without weakening claim identity."""

        return tuple(item.evidence_ref for item in self.citations)

    def expected_id(self) -> str:
        """Return the identity implied by this claim's canonical fields."""

        payload = (
            self.subject,
            self.predicate,
            self.temporal_scope.to_mapping(),
            self.canonical_value,
            tuple(item.to_mapping() for item in self.citations),
        )
        return f"claim:sha256:{digest_json(payload)}"

    def to_mapping(self) -> dict[str, object]:
        """Return the canonical claim representation."""

        return {
            "canonical_value": self.canonical_value,
            "citations": tuple(item.to_mapping() for item in self.citations),
            "claim_id": self.claim_id,
            "predicate": self.predicate,
            "subject": self.subject,
            "temporal_scope": self.temporal_scope.to_mapping(),
        }


@dataclass(frozen=True, slots=True)
class OntologyEvidenceItem:
    """One secured ontology fact path and its source envelope."""

    evidence_ref: str
    source: VerifiedEvidenceSourceReceipt
    target_object_id: str
    path: OperationalContextEvidencePath

    def __post_init__(self) -> None:
        require_ref(self.evidence_ref)
        require_ref(self.target_object_id)
        _validate_path_closure(target_object_id=self.target_object_id, path=self.path)


@dataclass(frozen=True, slots=True)
class StateEvidenceItem:
    """One authoritative state fact with its original lane metadata."""

    evidence_ref: str
    state_fact: StateFactMetadata
    source: VerifiedEvidenceSourceReceipt

    def __post_init__(self) -> None:
        require_ref(self.evidence_ref)
        if self.source.source_identity != self.state_fact.source_identity:
            raise ValueError("state source receipt identity does not match state fact")
        if self.source.source_revision != self.state_fact.source_revision:
            raise ValueError("state source receipt revision does not match state fact")
        temporal = self.source.temporal_scope
        if (
            temporal.effective_from != self.state_fact.effective_at
            or temporal.evidence_cutoff != self.state_fact.evidence_cutoff
            or temporal.recorded_at != self.state_fact.recorded_at
        ):
            raise ValueError("state source receipt temporal scope does not match state fact")
        if (
            self.source.freshness_ceiling_seconds != self.state_fact.freshness_ceiling_seconds
            or self.source.completeness != self.state_fact.completeness
            or self.source.synthetic is not self.state_fact.synthetic
            or self.source.conflicts != self.state_fact.conflicts
        ):
            raise ValueError("state source receipt quality does not match state fact")


@dataclass(frozen=True, slots=True)
class CatalogEvidenceItem:
    """One exact catalog or rule reference and its source envelope."""

    evidence_ref: str
    source: VerifiedEvidenceSourceReceipt
    catalog_ref: str

    def __post_init__(self) -> None:
        require_ref(self.evidence_ref)
        require_ref(self.catalog_ref)


@dataclass(frozen=True, slots=True)
class DocumentEvidenceExcerpt:
    """One governed document excerpt treated only as untrusted evidence data."""

    evidence_ref: str
    source: VerifiedEvidenceSourceReceipt
    document_ref: str
    excerpt_id: str
    text: str
    instruction_authority: Literal[False] = False

    def __post_init__(self) -> None:
        for value in (self.evidence_ref, self.document_ref, self.excerpt_id):
            require_ref(value)
        if not self.text:
            raise ValueError("DocumentEvidenceExcerpt.text MUST be non-empty")
        if len(self.text.encode()) > _MAX_DOCUMENT_TEXT_BYTES:
            raise ValueError("DocumentEvidenceExcerpt.text exceeds byte limit")
        if self.source.document_revision is None:
            raise ValueError("document evidence source receipt MUST pin document revision")
        if self.instruction_authority is not False:
            raise ValueError("document excerpts MUST NOT have instruction authority")


@dataclass(frozen=True, slots=True)
class CitationManifestEntry:
    """Content-addressed citation target for one included evidence item."""

    evidence_ref: str
    lane: EvidenceLane
    item_digest: str
    source_revision: str
    cutoff: datetime
    redaction_summary: tuple[str, ...]

    def __post_init__(self) -> None:
        require_ref(self.evidence_ref)
        require_ref(self.source_revision)
        object.__setattr__(self, "redaction_summary", tuple(self.redaction_summary))


@dataclass(frozen=True, slots=True)
class EvidenceConflict:
    """One deterministic conflict with the exact scope and involved values."""

    kind: str
    scope: str
    claim_ids: tuple[str, ...]
    canonical_values: tuple[str, ...]

    def __post_init__(self) -> None:
        require_ref(self.kind)
        require_ref(self.scope)
        object.__setattr__(self, "claim_ids", tuple(self.claim_ids))
        object.__setattr__(self, "canonical_values", tuple(self.canonical_values))


@dataclass(frozen=True, slots=True)
class OperationalEvidenceBundle:
    """Content-addressed hold-only evidence context with no action authority."""

    bundle_id: str
    digest: str
    cutoff: datetime
    trusted_recorded_at: datetime
    ontology_release_digest: str
    catalog_revision: str
    purpose: str
    scope: tuple[str, ...]
    claims: tuple[ClaimRecord, ...]
    ontology: tuple[OntologyEvidenceItem, ...]
    state: tuple[StateEvidenceItem, ...]
    catalog: tuple[CatalogEvidenceItem, ...]
    documents: tuple[DocumentEvidenceExcerpt, ...]
    citation_manifest: tuple[CitationManifestEntry, ...]
    conflicts: tuple[EvidenceConflict, ...]
    missing_paths: tuple[str, ...]
    evidence_issues: tuple[str, ...]
    hold_reasons: tuple[str, ...]
    max_items: int
    max_bytes: int
    used_items: int
    used_bytes: int
    autonomy_ceiling: Autonomy
    grants_action_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.cutoff.tzinfo is None or self.trusted_recorded_at.tzinfo is None:
            raise ValueError("OperationalEvidenceBundle timestamps MUST be timezone-aware")
        if self.cutoff > self.trusted_recorded_at:
            raise ValueError("bundle cutoff MUST NOT exceed trusted recorded time")
        for field_name in (
            "claims",
            "ontology",
            "state",
            "catalog",
            "documents",
            "citation_manifest",
            "conflicts",
            "missing_paths",
            "evidence_issues",
            "hold_reasons",
            "scope",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
        if self.grants_action_authority is not False:
            raise ValueError("operational evidence bundles MUST NOT grant action authority")
        if self.used_bytes > self.max_bytes:
            raise ValueError("canonical bundle body exceeds max_bytes")
        if self.bundle_id != f"operational-evidence-bundle:{self.digest}":
            raise ValueError("OperationalEvidenceBundle.bundle_id MUST match digest")
        from .evidence_bundle_identity import compute_bundle_digest

        if self.digest != compute_bundle_digest(self):
            raise ValueError("OperationalEvidenceBundle.digest MUST match canonical content")

    @property
    def hold_required(self) -> bool:
        """Return whether deterministic validation requires a no-action hold."""

        return bool(self.hold_reasons)


def canonical_json(value: Any) -> str:
    """Encode a JSON value canonically and reject non-finite or unsupported values."""

    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("claim value MUST be canonical JSON") from exc


def digest_json(value: Any) -> str:
    """Return a SHA-256 digest over canonical JSON."""

    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def require_ref(value: str) -> None:
    if not value.strip():
        raise ValueError("evidence references MUST be non-empty")
    if len(value) > _MAX_REF_LENGTH:
        raise ValueError("evidence reference exceeds length limit")


def _validate_path_closure(
    *,
    target_object_id: str,
    path: OperationalContextEvidencePath,
) -> None:
    links = tuple(path.links)
    if path.object_id == target_object_id:
        if links:
            raise ValueError("target self path MUST NOT contain links")
        return
    if not links:
        raise ValueError("ontology evidence path MUST connect target to object")
    if links[0].from_id != target_object_id or links[-1].to_id != path.object_id:
        raise ValueError("ontology evidence path endpoints do not match target and object")
    visited = {target_object_id}
    prior = target_object_id
    for link in links:
        if link.from_id != prior:
            raise ValueError("ontology evidence path links MUST form a closed chain")
        if link.to_id in visited:
            raise ValueError("ontology evidence path MUST NOT contain cycles")
        visited.add(link.to_id)
        prior = link.to_id


def utc_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "CatalogEvidenceItem",
    "CitationBinding",
    "CitationManifestEntry",
    "ClaimRecord",
    "DocumentEvidenceExcerpt",
    "EvidenceConflict",
    "EvidenceLane",
    "OntologyEvidenceItem",
    "OperationalEvidenceBundle",
    "StateEvidenceItem",
]
