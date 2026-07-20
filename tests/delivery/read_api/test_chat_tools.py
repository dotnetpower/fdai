"""Deterministic Command Deck read-tool tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fdai.delivery.read_api.read_model import HilQueueItem, InMemoryConsoleReadModel
from fdai.delivery.read_api.routes.chat_tools import ReadModelChatTools
from fdai.shared.providers import (
    ConversationRecord,
    ConversationTurnRecord,
    ConversationTurnRole,
)
from fdai.shared.providers.testing import (
    InMemoryConversationHistoryStore,
    InMemoryConversationSearch,
)

_NOW = datetime(2026, 7, 20, 6, tzinfo=UTC)


def _model() -> InMemoryConsoleReadModel:
    model = InMemoryConsoleReadModel()
    model.record_audit_entry(
        {
            "event_id": "event-1",
            "correlation_id": "corr-1",
            "outcome": "auto",
            "tier": "t0",
        },
        actor="Thor",
        action_kind="ops.restart-service",
        mode="shadow",
    )
    model.record_hil_pending(
        HilQueueItem(
            idempotency_key="idem-1",
            event_id="event-2",
            action_kind="ops.failover-primary",
            reason="high risk",
            requested_at="2026-07-15T00:00:00Z",
            correlation_id="corr-2",
        )
    )
    return model


def test_resolves_kpi_hil_and_audit_from_read_model() -> None:
    tools = ReadModelChatTools(_model())

    kpi = asyncio.run(tools.resolve("show KPI", principal_id="principal-a"))
    hil = asyncio.run(tools.resolve("pending approvals", principal_id="principal-a"))
    audit = asyncio.run(tools.resolve("latest audit log", principal_id="principal-a"))

    assert kpi is not None and kpi["result"]["event_count"] == 1
    assert hil is not None and hil["result"]["total"] == 1
    assert audit is not None and audit["result"]["items"][0]["actor"] == "Thor"


def test_unmatched_question_does_not_call_a_tool() -> None:
    assert (
        asyncio.run(
            ReadModelChatTools(_model()).resolve(
                "explain T2",
                principal_id="principal-a",
            )
        )
        is None
    )


def test_explicit_agent_request_precedes_generic_tool() -> None:
    assert (
        asyncio.run(
            ReadModelChatTools(_model()).resolve(
                "Ask Var for approval backlog",
                principal_id="principal-a",
            )
        )
        is None
    )


def test_conversation_search_is_principal_scoped_untrusted_tool_evidence() -> None:
    history = InMemoryConversationHistoryStore()

    async def exercise() -> dict[str, object] | None:
        for principal in ("principal-a", "principal-b"):
            conversation = f"conversation-{principal}"
            await history.create_conversation(
                ConversationRecord(conversation, principal, "web", _NOW, _NOW)
            )
            await history.append_turn(
                ConversationTurnRecord(
                    f"turn-{principal}",
                    conversation,
                    principal,
                    0,
                    ConversationTurnRole.OPERATOR,
                    "Investigate database latency.",
                    _NOW,
                    f"request-{principal}",
                )
            )
        tools = ReadModelChatTools(
            _model(),
            InMemoryConversationSearch(history=history),
        )
        return await tools.resolve(
            "search conversations database latency",
            principal_id="principal-a",
        )

    evidence = asyncio.run(exercise())

    assert evidence is not None
    assert evidence["tool"] == "search_conversations"
    result = evidence["result"]
    assert isinstance(result, dict)
    assert result["trusted"] is False
    assert [item["turn_id"] for item in result["hits"]] == ["turn-principal-a"]
