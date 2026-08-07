from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.delivery.operator_api.application.conversation.backend import ChatContentPolicyError
from fdai.delivery.operator_api.routes.chat import make_chat_route
from fdai.delivery.operator_api.routes.chat_content_policy import (
    answer_with_content_policy_recovery,
    collect_stream_with_content_policy_recovery,
)
from fdai.delivery.operator_api.routes.chat_history_context import (
    ChatHistoryPolicy,
    resolve_chat_history,
    resolve_chat_history_result,
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


async def test_content_policy_isolates_only_blocked_history_turn() -> None:
    class SelectiveCompressor:
        calls = 0

        async def compress(self, *, history: object) -> str:
            self.calls += 1
            assert isinstance(history, list)
            if any("blocked-history" in item["content"] for item in history):
                raise ChatContentPolicyError(stage="input")
            return "safe summary"

    store = InMemoryConversationHistoryStore()
    content = "long-safe-history-" + ("x" * 80)
    await _seed(
        store,
        principal_id="principal-a",
        conversation_id="conversation-1",
        count=24,
        content=content,
    )
    turns = store._turns[("principal-a", "conversation-1")]
    turns[1] = replace(turns[1], content="blocked-history")
    compressor = SelectiveCompressor()

    result = await resolve_chat_history_result(
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

    assert result.mode == "policy_degraded"
    assert result.omitted_turn_count == 1
    assert result.content_policy_stage == "history_compaction"
    assert result.messages[0]["content"].startswith("<history-omission")
    assert "digest=" not in result.messages[0]["content"]
    assert all("blocked-history" not in item["content"] for item in result.messages)
    assert compressor.calls == 5


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


async def test_compaction_retries_share_one_total_deadline() -> None:
    class SlowCompressor:
        calls = 0

        async def compress(self, *, history: object) -> str:
            import asyncio

            self.calls += 1
            await asyncio.sleep(1)
            return "late"

    store = InMemoryConversationHistoryStore()
    await _seed(
        store,
        principal_id="principal-a",
        conversation_id="conversation-1",
        count=24,
        content="long-history-" + ("x" * 80),
    )
    compressor = SlowCompressor()

    result = await resolve_chat_history_result(
        store=store,
        principal_id="principal-a",
        conversation_id="conversation-1",
        client_history=[],
        compressor=compressor,
        policy=ChatHistoryPolicy(
            max_exact_bytes=1_000,
            compression_timeout_seconds=0.02,
            compression_attempts=3,
            retry_delay_seconds=0,
        ),
    )

    assert result.mode == "recent20"
    assert compressor.calls == 1


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


async def test_answer_policy_recovery_compacts_blocked_history_once() -> None:
    calls: list[list[dict[str, str]]] = []

    async def invoke(history: list[dict[str, str]]) -> dict[str, object]:
        calls.append(history)
        if any("blocked-history" in item["content"] for item in history):
            raise ChatContentPolicyError(stage="input")
        return {"answer": "recovered", "model": "test"}

    class Compressor:
        async def compress(self, *, history: object) -> str:
            assert isinstance(history, list)
            if any("blocked-history" in item["content"] for item in history):
                raise ChatContentPolicyError(stage="input")
            return "safe summary"

    reply, receipt = await answer_with_content_policy_recovery(
        invoke=invoke,
        history=[
            {"role": "user", "content": "safe-history"},
            {"role": "assistant", "content": "blocked-history"},
        ],
        compressor=Compressor(),
        policy=ChatHistoryPolicy(retry_delay_seconds=0),
    )

    assert reply["answer"] == "recovered"
    assert len(calls) == 2
    assert receipt is not None
    assert receipt.mode == "policy_degraded"
    assert receipt.omitted_turn_count == 1


async def test_answer_output_policy_block_is_not_retried() -> None:
    calls = 0

    async def invoke(_history: list[dict[str, str]]) -> dict[str, object]:
        nonlocal calls
        calls += 1
        raise ChatContentPolicyError(stage="output")

    class Compressor:
        async def compress(self, *, history: object) -> str:
            raise AssertionError("output policy block must not compact history")

    with pytest.raises(ChatContentPolicyError) as exc_info:
        await answer_with_content_policy_recovery(
            invoke=invoke,
            history=[{"role": "user", "content": "safe"}],
            compressor=Compressor(),
            policy=ChatHistoryPolicy(retry_delay_seconds=0),
        )

    assert exc_info.value.stage == "output"
    assert calls == 1


async def test_recovery_timeout_does_not_cap_initial_normal_answer() -> None:
    import asyncio

    async def invoke(_history: list[dict[str, str]]) -> dict[str, object]:
        await asyncio.sleep(0.02)
        return {"answer": "normal", "model": "test"}

    class Compressor:
        async def compress(self, *, history: object) -> str:
            raise AssertionError("normal answer must not invoke recovery")

    reply, receipt = await answer_with_content_policy_recovery(
        invoke=invoke,
        history=[],
        compressor=Compressor(),
        policy=ChatHistoryPolicy(content_policy_recovery_timeout_seconds=0.001),
    )

    assert reply["answer"] == "normal"
    assert receipt is None


async def test_exhausted_recovery_timeout_remains_typed_policy_block() -> None:
    import asyncio

    calls = 0

    async def invoke(_history: list[dict[str, str]]) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ChatContentPolicyError(stage="input")
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    class Compressor:
        async def compress(self, *, history: object) -> str:
            return "summary"

    with pytest.raises(ChatContentPolicyError) as exc_info:
        await answer_with_content_policy_recovery(
            invoke=invoke,
            history=[{"role": "user", "content": "history"}],
            compressor=Compressor(),
            policy=ChatHistoryPolicy(content_policy_recovery_timeout_seconds=0.01),
        )

    assert exc_info.value.stage == "input"


def test_json_route_recovers_blocked_history_and_persists_receipt() -> None:
    class Backend:
        calls = 0

        async def answer(
            self,
            *,
            prompt: str,
            view_context: dict[str, object],
            history: list[dict[str, str]],
        ) -> dict[str, str]:
            self.calls += 1
            blocked = any("blocked-history" in item["content"] for item in history)
            if blocked:
                raise ChatContentPolicyError(stage="input")
            if view_context.get("routeId") == "chat-history-compaction":
                return {"answer": "safe summary", "model": "test"}
            return {"answer": f"recovered {prompt}", "model": "test"}

    store = InMemoryConversationHistoryStore()
    import asyncio

    asyncio.run(
        _seed(
            store,
            principal_id="principal-a",
            conversation_id="conversation-1",
            count=2,
            content="safe-history",
        )
    )
    turns = store._turns[("principal-a", "conversation-1")]
    turns[1] = replace(turns[1], content="blocked-history")
    backend = Backend()
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
            "prompt": "Continue safely.",
            "session_id": "conversation-1",
            "request_id": "policy-recovery",
            "history": [],
            "view_context": {},
        },
    )

    assert response.status_code == 200
    receipt = response.json()["history_context"]
    assert receipt["history_mode"] == "policy_degraded"
    assert receipt["history_omitted_turn_count"] == "1"
    stored = asyncio.run(
        store.get_turn_by_idempotency(
            principal_id="principal-a",
            idempotency_key="policy-recovery:assistant",
        )
    )
    assert stored is not None
    assert stored.metadata["history_omitted_turn_count"] == "1"
    assert "history_omission_digest" not in stored.metadata
    assert "history_omission_digest" not in receipt


