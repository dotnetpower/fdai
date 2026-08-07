from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.delivery.conversation_images import InMemoryConversationImageStore
from fdai.delivery.operator_api.application.conversation.backend import ChatBackend
from fdai.delivery.operator_api.routes.chat import (
    make_chat_route,
    make_chat_stream_route,
)
from fdai.shared.providers.testing.user_context import InMemoryConversationHistoryStore
from fdai.shared.telemetry import ConversationProgressMetrics


class _ChangingBackend(ChatBackend):
    def __init__(self) -> None:
        self.calls = 0

    async def answer(
        self,
        *,
        prompt: str,  # noqa: ARG002
        view_context: dict[str, Any],  # noqa: ARG002
        history: list[dict[str, str]],  # noqa: ARG002
    ) -> dict[str, str]:
        self.calls += 1
        return {"answer": f"answer-{self.calls}", "model": "changing-test"}


async def _authorize(request: Request) -> str:
    return request.headers.get("x-test-principal", "principal-a")


_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x00\x00\x00\x00"
)
_DATA_URL = f"data:image/png;base64,{base64.b64encode(_PNG).decode()}"


def _client() -> tuple[TestClient, _ChangingBackend, InMemoryConversationHistoryStore]:
    backend = _ChangingBackend()
    store = InMemoryConversationHistoryStore()
    images = InMemoryConversationImageStore()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_authorize,
                conversation_history_store=store,
                conversation_image_store=images,
            ),
            make_chat_stream_route(
                backend=backend,
                authorize=_authorize,
                conversation_history_store=store,
                conversation_image_store=images,
            ),
        ]
    )
    return TestClient(app), backend, store


def _client_with_progress_metrics() -> tuple[
    TestClient,
    _ChangingBackend,
    ConversationProgressMetrics,
]:
    backend = _ChangingBackend()
    store = InMemoryConversationHistoryStore()
    metrics = ConversationProgressMetrics()
    app = Starlette(
        routes=[
            make_chat_stream_route(
                backend=backend,
                authorize=_authorize,
                conversation_history_store=store,
                progress_metrics=metrics,
            ),
        ]
    )
    return TestClient(app), backend, metrics


def _request(
    *,
    prompt: str = "Show major issues.",
    session_id: str = "conversation-1",
) -> dict[str, Any]:
    return {
        "prompt": prompt,
        "session_id": session_id,
        "request_id": "request-1",
    }


def _image_request() -> dict[str, Any]:
    return {
        **_request(),
        "attachments": [{"id": "att-retry", "name": "retry.png", "data_url": _DATA_URL}],
    }


def _done_payload(response_text: str) -> dict[str, Any]:
    lines = response_text.splitlines()
    for index, line in enumerate(lines):
        if line == "event: done":
            return json.loads(lines[index + 1].removeprefix("data: "))
    raise AssertionError("stream did not emit done")


def _event_payloads(response_text: str) -> list[dict[str, Any]]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in response_text.splitlines()
        if line.startswith("data: ")
    ]


def _terminal_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in {"v", "request_id", "seq", "revision"}
    }


def test_json_exact_retry_replays_completed_response_without_backend_call() -> None:
    client, backend, store = _client()

    first = client.post("/chat", json=_request())
    retry = client.post("/chat", json=_request())

    assert first.status_code == retry.status_code == 200
    assert retry.json() == first.json()
    assert backend.calls == 1
    turns = asyncio.run(
        store.list_turns(principal_id="principal-a", conversation_id="conversation-1")
    )
    assert [turn.turn_index for turn in turns] == [0, 1]


