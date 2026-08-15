from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fdai_operator_service.families.conversation import ConversationQuery, PrincipalScope
from fdai_operator_service.families.conversation.contracts import ConversationBoundaryError
from fdai_operator_service.families.conversation.user_context import materialize_user_context

_NOW = datetime(2026, 8, 15, 6, 0, tzinfo=UTC)


class _Store:
    def __init__(self, *, conversations: int) -> None:
        self.conversation_calls: list[dict[str, Any]] = []
        self.record_calls: list[dict[str, Any]] = []
        self._conversations = conversations

    async def read_conversation_summaries(
        self,
        *,
        principal_id: str,
        before_last_active: datetime | None,
        before_conversation_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        self.conversation_calls.append(
            {
                "principal_id": principal_id,
                "before_last_active": before_last_active,
                "before_conversation_id": before_conversation_id,
                "limit": limit,
            }
        )
        return [
            {
                "conversation_id": f"conversation-{index}",
                "channel_id": "web",
                "started_at": _NOW,
                "last_active": _NOW,
                "status": "active",
                "latest_operator_turn_id": None,
                "first_operator_question": "What changed first?",
            }
            for index in range(min(self._conversations, limit))
        ]

    async def read_user_context_records(
        self,
        *,
        principal_id: str,
        limit: int,
    ) -> dict[str, list[dict[str, Any]]]:
        self.record_calls.append({"principal_id": principal_id, "limit": limit})
        return {
            "preference": [],
            "memories": [],
            "policies": [],
            "subscriptions": [],
            "briefing_runs": [],
            "scheduled_continuations": [
                {
                    "anchor_id": "anchor-one",
                    "task_id": "task-one",
                    "run_id": "run-one",
                    "owner_principal_id": principal_id,
                    "scope_ref": "scope-one",
                    "mode": "origin_thread",
                    "origin": {"channel_kind": "web", "audience": "direct"},
                    "result_digest": "digest-one",
                    "result_summary": "Observation completed.",
                    "evidence_refs": ["audit:one"],
                    "observation_started_at": _NOW,
                    "observation_ended_at": _NOW,
                    "created_at": _NOW,
                    "expires_at": _NOW,
                    "state": "active",
                }
            ],
        }


def _query(operation: str, **query: str) -> ConversationQuery:
    return ConversationQuery(
        operation=operation,
        scope=PrincipalScope(subject_id="operator-one", roles=frozenset({"Reader"})),
        query=dict(query),
    )


async def test_user_context_materializes_durable_records_in_principal_scope() -> None:
    store = _Store(conversations=2)
    response = await materialize_user_context(_query("user.context"), store=store)
    assert response is not None
    body = response.body
    assert isinstance(body, dict)
    assert body["preference"] is None
    assert body["memories"] == []
    continuations = body["scheduled_continuations"]
    assert isinstance(continuations, list)
    first = continuations[0]
    assert isinstance(first, dict)
    assert first["anchor_id"] == "anchor-one"
    conversations = body["conversations"]
    assert isinstance(conversations, list)
    assert len(conversations) == 2
    assert body["conversation_page"] == {"has_more": False, "next_cursor": None}
    assert store.record_calls[0]["principal_id"] == "operator-one"
    assert store.conversation_calls[0]["principal_id"] == "operator-one"


async def test_user_context_reports_a_cursor_when_more_conversations_remain() -> None:
    store = _Store(conversations=51)
    response = await materialize_user_context(_query("user.context"), store=store)
    assert response is not None
    body = response.body
    assert isinstance(body, dict)
    page = body["conversation_page"]
    assert isinstance(page, dict)
    assert page["has_more"] is True
    assert page["next_cursor"] == {
        "last_active": _NOW.isoformat(),
        "conversation_id": "conversation-49",
    }


async def test_conversation_page_forwards_the_requested_cursor() -> None:
    store = _Store(conversations=1)
    response = await materialize_user_context(
        _query(
            "user.conversations",
            before_last_active="2026-08-15T06:00:00+00:00",
            before_conversation_id="conversation-9",
        ),
        store=store,
    )
    assert response is not None
    assert store.conversation_calls[0]["before_last_active"] == _NOW
    assert store.conversation_calls[0]["before_conversation_id"] == "conversation-9"


async def test_partial_conversation_cursor_is_rejected() -> None:
    store = _Store(conversations=1)
    with pytest.raises(ConversationBoundaryError) as error:
        await materialize_user_context(
            _query("user.conversations", before_conversation_id="conversation-9"),
            store=store,
        )
    assert error.value.status_code == 400


async def test_unknown_query_parameter_is_rejected() -> None:
    store = _Store(conversations=1)
    with pytest.raises(ConversationBoundaryError) as error:
        await materialize_user_context(_query("user.context", limit="5"), store=store)
    assert error.value.status_code == 400


async def test_another_operation_is_not_materialized() -> None:
    store = _Store(conversations=1)
    assert await materialize_user_context(_query("chat.health"), store=store) is None
