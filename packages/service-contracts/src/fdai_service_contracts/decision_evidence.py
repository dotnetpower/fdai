"""Canonical evidence envelope for decision-critical observations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from fdai_service_contracts.executor_models import ContractBase, Digest, SemVer
from fdai_service_contracts.ontology_query import content_digest

EvidenceId = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_.-]{0,127}$"),
]
SourceIdentity = Annotated[
    str,
    Field(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,511}$"),
]
BasisPoints = Annotated[int, Field(strict=True, ge=0, le=10_000)]
_MAX_AUTHORITY_CLASSES = 16
_MAX_SOURCE_IDENTITIES = 32
_MAX_CONFLICTS = 32


class EvidenceConflictStatus(StrEnum):
    """Conflict disposition claimed by a separately verifiable evidence set."""

    CLEAR = "clear"
    CONFLICTING = "conflicting"
    UNKNOWN = "unknown"


class _DecisionCriticalEvidenceReceiptBody(ContractBase):
    schema_version: Literal["1.0.0"]
    authority_class: EvidenceId
    source_identity: SourceIdentity
    authentication_evidence_digest: Digest
    scope_digest: Digest
    purpose_id: EvidenceId
    producer_id: EvidenceId
    producer_version: SemVer
    method_id: EvidenceId
    method_version: SemVer
    source_revision: SourceIdentity
    evidence_digest: Digest
    provenance_digest: Digest
    event_at: datetime
    evidence_cutoff: datetime
    recorded_at: datetime
    fresh_until: datetime
    freshness_policy_id: EvidenceId
    freshness_policy_version: SemVer
    freshness_policy_digest: Digest
    freshness_ceiling_seconds: Annotated[int, Field(strict=True, ge=1, le=31_536_000)]
    completeness_basis_points: BasisPoints
    completeness_evidence_digest: Digest
    conflict_status: EvidenceConflictStatus
    conflict_evidence_digest: Digest
    conflict_evidence_digests: Annotated[tuple[Digest, ...], Field(max_length=_MAX_CONFLICTS)] = ()
    synthetic: bool
    execution_authority: Literal[False]

    @field_validator("event_at", "evidence_cutoff", "recorded_at", "fresh_until")
    @classmethod
    def _normalize_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("decision-critical evidence timestamps MUST include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _validate_evidence_window(self) -> _DecisionCriticalEvidenceReceiptBody:
        if self.event_at > self.evidence_cutoff:
            raise ValueError("evidence event time MUST NOT exceed its cutoff")
        if self.evidence_cutoff > self.recorded_at:
            raise ValueError("evidence cutoff MUST NOT exceed recorded time")
        expected_fresh_until = self.evidence_cutoff + timedelta(
            seconds=self.freshness_ceiling_seconds
        )
        if self.fresh_until != expected_fresh_until:
            raise ValueError("evidence freshness MUST match the policy-derived ceiling")
        if self.conflict_evidence_digests != tuple(sorted(self.conflict_evidence_digests)):
            raise ValueError("conflict evidence digests MUST be unique and ordered")
        if len(self.conflict_evidence_digests) != len(set(self.conflict_evidence_digests)):
            raise ValueError("conflict evidence digests MUST be unique and ordered")
        if (self.conflict_status is EvidenceConflictStatus.CONFLICTING) != bool(
            self.conflict_evidence_digests
        ):
            raise ValueError("conflict status does not match the cited conflict evidence")
        return self


class DecisionCriticalEvidenceReceipt(_DecisionCriticalEvidenceReceiptBody):
    """Bind evidence, authority, provenance, time, and completeness without granting authority."""

    receipt_digest: Digest

    @model_validator(mode="after")
    def _validate_receipt_digest(self) -> DecisionCriticalEvidenceReceipt:
        expected = content_digest(self.model_dump(mode="json", exclude={"receipt_digest"}))
        if self.receipt_digest != expected:
            raise ValueError("decision-critical evidence receipt digest does not match its content")
        return self


class LiveEvidenceClaimRequirement(ContractBase):
    """Expected identity, method, scope, and freshness for claim preflight."""

    allowed_authority_classes: Annotated[
        tuple[EvidenceId, ...],
        Field(min_length=1, max_length=_MAX_AUTHORITY_CLASSES),
    ]
    allowed_source_identities: Annotated[
        tuple[SourceIdentity, ...],
        Field(min_length=1, max_length=_MAX_SOURCE_IDENTITIES),
    ]
    scope_digest: Digest
    purpose_id: EvidenceId
    producer_id: EvidenceId
    producer_version: SemVer
    method_id: EvidenceId
    method_version: SemVer
    source_revision: SourceIdentity
    freshness_policy_digest: Digest
    freshness_ceiling_seconds: Annotated[int, Field(strict=True, ge=1, le=31_536_000)]
    minimum_completeness_basis_points: BasisPoints = 10_000

    @model_validator(mode="after")
    def _validate_canonical_policy(self) -> LiveEvidenceClaimRequirement:
        for field_name, values in (
            ("allowed authority classes", self.allowed_authority_classes),
            ("allowed source identities", self.allowed_source_identities),
        ):
            if values != tuple(sorted(values)) or len(values) != len(set(values)):
                raise ValueError(f"{field_name} MUST be unique and ordered")
        return self


class LiveEvidenceClaimRejectionReason(StrEnum):
    """Why a receipt cannot proceed to authoritative live-evidence verification."""

    AUTHORITY_MISMATCH = "authority_mismatch"
    CONFLICTING = "conflicting"
    INCOMPLETE = "incomplete"
    METHOD_MISMATCH = "method_mismatch"
    NOT_YET_RECORDED = "not_yet_recorded"
    POLICY_MISMATCH = "policy_mismatch"
    PRODUCER_MISMATCH = "producer_mismatch"
    PURPOSE_MISMATCH = "purpose_mismatch"
    SCOPE_MISMATCH = "scope_mismatch"
    SOURCE_REVISION_MISMATCH = "source_revision_mismatch"
    SOURCE_MISMATCH = "source_mismatch"
    STALE = "stale"
    SYNTHETIC = "synthetic"


class LiveEvidenceClaimAssessment(ContractBase):
    """Preflight result that never proves authentication, evidence, or readiness."""

    evaluated_at: datetime
    eligible_for_verification: bool
    rejection_reasons: tuple[LiveEvidenceClaimRejectionReason, ...]

    @field_validator("evaluated_at")
    @classmethod
    def _normalize_evaluated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("live evidence evaluation time MUST include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _validate_result(self) -> LiveEvidenceClaimAssessment:
        if self.rejection_reasons != tuple(sorted(set(self.rejection_reasons), key=str)):
            raise ValueError("live evidence rejection reasons MUST be unique and ordered")
        if self.eligible_for_verification == bool(self.rejection_reasons):
            raise ValueError("live evidence preflight result does not match its reasons")
        return self


def decision_critical_evidence_receipt_digest(**values: object) -> str:
    """Return the canonical digest for a decision-critical evidence receipt body."""

    body = dict(values)
    body.pop("receipt_digest", None)
    candidate = _DecisionCriticalEvidenceReceiptBody.model_validate(body)
    return content_digest(candidate.model_dump(mode="json"))


def assess_live_evidence_claim(
    receipt: DecisionCriticalEvidenceReceipt,
    requirement: LiveEvidenceClaimRequirement,
    *,
    evaluated_at: datetime,
) -> LiveEvidenceClaimAssessment:
    """Reject an invalid claim or pass it to separate authoritative verification."""

    normalized_evaluated_at = LiveEvidenceClaimAssessment._normalize_evaluated_at(evaluated_at)
    reasons: set[LiveEvidenceClaimRejectionReason] = set()
    if receipt.authority_class not in requirement.allowed_authority_classes:
        reasons.add(LiveEvidenceClaimRejectionReason.AUTHORITY_MISMATCH)
    if receipt.source_identity not in requirement.allowed_source_identities:
        reasons.add(LiveEvidenceClaimRejectionReason.SOURCE_MISMATCH)
    if receipt.scope_digest != requirement.scope_digest:
        reasons.add(LiveEvidenceClaimRejectionReason.SCOPE_MISMATCH)
    if receipt.purpose_id != requirement.purpose_id:
        reasons.add(LiveEvidenceClaimRejectionReason.PURPOSE_MISMATCH)
    if (receipt.producer_id, receipt.producer_version) != (
        requirement.producer_id,
        requirement.producer_version,
    ):
        reasons.add(LiveEvidenceClaimRejectionReason.PRODUCER_MISMATCH)
    if (receipt.method_id, receipt.method_version) != (
        requirement.method_id,
        requirement.method_version,
    ):
        reasons.add(LiveEvidenceClaimRejectionReason.METHOD_MISMATCH)
    if receipt.source_revision != requirement.source_revision:
        reasons.add(LiveEvidenceClaimRejectionReason.SOURCE_REVISION_MISMATCH)
    if (
        receipt.freshness_policy_digest != requirement.freshness_policy_digest
        or receipt.freshness_ceiling_seconds != requirement.freshness_ceiling_seconds
    ):
        reasons.add(LiveEvidenceClaimRejectionReason.POLICY_MISMATCH)
    if receipt.completeness_basis_points < requirement.minimum_completeness_basis_points:
        reasons.add(LiveEvidenceClaimRejectionReason.INCOMPLETE)
    if receipt.conflict_status is not EvidenceConflictStatus.CLEAR:
        reasons.add(LiveEvidenceClaimRejectionReason.CONFLICTING)
    if receipt.synthetic:
        reasons.add(LiveEvidenceClaimRejectionReason.SYNTHETIC)
    if normalized_evaluated_at < receipt.recorded_at:
        reasons.add(LiveEvidenceClaimRejectionReason.NOT_YET_RECORDED)
    if normalized_evaluated_at > receipt.fresh_until:
        reasons.add(LiveEvidenceClaimRejectionReason.STALE)
    ordered_reasons = tuple(sorted(reasons, key=str))
    return LiveEvidenceClaimAssessment(
        evaluated_at=normalized_evaluated_at,
        eligible_for_verification=not ordered_reasons,
        rejection_reasons=ordered_reasons,
    )


__all__ = [
    "DecisionCriticalEvidenceReceipt",
    "EvidenceConflictStatus",
    "LiveEvidenceClaimAssessment",
    "LiveEvidenceClaimRejectionReason",
    "LiveEvidenceClaimRequirement",
    "assess_live_evidence_claim",
    "decision_critical_evidence_receipt_digest",
]
