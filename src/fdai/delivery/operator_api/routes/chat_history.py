"""Durable principal-scoped transcript writes for Command Deck chat routes."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from fdai.core.user_context_projection import UserContextOntologyProjector
from fdai.shared.providers.user_context import (
    ConversationHistoryStore,
    ConversationRecord,
    ConversationTurnRecord,
    ConversationTurnRole,
    UserContextConflictError,
)

_REPLAY_PAYLOAD_KEY = "replay_payload"
_DEFAULT_PROJECTION_TIMEOUT_SECONDS = 2.0
_LOG = logging.getLogger(__name__)


async def ensure_conversation(
    *,
    store: ConversationHistoryStore,
    principal_id: str,
    conversation_id: str,
    recorded_at: datetime,
) -> ConversationRecord:
    conversation = await store.get_conversation(
        principal_id=principal_id,
        conversation_id=conversation_id,
    )
    if conversation is not None:
        return conversation
    return await store.create_conversation(
        ConversationRecord(
            conversation_id=conversation_id,
            principal_id=principal_id,
            channel_id="web",
            started_at=recorded_at,
            last_active=recorded_at,
        )
    )


async def append_operator_turn(
    *,
    store: ConversationHistoryStore,
    principal_id: str,
    conversation_id: str,
    request_id: str,
    content: str,
    recorded_at: datetime,
    metadata: dict[str, Any] | None = None,
    ontology_projector: UserContextOntologyProjector | None = None,
) -> ConversationTurnRecord:
    conversation = await ensure_conversation(
        store=store,
        principal_id=principal_id,
        conversation_id=conversation_id,
        recorded_at=recorded_at,
    )
    idempotency_key = f"{request_id}:operator"
    turn = ConversationTurnRecord(
        turn_id=f"turn:{request_id}:operator",
        conversation_id=conversation_id,
        principal_id=principal_id,
        turn_index=0,
        role=ConversationTurnRole.OPERATOR,
        content=content,
        recorded_at=recorded_at,
        idempotency_key=idempotency_key,
        metadata=dict(metadata or {}),
    )
    stored = await store.append_turn(turn, allocate_index=True)
    if ontology_projector is not None:
        await ontology_projector.project_conversation(conversation)
    return stored


async def append_assistant_turn(
    *,
    store: ConversationHistoryStore,
    principal_id: str,
    conversation_id: str,
    request_id: str,
    content: str,
    recorded_at: datetime,
    metadata: dict[str, str] | None = None,
    ontology_projector: UserContextOntologyProjector | None = None,
    projection_timeout_seconds: float = _DEFAULT_PROJECTION_TIMEOUT_SECONDS,
) -> ConversationTurnRecord:
    idempotency_key = f"{request_id}:assistant"
    turn = ConversationTurnRecord(
        turn_id=f"turn:{request_id}:assistant",
        conversation_id=conversation_id,
        principal_id=principal_id,
        turn_index=0,
        role=ConversationTurnRole.ASSISTANT,
        content=content,
        recorded_at=recorded_at,
        idempotency_key=idempotency_key,
        metadata=dict(metadata or {}),
    )
    stored = await store.append_turn(turn, allocate_index=True)
    if ontology_projector is not None:
        prior = await store.list_turns(
            principal_id=principal_id,
            conversation_id=conversation_id,
            limit=2,
        )
        conversation = await store.get_conversation(
            principal_id=principal_id,
            conversation_id=conversation_id,
        )
        operator = next(
            (item for item in prior if item.idempotency_key == f"{request_id}:operator"),
            None,
        )
        if conversation is not None and operator is not None:
            try:
                async with asyncio.timeout(projection_timeout_seconds):
                    await ontology_projector.project_turn_exchange(
                        conversation=conversation,
                        operator=operator,
                        assistant=stored,
                    )
            except TimeoutError:
                _LOG.warning("chat assistant ontology projection timed out")
            except Exception as exc:  # noqa: BLE001 - persisted answer remains authoritative
                _LOG.warning(
                    "chat assistant ontology projection failed: %s",
                    type(exc).__name__,
                )
    return stored


async def append_content_policy_receipt(
    *,
    store: ConversationHistoryStore,
    principal_id: str,
    conversation_id: str,
    request_id: str,
    stage: str,
    recorded_at: datetime,
    history_metadata: Mapping[str, str],
) -> ConversationTurnRecord:
    """Persist a content-free policy receipt without creating an assistant answer."""

    record = ConversationTurnRecord(
        turn_id=f"turn:{request_id}:content-policy",
        conversation_id=conversation_id,
        principal_id=principal_id,
        turn_index=0,
        role=ConversationTurnRole.SYSTEM,
        content="Model context was withheld by content policy.",
        recorded_at=recorded_at,
        idempotency_key=f"{request_id}:content-policy",
        metadata={
            **dict(history_metadata),
            "content_policy_stage": stage,
            "content_policy_blocked": "true",
        },
    )
    for attempt in range(2):
        try:
            return await store.append_turn(record, allocate_index=True)
        except Exception:  # noqa: BLE001 - idempotent transient retry
            if attempt == 1:
                raise
            await asyncio.sleep(0)
    raise AssertionError("unreachable")


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


def replay_metadata(
    *,
    model: str,
    payload: Mapping[str, Any],
    additional: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = dict(additional or {})
    metadata["model"] = model
    metadata[_REPLAY_PAYLOAD_KEY] = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return metadata


__all__ = [
    "append_assistant_turn",
    "append_content_policy_receipt",
    "append_operator_turn",
    "content_policy_replay_stage",
    "replay_metadata",
]
