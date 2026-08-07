"""End-to-end streaming visibility for vision-attachment escalation.

Drives ``make_chat_stream_route`` with an inline image attachment and asserts
the ``vision_analyzing`` and ``vision_grounded`` status frames are emitted
before the terminal answer, symmetric to the web-search progress phases.
"""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import timedelta
from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.delivery.conversation_images import InMemoryConversationImageStore
from fdai.delivery.operator_api.application.conversation.capabilities.conversation_context import (
    ConversationContextChatTools,
)
from fdai.delivery.operator_api.application.conversation.capabilities.llm_usage import (
    is_llm_usage_followup,
)
from fdai.delivery.operator_api.routes.chat import make_chat_route, make_chat_stream_route
from fdai.shared.providers.testing.user_context import InMemoryConversationHistoryStore

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x00\x00\x00\x00"
)
_DATA_URL = f"data:image/png;base64,{base64.b64encode(_PNG).decode()}"


class _Backend:
    """Records whether the narrator received a multimodal user turn."""

    def __init__(self) -> None:
        self.saw_image_part = False

    async def answer(
        self,
        *,
        prompt: str,
        view_context: dict[str, Any],
        history: list[dict[str, str]],
    ) -> dict[str, str]:
        del prompt, history
        # The route must have placed validated attachments for the narrator.
        attachments = view_context.get("_attachments")
        self.saw_image_part = bool(attachments)
        return {"answer": "The photo shows two people.", "model": "vision-test"}


class _UnexpectedPlanner:
    def __init__(self) -> None:
        self.calls = 0

    async def plan_turn(self, **_kwargs: object) -> None:
        self.calls += 1
        raise AssertionError("image turns must bypass semantic tool planning")


class _FailingImageStore(InMemoryConversationImageStore):
    async def put_many(self, images: Any) -> Any:
        del images
        raise RuntimeError("image store unavailable")


class _FailingHistoryStore(InMemoryConversationHistoryStore):
    async def append_turn(self, record: Any, *, allocate_index: bool = False) -> Any:
        del record, allocate_index
        raise RuntimeError("turn store unavailable")


class _FailingDeleteImageStore(InMemoryConversationImageStore):
    async def delete_many(self, **_kwargs: Any) -> None:
        raise RuntimeError("image cleanup unavailable")


async def _allow(request: Request) -> str:
    del request
    return "reader"


def _done_payload(body: str) -> dict[str, Any]:
    for block in body.split("\n\n"):
        if not block.startswith("event: done\n"):
            continue
        data = next(line[6:] for line in block.splitlines() if line.startswith("data: "))
        return json.loads(data)  # type: ignore[no-any-return]
    raise AssertionError("done event missing")


def test_chat_stream_emits_vision_phases_before_answer() -> None:
    backend = _Backend()
    app = Starlette(routes=[make_chat_stream_route(backend=backend, authorize=_allow)])

    with TestClient(app) as client:
        response = client.post(
            "/chat/stream",
            json={
                "prompt": "how many people are in this photo?",
                "view_context": {},
                "session_id": "session-vision",
                "request_id": "request-vision",
                "attachments": [{"name": "photo.png", "data_url": _DATA_URL}],
            },
        )

    assert response.status_code == 200
    body = response.text
    analyzing = body.index('"phase": "vision_analyzing"')
    grounded = body.index('"phase": "vision_grounded"')
    done = body.index("event: done")
    assert analyzing < grounded < done
    # The attachment preview carries display metadata, never the base64 body.
    assert '"label": "photo.png"' in body
    assert base64.b64encode(_PNG).decode() not in body
    assert backend.saw_image_part is True


@pytest.mark.parametrize("stream", [False, True])
def test_chat_attachment_preempts_prompt_only_routing(stream: bool) -> None:
    backend = _Backend()
    planner = _UnexpectedPlanner()
    tools = ConversationContextChatTools(analysis_predicate=is_llm_usage_followup)
    route_factory = make_chat_stream_route if stream else make_chat_route
    app = Starlette(
        routes=[
            route_factory(
                backend=backend,
                authorize=_allow,
                tool_resolver=tools,
                turn_planner=planner,  # type: ignore[arg-type]
            )
        ]
    )

    with TestClient(app) as client:
        response = client.post(
            "/chat/stream" if stream else "/chat",
            json={
                "prompt": "이 이미지의 주요 구성 요소를 표로 정리해줘.",
                "view_context": {},
                "session_id": "session-vision-table",
                "request_id": "request-vision-table",
                "attachments": [{"name": "outline.png", "data_url": _DATA_URL}],
            },
        )

    assert response.status_code == 200
    if stream:
        assert '"phase": "vision_analyzing"' in response.text
    assert "prior_analysis_context" not in response.text
    assert planner.calls == 0
    assert backend.saw_image_part is True
    payload = _done_payload(response.text) if stream else response.json()
    assert payload["answer"] == "The photo shows two people."
    assert payload["verification"]["status"] == "unverified"
    assert payload["verification"]["authority"] == "vision_narrator"
    assert payload["verification"]["reason_code"] == "vision_interpretation_unverified"
    assert payload["verification"]["evidence_refs"][0].startswith("conversation-image:att-")


