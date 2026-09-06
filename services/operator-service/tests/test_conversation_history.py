"""Terminal recovery is principal-bound, read-only, and independent of model availability."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from typing import Any

import pytest
from fdai_operator_service.families.conversation.contracts import (
    ConversationBoundaryError,
    ConversationProposal,
    ConversationQuery,
    PrincipalScope,
)
from fdai_operator_service.families.conversation.conversation_history import (
    materialize_conversation_history,
)
from fdai_operator_service.families.conversation.semantic_turn import SemanticTurnEnvelopeBuilder
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
)
from fdai_service_contracts import AdaptiveAnswer, SemanticTurnResult

_NOW = datetime(2026, 9, 6, tzinfo=UTC)
_SCOPE = PrincipalScope("operator-example", frozenset({"Reader"}))


def _record() -> dict[str, Any]:
    request = SemanticTurnEnvelopeBuilder(clock=lambda: _NOW).build(
        ConversationProposal(
            operation="chat.stream",
            scope=_SCOPE,
            idempotency_key="history-example",
            body={
                "prompt": "Compare rollout strategies.",
                "conversation_id": "conversation-example",
            },
        )
    )
    turn = request["semantic_turn"]
    answer = AdaptiveAnswer(
        answer="Blue-green switches environments; canary increases exposure gradually.",
        role_agent="Bragi",
        quality_status="limited",
        refinements=1,
        goals=[
            {
                "goal_id": "explain",
                "kind": "knowledge",
                "required": True,
                "status": "answered",
                "evidence_refs": [],
            }
        ],
    )
    result = SemanticTurnResult(
        disposition="advisory_response",
        reason_code="semantic_advisory_response",
        semantic_route="semantic_advisory_response",
        session_id=turn["session_id"],
        turn_id=turn["turn_id"],
        turn_sequence=turn["turn_sequence"],
        answer=answer.answer,
        adaptive_answer=answer,
    )
    return {
        "request": request,
        "result": {
            "request_id": request["request_id"],
            "recorded_at": _NOW.isoformat(),
            "semantic_result": result.model_dump(mode="json", exclude_none=True),
            "payload": {},
        },
    }


class _Store:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[dict[str, object]] = []

    async def read_conversation_history(
        self,
        *,
        principal_id: str,
        conversation_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        self.calls.append(
            dict(principal_id=principal_id, conversation_id=conversation_id, limit=limit)
        )
        return copy.deepcopy(self.rows)


def _query(**query) -> ConversationQuery:
    return ConversationQuery(
        operation="user.conversations.turns",
        scope=_SCOPE,
        path_params={"conversation_id": "conversation-example"},
        query=query,
    )


async def test_recovers_completed_answer_after_disconnect_without_resending() -> None:
    store = _Store([_record()])
    result = await materialize_conversation_history(_query(limit="1000"), store=store)
    assert result is not None
    turns = result.body["turns"]
    assert [turn["role"] for turn in turns] == ["operator", "assistant"]
    assert "canary" in turns[1]["content"]
    payload = json.loads(turns[1]["metadata"]["replay_payload"])
    assert payload["answer"] == turns[1]["content"]
    assert payload["adaptive_answer"]["quality_status"] == "limited"
    assert payload["execution_authority"] is False
    assert store.calls == [
        {
            "principal_id": "operator-example",
            "conversation_id": "conversation-example",
            "limit": 1000,
        }
    ]


async def test_pending_turn_stays_pending_and_empty_history_does_not_invent_answers() -> None:
    pending = _record()
    pending["result"] = None
    response = await materialize_conversation_history(_query(), store=_Store([pending]))
    assert [t["role"] for t in response.body["turns"]] == ["operator"]
    response = await materialize_conversation_history(_query(), store=_Store([]))
    assert response.body == {"turns": []}


@pytest.mark.parametrize("field", ["principal", "conversation", "request", "turn"])
async def test_recovery_rejects_mismatched_terminal_or_principal(field: str) -> None:
    record = _record()
    if field == "principal":
        record["request"]["semantic_turn"]["principal"]["subject_id"] = "different"
    elif field == "conversation":
        record["request"]["semantic_turn"]["session_id"] = "different"
    elif field == "request":
        record["result"]["request_id"] = "different"
    else:
        record["result"]["semantic_result"]["turn_id"] = "different"
    with pytest.raises(ValueError):
        await materialize_conversation_history(_query(), store=_Store([record]))


@pytest.mark.parametrize("limit", ["0", "1001", "-1", "1.5", True, {}, None])
async def test_recovery_limit_is_validated_before_read(limit) -> None:
    store = _Store([])
    with pytest.raises(ConversationBoundaryError):
        await materialize_conversation_history(_query(limit=limit), store=store)
    assert store.calls == []


async def test_legacy_conversation_rows_remain_readable() -> None:
    turn = {
        "turn_id": "legacy",
        "conversation_id": "conversation-example",
        "turn_index": 0,
        "role": "assistant",
        "content": "Previous answer",
        "recorded_at": _NOW,
        "metadata": {},
    }
    result = await materialize_conversation_history(
        _query(),
        store=_Store([{"kind": "legacy", "turn": turn}]),
    )
    assert result.body["turns"][0]["recorded_at"] == _NOW.isoformat()
    assert result.body["turns"][0]["content"] == "Previous answer"


async def test_sql_scopes_legacy_request_and_result_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    store = PostgresFamilyStore(
        PostgresFamilyStoreConfig(
            dsn="postgresql://example.invalid/fdai",
            role="fdai_operator",
        )
    )
    statements = []

    async def fetch(statement, parameters):
        statements.append(statement)
        assert parameters == {
            "principal_id": "operator-example",
            "conversation_id": "conversation-example",
            "limit": 10,
        }
        return []

    monkeypatch.setattr(store, "_fetch_all", fetch)
    assert (
        await store.read_conversation_history(
            principal_id="operator-example",
            conversation_id="conversation-example",
            limit=10,
        )
        == []
    )
    assert len(statements) == 2
    assert "principal_id = %(principal_id)s" in statements[0]
    assert "conversation_id = %(conversation_id)s" in statements[0]
    assert "request.value ->> 'principal_id' = %(principal_id)s" in statements[1]
    assert "terminal.value ->> 'principal_id' = %(principal_id)s" in statements[1]
    assert "LIMIT 1" in statements[1]
