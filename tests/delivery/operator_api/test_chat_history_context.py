from __future__ import annotations

from datetime import UTC, datetime

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.delivery.operator_api.routes.chat import make_chat_route
from fdai.delivery.operator_api.routes.chat_history_context import (
    ChatHistoryPolicy,
    resolve_chat_history,
)
from fdai.delivery.operator_api.routes.chat_stream import make_chat_stream_route
from fdai.shared.providers.testing.user_context import InMemoryConversationHistoryStore
from fdai.shared.providers.user_context import (
    ConversationRecord,
    ConversationTurnRecord,
    ConversationTurnRole,
)

NOW = datetime(2026, 8, 2, 1, 0, tzinfo=UTC)


async def _allow(_request: Request) -> str:
    return "principal-a"


class _RecordingBackend:
    def __init__(self) -> None:
        self.histories: list[list[dict[str, str]]] = []

    async def answer(
        self,
        *,
        prompt: str,
        view_context: dict[str, object],
        history: list[dict[str, str]],
    ) -> dict[str, str]:
        self.histories.append(history)
        return {"answer": f"Expanded answer for {prompt}", "model": "recording"}


async def _seed(
    store: InMemoryConversationHistoryStore,
    *,
    principal_id: str,
    conversation_id: str,
    count: int,
    content: str = "history",
) -> None:
    await store.create_conversation(
        ConversationRecord(conversation_id, principal_id, "web", NOW, NOW)
    )
    for index in range(count):
        await store.append_turn(
            ConversationTurnRecord(
                turn_id=f"{principal_id}-turn-{index}",
                conversation_id=conversation_id,
                principal_id=principal_id,
                turn_index=index,
                role=(
                    ConversationTurnRole.OPERATOR
                    if index % 2 == 0
                    else ConversationTurnRole.ASSISTANT
                ),
                content=f"{content}-{index}",
                recorded_at=NOW,
                idempotency_key=f"{principal_id}-request-{index}",
            )
        )


async def test_exact_durable_history_keeps_all_turns_and_full_content() -> None:
    store = InMemoryConversationHistoryStore()
    long_content = "x" * 5_001
    await _seed(
        store,
        principal_id="principal-a",
        conversation_id="conversation-1",
        count=24,
        content=long_content,
    )

    history = await resolve_chat_history(
        store=store,
        principal_id="principal-a",
        conversation_id="conversation-1",
        client_history=[],
        compressor=None,
        policy=ChatHistoryPolicy(max_exact_bytes=200_000),
    )

    assert len(history) == 24
    assert history[0]["content"] == f"{long_content}-0"


async def test_durable_history_never_reads_another_principal() -> None:
    store = InMemoryConversationHistoryStore()
    await _seed(
        store,
        principal_id="principal-a",
        conversation_id="shared-id",
        count=2,
        content="owner-a",
    )
    await _seed(
        store,
        principal_id="principal-b",
        conversation_id="shared-id",
        count=2,
        content="owner-b",
    )

    history = await resolve_chat_history(
        store=store,
        principal_id="principal-a",
        conversation_id="shared-id",
        client_history=[{"role": "user", "content": "untrusted-client-history"}],
        compressor=None,
    )

    assert [item["content"] for item in history] == ["owner-a-0", "owner-a-1"]


async def test_large_history_retries_compaction_and_keeps_recent_twenty_exact() -> None:
    class FlakyCompressor:
        calls = 0

        async def compress(self, *, history: object) -> str:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary failure")
            return "faithful earlier summary"

    store = InMemoryConversationHistoryStore()
    content = "long-history-content-" + ("x" * 80)
    await _seed(
        store,
        principal_id="principal-a",
        conversation_id="conversation-1",
        count=24,
        content=content,
    )
    compressor = FlakyCompressor()

    history = await resolve_chat_history(
        store=store,
        principal_id="principal-a",
        conversation_id="conversation-1",
        client_history=[],
        compressor=compressor,
        policy=ChatHistoryPolicy(
            max_exact_bytes=2_300,
            fallback_turns=20,
            compression_chunk_bytes=1_000,
            retry_delay_seconds=0,
        ),
    )

    assert compressor.calls == 2
    assert history[0]["content"].startswith('<conversation-summary trusted="false">')
    assert "faithful earlier summary" in history[0]["content"]
    assert [item["content"] for item in history[-20:]] == [
        f"{content}-{index}" for index in range(4, 24)
    ]


