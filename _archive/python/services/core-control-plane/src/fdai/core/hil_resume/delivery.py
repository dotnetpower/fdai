"""Shared delivery of an already persisted HIL approval request."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from fdai.core.hil_resume.escalation_supervisor import (
    EscalationRung,
    HumanNonResponseSupervisor,
)
from fdai.core.hil_resume.load_control import (
    ApprovalDispatchMode,
    ApprovalLoadController,
    approval_request_from_park,
)
from fdai.core.hil_resume.results import RequestApprovalResult, RequestOutcome
from fdai.shared.contracts.models import Action, Rule
from fdai.shared.providers.hil_channel import HilChannel, HilChannelError

HilAudit = Callable[..., Awaitable[None]]


async def dispatch_parked_approval(
    *,
    parked: Mapping[str, Any],
    action: Action,
    rule: Rule,
    approval_id: str,
    correlation_id: str,
    channel: HilChannel | None,
    load_controller: ApprovalLoadController | None,
    escalation_supervisor: HumanNonResponseSupervisor | None,
    escalation_rungs: Sequence[EscalationRung],
    audit: HilAudit,
    logger: logging.Logger,
) -> RequestApprovalResult:
    """Send one persisted approval request without changing execution authority."""

    load_plan = None
    if load_controller is not None:
        load_plan = await load_controller.plan(parked, severity=rule.severity.value)
    request = approval_request_from_park(
        parked,
        metadata=load_plan.metadata() if load_plan is not None else None,
    )
    if channel is None:
        await audit(
            action_kind="hil.request.dispatch_unavailable",
            idempotency_key=f"{action.idempotency_key}:hil_dispatch_unavailable",
            approval_id=approval_id,
            correlation_id=correlation_id,
            detail={"action_type": action.action_type},
        )
        return RequestApprovalResult(
            outcome=RequestOutcome.PARKED_DISPATCH_FAILED,
            approval_id=approval_id,
        )
    if load_plan is not None and load_plan.mode is not ApprovalDispatchMode.SEND_NOW:
        await audit(
            action_kind="hil.request.delivery_deferred",
            idempotency_key=f"{action.idempotency_key}:hil_delivery_deferred",
            approval_id=approval_id,
            correlation_id=correlation_id,
            detail={
                "action_type": action.action_type,
                "dispatch_mode": load_plan.mode.value,
                "group_id": load_plan.group_id,
                "group_size": load_plan.group_size,
                "pending_for_assignee": load_plan.pending_for_assignee,
                "overloaded": load_plan.overloaded,
            },
        )
        return RequestApprovalResult(
            outcome=RequestOutcome.PARKED_DEFERRED,
            approval_id=approval_id,
        )
    try:
        receipt = await channel.send(request)
    except HilChannelError:
        logger.warning(
            "hil_request_dispatch_failed",
            extra={"approval_id": approval_id, "correlation_id": correlation_id},
            exc_info=True,
        )
        await audit(
            action_kind="hil.request.dispatch_failed",
            idempotency_key=f"{action.idempotency_key}:hil_dispatch_failed",
            approval_id=approval_id,
            correlation_id=correlation_id,
            detail={"action_type": action.action_type},
        )
        return RequestApprovalResult(
            outcome=RequestOutcome.PARKED_DISPATCH_FAILED,
            approval_id=approval_id,
        )
    if escalation_supervisor is not None and escalation_rungs:
        await escalation_supervisor.mark_delivered(approval_id, at=receipt.sent_at)
    return RequestApprovalResult(
        outcome=RequestOutcome.PARKED,
        approval_id=approval_id,
        receipt=receipt,
    )


__all__ = ["HilAudit", "dispatch_parked_approval"]
