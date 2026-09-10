"""Authoritative recovery effect completion claims (#656).

Independently verify a recovery effect and persist one content-addressed
completion claim that a later release transaction can consume.  The claim
grants no execution authority and becomes ineligible when evidence is
incomplete, synthetic, stale, conflicting, or outside the approved impact
envelope.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from fdai_service_contracts.ontology_query import content_digest

_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")


# ---------------------------------------------------------------------------
# Evidence classification
# ---------------------------------------------------------------------------


class EffectEvidenceClass(StrEnum):
    """Observation authority class for effect verification."""

    AUTHORITATIVE_EXTERNAL = "authoritative_external"
    EXECUTOR_CONTROLLED = "executor_controlled"
    PROVIDER_DISPATCH = "provider_dispatch"
    SYNTHETIC = "synthetic"
    STALE = "stale"
    CONFLICTING = "conflicting"
    CENSORED = "censored"
    INCOMPLETE = "incomplete"
    OUT_OF_ENVELOPE = "out_of_envelope"
    MISSING = "missing"


_INELIGIBLE_CLASSES = frozenset(
    {
        EffectEvidenceClass.EXECUTOR_CONTROLLED,
        EffectEvidenceClass.PROVIDER_DISPATCH,
        EffectEvidenceClass.SYNTHETIC,
        EffectEvidenceClass.STALE,
        EffectEvidenceClass.CONFLICTING,
        EffectEvidenceClass.CENSORED,
        EffectEvidenceClass.INCOMPLETE,
        EffectEvidenceClass.OUT_OF_ENVELOPE,
        EffectEvidenceClass.MISSING,
    }
)


class CompletionClaimRejectionReason(StrEnum):
    """Why a completion claim cannot be created."""

    EVIDENCE_INELIGIBLE = "evidence_ineligible"
    IDENTITY_SEPARATION_VIOLATION = "identity_separation_violation"
    FINALITY_INCOMPLETE = "finality_incomplete"
    FORBIDDEN_EFFECT_PRESENT = "forbidden_effect_present"
    WATERMARK_STALE = "watermark_stale"
    ENVELOPE_VIOLATION = "envelope_violation"
    DIGEST_TAMPERED = "digest_tampered"
    ATTEMPT_MISMATCH = "attempt_mismatch"
    RECEIPT_MISMATCH = "receipt_mismatch"
    EVIDENCE_WINDOW_EXPIRED = "evidence_window_expired"
    DUPLICATE_CLAIM = "duplicate_claim"


# ---------------------------------------------------------------------------
# Effect evidence record
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EffectEvidenceRecord:
    """One post-effect observation with full provenance."""

    observer_identity: str
    observer_authority_class: EffectEvidenceClass
    purpose_version: str
    method_version: str
    event_time: datetime
    recorded_time: datetime
    freshness_policy_seconds: int
    completeness: bool
    provenance: str
    conflict_status: str
    synthetic: bool
    evidence_digest: str

    def __post_init__(self) -> None:
        if not self.observer_identity or not self.observer_identity.strip():
            raise ValueError("effect evidence requires an observer_identity")
        if self.event_time.tzinfo is None or self.event_time.utcoffset() is None:
            raise ValueError("effect evidence event_time MUST be timezone-aware")
        if self.recorded_time.tzinfo is None or self.recorded_time.utcoffset() is None:
            raise ValueError("effect evidence recorded_time MUST be timezone-aware")
        if self.freshness_policy_seconds < 0:
            raise ValueError("freshness_policy_seconds MUST be non-negative")
        if _DIGEST.fullmatch(self.evidence_digest) is None:
            raise ValueError("effect evidence requires a valid evidence_digest")
        if self.synthetic:
            raise ValueError("synthetic evidence is never eligible for completion claims")


# ---------------------------------------------------------------------------
# Finalized watermark
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FinalizedWatermark:
    """One authoritative source's finality observation."""

    source_id: str
    watermark: datetime
    final: bool
    watermark_digest: str

    def __post_init__(self) -> None:
        if not self.source_id or not self.source_id.strip():
            raise ValueError("watermark requires a source_id")
        if self.watermark.tzinfo is None or self.watermark.utcoffset() is None:
            raise ValueError("watermark MUST be timezone-aware")
        if _DIGEST.fullmatch(self.watermark_digest) is None:
            raise ValueError("watermark requires a valid digest")