def test_json_route_output_policy_block_is_422_without_assistant_turn() -> None:
    class Backend:
        calls = 0

        async def answer(self, **_kwargs: object) -> dict[str, str]:
            self.calls += 1
            raise ChatContentPolicyError(stage="output")

    store = InMemoryConversationHistoryStore()
    backend = Backend()
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
            "prompt": "A normal prompt.",
            "session_id": "conversation-1",
            "request_id": "output-block",
            "history": [],
            "view_context": {},
        },
    )

    assert response.status_code == 422
    assert backend.calls == 1
    import asyncio

    assert (
        asyncio.run(
            store.get_turn_by_idempotency(
                principal_id="principal-a",
                idempotency_key="output-block:assistant",
            )
        )
        is None
    )
    receipt = asyncio.run(
        store.get_turn_by_idempotency(
            principal_id="principal-a",
            idempotency_key="output-block:content-policy",
        )
    )
    assert receipt is not None
    assert receipt.role is ConversationTurnRole.SYSTEM
    assert receipt.metadata["content_policy_stage"] == "output"
    assert "Normal prompt" not in receipt.content


def test_json_route_replays_policy_receipt_without_backend_call() -> None:
    class Backend:
        calls = 0

        async def answer(self, **_kwargs: object) -> dict[str, str]:
            self.calls += 1
            raise ChatContentPolicyError(stage="output")

    store = InMemoryConversationHistoryStore()
    backend = Backend()
    preference_calls = 0

    async def resolve_preference(_principal_id: str) -> None:
        nonlocal preference_calls
        preference_calls += 1
        return None

    client = TestClient(
        Starlette(
            routes=[
                make_chat_route(
                    backend=backend,
                    authorize=_allow,
                    conversation_history_store=store,
                    model_preference_resolver=resolve_preference,
                )
            ]
        )
    )
    body = {
        "prompt": "A normal prompt.",
        "session_id": "conversation-1",
        "request_id": "policy-replay",
        "history": [],
        "view_context": {},
    }

    first = client.post("/chat", json=body)
    import asyncio

    async def append_large_history() -> None:
        for index in range(21):
            await store.append_turn(
                ConversationTurnRecord(
                    turn_id=f"policy-replay-history-{index}",
                    conversation_id="conversation-1",
                    principal_id="principal-a",
                    turn_index=0,
                    role=ConversationTurnRole.ASSISTANT,
                    content="x" * 10_000,
                    recorded_at=NOW,
                    idempotency_key=f"policy-replay-history-{index}",
                ),
                allocate_index=True,
            )

    asyncio.run(append_large_history())
    replay = client.post("/chat", json=body)
    conflict = client.post("/chat", json={**body, "prompt": "Changed prompt."})

    assert first.status_code == 422
    assert replay.status_code == 422
    assert replay.text == "chat request blocked by content policy"
    assert conflict.status_code == 409
    assert backend.calls == 1
    assert preference_calls == 1