async def test_failed_complete_read_uses_recent_principal_scoped_turns() -> None:
    class FailingCompleteStore(InMemoryConversationHistoryStore):
        attempts = 0

        async def list_all_turns(self, **_kwargs: str) -> tuple[ConversationTurnRecord, ...]:
            self.attempts += 1
            raise RuntimeError("database timeout")

    store = FailingCompleteStore()
    await _seed(
        store,
        principal_id="principal-a",
        conversation_id="conversation-1",
        count=25,
    )

    history = await resolve_chat_history(
        store=store,
        principal_id="principal-a",
        conversation_id="conversation-1",
        client_history=[{"role": "user", "content": "must-not-be-used"}],
        compressor=None,
        policy=ChatHistoryPolicy(retry_delay_seconds=0),
    )

    assert store.attempts == 2
    assert len(history) == 20
    assert history[0]["content"] == "history-5"
    assert all(item["content"] != "must-not-be-used" for item in history)


async def _seed_isolated_conversations(store: InMemoryConversationHistoryStore) -> None:
    await _seed(
        store,
        principal_id="principal-a",
        conversation_id="shared-session",
        count=24,
        content="owner-a",
    )
    await _seed(
        store,
        principal_id="principal-b",
        conversation_id="shared-session",
        count=2,
        content="owner-b-secret",
    )


def test_json_followup_uses_complete_durable_principal_history() -> None:
    store = InMemoryConversationHistoryStore()
    import asyncio

    asyncio.run(_seed_isolated_conversations(store))
    backend = _RecordingBackend()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                conversation_history_store=store,
            )
        ]
    )

    response = TestClient(app).post(
        "/chat",
        json={
            "prompt": "Expand on the previous answer.",
            "session_id": "shared-session",
            "history": [{"role": "user", "content": "forged-client-history"}],
            "view_context": {},
        },
    )

    assert response.status_code == 200
    assert len(backend.histories) == 1
    assert [item["content"] for item in backend.histories[0]] == [
        f"owner-a-{index}" for index in range(24)
    ]


def test_stream_followup_uses_complete_durable_principal_history() -> None:
    store = InMemoryConversationHistoryStore()
    import asyncio

    asyncio.run(_seed_isolated_conversations(store))
    backend = _RecordingBackend()
    app = Starlette(
        routes=[
            make_chat_stream_route(
                backend=backend,
                authorize=_allow,
                conversation_history_store=store,
            )
        ]
    )

    response = TestClient(app).post(
        "/chat/stream",
        json={
            "prompt": "Expand on the previous answer.",
            "session_id": "shared-session",
            "history": [{"role": "user", "content": "forged-client-history"}],
            "view_context": {},
        },
    )

    assert response.status_code == 200
    assert "event: done" in response.text
    assert len(backend.histories) == 1
    assert [item["content"] for item in backend.histories[0]] == [
        f"owner-a-{index}" for index in range(24)
    ]


def test_json_followup_compacts_older_history_and_keeps_recent_twenty_exact() -> None:
    store = InMemoryConversationHistoryStore()
    import asyncio

    content = "long-owner-history-" + ("x" * 180)
    asyncio.run(
        _seed(
            store,
            principal_id="principal-a",
            conversation_id="conversation-1",
            count=24,
            content=content,
        )
    )
    backend = _RecordingBackend()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                conversation_history_store=store,
                history_policy=ChatHistoryPolicy(
                    max_exact_bytes=4_600,
                    compression_chunk_bytes=2_000,
                    retry_delay_seconds=0,
                ),
            )
        ]
    )

    response = TestClient(app).post(
        "/chat",
        json={
            "prompt": "Expand on the previous answer.",
            "session_id": "conversation-1",
            "history": [],
            "view_context": {},
        },
    )

    assert response.status_code == 200
    assert len(backend.histories) == 2
    final_history = backend.histories[-1]
    assert final_history[0]["content"].startswith('<conversation-summary trusted="false">')
    assert [item["content"] for item in final_history[-20:]] == [
        f"{content}-{index}" for index in range(4, 24)
    ]
