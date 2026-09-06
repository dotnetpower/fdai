"""Recover durable conversation terminals without repeating model work."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Protocol, cast

from fdai_operator_service.families.conversation.contracts import (
    ConversationBoundaryError,
    ConversationQuery,
    ConversationResponse,
    JsonObject,
)
from fdai_operator_service.families.conversation.semantic_turn_presentation import (
    semantic_done_event_data,
)
from fdai_service_contracts import SemanticTurnRequest, SemanticTurnResult


class ConversationHistoryStore(Protocol):
    """Read bounded legacy rows and semantic terminals for one authenticated principal."""

    async def read_conversation_history(
        self,
        *,
        principal_id: str,
        conversation_id: str,
        limit: int,
    ) -> list[dict[str, Any]]: ...


async def materialize_conversation_history(
    query: ConversationQuery,
    *,
    store: ConversationHistoryStore,
) -> ConversationResponse | None:
    """Restore existing results through their ordinary validator, never invoke a model."""
    if query.operation != "user.conversations.turns":
        return None
    conversation_id = query.path_params.get("conversation_id", "")
    if (
        not isinstance(conversation_id, str)
        or not conversation_id
        or len(conversation_id) > 200
        or set(query.query) - {"limit"}
        or set(query.path_params) != {"conversation_id"}
    ):
        raise ConversationBoundaryError(
            400, "invalid_history_query", "invalid conversation history query"
        )
    raw_limit = query.query.get("limit", "1000")
    if not isinstance(raw_limit, str) or not raw_limit.isascii() or not raw_limit.isdecimal():
        raise ConversationBoundaryError(400, "invalid_history_limit", "invalid history limit")
    limit = int(raw_limit)
    if not 1 <= limit <= 1000:
        raise ConversationBoundaryError(
            400, "invalid_history_limit", "history limit must be 1..1000"
        )
    records = await store.read_conversation_history(
        principal_id=query.scope.subject_id,
        conversation_id=conversation_id,
        limit=limit,
    )
    turns: dict[str, dict[str, object]] = {}
    for record in records:
        if record.get("kind") == "legacy":
            turn = dict(record["turn"])
            if turn["conversation_id"] != conversation_id:
                raise ValueError("conversation history scope mismatch")
            if isinstance(turn["recorded_at"], datetime):
                turn["recorded_at"] = turn["recorded_at"].isoformat()
            turns[str(turn["turn_id"])] = turn
            continue
        envelope = record["request"]
        request = SemanticTurnRequest.model_validate(envelope["semantic_turn"])
        if (
            request.session_id != conversation_id
            or request.principal.subject_id != query.scope.subject_id
        ):
            raise ValueError("semantic history principal or conversation mismatch")
        request_id = envelope["request_id"]
        turns[f"{request_id}:operator"] = {
            "turn_id": f"{request_id}:operator",
            "conversation_id": conversation_id,
            "turn_index": request.turn_sequence * 2,
            "role": "operator",
            "content": request.utterance,
            "recorded_at": envelope["requested_at"],
            "metadata": {},
        }
        projection = record.get("result")
        if projection is None:
            continue
        result = SemanticTurnResult.model_validate(projection["semantic_result"])
        if (
            projection["request_id"] != request_id
            or result.session_id != conversation_id
            or result.turn_id != request.turn_id
            or result.turn_sequence != request.turn_sequence
        ):
            raise ValueError("semantic history terminal binding mismatch")
        done = semantic_done_event_data(projection, locale=request.locale)
        answer = done.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("semantic history terminal has no readable answer")
        turns[f"{request_id}:assistant"] = {
            "turn_id": f"{request_id}:assistant",
            "conversation_id": conversation_id,
            "turn_index": request.turn_sequence * 2 + 1,
            "role": "assistant",
            "content": answer,
            "recorded_at": projection["recorded_at"],
            "metadata": {
                "source": str(done.get("source", "history")),
                "replay_payload": json.dumps(done, ensure_ascii=False, separators=(",", ":")),
            },
        }
    ordered = sorted(
        turns.values(),
        key=lambda turn: (
            datetime.fromisoformat(str(turn["recorded_at"]).replace("Z", "+00:00")),
            int(cast(int, turn["turn_index"])),
            str(turn["turn_id"]),
        ),
    )
    return ConversationResponse(body=cast(JsonObject, {"turns": ordered[-limit:]}))