def test_json_policy_receipt_failure_is_explicit_503() -> None:
    class FailingReceiptStore(InMemoryConversationHistoryStore):
        receipt_attempts = 0

        async def append_turn(
            self,
            record: ConversationTurnRecord,
            *,
            allocate_index: bool = False,
        ) -> ConversationTurnRecord:
            if record.role is ConversationTurnRole.SYSTEM:
                self.receipt_attempts += 1
                raise RuntimeError("receipt store unavailable")
            return await super().append_turn(record, allocate_index=allocate_index)

    class Backend:
        async def answer(self, **_kwargs: object) -> dict[str, str]:
            raise ChatContentPolicyError(stage="output")

    store = FailingReceiptStore()
    response = TestClient(
        Starlette(
            routes=[
                make_chat_route(
                    backend=Backend(),
                    authorize=_allow,
                    conversation_history_store=store,
                )
            ]
        )
    ).post(
        "/chat",
        json={
            "prompt": "A normal prompt.",
            "session_id": "conversation-1",
            "request_id": "receipt-failure",
            "history": [],
            "view_context": {},
        },
    )

    assert response.status_code == 503
    assert response.text == "content policy receipt unavailable"
    assert store.receipt_attempts == 2


def test_stream_route_recovers_blocked_history_without_partial_leak() -> None:
    class Backend:
        async def answer(
            self,
            *,
            view_context: dict[str, object],
            history: list[dict[str, str]],
            **_kwargs: object,
        ) -> dict[str, str]:
            if any("blocked-history" in item["content"] for item in history):
                raise ChatContentPolicyError(stage="input")
            if view_context.get("routeId") == "chat-history-compaction":
                return {"answer": "safe summary", "model": "test"}
            return {"answer": "recovered", "model": "test"}

        async def answer_stream(
            self, *, history: list[dict[str, str]], **_kwargs: object
        ) -> object:
            if any("blocked-history" in item["content"] for item in history):
                raise ChatContentPolicyError(stage="input")
            yield {"type": "token", "delta": "recovered"}
            yield {"type": "done", "answer": "recovered", "model": "test"}

    store = InMemoryConversationHistoryStore()
    import asyncio

    asyncio.run(
        _seed(
            store,
            principal_id="principal-a",
            conversation_id="conversation-1",
            count=2,
            content="safe-history",
        )
    )
    turns = store._turns[("principal-a", "conversation-1")]
    turns[1] = replace(turns[1], content="blocked-history")
    app = Starlette(
        routes=[
            make_chat_stream_route(
                backend=Backend(),
                authorize=_allow,
                conversation_history_store=store,
            )
        ]
    )

    response = TestClient(app).post(
        "/chat/stream",
        json={
            "prompt": "Continue safely.",
            "session_id": "conversation-1",
            "request_id": "stream-policy-recovery",
            "history": [],
            "view_context": {},
        },
    )

    assert response.status_code == 200
    assert "event: done" in response.text
    assert '"history_mode": "policy_degraded"' in response.text
    assert "blocked-history" not in response.text


def test_stream_output_policy_block_discards_buffered_tokens() -> None:
    class Backend:
        async def answer(self, **_kwargs: object) -> dict[str, str]:
            raise AssertionError("stream backend must not use one-shot answer")

        async def answer_stream(self, **_kwargs: object) -> object:
            yield {"type": "token", "delta": "must-not-leak"}
            raise ChatContentPolicyError(stage="output")

    response = TestClient(
        Starlette(routes=[make_chat_stream_route(backend=Backend(), authorize=_allow)])
    ).post(
        "/chat/stream",
        json={"prompt": "Normal prompt", "history": [], "view_context": {}},
    )

    assert response.status_code == 200
    assert "event: error" in response.text
    assert '"code": "content_policy_block"' in response.text
    assert '"stage": "output"' in response.text
    assert "must-not-leak" not in response.text
    assert "event: done" not in response.text


