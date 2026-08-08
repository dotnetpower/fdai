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

from .models import OperationalContextEvidencePath


class EvidenceLane(StrEnum):
    """Authority-separated evidence lane in a materialized bundle."""

    ONTOLOGY = "ontology"
    STATE = "state"
    CATALOG = "catalog"
    DOCUMENT = "document"


@dataclass(frozen=True, slots=True)
class EvidenceSourceMetadata:
    """Source authority, revision, cutoff, freshness, completeness, and redaction."""

    authority: str
    source_identity: str
    source_revision: str
    cutoff: datetime
    freshness_ceiling_seconds: int
    completeness: float
    redaction: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("authority", self.authority),
            ("source_identity", self.source_identity),
            ("source_revision", self.source_revision),
            ("redaction", self.redaction),
        ):
            if not value.strip():
                raise ValueError(f"EvidenceSourceMetadata.{field_name} MUST be non-empty")
        if self.cutoff.tzinfo is None:
            raise ValueError("EvidenceSourceMetadata.cutoff MUST be timezone-aware")
        if isinstance(self.freshness_ceiling_seconds, bool) or not isinstance(
            self.freshness_ceiling_seconds, int
        ):
            raise ValueError("freshness_ceiling_seconds MUST be an integer")
        if self.freshness_ceiling_seconds < 1:
            raise ValueError("freshness_ceiling_seconds MUST be >= 1")
        if isinstance(self.completeness, bool) or not isinstance(self.completeness, (int, float)):
            raise ValueError("completeness MUST be numeric")
        if not 0.0 <= self.completeness <= 1.0:
            raise ValueError("completeness MUST be between 0 and 1")

    def to_mapping(self) -> dict[str, object]:
        """Return the canonical source envelope used by bundle identity."""

        return {
            "authority": self.authority,
            "completeness": self.completeness,
            "cutoff": utc_timestamp(self.cutoff),
            "freshness_ceiling_seconds": self.freshness_ceiling_seconds,
            "redaction": self.redaction,
            "source_identity": self.source_identity,
            "source_revision": self.source_revision,
        }


@dataclass(frozen=True, slots=True)
class ClaimRecord:
    """One exact typed claim with canonical value and cited evidence references."""

    claim_id: str
    subject: str
    predicate: str
    cutoff_scope: str
    canonical_value: str
    citation_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name, value in (
            ("claim_id", self.claim_id),
            ("subject", self.subject),
            ("predicate", self.predicate),
            ("cutoff_scope", self.cutoff_scope),
        ):
            if not value.strip():
                raise ValueError(f"ClaimRecord.{field_name} MUST be non-empty")
        canonical = canonical_json(json.loads(self.canonical_value))
        if canonical != self.canonical_value:
            raise ValueError("ClaimRecord.canonical_value MUST use canonical JSON")
        citations = tuple(sorted(set(self.citation_refs)))
        if any(not item.strip() for item in citations):
            raise ValueError("ClaimRecord.citation_refs MUST contain non-empty values")
        object.__setattr__(self, "citation_refs", citations)
        if self.claim_id != self.expected_id():
            raise ValueError("ClaimRecord.claim_id MUST match the canonical claim digest")

    @classmethod
    def create(
        cls,
        *,
        subject: str,
        predicate: str,
        value: Any,
        cutoff_scope: str,
        citation_refs: tuple[str, ...],
    ) -> ClaimRecord:
        """Create a content-addressed claim from a JSON-compatible typed value."""

        canonical_value = canonical_json(value)
        citations = tuple(sorted(set(citation_refs)))
        payload = (subject, predicate, cutoff_scope, canonical_value, citations)
        claim_id = f"claim:sha256:{digest_json(payload)}"
        return cls(
            claim_id=claim_id,
            subject=subject,
            predicate=predicate,
            cutoff_scope=cutoff_scope,
            canonical_value=canonical_value,
            citation_refs=citations,
        )

    def expected_id(self) -> str:
        """Return the identity implied by this claim's canonical fields."""

        payload = (
            self.subject,
            self.predicate,
            self.cutoff_scope,
            self.canonical_value,
            self.citation_refs,
        )
        return f"claim:sha256:{digest_json(payload)}"

    def to_mapping(self) -> dict[str, object]:
        """Return the canonical claim representation."""

        return {
            "canonical_value": self.canonical_value,
            "citation_refs": self.citation_refs,
            "claim_id": self.claim_id,
            "cutoff_scope": self.cutoff_scope,
            "predicate": self.predicate,
            "subject": self.subject,
        }


