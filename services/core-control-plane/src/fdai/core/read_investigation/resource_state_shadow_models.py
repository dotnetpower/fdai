"""Immutable contracts for resource-state shadow comparison evidence."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from fdai.core.ontology_platform.functions import ontology_function_digest
from fdai.core.read_investigation.models import ReadInvestigationResult
from fdai.shared.contracts.models import ContractBase

_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"
_MAX_REF = 256


class ShadowComparisonOutcome(StrEnum):
    """Terminal classification of one side-effect-free comparison."""

    MATCH = "match"
    DIVERGENCE = "divergence"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


class ShadowComparisonReason(StrEnum):
    """Stable reason vocabulary that never grants action authority."""

    RESOURCE_IDENTITY_MISMATCH = "resource_identity_mismatch"
    STATE_MISMATCH = "state_mismatch"
    OBSERVED_AT_MISMATCH = "observed_at_mismatch"
    EXISTING_EVIDENCE_UNAVAILABLE = "existing_evidence_unavailable"
    EXISTING_EVIDENCE_TRUNCATED = "existing_evidence_truncated"
    EXISTING_OBSERVATION_STALE = "existing_observation_stale"
    SEMANTIC_RESULT_UNAVAILABLE = "semantic_result_unavailable"
    SEMANTIC_RESULT_TRUNCATED = "semantic_result_truncated"
    SEMANTIC_OBSERVATION_STALE = "semantic_observation_stale"
    EXISTING_EVIDENCE_MALFORMED = "existing_evidence_malformed"
    SEMANTIC_EVIDENCE_MALFORMED = "semantic_evidence_malformed"
    SEMANTIC_LINEAGE_MISMATCH = "semantic_lineage_mismatch"
    CONTEXT_REF_MISMATCH = "context_ref_mismatch"


class ShadowReceiptPersistence(StrEnum):
    """Observable sink result, separate from comparison outcome."""

    RECORDED = "recorded"
    FAILED = "failed"


_DIVERGENCE_REASONS = frozenset(
    {
        ShadowComparisonReason.RESOURCE_IDENTITY_MISMATCH,
        ShadowComparisonReason.STATE_MISMATCH,
        ShadowComparisonReason.OBSERVED_AT_MISMATCH,
    }
)
_UNAVAILABLE_REASONS = frozenset(
    {
        ShadowComparisonReason.EXISTING_EVIDENCE_UNAVAILABLE,
        ShadowComparisonReason.EXISTING_EVIDENCE_TRUNCATED,
        ShadowComparisonReason.EXISTING_OBSERVATION_STALE,
        ShadowComparisonReason.SEMANTIC_RESULT_UNAVAILABLE,
        ShadowComparisonReason.SEMANTIC_RESULT_TRUNCATED,
        ShadowComparisonReason.SEMANTIC_OBSERVATION_STALE,
    }
)
_ERROR_REASONS = frozenset(
    {
        ShadowComparisonReason.EXISTING_EVIDENCE_MALFORMED,
        ShadowComparisonReason.SEMANTIC_EVIDENCE_MALFORMED,
        ShadowComparisonReason.SEMANTIC_LINEAGE_MISMATCH,
        ShadowComparisonReason.CONTEXT_REF_MISMATCH,
    }
)


class ShadowComparisonReceipt(ContractBase):
    """Immutable comparison evidence with no approval or execution authority.

    ``receipt_digest`` addresses stable comparison content. Optional attempt
    latency is deliberately excluded so retries retain one comparison identity.
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    outcome: ShadowComparisonOutcome
    reasons: tuple[ShadowComparisonReason, ...] = ()
    correlation_ref: Annotated[str, Field(min_length=1, max_length=_MAX_REF)]
    principal_ref: Annotated[str, Field(min_length=1, max_length=_MAX_REF)]
    plan_id: Literal["read.resource-state.v1"] = "read.resource-state.v1"
    release_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    profile_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    plan_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    invocation_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    existing_evidence_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    semantic_evidence_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    attempt_latency_ms: float | None = Field(default=None, ge=0)
    authority: Literal["shadow_read_only"] = "shadow_read_only"
    execution_authority: Literal[False] = False
    receipt_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]

    @model_validator(mode="after")
    def _validate_content_identity(self) -> ShadowComparisonReceipt:
        _bounded_ref("correlation_ref", self.correlation_ref)
        _bounded_ref("principal_ref", self.principal_ref)
        if self.attempt_latency_ms is not None and not math.isfinite(self.attempt_latency_ms):
            raise ValueError("shadow comparison attempt latency MUST be finite")
        canonical_reasons = tuple(sorted(set(self.reasons), key=str))
        if canonical_reasons != self.reasons:
            raise ValueError("shadow comparison reasons MUST be unique and sorted")
        allowed = {
            ShadowComparisonOutcome.MATCH: frozenset(),
            ShadowComparisonOutcome.DIVERGENCE: _DIVERGENCE_REASONS,
            ShadowComparisonOutcome.UNAVAILABLE: _UNAVAILABLE_REASONS,
            ShadowComparisonOutcome.ERROR: _ERROR_REASONS,
        }[self.outcome]
        if self.outcome is ShadowComparisonOutcome.MATCH:
            if self.reasons:
                raise ValueError("matching shadow comparison MUST NOT carry reasons")
        elif not self.reasons or any(reason not in allowed for reason in self.reasons):
            raise ValueError("shadow comparison reasons do not match outcome")
        if self.receipt_digest != shadow_receipt_digest(
            outcome=self.outcome,
            reasons=self.reasons,
            correlation_ref=self.correlation_ref,
            principal_ref=self.principal_ref,
            release_digest=self.release_digest,
            profile_digest=self.profile_digest,
            plan_digest=self.plan_digest,
            invocation_digest=self.invocation_digest,
            existing_evidence_digest=self.existing_evidence_digest,
            semantic_evidence_digest=self.semantic_evidence_digest,
        ):
            raise ValueError("shadow comparison receipt digest does not match its content")
        return self


