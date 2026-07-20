from __future__ import annotations

import json
from datetime import UTC, datetime

from fdai.core.conversation import Principal, Role, SearchConversationsTool
from fdai.shared.providers import (
    ConversationRecord,
    ConversationTurnRecord,
    ConversationTurnRole,
)
from fdai.shared.providers.testing import (
    InMemoryConversationHistoryStore,
    InMemoryConversationSearch,
)

_NOW = datetime(2026, 7, 20, 5, tzinfo=UTC)


async def test_search_tool_returns_only_principal_scoped_untrusted_evidence() -> None:
    history = InMemoryConversationHistoryStore()
    for principal in ("principal-a", "principal-b"):
        conversation_id = f"conversation-{principal}"
        await history.create_conversation(
            ConversationRecord(conversation_id, principal, "web", _NOW, _NOW)
        )
        await history.append_turn(
            ConversationTurnRecord(
                turn_id=f"turn-{principal}",
                conversation_id=conversation_id,
                principal_id=principal,
                turn_index=0,
                role=ConversationTurnRole.OPERATOR,
                content="Investigate database latency.",
                recorded_at=_NOW,
                idempotency_key=f"request-{principal}",
                metadata={"evidence_refs": json.dumps([f"audit:{principal}"])},
            )
        )
    tool = SearchConversationsTool(search=InMemoryConversationSearch(history=history))

    result = await tool.call(
        arguments={"query": "database latency", "limit": 10},
        principal=Principal(id="principal-a", role=Role.READER),
    )

    assert result.status == "ok"
    assert result.data["trusted"] is False
    assert [hit["turn_id"] for hit in result.data["hits"]] == ["turn-principal-a"]
    assert result.evidence_refs == ("audit:principal-a",)


async def test_search_tool_returns_bounded_validation_error() -> None:
    tool = SearchConversationsTool(
        search=InMemoryConversationSearch(history=InMemoryConversationHistoryStore())
    )

    result = await tool.call(
        arguments={"query": "%%%"},
        principal=Principal(id="principal-a", role=Role.READER),
    )

    assert result.status == "error"
    assert "letter or digit" in result.preview
