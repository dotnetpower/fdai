from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from fdai.delivery.operator_api.routes.chat_history import (
    append_assistant_turn,
    append_operator_turn,
)
from fdai.shared.providers.testing.user_context import InMemoryConversationHistoryStore

NOW = datetime(2026, 7, 16, 7, 0, tzinfo=UTC)


async def test_chat_history_appends_ordered_idempotent_turns() -> None:
    store = InMemoryConversationHistoryStore()
    operator = await append_operator_turn(
        store=store,
        principal_id="principal-a",
        conversation_id="conversation-1",
        request_id="request-1",
        content="Show major issues.",
        recorded_at=NOW + timedelta(seconds=1),
    )
    retry = await append_operator_turn(
        store=store,
        principal_id="principal-a",
        conversation_id="conversation-1",
        request_id="request-1",
        content="Show major issues.",
        recorded_at=NOW,
    )
    assistant = await append_assistant_turn(
        store=store,
        principal_id="principal-a",
        conversation_id="conversation-1",
        request_id="request-1",
        content="Two major issues were recorded.",
        recorded_at=NOW,
        metadata={"model": "narrator"},
    )

    assert retry == operator
    assert operator.turn_index == 0
    assert assistant.turn_index == 1
    assert (
        await store.list_turns(principal_id="principal-b", conversation_id="conversation-1") == ()
    )


async def test_assistant_history_does_not_wait_for_stalled_projection() -> None:
    class BlockingProjector:
        started = False

        async def project_turn_exchange(self, **_kwargs: object) -> None:
            self.started = True
            await asyncio.Event().wait()

    store = InMemoryConversationHistoryStore()
    await append_operator_turn(
        store=store,
        principal_id="principal-a",
        conversation_id="conversation-1",
        request_id="request-1",
        content="Show major issues.",
        recorded_at=NOW,
    )
    projector = BlockingProjector()

    assistant = await append_assistant_turn(
        store=store,
        principal_id="principal-a",
        conversation_id="conversation-1",
        request_id="request-1",
        content="Two major issues were recorded.",
        recorded_at=NOW,
        ontology_projector=projector,  # type: ignore[arg-type]
        projection_timeout_seconds=0.01,
    )

    assert assistant.turn_index == 1
    assert projector.started is True