@dataclass(frozen=True, slots=True)
class OntologyEvidenceItem:
    """One secured ontology fact path and its source envelope."""

    evidence_ref: str
    source: EvidenceSourceMetadata
    path: OperationalContextEvidencePath

    def __post_init__(self) -> None:
        require_ref(self.evidence_ref)


@dataclass(frozen=True, slots=True)
class StateEvidenceItem:
    """One authoritative state fact with its original lane metadata."""

    evidence_ref: str
    state_fact: StateFactMetadata
    redaction: str

    def __post_init__(self) -> None:
        require_ref(self.evidence_ref)
        if not self.redaction.strip():
            raise ValueError("StateEvidenceItem.redaction MUST be non-empty")

    @property
    def source(self) -> EvidenceSourceMetadata:
        """Project the state-fact envelope without changing its lane or authority."""

        return EvidenceSourceMetadata(
            authority=f"{self.state_fact.lane.value}:{self.state_fact.authority.value}",
            source_identity=self.state_fact.source_identity,
            source_revision=self.state_fact.source_revision,
            cutoff=self.state_fact.evidence_cutoff,
            freshness_ceiling_seconds=self.state_fact.freshness_ceiling_seconds,
            completeness=self.state_fact.completeness,
            redaction=self.redaction,
        )


@dataclass(frozen=True, slots=True)
class CatalogEvidenceItem:
    """One exact catalog or rule reference and its source envelope."""

    evidence_ref: str
    source: EvidenceSourceMetadata
    catalog_ref: str

    def __post_init__(self) -> None:
        require_ref(self.evidence_ref)
        require_ref(self.catalog_ref)


@dataclass(frozen=True, slots=True)
class DocumentEvidenceExcerpt:
    """One governed document excerpt treated only as untrusted evidence data."""

    evidence_ref: str
    source: EvidenceSourceMetadata
    document_ref: str
    excerpt_id: str
    text: str
    instruction_authority: Literal[False] = False

    def __post_init__(self) -> None:
        for value in (self.evidence_ref, self.document_ref, self.excerpt_id):
            require_ref(value)
        if not self.text:
            raise ValueError("DocumentEvidenceExcerpt.text MUST be non-empty")
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
    redaction: str


@dataclass(frozen=True, slots=True)
class EvidenceConflict:
    """One deterministic conflict with the exact scope and involved values."""

    kind: str
    scope: str
    claim_ids: tuple[str, ...]
    canonical_values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OperationalEvidenceBundle:
    """Content-addressed hold-only evidence context with no action authority."""

    bundle_id: str
    digest: str
    cutoff: datetime
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
        if self.cutoff.tzinfo is None:
            raise ValueError("OperationalEvidenceBundle.cutoff MUST be timezone-aware")
        if self.grants_action_authority is not False:
            raise ValueError("operational evidence bundles MUST NOT grant action authority")
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


def utc_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "CatalogEvidenceItem",
    "CitationManifestEntry",
    "ClaimRecord",
    "DocumentEvidenceExcerpt",
    "EvidenceConflict",
    "EvidenceLane",
    "EvidenceSourceMetadata",
    "OntologyEvidenceItem",
    "OperationalEvidenceBundle",
    "StateEvidenceItem",
]