# ---------------------------------------------------------------------------
# Completion claim
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EffectCompletionClaim:
    """Content-addressed success or non-success claim for one recovery effect."""

    attempt_identity_digest: str
    action_digest: str
    safeguard_bundle_digest: str
    provider_receipt_digest: str
    target_digest: str
    expected_effect_digest: str
    approved_envelope_digest: str
    source_revision: str
    evidence_window_start: datetime
    evidence_window_end: datetime
    effect_evidence_digest: str
    validity_start: datetime
    validity_end: datetime
    watermark_set_digest: str
    hold_revision: int
    admission_digest: str
    success: bool
    generation: int
    superseded_by: str | None
    claim_digest: str
    execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if self.execution_authority is not False:
            raise ValueError("effect completion claim MUST NOT grant execution authority")
        if _DIGEST.fullmatch(self.attempt_identity_digest) is None:
            raise ValueError("completion claim requires a valid attempt_identity_digest")
        if _DIGEST.fullmatch(self.claim_digest) is None:
            raise ValueError("completion claim requires a valid claim_digest")
        if not isinstance(self.generation, int) or self.generation < 1:
            raise ValueError("completion claim generation MUST be positive")
        if not isinstance(self.hold_revision, int) or self.hold_revision < 1:
            raise ValueError("completion claim hold_revision MUST be positive")
        if self.validity_start.tzinfo is None or self.validity_end.tzinfo is None:
            raise ValueError("completion claim validity MUST be timezone-aware")
        if self.evidence_window_start.tzinfo is None or self.evidence_window_end.tzinfo is None:
            raise ValueError("completion claim evidence window MUST be timezone-aware")
        expected = _completion_claim_digest(self)
        if self.claim_digest != expected:
            raise ValueError("completion claim digest mismatched")

    @classmethod
    def create_success(
        cls,
        *,
        attempt_identity_digest: str,
        action_digest: str,
        safeguard_bundle_digest: str,
        provider_receipt_digest: str,
        target_digest: str,
        expected_effect_digest: str,
        approved_envelope_digest: str,
        source_revision: str,
        evidence_window_start: datetime,
        evidence_window_end: datetime,
        effect_evidence_digest: str,
        validity_start: datetime,
        validity_end: datetime,
        watermark_set_digest: str,
        hold_revision: int,
        admission_digest: str,
        generation: int,
    ) -> EffectCompletionClaim:
        # Build fields for digest calculation
        fields = {
            "attempt_identity_digest": attempt_identity_digest,
            "action_digest": action_digest,
            "safeguard_bundle_digest": safeguard_bundle_digest,
            "provider_receipt_digest": provider_receipt_digest,
            "target_digest": target_digest,
            "expected_effect_digest": expected_effect_digest,
            "approved_envelope_digest": approved_envelope_digest,
            "source_revision": source_revision,
            "evidence_window_start": evidence_window_start,
            "evidence_window_end": evidence_window_end,
            "effect_evidence_digest": effect_evidence_digest,
            "validity_start": validity_start,
            "validity_end": validity_end,
            "watermark_set_digest": watermark_set_digest,
            "hold_revision": hold_revision,
            "admission_digest": admission_digest,
            "success": True,
            "generation": generation,
            "superseded_by": None,
            "execution_authority": False,
            "claim_digest": None,
        }
        digest = content_digest(
            {
                k: (v.astimezone(UTC).isoformat() if isinstance(v, datetime) else v)
                for k, v in fields.items()
            }
        )
        return cls(
            attempt_identity_digest=attempt_identity_digest,
            action_digest=action_digest,
            safeguard_bundle_digest=safeguard_bundle_digest,
            provider_receipt_digest=provider_receipt_digest,
            target_digest=target_digest,
            expected_effect_digest=expected_effect_digest,
            approved_envelope_digest=approved_envelope_digest,
            source_revision=source_revision,
            evidence_window_start=evidence_window_start,
            evidence_window_end=evidence_window_end,
            effect_evidence_digest=effect_evidence_digest,
            validity_start=validity_start,
            validity_end=validity_end,
            watermark_set_digest=watermark_set_digest,
            hold_revision=hold_revision,
            admission_digest=admission_digest,
            success=True,
            generation=generation,
            superseded_by=None,
            claim_digest=digest,
        )

    @classmethod
    def create_non_success(
        cls,
        *,
        attempt_identity_digest: str,
        action_digest: str,
        safeguard_bundle_digest: str,
        provider_receipt_digest: str,
        target_digest: str,
        expected_effect_digest: str,
        approved_envelope_digest: str,
        source_revision: str,
        evidence_window_start: datetime,
        evidence_window_end: datetime,
        effect_evidence_digest: str,
        validity_start: datetime,
        validity_end: datetime,
        watermark_set_digest: str,
        hold_revision: int,
        admission_digest: str,
        generation: int,
    ) -> EffectCompletionClaim:
        fields = {
            "attempt_identity_digest": attempt_identity_digest,
            "action_digest": action_digest,
            "safeguard_bundle_digest": safeguard_bundle_digest,
            "provider_receipt_digest": provider_receipt_digest,
            "target_digest": target_digest,
            "expected_effect_digest": expected_effect_digest,
            "approved_envelope_digest": approved_envelope_digest,
            "source_revision": source_revision,
            "evidence_window_start": evidence_window_start,
            "evidence_window_end": evidence_window_end,
            "effect_evidence_digest": effect_evidence_digest,
            "validity_start": validity_start,
            "validity_end": validity_end,
            "watermark_set_digest": watermark_set_digest,
            "hold_revision": hold_revision,
            "admission_digest": admission_digest,
            "success": False,
            "generation": generation,
            "superseded_by": None,
            "execution_authority": False,
            "claim_digest": None,
        }
        digest = content_digest(
            {
                k: (v.astimezone(UTC).isoformat() if isinstance(v, datetime) else v)
                for k, v in fields.items()
            }
        )
        return cls(
            attempt_identity_digest=attempt_identity_digest,
            action_digest=action_digest,
            safeguard_bundle_digest=safeguard_bundle_digest,
            provider_receipt_digest=provider_receipt_digest,
            target_digest=target_digest,
            expected_effect_digest=expected_effect_digest,
            approved_envelope_digest=approved_envelope_digest,
            source_revision=source_revision,
            evidence_window_start=evidence_window_start,
            evidence_window_end=evidence_window_end,
            effect_evidence_digest=effect_evidence_digest,
            validity_start=validity_start,
            validity_end=validity_end,
            watermark_set_digest=watermark_set_digest,
            hold_revision=hold_revision,
            admission_digest=admission_digest,
            success=False,
            generation=generation,
            superseded_by=None,
            claim_digest=digest,
        )