def test_stream_upstream_failure_discards_buffered_tokens() -> None:
    class Backend:
        async def answer(self, **_kwargs: object) -> dict[str, str]:
            raise AssertionError("stream backend must not use one-shot answer")

        async def answer_stream(self, **_kwargs: object) -> object:
            yield {"type": "token", "delta": "must-not-leak"}
            raise HTTPException(
                status_code=502,
                detail="upstream failed at https://internal.example/token-secret",
            )

    response = TestClient(
        Starlette(routes=[make_chat_stream_route(backend=Backend(), authorize=_allow)])
    ).post(
        "/chat/stream",
        json={"prompt": "Normal prompt", "history": [], "view_context": {}},
    )

    assert response.status_code == 200
    assert "event: error" in response.text
    assert '"code": "chat_stream_failed"' in response.text
    assert '"detail": "chat stream failed"' in response.text
    assert "internal.example" not in response.text
    assert "token-secret" not in response.text
    assert "must-not-leak" not in response.text
    assert "event: done" not in response.text


def test_stream_route_replays_policy_receipt_without_backend_call() -> None:
    class Backend:
        calls = 0

        async def answer(self, **_kwargs: object) -> dict[str, str]:
            raise AssertionError("stream path expected")

        async def answer_stream(self, **_kwargs: object) -> object:
            self.calls += 1
            raise ChatContentPolicyError(stage="output")
            yield {}

    store = InMemoryConversationHistoryStore()
    backend = Backend()
    preference_calls = 0

    async def resolve_preference(_principal_id: str) -> None:
        nonlocal preference_calls
        preference_calls += 1
        return None

    client = TestClient(
        Starlette(
            routes=[
                make_chat_stream_route(
                    backend=backend,
                    authorize=_allow,
                    conversation_history_store=store,
                    model_preference_resolver=resolve_preference,
                )
            ]
        )
    )
    body = {
        "prompt": "Normal prompt",
        "session_id": "conversation-1",
        "request_id": "stream-policy-replay",
        "history": [],
        "view_context": {},
    }

    first = client.post("/chat/stream", json=body)
    replay = client.post("/chat/stream", json=body)

    assert '"code": "content_policy_block"' in first.text
    assert '"code": "content_policy_block"' in replay.text
    assert '"stage": "output"' in replay.text
    assert '"receipt_persisted": true' in replay.text
    assert backend.calls == 1
    assert preference_calls == 1


def test_stream_receipt_failure_keeps_policy_block_code() -> None:
    class FailingReceiptStore(InMemoryConversationHistoryStore):
        async def append_turn(
            self,
            record: ConversationTurnRecord,
            *,
            allocate_index: bool = False,
        ) -> ConversationTurnRecord:
            if record.role is ConversationTurnRole.SYSTEM:
                raise RuntimeError("receipt store unavailable")
            return await super().append_turn(record, allocate_index=allocate_index)

    class Backend:
        async def answer(self, **_kwargs: object) -> dict[str, str]:
            raise AssertionError("stream path expected")

        async def answer_stream(self, **_kwargs: object) -> object:
            raise ChatContentPolicyError(stage="output")
            yield {}

    response = TestClient(
        Starlette(
            routes=[
                make_chat_stream_route(
                    backend=Backend(),
                    authorize=_allow,
                    conversation_history_store=FailingReceiptStore(),
                )
            ]
        )
    ).post(
        "/chat/stream",
        json={
            "prompt": "Normal prompt",
            "request_id": "stream-receipt-failure",
            "history": [],
            "view_context": {},
        },
    )

    assert '"code": "content_policy_block"' in response.text
    assert '"receipt_persisted": false' in response.text


async def test_stream_buffering_propagates_cancellation_to_provider() -> None:
    import asyncio

    provider_cancelled = asyncio.Event()

    async def invoke(_history: list[dict[str, str]]) -> object:
        try:
            await asyncio.Event().wait()
            yield {}
        finally:
            provider_cancelled.set()

    class Compressor:
        async def compress(self, *, history: object) -> str:
            return "summary"

    task = asyncio.create_task(
        collect_stream_with_content_policy_recovery(
            invoke=invoke,
            history=[],
            compressor=Compressor(),
            policy=ChatHistoryPolicy(content_policy_recovery_timeout_seconds=10),
        )
    )
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert provider_cancelled.is_set()
