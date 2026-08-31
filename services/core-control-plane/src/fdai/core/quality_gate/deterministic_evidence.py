"""Typed independent evidence required before a T2 candidate can become eligible."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from fdai.core.quality_gate.gate import QualityCandidate


class DeterministicEvidenceKind(StrEnum):
    """Mandatory independent verifier evidence families."""

    WHAT_IF = "what_if"
    SECURITY = "security"


class DeterministicEvidenceStatus(StrEnum):
    """Evidence outcome before the quality gate applies freshness and lineage checks."""

    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    CONFLICT = "conflict"


_EXPECTED_AUTHORITY = {
    DeterministicEvidenceKind.WHAT_IF: "simulation_engine",
    DeterministicEvidenceKind.SECURITY: "security_scanner",
}


@dataclass(frozen=True, slots=True)
class DeterministicVerifierEvidence:
    """Versioned evidence from a deterministic authority independent of T2 output."""

    schema_version: str
    kind: DeterministicEvidenceKind
    status: DeterministicEvidenceStatus
    candidate_digest: str
    source_authority: str
    producer_id: str
    observed_at: datetime
    expires_at: datetime
    evidence_refs: tuple[str, ...] = ()
    synthetic: bool = False
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("deterministic evidence schema_version MUST be 1.0.0")
        if self.source_authority != _EXPECTED_AUTHORITY[self.kind]:
            raise ValueError("deterministic evidence source authority does not match its kind")
        if not self.producer_id.strip() or len(self.producer_id) > 128:
            raise ValueError("deterministic evidence producer_id MUST be bounded text")
        if not _is_digest(self.candidate_digest):
            raise ValueError("deterministic evidence candidate_digest MUST be SHA-256")
        if self.observed_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("deterministic evidence timestamps MUST include timezone")
        if self.expires_at < self.observed_at:
            raise ValueError("deterministic evidence expires_at MUST not precede observed_at")
        if self.status is DeterministicEvidenceStatus.PASSED and not self.evidence_refs:
            raise ValueError("passed deterministic evidence MUST cite at least one evidence ref")
        if (
            len(self.evidence_refs) > 64
            or len(self.evidence_refs) != len(set(self.evidence_refs))
            or any(not item.strip() or len(item) > 512 for item in self.evidence_refs)
        ):
            raise ValueError("deterministic evidence refs MUST be bounded and unique")
        if self.reason is not None and (not self.reason.strip() or len(self.reason) > 512):
            raise ValueError("deterministic evidence reason MUST be bounded text")


@runtime_checkable
class DeterministicEvidenceVerifier(Protocol):
    """Produce one evidence family without model, decision, or execution authority."""

    @property
    def kind(self) -> DeterministicEvidenceKind: ...

    def verify(self, candidate: QualityCandidate) -> DeterministicVerifierEvidence: ...


@dataclass(frozen=True, slots=True)
class UnavailableDeterministicEvidenceVerifier:
    """Safe runtime default until an authoritative producer is injected."""

    kind: DeterministicEvidenceKind
    reason: str

    def verify(self, candidate: QualityCandidate) -> DeterministicVerifierEvidence:
        now = datetime.now(tz=UTC)
        return DeterministicVerifierEvidence(
            schema_version="1.0.0",
            kind=self.kind,
            status=DeterministicEvidenceStatus.UNAVAILABLE,
            candidate_digest=quality_candidate_digest(candidate),
            source_authority=_EXPECTED_AUTHORITY[self.kind],
            producer_id="unbound",
            observed_at=now,
            expires_at=now,
            reason=self.reason,
        )


def quality_candidate_digest(candidate: QualityCandidate) -> str:
    """Return the core-owned digest that evidence must bind exactly."""

    payload = json.dumps(
        {
            "action_type": candidate.action_type,
            "target_resource_ref": candidate.target_resource_ref,
            "target_resource_type": candidate.target_resource_type,
            "params": candidate.params,
            "cited_rule_ids": list(candidate.cited_rule_ids),
        },
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def expected_evidence_authority(kind: DeterministicEvidenceKind) -> str:
    """Return the fixed authority class for one evidence family."""

    return _EXPECTED_AUTHORITY[kind]


def _is_digest(value: str) -> bool:
    prefix = "sha256:"
    digest = value.removeprefix(prefix)
    return (
        value.startswith(prefix)
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
    )


__all__ = [
    "DeterministicEvidenceKind",
    "DeterministicEvidenceStatus",
    "DeterministicEvidenceVerifier",
    "DeterministicVerifierEvidence",
    "UnavailableDeterministicEvidenceVerifier",
    "expected_evidence_authority",
    "quality_candidate_digest",
]
