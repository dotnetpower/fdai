"""Durable content-policy replay lookup for chat request preparation."""

from __future__ import annotations

from fdai.shared.providers.user_context import (
    ConversationHistoryStore,
    ConversationTurnRole,
    UserContextConflictError,
)


async def content_policy_replay_stage(
    *,
    store: ConversationHistoryStore,
    principal_id: str,
    conversation_id: str,
    request_id: str,
    content: str,
) -> str | None:
    """Return a prior policy stage only when the complete request identity matches."""

    receipt = await store.get_turn_by_idempotency(
        principal_id=principal_id,
        idempotency_key=f"{request_id}:content-policy",
    )
    if receipt is None:
        return None
    operator = await store.get_turn_by_idempotency(
        principal_id=principal_id,
        idempotency_key=f"{request_id}:operator",
    )
    if (
        operator is None
        or operator.conversation_id != conversation_id
        or operator.content != content
        or receipt.conversation_id != conversation_id
        or receipt.role is not ConversationTurnRole.SYSTEM
        or receipt.metadata.get("content_policy_blocked") != "true"
    ):
        raise UserContextConflictError(
            f"content-policy receipt for request {request_id!r} conflicts"
        )
    stage = receipt.metadata.get("content_policy_stage")
    return stage if stage in {"input", "output", "history_compaction"} else "unknown"


__all__ = ["content_policy_replay_stage"]