def test_chat_stream_without_attachments_emits_no_vision_phase() -> None:
    app = Starlette(routes=[make_chat_stream_route(backend=_Backend(), authorize=_allow)])

    with TestClient(app) as client:
        response = client.post(
            "/chat/stream",
            json={
                "prompt": "what is HIL?",
                "view_context": {},
                "session_id": "session-plain",
                "request_id": "request-plain",
            },
        )

    assert response.status_code == 200
    assert "vision_analyzing" not in response.text
    assert "vision_grounded" not in response.text


def test_chat_stream_persists_image_bytes_outside_turn_metadata() -> None:
    history = InMemoryConversationHistoryStore()
    images = InMemoryConversationImageStore()
    app = Starlette(
        routes=[
            make_chat_stream_route(
                backend=_Backend(),
                authorize=_allow,
                conversation_history_store=history,
                conversation_image_store=images,
            )
        ]
    )

    response = TestClient(app).post(
        "/chat/stream",
        json={
            "prompt": "what is shown?",
            "session_id": "session-history-image",
            "request_id": "request-history-image",
            "attachments": [
                {"id": "att-history-image", "name": "photo.png", "data_url": _DATA_URL}
            ],
        },
    )

    assert response.status_code == 200

    async def load() -> tuple[Any, Any]:
        turns = await history.list_all_turns(
            principal_id="reader",
            conversation_id="session-history-image",
        )
        image = await images.get(
            principal_id="reader",
            conversation_id="session-history-image",
            image_id="att-history-image",
        )
        return turns[0], image

    operator_turn, stored_image = asyncio.run(load())
    assert json.loads(operator_turn.metadata["attachments"]) == [
        {"id": "att-history-image", "name": "photo.png", "media_type": "image/png"}
    ]
    assert _DATA_URL not in json.dumps(dict(operator_turn.metadata))
    assert stored_image is not None
    assert stored_image.content == _PNG
    assert stored_image.expires_at - stored_image.created_at == timedelta(days=90)


def test_chat_stream_image_failure_leaves_no_operator_turn() -> None:
    history = InMemoryConversationHistoryStore()
    app = Starlette(
        routes=[
            make_chat_stream_route(
                backend=_Backend(),
                authorize=_allow,
                conversation_history_store=history,
                conversation_image_store=_FailingImageStore(),
            )
        ]
    )

    with pytest.raises(RuntimeError, match="image store unavailable"):
        TestClient(app).post(
            "/chat/stream",
            json={
                "prompt": "what is shown?",
                "session_id": "session-failed-image",
                "request_id": "request-failed-image",
                "attachments": [{"name": "photo.png", "data_url": _DATA_URL}],
            },
        )

    turns = asyncio.run(
        history.list_all_turns(
            principal_id="reader",
            conversation_id="session-failed-image",
        )
    )
    assert len(turns) == 0


def test_chat_stream_turn_failure_compensates_new_image() -> None:
    history = _FailingHistoryStore()
    images = InMemoryConversationImageStore()
    app = Starlette(
        routes=[
            make_chat_stream_route(
                backend=_Backend(),
                authorize=_allow,
                conversation_history_store=history,
                conversation_image_store=images,
            )
        ]
    )

    with pytest.raises(RuntimeError, match="turn store unavailable"):
        TestClient(app).post(
            "/chat/stream",
            json={
                "prompt": "what is shown?",
                "session_id": "session-failed-turn",
                "request_id": "request-failed-turn",
                "attachments": [
                    {"id": "att-compensated", "name": "photo.png", "data_url": _DATA_URL}
                ],
            },
        )

    stored = asyncio.run(
        images.get(
            principal_id="reader",
            conversation_id="session-failed-turn",
            image_id="att-compensated",
        )
    )
    assert stored is None


def test_chat_stream_cleanup_failure_leaves_only_short_pending_expiry() -> None:
    history = _FailingHistoryStore()
    images = _FailingDeleteImageStore()
    app = Starlette(
        routes=[
            make_chat_stream_route(
                backend=_Backend(),
                authorize=_allow,
                conversation_history_store=history,
                conversation_image_store=images,
            )
        ]
    )

    with pytest.raises(RuntimeError, match="turn store unavailable"):
        TestClient(app).post(
            "/chat/stream",
            json={
                "prompt": "what is shown?",
                "session_id": "session-failed-cleanup",
                "request_id": "request-failed-cleanup",
                "attachments": [{"id": "att-pending", "name": "photo.png", "data_url": _DATA_URL}],
            },
        )

    stored = asyncio.run(
        images.get(
            principal_id="reader",
            conversation_id="session-failed-cleanup",
            image_id="att-pending",
        )
    )
    assert stored is not None
    assert stored.expires_at - stored.created_at == timedelta(minutes=15)
