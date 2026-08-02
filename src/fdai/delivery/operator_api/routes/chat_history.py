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
)

_REPLAY_PAYLOAD_KEY = "replay_payload"
_DEFAULT_PROJECTION_TIMEOUT_SECONDS = 2.0
_LOG = logging.getLogger(__name__)


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
    conversation = await store.get_conversation(
        principal_id=principal_id,
        conversation_id=conversation_id,
    )
    if conversation is None:
        conversation = await store.create_conversation(
            ConversationRecord(
                conversation_id=conversation_id,
                principal_id=principal_id,
                channel_id="web",
                started_at=recorded_at,
                last_active=recorded_at,
            )
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


def completed_replay_payload(turn: ConversationTurnRecord) -> dict[str, Any]:
    raw = turn.metadata.get(_REPLAY_PAYLOAD_KEY)
    if isinstance(raw, str):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and payload.get("answer") == turn.content:
            return payload
    return {
        "answer": turn.content,
        "model": str(turn.metadata.get("model") or "unknown"),
        "source": "conversation-history",
    }


__all__ = [
    "append_assistant_turn",
    "append_operator_turn",
    "completed_replay_payload",
    "replay_metadata",
]
