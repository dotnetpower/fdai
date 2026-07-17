"""Data contracts for deterministic screen-claim verification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ClaimKind = Literal["id", "number", "percentage", "timestamp", "causal", "scope"]
ClaimStatus = Literal["supported", "unsupported", "ambiguous"]


@dataclass(frozen=True, slots=True)
class EvidenceEntry:
    ref: str
    path: str
    field: str
    kind: str
    raw_value: str
    normalized_value: str
    anchors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "path": self.path,
            "field": self.field,
            "kind": self.kind,
            "raw_value": self.raw_value,
            "normalized_value": self.normalized_value,
            "anchors": list(self.anchors),
        }


@dataclass(frozen=True, slots=True)
class AtomicClaim:
    claim_id: str
    kind: ClaimKind
    text: str
    start: int
    end: int
    raw_value: str
    normalized_value: str
    unit: str | None
    anchors: tuple[str, ...]
    status: ClaimStatus
    evidence_refs: tuple[str, ...]
    reason_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "kind": self.kind,
            "text": self.text,
            "span": {"start": self.start, "end": self.end},
            "raw_value": self.raw_value,
            "normalized_value": self.normalized_value,
            "unit": self.unit,
            "anchors": list(self.anchors),
            "status": self.status,
            "evidence_refs": list(self.evidence_refs),
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True, slots=True)
class EvidenceManifest:
    schema_version: int
    manifest_id: str
    authority: str
    route_id: str | None
    captured_at: str | None
    complete: bool
    source_entry_count: int
    entries: tuple[EvidenceEntry, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "authority": self.authority,
            "route_id": self.route_id,
            "captured_at": self.captured_at,
            "complete": self.complete,
            "source_entry_count": self.source_entry_count,
            "entries": [entry.to_dict() for entry in self.entries],
        }


@dataclass(frozen=True, slots=True)
class ScreenClaimResult:
    claims: tuple[AtomicClaim, ...]
    manifest: EvidenceManifest
    overflow: bool = False

    @property
    def failed_claim_ids(self) -> tuple[str, ...]:
        return tuple(claim.claim_id for claim in self.claims if claim.status != "supported")

    @property
    def supported(self) -> bool:
        return not self.overflow and not self.failed_claim_ids


@dataclass(frozen=True, slots=True)
class ClaimDraft:
    kind: ClaimKind
    text: str
    start: int
    end: int
    raw_value: str
    normalized_value: str
    unit: str | None
    anchors: tuple[str, ...]
