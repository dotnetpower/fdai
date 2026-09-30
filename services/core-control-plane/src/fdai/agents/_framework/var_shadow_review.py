"""Per-correlation shadow-review completion for Var."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fdai.agents._framework.bus import PantheonBus
from fdai.agents._framework.var_decisions import PendingShadowReview
from fdai.agents._framework.var_pending_durability import mark_shadow_review_closed
from fdai.shared.providers.state_store import StateStore


@dataclass
class RefCountedAsyncLock:
    lock: asyncio.Lock
    ref_count: int = 0


async def decide_shadow_review_once(
    *,
    pending: dict[str, PendingShadowReview],
    locks: dict[str, RefCountedAsyncLock],
    state_store: StateStore | None,
    bus: PantheonBus | None,
    record_behavior: Callable[[str], None],
    record_blocked_attempt: Callable[[str, str, str], None],
    correlation_id: str,
    reviewer: str,
    agreed: bool,
) -> dict[str, Any] | None:
    """Close one pending shadow review before publishing its Var approval."""

    lock_entry = locks.get(correlation_id)
    if lock_entry is None:
        lock_entry = RefCountedAsyncLock(asyncio.Lock())
        locks[correlation_id] = lock_entry
    lock_entry.ref_count += 1
    try:
        async with lock_entry.lock:
            approval = await _decide_shadow_review_locked(
                pending=pending,
                state_store=state_store,
                record_behavior=record_behavior,
                record_blocked_attempt=record_blocked_attempt,
                correlation_id=correlation_id,
                reviewer=reviewer,
                agreed=agreed,
            )
    finally:
        lock_entry.ref_count -= 1
        if lock_entry.ref_count == 0 and locks.get(correlation_id) is lock_entry:
            del locks[correlation_id]
    if approval is None:
        return {"state": "rejected", "reason": "missing_ticket"}
    if bus is not None:
        await bus.publish("Var", "object.approval", approval)
    record_behavior("shadow_review_completed")
    return approval


async def _decide_shadow_review_locked(
    *,
    pending: dict[str, PendingShadowReview],
    state_store: StateStore | None,
    record_behavior: Callable[[str], None],
    record_blocked_attempt: Callable[[str, str, str], None],
    correlation_id: str,
    reviewer: str,
    agreed: bool,
) -> dict[str, Any] | None:
    ticket = pending.get(correlation_id)
    if ticket is None:
        record_behavior("shadow_review:missing_ticket")
        return None
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
    return approval


__all__ = ["RefCountedAsyncLock", "decide_shadow_review_once"]