@dataclass(frozen=True, slots=True)
class ShadowComparisonAttempt:
    """Existing authoritative response plus non-authoritative receipt delivery state."""

    authoritative_result: ReadInvestigationResult
    receipt: ShadowComparisonReceipt
    persistence: ShadowReceiptPersistence
    sink_error_kind: str | None = None

    def __post_init__(self) -> None:
        if (self.persistence is ShadowReceiptPersistence.FAILED) != (
            self.sink_error_kind is not None
        ):
            raise ValueError("shadow comparison sink status is inconsistent")
        if self.sink_error_kind is not None:
            _bounded_ref("sink_error_kind", self.sink_error_kind)


def select_shadow_outcome(
    reasons: set[ShadowComparisonReason],
) -> tuple[ShadowComparisonOutcome | None, tuple[ShadowComparisonReason, ...]]:
    """Select a blocking error or unavailable outcome before fact comparison."""

    error_reasons = reasons & _ERROR_REASONS
    unavailable_reasons = reasons & _UNAVAILABLE_REASONS
    if error_reasons:
        return ShadowComparisonOutcome.ERROR, tuple(sorted(error_reasons, key=str))
    if unavailable_reasons:
        return ShadowComparisonOutcome.UNAVAILABLE, tuple(sorted(unavailable_reasons, key=str))
    return None, ()


def build_shadow_receipt(
    *,
    outcome: ShadowComparisonOutcome,
    reasons: tuple[ShadowComparisonReason, ...],
    correlation_ref: str,
    principal_ref: str,
    release_digest: str,
    profile_digest: str,
    plan_digest: str,
    invocation_digest: str,
    existing_evidence_digest: str,
    semantic_evidence_digest: str,
    attempt_latency_ms: float | None,
) -> ShadowComparisonReceipt:
    """Build a validated receipt from stable comparison lineage and evidence."""

    digest = shadow_receipt_digest(
        outcome=outcome,
        reasons=reasons,
        correlation_ref=correlation_ref,
        principal_ref=principal_ref,
        release_digest=release_digest,
        profile_digest=profile_digest,
        plan_digest=plan_digest,
        invocation_digest=invocation_digest,
        existing_evidence_digest=existing_evidence_digest,
        semantic_evidence_digest=semantic_evidence_digest,
    )
    return ShadowComparisonReceipt(
        outcome=outcome,
        reasons=reasons,
        correlation_ref=correlation_ref,
        principal_ref=principal_ref,
        release_digest=release_digest,
        profile_digest=profile_digest,
        plan_digest=plan_digest,
        invocation_digest=invocation_digest,
        existing_evidence_digest=existing_evidence_digest,
        semantic_evidence_digest=semantic_evidence_digest,
        attempt_latency_ms=attempt_latency_ms,
        receipt_digest=digest,
    )


def shadow_receipt_digest(
    *,
    outcome: ShadowComparisonOutcome,
    reasons: tuple[ShadowComparisonReason, ...],
    correlation_ref: str,
    principal_ref: str,
    release_digest: str,
    profile_digest: str,
    plan_digest: str,
    invocation_digest: str,
    existing_evidence_digest: str,
    semantic_evidence_digest: str,
) -> str:
    """Return the stable identity that intentionally excludes attempt latency."""

    return ontology_function_digest(
        {
            "schema_version": "1.0.0",
            "outcome": outcome.value,
            "reasons": [reason.value for reason in reasons],
            "correlation_ref": correlation_ref,
            "principal_ref": principal_ref,
            "plan_id": "read.resource-state.v1",
            "release_digest": release_digest,
            "profile_digest": profile_digest,
            "plan_digest": plan_digest,
            "invocation_digest": invocation_digest,
            "existing_evidence_digest": existing_evidence_digest,
            "semantic_evidence_digest": semantic_evidence_digest,
            "authority": "shadow_read_only",
            "execution_authority": False,
        }
    )


def _bounded_ref(name: str, value: str) -> None:
    if len(value) > _MAX_REF or any(ord(char) < 32 for char in value):
        raise ValueError(f"{name} MUST be a bounded opaque reference")


__all__ = [
    "ShadowComparisonAttempt",
    "ShadowComparisonOutcome",
    "ShadowComparisonReason",
    "ShadowComparisonReceipt",
    "ShadowReceiptPersistence",
    "build_shadow_receipt",
    "select_shadow_outcome",
]
