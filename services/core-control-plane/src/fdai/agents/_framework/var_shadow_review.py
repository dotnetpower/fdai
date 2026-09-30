"""Per-correlation shadow-review completion for Var."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.var_decisions import PendingShadowReview
from fdai.agents._framework.var_pending_durability import mark_shadow_review_closed
from fdai.shared.providers.state_store import StateStore


async def decide_shadow_review_once(
    *,
    pending: dict[str, PendingShadowReview],
    locks: dict[str, asyncio.Lock],
    state_store: StateStore | None,
    bus: PantheonBus | None,
    record_behavior: Callable[[str], None],
    record_blocked_attempt: Callable[[str, str, str], None],
    correlation_id: str,
    reviewer: str,
    agreed: bool,
) -> dict[str, Any] | None:
    """Close one pending shadow review before publishing its Var approval."""

    lock = locks.setdefault(correlation_id, asyncio.Lock())
    async with lock:
        ticket = pending.get(correlation_id)
        if ticket is None:
            record_behavior("shadow_review:missing_ticket")
            return {"state": "rejected", "reason": "missing_ticket"}
        reviewer_norm = reviewer.strip().casefold()
        if not reviewer_norm:
            raise ValueError("shadow outcome reviewer MUST be a non-empty principal")
        if not isinstance(agreed, bool):
            raise ValueError("shadow outcome agreement MUST be boolean")
        initiator_norm = (ticket.initiator_principal or "").strip().casefold()
        if initiator_norm and reviewer_norm == initiator_norm:
            record_blocked_attempt(
                "shadow_review_self_approval_blocked",
                correlation_id,
                reviewer_norm,
            )
            raise ValueError("a shadow outcome initiator cannot review their own action")
        approval: dict[str, Any] = {
            "producer_principal": "Var",
            "kind": "shadow_outcome_review",
            "correlation_id": ticket.correlation_id,
            "idempotency_key": f"shadow-review:{ticket.correlation_id}",
            "action_type": ticket.action_type,
            "state": "reviewed",
            "approvers": [reviewer_norm],
            "shadow_mode": True,
            "shadow_observation_id": ticket.correlation_id,
            "observed_at": ticket.observed_at,
            "operator_reviewed": True,
            "operator_agreed": agreed,
            "policy_escape": ticket.policy_escape,
        }
        del pending[correlation_id]
        await mark_shadow_review_closed(state_store, correlation_id)
    if bus is not None:
        await bus.publish("Var", "object.approval", approval)
    record_behavior("shadow_review_completed")
    return approval


__all__ = ["decide_shadow_review_once"]
