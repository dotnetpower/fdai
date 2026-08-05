"""End-to-end streaming visibility for vision-attachment escalation.

Drives ``make_chat_stream_route`` with an inline image attachment and asserts
the ``vision_analyzing`` and ``vision_grounded`` status frames are emitted
before the terminal answer, symmetric to the web-search progress phases.
"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.delivery.conversation_images import InMemoryConversationImageStore
from fdai.delivery.operator_api.routes.chat import make_chat_stream_route
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


class _FailingImageStore(InMemoryConversationImageStore):
    async def put_many(self, images: Any) -> Any:
        del images
        raise RuntimeError("image store unavailable")


class _FailingHistoryStore(InMemoryConversationHistoryStore):
    async def append_turn(self, record: Any, *, allocate_index: bool = False) -> Any:
        del record, allocate_index
        raise RuntimeError("turn store unavailable")


async def _allow(request: Request) -> str:
    del request
    return "reader"


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
