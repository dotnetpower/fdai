"""Conservative reduction of per-requirement authorization outcomes."""

from __future__ import annotations

from dataclasses import dataclass

from fdai.shared.providers.execution_authorization import (
    ExecutionAccessGrantProposal,
    ExecutionAuthorizationContext,
    ExecutionAuthorizationRequest,
    ExecutionAuthorizationResult,
    ExecutionAuthorizationStatus,
    ExecutionIdentityBinding,
    ProviderPermissionMapping,
)

from ._canonical import canonical_digest
from .models import AuthorizationDecision, AuthorizationObservation

_STATUS_PRECEDENCE = (
    ExecutionAuthorizationStatus.PROHIBITED,
    ExecutionAuthorizationStatus.POLICY_CONFLICT,
    ExecutionAuthorizationStatus.UNKNOWN,
    ExecutionAuthorizationStatus.UNCONFIGURED,
    ExecutionAuthorizationStatus.DELEGATED,
    ExecutionAuthorizationStatus.GRANT_REQUIRED,
    ExecutionAuthorizationStatus.AUTHORIZED,
)


@dataclass(frozen=True, slots=True)
class RequirementOutcome:
    requirement_id: str
    status: ExecutionAuthorizationStatus
    reasons: tuple[str, ...]
    scope_evidence_digest: str
    decision: AuthorizationDecision | None = None
    observations: tuple[AuthorizationObservation, ...] = ()
    identity_binding: ExecutionIdentityBinding | None = None
    mapping: ProviderPermissionMapping | None = None


def combined_status(
    outcomes: tuple[RequirementOutcome, ...],
) -> ExecutionAuthorizationStatus:
    statuses = {outcome.status for outcome in outcomes}
    return next(status for status in _STATUS_PRECEDENCE if status in statuses)


def combined_digest(
    *,
    request: ExecutionAuthorizationRequest,
    context: ExecutionAuthorizationContext,
    status: ExecutionAuthorizationStatus,
    outcomes: tuple[RequirementOutcome, ...],
    extra_reasons: tuple[str, ...],
) -> str:
    return canonical_digest(
        {
            "action_id": request.action_id,
            "action_type_id": request.action_type_id,
            "target_resource_ref": request.target_resource_ref,
            "idempotency_key": request.idempotency_key,
            "inventory_generation": context.inventory_generation,
            "status": status.value,
            "outcomes": [
                {
                    "requirement_id": outcome.requirement_id,
                    "status": outcome.status.value,
                    "reasons": outcome.reasons,
                    "scope_evidence_digest": outcome.scope_evidence_digest,
                    "decision_digest": (
                        outcome.decision.decision_digest if outcome.decision is not None else None
                    ),
                    "identity_binding_digest": (
                        outcome.identity_binding.binding_digest
                        if outcome.identity_binding is not None
                        else None
                    ),
                    "mapping_digest": (
                        outcome.mapping.mapping_digest if outcome.mapping is not None else None
                    ),
                }
                for outcome in outcomes
            ],
            "extra_reasons": extra_reasons,
        }
    )


def build_result(
    *,
    request: ExecutionAuthorizationRequest,
    context: ExecutionAuthorizationContext,
    status: ExecutionAuthorizationStatus,
    outcomes: tuple[RequirementOutcome, ...],
    extra_reasons: tuple[str, ...],
    evaluator_ref: str,
    grant_proposals: tuple[ExecutionAccessGrantProposal, ...] = (),
) -> ExecutionAuthorizationResult:
    identity_refs = {
        outcome.identity_binding.identity_ref
        for outcome in outcomes
        if outcome.identity_binding is not None
    }
    if status is ExecutionAuthorizationStatus.AUTHORIZED and len(identity_refs) != 1:
        raise ValueError("authorized requirements MUST resolve one executor identity")
    digest = combined_digest(
        request=request,
        context=context,
        status=status,
        outcomes=outcomes,
        extra_reasons=extra_reasons,
    )
    if any(proposal.authorization_decision_digest != digest for proposal in grant_proposals):
        raise ValueError("grant proposal is not bound to the combined authorization decision")
    reasons = (
        tuple(
            reason
            for outcome in outcomes
            for reason in (f"{outcome.requirement_id}:{item}" for item in outcome.reasons)
        )
        + extra_reasons
    )
    return ExecutionAuthorizationResult(
        status=status,
        decision_digest=digest,
        evaluator_ref=evaluator_ref,
        reason_codes=reasons or ("authorization_requirements_satisfied",),
        executor_identity_ref=(next(iter(identity_refs)) if len(identity_refs) == 1 else None),
        audit_context={
            "inventory_generation": context.inventory_generation,
            "requirements": [
                {
                    "requirement_id": outcome.requirement_id,
                    "status": outcome.status.value,
                    "scope_evidence_digest": outcome.scope_evidence_digest,
                    "decision": (
                        outcome.decision.as_audit_dict() if outcome.decision is not None else None
                    ),
                    "identity_binding_digest": (
                        outcome.identity_binding.binding_digest
                        if outcome.identity_binding is not None
                        else None
                    ),
                    "mapping_digest": (
                        outcome.mapping.mapping_digest if outcome.mapping is not None else None
                    ),
                }
                for outcome in outcomes
            ],
        },
        grant_proposals=grant_proposals,
    )


__all__ = ["RequirementOutcome", "build_result", "combined_digest", "combined_status"]
