"""Pure fail-closed shadow-reversion planning for A3-E effect evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal

from fdai.core.ontology_platform.kinetics import (
    MutationPlan,
    ReconciliationStatus,
)
from fdai.core.ontology_platform.reconciliation_contracts import (
    ReconciliationOutcome,
)
from fdai.core.standing_authority.lifecycle_codec import (
    AuthorizationLifecycleError,
    aware_utc,
    content_digest,
    instant,
    require_aware,
    require_digest,
    require_text,
)
from fdai.shared.contracts.models import OntologyActionType

_ACTION_TYPE = "ops.start-vm"
_ACTION_VERSION = "1.0.0"
_REVISION = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_UNQUALIFIED_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_OBSERVATION_ID = re.compile(r"^effect-observation:[0-9a-f]{64}$")
_RECONCILIATION_ID = re.compile(r"^reconciliation:[0-9a-f]{64}$")
_REASON_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class EffectEvidenceDisposition(StrEnum):
    """Normalized effect-evidence state used for authority reduction."""

    PENDING = "pending"
    MATCHED = "matched"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    MISSING = "missing"
    STALE = "stale"
    CONFLICTING = "conflicting"
    CENSORED = "censored"
    UNSCORABLE = "unscorable"


class ShadowReversionTransition(StrEnum):
    """Only transitions a shadow-only planner may propose."""

    NONE = "none"
    RETURN_TO_SHADOW = "return_to_shadow"


@dataclass(frozen=True, slots=True)
class EffectVerificationFinding:
    """Exact effect-evidence binding consumed by the pure reversion planner."""

    action_type_name: str
    action_type_version: str
    action_type_digest: str
    target_digest: str
    source_revision_id: str
    candidate_id: str
    fencing_generation: int
    correlation_id: str
    plan_digest: str
    deadline: datetime
    evaluated_at: datetime
    reconciliation_status: ReconciliationStatus | None
    reason_code: str
    observation_id: str | None = None
    reconciliation_id: str | None = None
    receipt_digest: str | None = None
    finding_id: str = field(init=False)

    def __post_init__(self) -> None:
        if self.action_type_name != _ACTION_TYPE or self.action_type_version != _ACTION_VERSION:
            raise AuthorizationLifecycleError("effect finding MUST bind ops.start-vm@1.0.0")
        if _UNQUALIFIED_DIGEST.fullmatch(self.action_type_digest) is None:
            raise AuthorizationLifecycleError(
                "action_type_digest MUST be an unqualified SHA-256 digest"
            )
        require_digest("target_digest", self.target_digest)
        if _REVISION.fullmatch(self.source_revision_id) is None:
            raise AuthorizationLifecycleError(
                "source_revision_id MUST be a full immutable revision"
            )
        require_digest("candidate_id", self.candidate_id)
        if self.fencing_generation < 1:
            raise AuthorizationLifecycleError("fencing_generation MUST be positive")
        require_text("correlation_id", self.correlation_id)
        require_digest("plan_digest", self.plan_digest)
        require_aware("deadline", self.deadline)
        require_aware("evaluated_at", self.evaluated_at)
        if _REASON_CODE.fullmatch(self.reason_code) is None:
            raise AuthorizationLifecycleError("effect finding reason_code MUST be canonical")
        if self.reconciliation_status is None:
            if any(
                value is not None
                for value in (
                    self.observation_id,
                    self.reconciliation_id,
                    self.receipt_digest,
                )
            ):
                raise AuthorizationLifecycleError(
                    "missing observation finding MUST NOT carry outcome identities"
                )
            missing_reason = (
                "observation_pending"
                if self.evaluated_at < self.deadline
                else "observation_missing"
            )
            if self.reason_code != missing_reason:
                raise AuthorizationLifecycleError(
                    "missing observation reason does not match its deadline"
                )
        else:
            if (
                self.observation_id is None
                or _OBSERVATION_ID.fullmatch(self.observation_id) is None
                or self.reconciliation_id is None
                or _RECONCILIATION_ID.fullmatch(self.reconciliation_id) is None
            ):
                raise AuthorizationLifecycleError(
                    "reconciliation finding requires observation and reconciliation ids"
                )
            require_digest("receipt_digest", self.receipt_digest or "")
            status_reason = {
                ReconciliationStatus.MATCHED: "effects_matched",
                ReconciliationStatus.MISMATCHED: "effects_mismatched",
            }.get(self.reconciliation_status)
            if status_reason is not None and self.reason_code != status_reason:
                raise AuthorizationLifecycleError(
                    "effect finding reason does not match reconciliation status"
                )
            if (
                self.reconciliation_status is ReconciliationStatus.TIMED_OUT
                and not self.reason_code.startswith("timed_out_")
            ):
                raise AuthorizationLifecycleError("timed-out finding requires a timed_out reason")
        object.__setattr__(self, "finding_id", content_digest(_finding_body(self)))


@dataclass(frozen=True, slots=True)
class ShadowReversionPlan:
    """Content-addressed no-authority proposal to preserve or lower authority."""

    finding_id: str
    disposition: EffectEvidenceDisposition
    required_transition: ShadowReversionTransition
    reason_code: str
    proposal_only: Literal[True] = True
    grants_authority: Literal[False] = False
    registry_mutated: Literal[False] = False
    recovery_authority: Literal[False] = False
    plan_id: str = field(init=False)

    def __post_init__(self) -> None:
        require_digest("finding_id", self.finding_id)
        require_text("reason_code", self.reason_code)
        if self.required_transition is ShadowReversionTransition.NONE:
            if self.disposition not in {
                EffectEvidenceDisposition.PENDING,
                EffectEvidenceDisposition.MATCHED,
            }:
                raise AuthorizationLifecycleError(
                    "only pending or matched evidence may avoid shadow reversion"
                )
        elif self.disposition in {
            EffectEvidenceDisposition.PENDING,
            EffectEvidenceDisposition.MATCHED,
        }:
            raise AuthorizationLifecycleError(
                "pending or matched evidence MUST NOT require shadow reversion"
            )
        if (
            self.proposal_only is not True
            or self.grants_authority is not False
            or self.registry_mutated is not False
            or self.recovery_authority is not False
        ):
            raise AuthorizationLifecycleError(
                "shadow reversion plan MUST remain proposal-only and no-authority"
            )
        object.__setattr__(self, "plan_id", content_digest(_plan_body(self)))


def build_effect_verification_finding(
    *,
    action_type: OntologyActionType,
    plan: MutationPlan,
    source_revision_id: str,
    candidate_id: str,
    fencing_generation: int,
    outcome: ReconciliationOutcome | None = None,
    evaluated_at: datetime | None = None,
    deadline: datetime | None = None,
    correlation_id: str | None = None,
) -> EffectVerificationFinding:
    """Bind an exact reconciliation outcome or an explicit missing observation."""

    _validate_action_and_plan(action_type, plan)
    if outcome is not None:
        if any(value is not None for value in (evaluated_at, deadline, correlation_id)):
            raise AuthorizationLifecycleError(
                "outcome finding MUST use the outcome timestamps and correlation id"
            )
        _validate_outcome(outcome, action_type=action_type, plan=plan)
        finding_deadline = outcome.request.deadline
        finding_evaluated_at = outcome.request.evaluated_at
        finding_correlation_id = outcome.correlation_id
        reconciliation_status = outcome.receipt.status
        reason_code = outcome.recommendation.reason_code
        observation_id = outcome.request.evidence.observation_id
        reconciliation_id = outcome.reconciliation_id
        receipt_digest = outcome.receipt_digest
    else:
        if evaluated_at is None or deadline is None or correlation_id is None:
            raise AuthorizationLifecycleError(
                "missing observation finding requires evaluated_at, deadline, and correlation_id"
            )
        evaluated_at = aware_utc(evaluated_at)
        deadline = aware_utc(deadline)
        finding_deadline = deadline
        finding_evaluated_at = evaluated_at
        finding_correlation_id = correlation_id
        reconciliation_status = None
        reason_code = "observation_pending" if evaluated_at < deadline else "observation_missing"
        observation_id = None
        reconciliation_id = None
        receipt_digest = None
    return EffectVerificationFinding(
        action_type_name=action_type.name,
        action_type_version=action_type.version,
        action_type_digest=_action_type_digest(action_type),
        target_digest=_target_digest(plan),
        source_revision_id=source_revision_id,
        candidate_id=candidate_id,
        fencing_generation=fencing_generation,
        correlation_id=finding_correlation_id,
        plan_digest=plan.digest,
        deadline=finding_deadline,
        evaluated_at=finding_evaluated_at,
        reconciliation_status=reconciliation_status,
        reason_code=reason_code,
        observation_id=observation_id,
        reconciliation_id=reconciliation_id,
        receipt_digest=receipt_digest,
    )


def plan_effect_shadow_reversion(
    finding: EffectVerificationFinding,
) -> ShadowReversionPlan:
    """Map every non-matched terminal or missing result to shadow reversion."""

    disposition = _disposition(finding)
    transition = (
        ShadowReversionTransition.NONE
        if disposition
        in {
            EffectEvidenceDisposition.PENDING,
            EffectEvidenceDisposition.MATCHED,
        }
        else ShadowReversionTransition.RETURN_TO_SHADOW
    )
    return ShadowReversionPlan(
        finding_id=finding.finding_id,
        disposition=disposition,
        required_transition=transition,
        reason_code=finding.reason_code,
    )


def _disposition(finding: EffectVerificationFinding) -> EffectEvidenceDisposition:
    status = finding.reconciliation_status
    if status is None:
        return (
            EffectEvidenceDisposition.PENDING
            if finding.evaluated_at < finding.deadline
            else EffectEvidenceDisposition.MISSING
        )
    if status is ReconciliationStatus.MATCHED:
        return EffectEvidenceDisposition.MATCHED
    if status is ReconciliationStatus.MISMATCHED:
        return EffectEvidenceDisposition.FAILED
    if status is ReconciliationStatus.TIMED_OUT:
        return EffectEvidenceDisposition.TIMED_OUT
    return {
        "observation_stale": EffectEvidenceDisposition.STALE,
        "observation_conflicted": EffectEvidenceDisposition.CONFLICTING,
        "observation_censored": EffectEvidenceDisposition.CENSORED,
    }.get(finding.reason_code, EffectEvidenceDisposition.UNSCORABLE)


def _validate_action_and_plan(
    action_type: OntologyActionType,
    plan: MutationPlan,
) -> None:
    if action_type.name != _ACTION_TYPE or action_type.version != _ACTION_VERSION:
        raise AuthorizationLifecycleError("effect reversion supports only ops.start-vm@1.0.0")
    if (
        plan.action_type_ref.name != action_type.name
        or plan.action_type_ref.version != action_type.version
        or len(plan.targets) != 1
    ):
        raise AuthorizationLifecycleError(
            "effect reversion plan MUST bind one exact ops.start-vm target"
        )


def _validate_outcome(
    outcome: ReconciliationOutcome,
    *,
    action_type: OntologyActionType,
    plan: MutationPlan,
) -> None:
    request = outcome.request
    if (
        request.plan != plan
        or request.action_type != action_type
        or outcome.request_digest != request.request_digest
        or outcome.receipt.plan_digest != plan.digest
    ):
        raise AuthorizationLifecycleError(
            "effect outcome does not match the exact ActionType and plan"
        )


def _action_type_digest(action_type: OntologyActionType) -> str:
    value = action_type.model_dump(mode="json", exclude={"provenance"}, exclude_none=True)
    return content_digest(value).removeprefix("sha256:")


def _target_digest(plan: MutationPlan) -> str:
    return content_digest([target.model_dump(mode="json") for target in plan.targets])


def _finding_body(finding: EffectVerificationFinding) -> dict[str, object]:
    return {
        "action_type_name": finding.action_type_name,
        "action_type_version": finding.action_type_version,
        "action_type_digest": finding.action_type_digest,
        "target_digest": finding.target_digest,
        "source_revision_id": finding.source_revision_id,
        "candidate_id": finding.candidate_id,
        "fencing_generation": finding.fencing_generation,
        "correlation_id": finding.correlation_id,
        "plan_digest": finding.plan_digest,
        "deadline": instant(finding.deadline),
        "evaluated_at": instant(finding.evaluated_at),
        "reconciliation_status": (
            finding.reconciliation_status.value
            if finding.reconciliation_status is not None
            else None
        ),
        "reason_code": finding.reason_code,
        "observation_id": finding.observation_id,
        "reconciliation_id": finding.reconciliation_id,
        "receipt_digest": finding.receipt_digest,
    }


def _plan_body(plan: ShadowReversionPlan) -> dict[str, object]:
    return {
        "finding_id": plan.finding_id,
        "disposition": plan.disposition.value,
        "required_transition": plan.required_transition.value,
        "reason_code": plan.reason_code,
        "proposal_only": True,
        "grants_authority": False,
        "registry_mutated": False,
        "recovery_authority": False,
    }


__all__ = [
    "EffectEvidenceDisposition",
    "EffectVerificationFinding",
    "ShadowReversionPlan",
    "ShadowReversionTransition",
    "build_effect_verification_finding",
    "plan_effect_shadow_reversion",
]
