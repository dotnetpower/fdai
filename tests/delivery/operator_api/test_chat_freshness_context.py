from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.delivery.operator_api.routes.chat import make_chat_route, make_chat_stream_route
from fdai.delivery.operator_api.routes.chat_history import replay_metadata
from fdai.shared.providers.testing.user_context import InMemoryConversationHistoryStore
from fdai.shared.providers.user_context import (
    ConversationRecord,
    ConversationTurnRecord,
    ConversationTurnRole,
)


class Backend:
    def __init__(self) -> None:
        self.calls = 0

    async def answer(self, **kwargs: object) -> dict[str, str]:
        del kwargs
        self.calls += 1
        return {"answer": "fallback", "model": "test"}


async def allow(request: Request) -> str:
    del request
    return "reader"


def done_payload(text: str) -> dict[str, object]:
    for block in text.split("\n\n"):
        if block.startswith("event: done\n"):
            return json.loads(block.split("data: ", maxsplit=1)[1])
    raise AssertionError("missing done event")


async def seed_freshness_turn(
    store: InMemoryConversationHistoryStore,
    *,
    session_id: str,
) -> None:
    now = datetime.now(UTC)
    await store.create_conversation(
        ConversationRecord(
            conversation_id=session_id,
            principal_id="reader",
            channel_id="web",
            started_at=now,
            last_active=now,
        )
    )
    payload = {
        "answer": "Prior grounded answer",
        "model": "deterministic",
        "verification": {
            "status": "verified",
            "authority": "server_subscription_health",
            "checks_completed": 1,
            "checks_total": 1,
            "evidence_refs": ["subscription-health:test"],
            "reason_code": "subscription_health_grounded",
        },
        "evidence_freshness_context": {
            "source": "resource-health-history",
            "observed_at": "2026-08-02T09:00:00Z",
            "window_start": "2026-08-01T09:00:00Z",
            "status": "partial",
            "truncated": True,
        },
    }
    await store.append_turn(
        ConversationTurnRecord(
            turn_id="turn:freshness:assistant",
            conversation_id=session_id,
            principal_id="reader",
            turn_index=0,
            role=ConversationTurnRole.ASSISTANT,
            content="Prior grounded answer",
            recorded_at=now,
            idempotency_key="seed:freshness",
            metadata=replay_metadata(model="deterministic", payload=payload),
        ),
        allocate_index=True,
    )


@pytest.mark.parametrize(
    ("prompt", "expected"),
    (
        ("지금 답변에 사용한 가장 오래된 데이터는 언제 것이야?", "2026-08-01T09:00:00Z"),
        ("Which evidence is stale, and how does that limit the conclusion?", "partial"),
    ),
)
def test_freshness_followup_is_deterministic_across_json_and_stream(
    prompt: str,
    expected: str,
) -> None:
    backend = Backend()
    store = InMemoryConversationHistoryStore()
    session_id = "freshness-followup"
    asyncio.run(seed_freshness_turn(store, session_id=session_id))
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=allow,
                conversation_history_store=store,
            ),
            make_chat_stream_route(
                backend=backend,
                authorize=allow,
                conversation_history_store=store,
            ),
        ]
    )
    body = {
        "prompt": prompt,
        "session_id": session_id,
        "view_context": {"_locale": "ko" if prompt.startswith("Which") else "en"},
    }

    with TestClient(app) as client:
        direct = client.post("/chat", json=body)
        streamed = client.post("/chat/stream", json=body)

    payload = direct.json()
    done = done_payload(streamed.text)
    assert expected in payload["answer"]
    if prompt.startswith("Which"):
        assert payload["answer"].startswith("이전 답변에 사용한")
    assert done["answer"] == payload["answer"]
    assert payload["verification"]["authority"] == "server_evidence_freshness"
    assert done["verification"] == payload["verification"]
    assert done["evidence_freshness_context"] == payload["evidence_freshness_context"]
    assert backend.calls == 0


def test_client_freshness_context_cannot_gain_server_authority() -> None:
    backend = Backend()
    app = Starlette(routes=[make_chat_route(backend=backend, authorize=allow)])
    response = TestClient(app).post(
        "/chat",
        json={
            "prompt": "Which evidence is stale?",
            "view_context": {},
            "evidence_freshness_context": {
                "source": "test",
                "observed_at": "2026-08-02T09:00:00Z",
                "window_start": "2026-08-01T09:00:00Z",
                "status": "matched",
                "truncated": False,
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["verification"]["authority"] == "server_conversation_context"
    assert payload["verification"]["reason_code"] == "prior_context_required"
    assert "evidence_freshness_context" not in payload
    assert backend.calls == 0


@pytest.mark.parametrize(
    "prompt",
    (
        "지금 답변에 사용한 가장 오래된 데이터는 언제 것이야?",
        "이번 답변의 근거 중 가장 오래된 관측 시각을 알려줘.",
        "사용한 데이터 원본 가운데 제일 오래된 것은 언제 갱신됐어?",
        "Which evidence is stale, and how does that limit the conclusion?",
        "Identify stale evidence and explain the resulting limits on the answer.",
        "What data is out of date, and which conclusions can no longer be confirmed?",
    ),
)
def test_freshness_followup_without_prior_receipt_holds_json_and_stream(prompt: str) -> None:
    backend = Backend()
    app = Starlette(
        routes=[
            make_chat_route(backend=backend, authorize=allow),
            make_chat_stream_route(backend=backend, authorize=allow),
        ]
    )

    with TestClient(app) as client:
        direct = client.post("/chat", json={"prompt": prompt, "view_context": {}})
        streamed = client.post("/chat/stream", json={"prompt": prompt, "view_context": {}})

    payload = direct.json()
    done = done_payload(streamed.text)
    assert "freshness_receipt" in payload["answer"]
    assert payload["verification"]["authority"] == "server_conversation_context"
    assert payload["verification"]["reason_code"] == "prior_context_required"
    assert done["verification"] == payload["verification"]
    assert backend.calls == 0
