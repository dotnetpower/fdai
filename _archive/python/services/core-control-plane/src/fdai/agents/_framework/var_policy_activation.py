"""Var-owned approval tickets for Mimir policy activation quorum."""

from __future__ import annotations

from typing import Any, Protocol

from fdai.agents._framework.var_pending_durability import checkpoint_pending_ticket
from fdai.agents._framework.var_ticket_identity import PendingHilTicket, evict_oldest_ticket


class _VarPolicyActivationState(Protocol):
    _MAX_PENDING: int
    _pending: dict[str, PendingHilTicket]
    _state_store: Any

    async def _load_final_approval(
        self,
        correlation_id: str,
        action_run_identity: str | None,
    ) -> dict[str, Any] | None: ...

    def record_behavior(self, name: str, amount: int = 1) -> None: ...


async def ingest_policy_activation_request(
    state: _VarPolicyActivationState,
    payload: dict[str, Any],
) -> None:
    """Create a Var quorum ticket from Mimir's typed activation request."""

    if (
        payload.get("producer_principal") != "Mimir"
        or payload.get("kind") != "policy_activation_approval_requested"
    ):
        state.record_behavior("policy_activation:ignored")
        return
    correlation = str(payload.get("correlation_id") or "")
    revision_id = str(payload.get("revision_id") or "")
    policy_kind = str(payload.get("policy_kind") or "")
    policy_digest = str(payload.get("policy_digest") or "")
    request_id = str(payload.get("request_id") or "")
    author = str(payload.get("author_principal") or "").strip()
    quorum = _positive_int(payload.get("quorum_required"))
    original_quorum = _positive_int(payload.get("original_quorum_required")) or quorum
    effective_quorum = _positive_int(payload.get("effective_quorum_required")) or quorum
    if (
        not correlation
        or not revision_id
        or not policy_kind
        or not policy_digest.startswith("sha256:")
        or not request_id
        or not author
        or quorum < 2
        or original_quorum < quorum
        or effective_quorum != quorum
    ):
        state.record_behavior("policy_activation:invalid")
        return
    if await state._load_final_approval(correlation, None) is not None:
        state.record_behavior("policy_activation:finalized_replay")
        return
    existing = state._pending.get(correlation)
    if existing is not None:
        state.record_behavior("policy_activation:duplicate")
        return
    ticket = PendingHilTicket(
        correlation_id=correlation,
        action_type="policy.activate-revision",
        resource_id=f"policy:{policy_kind}",
        quorum_required=quorum,
        original_quorum_required=original_quorum,
        effective_quorum_required=effective_quorum,
        action_run_identity=None,
        initiator_principal=author,
        idempotency_key=str(payload.get("idempotency_key") or correlation),
        params={
            "policy_kind": policy_kind,
            "revision_id": revision_id,
            "policy_digest": policy_digest,
            "request_id": request_id,
            "validation_digest": str(payload.get("validation_digest") or ""),
            "parent_revision_id": payload.get("parent_revision_id"),
        },
        kind="policy_activation",
    )
    await checkpoint_pending_ticket(state._state_store, ticket)
    state._pending[correlation] = ticket
    state.record_behavior("policy_activation:pending")
    if state._state_store is None:
        evict_oldest_ticket(state._pending, state._MAX_PENDING, keep=correlation)


def _positive_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value if value > 0 else 0
    if not isinstance(value, str):
        return 0
    try:
        parsed = int(value)
    except ValueError:
        return 0
    return parsed if parsed > 0 else 0


__all__ = ["ingest_policy_activation_request"]
