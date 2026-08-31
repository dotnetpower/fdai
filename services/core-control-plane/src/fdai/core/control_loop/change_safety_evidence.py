"""Join independent drift and what-if evidence before Change Safety action authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from fdai.shared.contracts.models import Action, Event


class ChangeSafetyEvidenceStatus(StrEnum):
    """Status of one pre-authority evidence family."""

    PASSED = "passed"
    UNAVAILABLE = "unavailable"
    STALE = "stale"
    CONFLICT = "conflict"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ChangeSafetyPreAuthorityEvidence:
    """Versioned drift and what-if evidence for one exact event and action."""

    schema_version: str
    event_id: str
    action_id: str
    drift_status: ChangeSafetyEvidenceStatus
    what_if_status: ChangeSafetyEvidenceStatus
    drift_evidence_ref: str | None
    what_if_evidence_ref: str | None
    observed_at: datetime
    expires_at: datetime
    affected_count: int | None
    synthetic: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("change safety evidence schema_version MUST be 1.0.0")
        if not self.event_id.strip() or not self.action_id.strip():
            raise ValueError("change safety evidence identities MUST be non-empty")
        if self.observed_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("change safety evidence timestamps MUST include timezone")
        if self.expires_at < self.observed_at:
            raise ValueError("change safety evidence expiry MUST not precede observation")
        if self.affected_count is not None and self.affected_count < 0:
            raise ValueError("change safety affected_count MUST be non-negative")


@runtime_checkable
class ChangeSafetyPreAuthorityEvidenceProvider(Protocol):
    """Produce drift and prediction evidence without decision or execution authority."""

    async def evaluate(
        self,
        *,
        event: Event,
        action: Action,
    ) -> ChangeSafetyPreAuthorityEvidence: ...


@dataclass(frozen=True, slots=True)
class ChangeSafetyPreAuthorityDecision:
    """Action enrichment or an explicit hold that preserves the original finding."""

    ready_for_risk: bool
    reason: str
    action: Action
    evidence: ChangeSafetyPreAuthorityEvidence | None
    finding_preserved: bool = True


async def evaluate_change_safety_pre_authority(
    provider: ChangeSafetyPreAuthorityEvidenceProvider | None,
    *,
    event: Event,
    action: Action,
    evaluated_at: datetime,
) -> ChangeSafetyPreAuthorityDecision:
    """Validate exact current evidence and enrich only the risk input blast count."""

    if evaluated_at.tzinfo is None:
        raise ValueError("change safety evaluation time MUST include timezone")
    if provider is None:
        return ChangeSafetyPreAuthorityDecision(
            ready_for_risk=False,
            reason="change_safety_evidence_provider_unavailable",
            action=action,
            evidence=None,
        )
    try:
        evidence = await provider.evaluate(event=event, action=action)
    except Exception as exc:  # noqa: BLE001 - provider failure is an explicit hold
        return ChangeSafetyPreAuthorityDecision(
            ready_for_risk=False,
            reason=f"change_safety_evidence_provider_failed:{type(exc).__name__}",
            action=action,
            evidence=None,
        )
    reason = _rejection_reason(evidence, event=event, action=action, evaluated_at=evaluated_at)
    if reason is not None:
        return ChangeSafetyPreAuthorityDecision(
            ready_for_risk=False,
            reason=reason,
            action=action,
            evidence=evidence,
        )
    enriched = action.model_copy(
        update={
            "blast_radius": action.blast_radius.model_copy(
                update={"count": evidence.affected_count}
            )
        }
    )
    return ChangeSafetyPreAuthorityDecision(
        ready_for_risk=True,
        reason="change_safety_evidence_ready",
        action=enriched,
        evidence=evidence,
    )


def _rejection_reason(
    evidence: ChangeSafetyPreAuthorityEvidence,
    *,
    event: Event,
    action: Action,
    evaluated_at: datetime,
) -> str | None:
    if evidence.event_id != str(event.event_id) or evidence.action_id != str(action.action_id):
        return "change_safety_evidence_identity_mismatch"
    if evidence.synthetic:
        return "change_safety_evidence_synthetic"
    if evidence.observed_at > evaluated_at:
        return "change_safety_evidence_from_future"
    if evidence.expires_at < evaluated_at:
        return "change_safety_evidence_stale"
    if evidence.drift_status is not ChangeSafetyEvidenceStatus.PASSED:
        return f"change_safety_drift_{evidence.drift_status.value}"
    if evidence.what_if_status is not ChangeSafetyEvidenceStatus.PASSED:
        return f"change_safety_what_if_{evidence.what_if_status.value}"
    if not evidence.drift_evidence_ref or not evidence.what_if_evidence_ref:
        return "change_safety_evidence_reference_missing"
    if evidence.affected_count is None:
        return "change_safety_what_if_count_missing"
    return None


__all__ = [
    "ChangeSafetyEvidenceStatus",
    "ChangeSafetyPreAuthorityDecision",
    "ChangeSafetyPreAuthorityEvidence",
    "ChangeSafetyPreAuthorityEvidenceProvider",
    "evaluate_change_safety_pre_authority",
]
