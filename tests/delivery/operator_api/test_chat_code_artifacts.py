"""Terminal chat replies expose inert, grounded code artifacts."""

from __future__ import annotations

import json
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.delivery.operator_api.application.conversation.backend import ChatBackend
from fdai.delivery.operator_api.routes.chat import (
    make_chat_route,
    make_chat_stream_route,
)


class _CodeBackend(ChatBackend):
    async def answer(
        self,
        *,
        prompt: str,  # noqa: ARG002
        view_context: dict[str, Any],  # noqa: ARG002
        history: list[dict[str, str]],  # noqa: ARG002
    ) -> dict[str, str]:
        return {
            "answer": "Use this snippet:\n\n```python\nprint('grounded')\n```",
            "model": "code-test",
        }


async def _allow(_: Request) -> str:
    return "test-reader"


def _events(body: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for frame in body.strip().split("\n\n"):
        name = "message"
        payload: dict[str, Any] | None = None
        for line in frame.splitlines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                parsed = json.loads(line[5:].strip())
                if isinstance(parsed, dict):
                    payload = parsed
        if payload is not None:
            events.append((name, payload))
    return events


def test_chat_reply_includes_grounded_code_artifact() -> None:
    app = Starlette(routes=[make_chat_route(backend=_CodeBackend(), authorize=_allow)])

    response = TestClient(app).post(
        "/chat",
        json={"prompt": "write python", "view_context": {}, "history": []},
    )

    assert response.status_code == 200
    artifact = response.json()["code_artifacts"][0]
    assert artifact["artifact_ref"] == f"code:sha256:{artifact['sha256']}"
    assert artifact["language"] == "python"
    assert artifact["content"] == "print('grounded')\n"
    assert artifact["validation_status"] == "valid"
    assert artifact["validation_detail"] is None


def test_stream_done_includes_same_grounded_code_artifact() -> None:
    app = Starlette(routes=[make_chat_stream_route(backend=_CodeBackend(), authorize=_allow)])

    response = TestClient(app).post(
        "/chat/stream",
        json={"prompt": "write python", "view_context": {}, "history": []},
    )

    assert response.status_code == 200
    done = next(payload for name, payload in _events(response.text) if name == "done")
    artifact = done["code_artifacts"][0]
    assert artifact["content"] == "print('grounded')\n"
    assert artifact["validation_status"] == "valid"