def supersede_claim(
    prior: EffectCompletionClaim,
    *,
    superseding_digest: str,
) -> EffectCompletionClaim:
    """Atomically mark a prior claim as superseded by a newer generation."""

    if prior.superseded_by is not None:
        raise ValueError("claim is already superseded")
    if _DIGEST.fullmatch(superseding_digest) is None:
        raise ValueError("superseding_digest MUST be a valid digest")
    # Recreate with superseded_by set - digest changes
    fields = {
        "attempt_identity_digest": prior.attempt_identity_digest,
        "action_digest": prior.action_digest,
        "safeguard_bundle_digest": prior.safeguard_bundle_digest,
        "provider_receipt_digest": prior.provider_receipt_digest,
        "target_digest": prior.target_digest,
        "expected_effect_digest": prior.expected_effect_digest,
        "approved_envelope_digest": prior.approved_envelope_digest,
        "source_revision": prior.source_revision,
        "evidence_window_start": prior.evidence_window_start,
        "evidence_window_end": prior.evidence_window_end,
        "effect_evidence_digest": prior.effect_evidence_digest,
        "validity_start": prior.validity_start,
        "validity_end": prior.validity_end,
        "watermark_set_digest": prior.watermark_set_digest,
        "hold_revision": prior.hold_revision,
        "admission_digest": prior.admission_digest,
        "success": prior.success,
        "generation": prior.generation,
        "superseded_by": superseding_digest,
        "execution_authority": False,
        "claim_digest": None,
    }
    digest = content_digest(
        {
            k: (v.astimezone(UTC).isoformat() if isinstance(v, datetime) else v)
            for k, v in fields.items()
        }
    )
    return EffectCompletionClaim(
        attempt_identity_digest=prior.attempt_identity_digest,
        action_digest=prior.action_digest,
        safeguard_bundle_digest=prior.safeguard_bundle_digest,
        provider_receipt_digest=prior.provider_receipt_digest,
        target_digest=prior.target_digest,
        expected_effect_digest=prior.expected_effect_digest,
        approved_envelope_digest=prior.approved_envelope_digest,
        source_revision=prior.source_revision,
        evidence_window_start=prior.evidence_window_start,
        evidence_window_end=prior.evidence_window_end,
        effect_evidence_digest=prior.effect_evidence_digest,
        validity_start=prior.validity_start,
        validity_end=prior.validity_end,
        watermark_set_digest=prior.watermark_set_digest,
        hold_revision=prior.hold_revision,
        admission_digest=prior.admission_digest,
        success=prior.success,
        generation=prior.generation,
        superseded_by=superseding_digest,
        claim_digest=digest,
    )


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def verify_effect_evidence(
    *,
    evidence: EffectEvidenceRecord,
    executor_identity: str,
    provider_identity: str,
) -> tuple[bool, tuple[CompletionClaimRejectionReason, ...]]:
    """Verify evidence eligibility with identity separation."""

    reasons: list[CompletionClaimRejectionReason] = []
    normalized_observer = evidence.observer_identity.strip().casefold()
    normalized_executor = executor_identity.strip().casefold()
    normalized_provider = provider_identity.strip().casefold()

    if evidence.observer_authority_class in _INELIGIBLE_CLASSES:
        reasons.append(CompletionClaimRejectionReason.EVIDENCE_INELIGIBLE)
    if normalized_observer == normalized_executor:
        reasons.append(CompletionClaimRejectionReason.IDENTITY_SEPARATION_VIOLATION)
    if normalized_observer == normalized_provider:
        reasons.append(CompletionClaimRejectionReason.IDENTITY_SEPARATION_VIOLATION)
    if not evidence.completeness:
        reasons.append(CompletionClaimRejectionReason.FINALITY_INCOMPLETE)
    if evidence.conflict_status != "none":
        reasons.append(CompletionClaimRejectionReason.EVIDENCE_INELIGIBLE)

    return (len(reasons) == 0, tuple(sorted(set(reasons), key=str)))


