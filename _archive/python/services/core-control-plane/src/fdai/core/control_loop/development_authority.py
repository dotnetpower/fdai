"""Focused development-authority bridge for unified control-loop risk."""

from __future__ import annotations

from collections.abc import Sequence

from fdai.core.risk_gate.authority import ExecutionAuthorityDecision
from fdai.core.risk_gate.gate import RiskDecision, RiskGate
from fdai.core.risk_gate.preconditions import PreconditionEvaluation
from fdai.shared.contracts.models import (
    Action,
    DevelopmentActionConfirmation,
    DevelopmentAuthorityEnvelope,
    FullAuthorityDevelopmentProfile,
    OntologyActionType,
    Rule,
)
from fdai.shared.providers.development_authority import (
    DevelopmentAuthorityBindingRequest,
    DevelopmentAuthorityBindingSource,
)


def evaluate_gate(
    *,
    risk_gate: RiskGate,
    action: Action,
    rule: Rule,
    action_type: OntologyActionType,
    authority: ExecutionAuthorityDecision,
    confirmation: DevelopmentActionConfirmation | None,
    inventory_age_seconds: int | None,
    precondition_evaluations: Sequence[PreconditionEvaluation],
    automation_hold_engaged: bool,
    automation_hold_recovery: bool,
) -> RiskDecision:
    """Apply current development evidence to the ordinary runtime RiskGate."""

    development = authority.development_authority
    grant = development.grant if development is not None and development.eligible else None
    envelope = (
        DevelopmentAuthorityEnvelope(
            confirmation=confirmation,
            binding_verification=development.binding_verification,
            grant=grant,
        )
        if grant is not None
        and development is not None
        and development.binding_verification is not None
        and confirmation is not None
        else None
    )
    return risk_gate.evaluate(
        action=action,
        rule=rule,
        action_type=action_type,
        inventory_age_seconds=inventory_age_seconds,
        precondition_evaluations=precondition_evaluations,
        automation_hold_engaged=automation_hold_engaged,
        automation_hold_recovery=automation_hold_recovery,
        development_authority=envelope,
    )


__all__ = [
    "DevelopmentActionConfirmation",
    "DevelopmentAuthorityBindingRequest",
    "DevelopmentAuthorityBindingSource",
    "FullAuthorityDevelopmentProfile",
    "evaluate_gate",
]
