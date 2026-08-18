"""Fail-closed activation gate for inert rule discovery candidates."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from fdai.shared.contracts.models import ContractBase
from fdai.shared.providers.state_store import StateStore

DISCOVERY_ACTIVATION_STATE_KEY = "runtime:discovery-activation:latest"


class DiscoveryActivationDecision(StrEnum):
    """Whether Norns may publish inert RuleCandidate records."""

    DISABLED = "disabled"
    ENABLED = "enabled"


class DiscoveryEvidenceStatus(StrEnum):
    """Sanitized terminal status for one activation prerequisite."""

    PASSED = "passed"
    FAILED = "failed"


class DiscoveryActivationReason(StrEnum):
    """Replay-stable reasons that keep discovery publication disabled."""

    POLICY_DISABLED = "policy_disabled"
    SHADOW_EVIDENCE_MISSING = "shadow_evidence_missing"
    SHADOW_EVIDENCE_STALE = "shadow_evidence_stale"
    SHADOW_EVIDENCE_FAILED = "shadow_evidence_failed"
    SHADOW_THRESHOLD_NOT_MET = "shadow_threshold_not_met"
    COLLECTOR_EVIDENCE_MISSING = "collector_evidence_missing"
    COLLECTOR_EVIDENCE_STALE = "collector_evidence_stale"
    COLLECTOR_EVIDENCE_FAILED = "collector_evidence_failed"
    CROSS_CHECK_EVIDENCE_MISSING = "cross_check_evidence_missing"
    CROSS_CHECK_EVIDENCE_STALE = "cross_check_evidence_stale"
    CROSS_CHECK_EVIDENCE_FAILED = "cross_check_evidence_failed"
    VERIFIER_EVIDENCE_MISSING = "verifier_evidence_missing"
    VERIFIER_EVIDENCE_STALE = "verifier_evidence_stale"
    VERIFIER_EVIDENCE_FAILED = "verifier_evidence_failed"
    SMOKE_EVIDENCE_MISSING = "smoke_evidence_missing"
    SMOKE_EVIDENCE_STALE = "smoke_evidence_stale"
    SMOKE_EVIDENCE_FAILED = "smoke_evidence_failed"


class TimedDiscoveryEvidence(ContractBase):
    """Current-or-expired sanitized evidence for one activation gate."""

    status: DiscoveryEvidenceStatus
    observed_at: datetime
    expires_at: datetime

    @field_validator("observed_at", "expires_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("discovery evidence timestamps MUST be timezone-aware")
        return value

    @model_validator(mode="after")
    def require_positive_window(self) -> TimedDiscoveryEvidence:
        if self.expires_at <= self.observed_at:
            raise ValueError("discovery evidence expiry MUST follow observation time")
        return self


class ShadowDecisionEvidence(TimedDiscoveryEvidence):
    """Observed shadow decisions compared with the configured threshold."""

    decision_count: Annotated[int, Field(ge=0)]


class CollectorRunEvidence(TimedDiscoveryEvidence):
    """Verified collector receipt projected into the activation boundary."""

    source_id: Annotated[str, Field(min_length=1, max_length=128)]
    resolved_revision: Annotated[str, Field(min_length=1, max_length=512)]
    content_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    license: Annotated[str, Field(min_length=1, max_length=128)]
    redistribution: Literal["embeddable", "reference-only"]
    verified_rules: Annotated[int, Field(ge=1)]
    schema_validated: bool
    provenance_validated: bool

    @model_validator(mode="after")
    def require_validated_output(self) -> CollectorRunEvidence:
        if not self.schema_validated or not self.provenance_validated:
            raise ValueError("collector activation evidence MUST be fully validated")
        return self


class DiscoveryActivationInputs(ContractBase):
    """Complete typed input set for one deterministic activation reduction."""

    policy_enabled: bool = False
    shadow_decision_threshold: Annotated[int, Field(ge=1)]
    shadow: ShadowDecisionEvidence | None = None
    collector: CollectorRunEvidence | None = None
    cross_check: TimedDiscoveryEvidence | None = None
    verifier: TimedDiscoveryEvidence | None = None
    post_deploy_smoke: TimedDiscoveryEvidence | None = None


class DiscoveryActivationReport(ContractBase):
    """Sanitized decision report suitable for persistence and replay."""

    generated_at: datetime
    decision: DiscoveryActivationDecision
    reason_codes: tuple[DiscoveryActivationReason, ...]
    shadow_decision_threshold: int
    shadow_decision_count: int | None
    evidence_observed_at: dict[str, datetime] = Field(default_factory=dict)

    @field_validator("generated_at")
    @classmethod
    def require_generated_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("discovery report timestamp MUST be timezone-aware")
        return value

    def to_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")

    def to_json(self) -> str:
        """Return byte-stable JSON for persistence and deterministic replay."""
        return json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )

    def transition_fingerprint(self) -> str:
        """Identify semantic gate state without volatile evidence timestamps."""
        material = json.dumps(
            {
                "decision": self.decision.value,
                "reason_codes": [reason.value for reason in self.reason_codes],
                "shadow_decision_threshold": self.shadow_decision_threshold,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


def reduce_discovery_activation(
    inputs: DiscoveryActivationInputs,
    *,
    generated_at: datetime,
) -> DiscoveryActivationReport:
    """Enable candidate publication only when every current prerequisite passes."""
    reason_codes: tuple[DiscoveryActivationReason, ...]
    if not inputs.policy_enabled:
        reason_codes = (DiscoveryActivationReason.POLICY_DISABLED,)
    else:
        mutable_reasons: list[DiscoveryActivationReason] = []
        shadow_reason = _evidence_reason(
            inputs.shadow,
            generated_at=generated_at,
            missing=DiscoveryActivationReason.SHADOW_EVIDENCE_MISSING,
            stale=DiscoveryActivationReason.SHADOW_EVIDENCE_STALE,
            failed=DiscoveryActivationReason.SHADOW_EVIDENCE_FAILED,
        )
        if shadow_reason is not None:
            mutable_reasons.append(shadow_reason)
        elif inputs.shadow is not None and (
            inputs.shadow.decision_count < inputs.shadow_decision_threshold
        ):
            mutable_reasons.append(DiscoveryActivationReason.SHADOW_THRESHOLD_NOT_MET)
        for gate_evidence, missing, stale, failed in (
            (
                inputs.collector,
                DiscoveryActivationReason.COLLECTOR_EVIDENCE_MISSING,
                DiscoveryActivationReason.COLLECTOR_EVIDENCE_STALE,
                DiscoveryActivationReason.COLLECTOR_EVIDENCE_FAILED,
            ),
            (
                inputs.cross_check,
                DiscoveryActivationReason.CROSS_CHECK_EVIDENCE_MISSING,
                DiscoveryActivationReason.CROSS_CHECK_EVIDENCE_STALE,
                DiscoveryActivationReason.CROSS_CHECK_EVIDENCE_FAILED,
            ),
            (
                inputs.verifier,
                DiscoveryActivationReason.VERIFIER_EVIDENCE_MISSING,
                DiscoveryActivationReason.VERIFIER_EVIDENCE_STALE,
                DiscoveryActivationReason.VERIFIER_EVIDENCE_FAILED,
            ),
            (
                inputs.post_deploy_smoke,
                DiscoveryActivationReason.SMOKE_EVIDENCE_MISSING,
                DiscoveryActivationReason.SMOKE_EVIDENCE_STALE,
                DiscoveryActivationReason.SMOKE_EVIDENCE_FAILED,
            ),
        ):
            reason = _evidence_reason(
                gate_evidence,
                generated_at=generated_at,
                missing=missing,
                stale=stale,
                failed=failed,
            )
            if reason is not None:
                mutable_reasons.append(reason)
        reason_codes = tuple(mutable_reasons)
    evidence_observed_at = {
        name: item.observed_at
        for name, item in (
            ("shadow", inputs.shadow),
            ("collector", inputs.collector),
            ("cross_check", inputs.cross_check),
            ("verifier", inputs.verifier),
            ("post_deploy_smoke", inputs.post_deploy_smoke),
        )
        if item is not None
    }
    return DiscoveryActivationReport(
        generated_at=generated_at,
        decision=(
            DiscoveryActivationDecision.ENABLED
            if not reason_codes
            else DiscoveryActivationDecision.DISABLED
        ),
        reason_codes=reason_codes,
        shadow_decision_threshold=inputs.shadow_decision_threshold,
        shadow_decision_count=(inputs.shadow.decision_count if inputs.shadow is not None else None),
        evidence_observed_at=evidence_observed_at,
    )


def _evidence_reason(
    evidence: TimedDiscoveryEvidence | None,
    *,
    generated_at: datetime,
    missing: DiscoveryActivationReason,
    stale: DiscoveryActivationReason,
    failed: DiscoveryActivationReason,
) -> DiscoveryActivationReason | None:
    if evidence is None:
        return missing
    if evidence.expires_at <= generated_at:
        return stale
    if evidence.status is DiscoveryEvidenceStatus.FAILED:
        return failed
    return None


class DiscoveryActivationCoordinator:
    """Persist activation reports and append only semantic transitions."""

    def __init__(self, *, state_store: StateStore) -> None:
        self._state_store = state_store

    async def evaluate(
        self,
        inputs: DiscoveryActivationInputs,
        *,
        generated_at: datetime,
    ) -> DiscoveryActivationReport:
        report = reduce_discovery_activation(inputs, generated_at=generated_at)
        previous = await self._state_store.read_state(DISCOVERY_ACTIVATION_STATE_KEY)
        previous_fingerprint = str(previous.get("fingerprint") or "") if previous else ""
        fingerprint = report.transition_fingerprint()
        previous_revision = int(previous.get("revision", 0)) if previous else 0
        state = {
            **report.to_dict(),
            "fingerprint": fingerprint,
            "revision": previous_revision,
        }
        if previous_fingerprint == fingerprint:
            return report
        revision = previous_revision + 1
        state["revision"] = revision
        audit = {
            "kind": "discovery_activation.transition",
            "event_id": fingerprint,
            "correlation_id": None,
            "tier": "t0",
            "decision": report.decision.value,
            "idempotency_key": f"discovery-activation:{revision}:{fingerprint}",
            "actor_identity": "runtime.discovery-activation",
            "timestamp": generated_at.isoformat(),
            "mode": "shadow",
            "rollback_reference": None,
            "reason_codes": [reason.value for reason in report.reason_codes],
            "shadow_decision_threshold": report.shadow_decision_threshold,
        }
        if previous is None:
            applied = await self._state_store.write_state_with_audit_if_absent(
                DISCOVERY_ACTIVATION_STATE_KEY,
                state,
                audit,
            )
        else:
            applied = await self._state_store.compare_and_set_state_with_audit(
                DISCOVERY_ACTIVATION_STATE_KEY,
                state,
                expected_revision=previous_revision,
                audit_entry=audit,
            )
        if not applied:
            raise RuntimeError("discovery activation state changed concurrently")
        return report


__all__ = [
    "CollectorRunEvidence",
    "DISCOVERY_ACTIVATION_STATE_KEY",
    "DiscoveryActivationCoordinator",
    "DiscoveryActivationDecision",
    "DiscoveryActivationInputs",
    "DiscoveryActivationReason",
    "DiscoveryActivationReport",
    "DiscoveryEvidenceStatus",
    "ShadowDecisionEvidence",
    "TimedDiscoveryEvidence",
    "reduce_discovery_activation",
]