def is_current_success(claim: EffectCompletionClaim, *, now: datetime) -> bool:
    """True only when the claim is a non-superseded success within validity."""

    if not claim.success:
        return False
    if claim.superseded_by is not None:
        return False
    if now.tzinfo is None or now.utcoffset() is None:
        return False
    normalized = now.astimezone(UTC)
    if normalized < claim.validity_start.astimezone(UTC):
        return False
    if normalized >= claim.validity_end.astimezone(UTC):
        return False
    return True


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _completion_claim_digest(claim: EffectCompletionClaim) -> str:
    fields = {
        "attempt_identity_digest": claim.attempt_identity_digest,
        "action_digest": claim.action_digest,
        "safeguard_bundle_digest": claim.safeguard_bundle_digest,
        "provider_receipt_digest": claim.provider_receipt_digest,
        "target_digest": claim.target_digest,
        "expected_effect_digest": claim.expected_effect_digest,
        "approved_envelope_digest": claim.approved_envelope_digest,
        "source_revision": claim.source_revision,
        "evidence_window_start": claim.evidence_window_start.astimezone(UTC).isoformat(),
        "evidence_window_end": claim.evidence_window_end.astimezone(UTC).isoformat(),
        "effect_evidence_digest": claim.effect_evidence_digest,
        "validity_start": claim.validity_start.astimezone(UTC).isoformat(),
        "validity_end": claim.validity_end.astimezone(UTC).isoformat(),
        "watermark_set_digest": claim.watermark_set_digest,
        "hold_revision": claim.hold_revision,
        "admission_digest": claim.admission_digest,
        "success": claim.success,
        "generation": claim.generation,
        "superseded_by": claim.superseded_by,
        "execution_authority": False,
        "claim_digest": None,
    }
    return str(content_digest(fields))


__all__ = [
    "CompletionClaimRejectionReason",
    "EffectCompletionClaim",
    "EffectEvidenceClass",
    "EffectEvidenceRecord",
    "FinalizedWatermark",
    "is_current_success",
    "supersede_claim",
    "verify_effect_evidence",
]
