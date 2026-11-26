"""Governed MSCP profile lifecycle and never-raising ControlLoop ceiling binding.

Starts in ``shadow`` mode by default, activates only with a verified readiness window receipt
(distinct reviewer and approver identity, zero audit failures, unchanged executor outcomes),
applies a strictly never-raising authority ceiling (``min(fdai_decision, mscp_ceiling)``) when
active, supports immediate rollback to ``shadow``, and deterministically replays any historical
decision against a pinned lifecycle revision.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal

from fdai.core.mscp_profile.authority_ceiling import (
    MscpAuthorityCeiling,
    MscpAuthorityReason,
    combine_mscp_authority,
)
from fdai.core.mscp_profile.profile import DEFAULT_PROFILE
from fdai.core.mscp_profile.profile_lifecycle import (
    IndependentProfileReview,
    MscpProfileLifecycleConflictError,
    readiness_digest,
)
from fdai.core.mscp_profile.readiness import MscpCandidateKey, MscpReadinessReport
from fdai.core.risk_gate.evaluator import UnifiedRiskDecision, combine
from fdai.core.risk_gate.gate import RiskDecision, RiskDecisionOutcome
from fdai.shared.contracts.models import Mode

ControlDecisionLevel = Literal["deny", "hold", "require_approval", "execute"]
BindingLifecycleMode = Literal["shadow", "active"]

_DECISION_ORDER: dict[ControlDecisionLevel, int] = {
    "deny": 0,
    "hold": 1,
    "require_approval": 2,
    "execute": 3,
}
_ORDER_TO_DECISION: dict[int, ControlDecisionLevel] = {
    0: "deny",
    1: "hold",
    2: "require_approval",
    3: "execute",
}
_NORMALIZE_DECISION: dict[str, ControlDecisionLevel] = {
    "deny": "deny",
    "hold": "hold",
    "shadow": "hold",
    "require_approval": "require_approval",
    "human_approval": "require_approval",
    "hil": "require_approval",
    "execute": "execute",
    "auto": "execute",
    "preserve": "execute",
}
_CEILING_TO_ENUM: dict[ControlDecisionLevel, MscpAuthorityCeiling] = {
    "execute": MscpAuthorityCeiling.PRESERVE,
    "require_approval": MscpAuthorityCeiling.HUMAN_APPROVAL,
    "hold": MscpAuthorityCeiling.HOLD,
    "deny": MscpAuthorityCeiling.DENY,
}


class GovernedCeilingBindingError(MscpProfileLifecycleConflictError, ValueError):
    """Activation, rollback, or replay violated governed MSCP ceiling invariants."""


def _require_aware(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise GovernedCeilingBindingError(f"{name} MUST be a timezone-aware datetime")
    return value


def _require_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise GovernedCeilingBindingError(f"{name} MUST be bounded non-empty text")
    return value


def normalize_decision_level(value: str | MscpAuthorityCeiling) -> ControlDecisionLevel:
    """Normalize FDAI or MSCP ceiling token into canonical ``ControlDecisionLevel``."""
    raw = value.value if isinstance(value, MscpAuthorityCeiling) else value
    if not isinstance(raw, str) or raw not in _NORMALIZE_DECISION:
        raise GovernedCeilingBindingError(f"unsupported decision or ceiling token: {value!r}")
    return _NORMALIZE_DECISION[raw]


def _synthetic_unified(decision: ControlDecisionLevel) -> UnifiedRiskDecision:
    mapping = {
        "execute": (RiskDecisionOutcome.AUTO, Mode.ENFORCE),
        "require_approval": (RiskDecisionOutcome.HIL, Mode.ENFORCE),
        "hold": (RiskDecisionOutcome.AUTO, Mode.SHADOW),
        "deny": (RiskDecisionOutcome.DENY, Mode.ENFORCE),
    }
    outcome, mode = mapping[decision]
    return combine(
        RiskDecision(outcome=outcome, action_id="mscp-ceiling-binding", effective_mode=mode),
        None,
    )


def apply_authority_ceiling(
    fdai_decision: str,
    mscp_ceiling: str | MscpAuthorityCeiling,
    *,
    reason: MscpAuthorityReason = MscpAuthorityReason.CHECKS_PASSED,
) -> tuple[ControlDecisionLevel, bool, dict[str, object]]:
    """Apply the never-raising MSCP authority ceiling (``min(fdai_decision, mscp_ceiling)``)."""
    canonical_fdai = normalize_decision_level(fdai_decision)
    canonical_ceiling = normalize_decision_level(mscp_ceiling)
    combined = combine_mscp_authority(
        _synthetic_unified(canonical_fdai),
        ceiling=_CEILING_TO_ENUM[canonical_ceiling],
        reason=reason,
    )
    effective_rank = min(_DECISION_ORDER[canonical_fdai], _DECISION_ORDER[canonical_ceiling])
    effective = _ORDER_TO_DECISION[effective_rank]
    lowered = effective_rank < _DECISION_ORDER[canonical_fdai]
    if combined.lowered != lowered:
        raise GovernedCeilingBindingError("MSCP ceiling combination invariant mismatch")
    return effective, lowered, combined.as_audit_dict()


@dataclass(frozen=True, slots=True)
class GovernedReadinessWindowReceipt:
    """Verified readiness window receipt required to transition a binding from shadow to active."""

    candidate: MscpCandidateKey
    readiness_report: MscpReadinessReport
    review: IndependentProfileReview
    approver_id: str
    audit_failure_count: int = 0
    executor_outcomes_unchanged: bool = True

    def __post_init__(self) -> None:
        _require_text("approver_id", self.approver_id)
        if (
            isinstance(self.audit_failure_count, bool)
            or not isinstance(self.audit_failure_count, int)
            or self.audit_failure_count < 0
        ):
            raise GovernedCeilingBindingError("audit_failure_count MUST be a non-negative integer")
        if not isinstance(self.executor_outcomes_unchanged, bool):
            raise GovernedCeilingBindingError("executor_outcomes_unchanged MUST be a boolean")
        if self.readiness_report.candidate != self.candidate:
            raise GovernedCeilingBindingError("readiness_report candidate does not match binding")
        if not self.readiness_report.ready_for_review or self.readiness_report.gaps:
            raise GovernedCeilingBindingError(
                "readiness window is incomplete or has unresolved gaps"
            )
        expected_digest = readiness_digest(self.readiness_report)
        if (
            self.review.candidate != self.candidate
            or self.review.readiness_digest != expected_digest
            or not self.review.approved
        ):
            raise GovernedCeilingBindingError(
                "independent review does not approve the exact readiness report digest"
            )
        if self.review.reviewer_id == self.approver_id:
            raise GovernedCeilingBindingError(
                "governed activation requires distinct reviewer_id and approver_id"
            )
        if self.audit_failure_count != 0:
            raise GovernedCeilingBindingError(
                "governed activation requires zero audit failures in the shadow window"
            )
        if not self.executor_outcomes_unchanged:
            raise GovernedCeilingBindingError(
                "governed activation requires unchanged executor outcomes during shadow window"
            )

    @property
    def digest(self) -> str:
        return readiness_digest(self.readiness_report)


@dataclass(frozen=True, slots=True)
class GovernedLifecycleSnapshot:
    """Immutable snapshot of one lifecycle revision for deterministic evaluation and replay."""

    candidate: MscpCandidateKey
    mode: BindingLifecycleMode
    revision: int
    updated_at: datetime
    transition_reason: str
    actor_id: str
    readiness_digest: str | None = None
    review_id: str | None = None
    reviewer_id: str | None = None
    approver_id: str | None = None


@dataclass(frozen=True, slots=True)
class GovernedCeilingDecisionInput:
    """Typed ControlLoop decision input evaluated against the governed MSCP ceiling binding."""

    decision_id: str
    candidate: MscpCandidateKey
    fdai_decision: str
    mscp_ceiling: str | MscpAuthorityCeiling
    evaluated_at: datetime
    mscp_reason: MscpAuthorityReason = MscpAuthorityReason.CHECKS_PASSED
    risk_tier: str = "low"
    approval_required: bool = False
    executor_identity: str = "Thor"
    audit_owner: str = "Saga"

    def __post_init__(self) -> None:
        _require_text("decision_id", self.decision_id)
        normalize_decision_level(self.fdai_decision)
        normalize_decision_level(self.mscp_ceiling)
        _require_aware("evaluated_at", self.evaluated_at)
        _require_text("risk_tier", self.risk_tier)
        if not isinstance(self.approval_required, bool):
            raise GovernedCeilingBindingError("approval_required MUST be a boolean")
        _require_text("executor_identity", self.executor_identity)
        _require_text("audit_owner", self.audit_owner)


@dataclass(frozen=True, slots=True)
class AuthorityCeilingResult:
    """Immutable evaluation outcome preserving FDAI risk, approval, executor, and audit owners."""

    decision_id: str
    candidate: MscpCandidateKey
    profile_mode: BindingLifecycleMode
    lifecycle_revision: int
    fdai_decision: ControlDecisionLevel
    mscp_ceiling: ControlDecisionLevel
    shadow_projected_decision: ControlDecisionLevel
    effective_decision: ControlDecisionLevel
    lowered: bool
    shadow_would_lower: bool
    risk_tier: str
    approval_required: bool
    executor_identity: str
    audit_owner: str
    readiness_digest: str | None
    review_id: str | None
    audit_fields: Mapping[str, object]
    receipt_digest: str

    def to_audit_dict(self) -> dict[str, object]:
        return {
            "decision_id": self.decision_id,
            "profile_mode": self.profile_mode,
            "lifecycle_revision": self.lifecycle_revision,
            "fdai_decision": self.fdai_decision,
            "mscp_ceiling": self.mscp_ceiling,
            "shadow_projected_decision": self.shadow_projected_decision,
            "effective_decision": self.effective_decision,
            "lowered": self.lowered,
            "shadow_would_lower": self.shadow_would_lower,
            "risk_tier": self.risk_tier,
            "approval_required": self.approval_required,
            "executor_identity": self.executor_identity,
            "audit_owner": self.audit_owner,
            "readiness_digest": self.readiness_digest,
            "review_id": self.review_id,
            "receipt_digest": self.receipt_digest,
        }


class GovernedMscpCeilingBinding:
    """Compose governed MSCP lifecycle transitions with the never-raising authority ceiling."""

    def __init__(
        self,
        *,
        candidate: MscpCandidateKey,
        registered_at: datetime,
        actor_id: str = "system",
    ) -> None:
        _require_aware("registered_at", registered_at)
        _require_text("actor_id", actor_id)
        self._candidate = candidate
        initial = GovernedLifecycleSnapshot(
            candidate=candidate,
            mode="shadow",
            revision=1,
            updated_at=registered_at,
            transition_reason="registered_shadow_default",
            actor_id=actor_id,
        )
        self._revisions: dict[int, GovernedLifecycleSnapshot] = {1: initial}
        self._current_revision = 1

    @property
    def candidate(self) -> MscpCandidateKey:
        return self._candidate

    @property
    def current_snapshot(self) -> GovernedLifecycleSnapshot:
        return self._revisions[self._current_revision]

    @property
    def mode(self) -> BindingLifecycleMode:
        return self.current_snapshot.mode

    @property
    def revision(self) -> int:
        return self._current_revision

    def history(self) -> tuple[GovernedLifecycleSnapshot, ...]:
        """Return the ordered history of lifecycle snapshots from revision 1 to current."""
        return tuple(self._revisions[rev] for rev in sorted(self._revisions))

    def activate(
        self, receipt: GovernedReadinessWindowReceipt, *, now: datetime
    ) -> GovernedLifecycleSnapshot:
        """Transition from ``shadow`` to ``active`` only when a readiness receipt passes."""
        _require_aware("now", now)
        if not isinstance(receipt, GovernedReadinessWindowReceipt):
            raise GovernedCeilingBindingError(
                "activate requires a verified GovernedReadinessWindowReceipt"
            )
        if receipt.candidate != self._candidate:
            raise GovernedCeilingBindingError(
                "readiness receipt candidate does not match this governed binding"
            )
        if receipt.review.reviewed_at > now:
            raise GovernedCeilingBindingError("review timestamp cannot be in the future")
        if now < self.current_snapshot.updated_at:
            raise GovernedCeilingBindingError(
                "activation timestamp MUST NOT precede current snapshot"
            )
        next_rev = self._current_revision + 1
        snapshot = GovernedLifecycleSnapshot(
            self._candidate,
            "active",
            next_rev,
            now,
            "readiness_verified_activation",
            receipt.approver_id,
            receipt.digest,
            receipt.review.review_id,
            receipt.review.reviewer_id,
            receipt.approver_id,
        )
        self._revisions[next_rev] = snapshot
        self._current_revision = next_rev
        return snapshot

    def rollback(self, reason: str, actor: str, now: datetime) -> GovernedLifecycleSnapshot:
        """Immediately demote/roll back the profile to ``shadow`` mode with an audited reason."""
        _require_text("reason", reason)
        _require_text("actor", actor)
        _require_aware("now", now)
        cur = self.current_snapshot
        if now < cur.updated_at:
            raise GovernedCeilingBindingError(
                "rollback timestamp MUST NOT precede current snapshot"
            )
        next_rev = self._current_revision + 1
        snapshot = GovernedLifecycleSnapshot(
            self._candidate,
            "shadow",
            next_rev,
            now,
            reason,
            actor,
            cur.readiness_digest,
            cur.review_id,
            cur.reviewer_id,
            cur.approver_id,
        )
        self._revisions[next_rev] = snapshot
        self._current_revision = next_rev
        return snapshot

    def evaluate(self, decision_input: GovernedCeilingDecisionInput) -> AuthorityCeilingResult:
        """Evaluate ``decision_input`` under the current lifecycle revision."""
        return self._evaluate_at_snapshot(decision_input, self.current_snapshot)

    def replay(
        self, decision_input: GovernedCeilingDecisionInput, pinned_lifecycle_revision: int
    ) -> AuthorityCeilingResult:
        """Deterministically reproduce the exact outcome and audit fields at a pinned revision."""
        if (
            isinstance(pinned_lifecycle_revision, bool)
            or not isinstance(pinned_lifecycle_revision, int)
            or pinned_lifecycle_revision not in self._revisions
        ):
            raise GovernedCeilingBindingError(
                f"unknown pinned_lifecycle_revision: {pinned_lifecycle_revision!r}"
            )
        return self._evaluate_at_snapshot(
            decision_input, self._revisions[pinned_lifecycle_revision]
        )

    def _evaluate_at_snapshot(
        self,
        decision_input: GovernedCeilingDecisionInput,
        snapshot: GovernedLifecycleSnapshot,
    ) -> AuthorityCeilingResult:
        if decision_input.candidate != self._candidate:
            raise GovernedCeilingBindingError(
                "decision_input.candidate does not match governed binding candidate"
            )
        fdai_level = normalize_decision_level(decision_input.fdai_decision)
        ceiling_level = normalize_decision_level(decision_input.mscp_ceiling)
        projected, would_lower, raw_audit = apply_authority_ceiling(
            fdai_level, ceiling_level, reason=decision_input.mscp_reason
        )
        effective = fdai_level if snapshot.mode == "shadow" else projected
        lowered = False if snapshot.mode == "shadow" else would_lower
        effective_approval = decision_input.approval_required or (effective == "require_approval")

        audit_fields: dict[str, object] = {
            **DEFAULT_PROFILE.audit_context(),
            "decision_id": decision_input.decision_id,
            "candidate": asdict(self._candidate),
            "profile_mode": snapshot.mode,
            "lifecycle_revision": snapshot.revision,
            "transition_reason": snapshot.transition_reason,
            "fdai_decision": fdai_level,
            "mscp_ceiling": ceiling_level,
            "shadow_projected_decision": projected,
            "effective_decision": effective,
            "lowered": lowered,
            "shadow_would_lower": would_lower,
            "mscp_reason": decision_input.mscp_reason.value,
            "risk_tier": decision_input.risk_tier,
            "approval_required": effective_approval,
            "executor_identity": decision_input.executor_identity,
            "audit_owner": decision_input.audit_owner,
            "readiness_digest": snapshot.readiness_digest,
            "review_id": snapshot.review_id,
            "reviewer_id": snapshot.reviewer_id,
            "approver_id": snapshot.approver_id,
            "authority_ceiling_audit": raw_audit,
            "evaluated_at": decision_input.evaluated_at.astimezone(UTC).isoformat(),
        }
        encoded = json.dumps(audit_fields, sort_keys=True, separators=(",", ":")).encode("utf-8")
        receipt_digest = "sha256:" + hashlib.sha256(encoded).hexdigest()
        return AuthorityCeilingResult(
            decision_input.decision_id,
            self._candidate,
            snapshot.mode,
            snapshot.revision,
            fdai_level,
            ceiling_level,
            projected,
            effective,
            lowered,
            would_lower,
            decision_input.risk_tier,
            effective_approval,
            decision_input.executor_identity,
            decision_input.audit_owner,
            snapshot.readiness_digest,
            snapshot.review_id,
            audit_fields,
            receipt_digest,
        )


__all__ = [
    "AuthorityCeilingResult",
    "BindingLifecycleMode",
    "ControlDecisionLevel",
    "GovernedCeilingBindingError",
    "GovernedCeilingDecisionInput",
    "GovernedLifecycleSnapshot",
    "GovernedMscpCeilingBinding",
    "GovernedReadinessWindowReceipt",
    "apply_authority_ceiling",
    "normalize_decision_level",
]