def test_stream_exact_retry_replays_only_completed_terminal_response() -> None:
    client, backend, _ = _client()

    first = client.post("/chat/stream", json=_request())
    retry = client.post("/chat/stream", json=_request())
    first_payloads = _event_payloads(first.text)
    retry_payloads = _event_payloads(retry.text)

    assert first.status_code == retry.status_code == 200
    assert _terminal_payload(_done_payload(retry.text)) == _terminal_payload(
        _done_payload(first.text)
    )
    assert retry.text.count("event: done") == 1
    assert "event: token" not in retry.text
    assert [payload["seq"] for payload in first_payloads] == list(range(1, len(first_payloads) + 1))
    assert [payload["revision"] for payload in first_payloads] == sorted(
        payload["revision"] for payload in first_payloads
    )
    assert retry_payloads == [
        {
            **_done_payload(retry.text),
            "v": 1,
            "request_id": "request-1",
            "seq": 1,
            "revision": 0,
        }
    ]
    assert backend.calls == 1


def test_json_exact_image_retry_replays_without_conflict() -> None:
    client, backend, _ = _client()

    first = client.post("/chat", json=_image_request())
    retry = client.post("/chat", json=_image_request())

    assert first.status_code == retry.status_code == 200
    assert retry.json() == first.json()
    assert backend.calls == 1


def test_stream_exact_image_retry_replays_without_conflict() -> None:
    client, backend, _ = _client()

    first = client.post("/chat/stream", json=_image_request())
    retry = client.post("/chat/stream", json=_image_request())

    assert first.status_code == retry.status_code == 200
    assert _terminal_payload(_done_payload(retry.text)) == _terminal_payload(
        _done_payload(first.text)
    )
    assert backend.calls == 1


def test_stream_replay_records_time_to_first_confirmed_latency() -> None:
    client, backend, metrics = _client_with_progress_metrics()

    first = client.post("/chat/stream", json=_request())
    retry = client.post("/chat/stream", json=_request())

    assert first.status_code == retry.status_code == 200
    assert backend.calls == 1
    snapshot = metrics.snapshot()
    assert snapshot.counts["replays"] == 1
    assert snapshot.latency_ms["time_to_first_confirmed"].count == 2


def test_json_changed_prompt_retry_is_conflict() -> None:
    client, backend, _ = _client()
    assert client.post("/chat", json=_request()).status_code == 200

    conflict = client.post("/chat", json=_request(prompt="Show a different result."))

    assert conflict.status_code == 409
    assert backend.calls == 1


def test_stream_changed_prompt_retry_is_conflict() -> None:
    client, backend, _ = _client()
    assert client.post("/chat/stream", json=_request()).status_code == 200

    conflict = client.post(
        "/chat/stream",
        json=_request(prompt="Show a different result."),
    )

    assert conflict.status_code == 409
    assert backend.calls == 1


def test_json_then_stream_reuses_json_terminal_payload() -> None:
    client, backend, _ = _client()
    first = client.post("/chat", json=_request())

    retry = client.post("/chat/stream", json=_request())

    assert _terminal_payload(_done_payload(retry.text)) == first.json()
    assert backend.calls == 1


def test_stream_then_json_reuses_stream_terminal_payload() -> None:
    client, backend, _ = _client()
    first = client.post("/chat/stream", json=_request())

    retry = client.post("/chat", json=_request())

    assert retry.json() == _terminal_payload(_done_payload(first.text))
    assert backend.calls == 1


def test_request_idempotency_is_principal_scoped() -> None:
    client, backend, store = _client()

    first = client.post(
        "/chat",
        json=_request(),
        headers={"x-test-principal": "principal-a"},
    )
    second = client.post(
        "/chat",
        json=_request(),
        headers={"x-test-principal": "principal-b"},
    )

    assert first.status_code == second.status_code == 200
    assert first.json()["answer"] != second.json()["answer"]
    assert backend.calls == 2
    for principal_id in ("principal-a", "principal-b"):
        turns = asyncio.run(
            store.list_turns(principal_id=principal_id, conversation_id="conversation-1")
        )
        assert len(turns) == 2


def test_request_id_cannot_move_to_another_conversation() -> None:
    client, backend, _ = _client()
    assert client.post("/chat", json=_request()).status_code == 200

    conflict = client.post(
        "/chat",
        json=_request(session_id="conversation-2"),
    )

    assert conflict.status_code == 409
    assert backend.calls == 1
