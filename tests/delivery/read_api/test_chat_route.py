"""Tests for the ``POST /chat`` route latency + model surfacing."""

from __future__ import annotations

import asyncio
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.delivery.read_api.chat import (
    ChatBackend,
    ChatBackendUnavailableError,
    make_chat_route,
)


class _RecordingBackend(ChatBackend):
    """Deterministic backend that returns a canned reply after a small delay."""

    def __init__(self, *, model: str, delay_ms: int) -> None:
        self._model = model
        self._delay_ms = delay_ms

    async def answer(
        self,
        *,
        prompt: str,  # noqa: ARG002 - Protocol required
        view_context: dict[str, Any],  # noqa: ARG002
        history: list[dict[str, str]],  # noqa: ARG002
    ) -> dict[str, str]:
        await asyncio.sleep(self._delay_ms / 1000)
        return {"answer": "hello", "model": self._model}


class _DisabledBackend(ChatBackend):
    async def answer(
        self,
        *,
        prompt: str,  # noqa: ARG002 - Protocol required
        view_context: dict[str, Any],  # noqa: ARG002
        history: list[dict[str, str]],  # noqa: ARG002
    ) -> dict[str, str]:
        raise ChatBackendUnavailableError("disabled for test")


async def _allow(_: Request) -> str:
    return "test-reader"


def _app(backend: ChatBackend) -> Starlette:
    return Starlette(routes=[make_chat_route(backend=backend, authorize=_allow)])


class TestChatRouteLatencySurface:
    def test_reply_includes_model_and_latency_ms(self) -> None:
        backend = _RecordingBackend(model="gpt-5.4-mini", delay_ms=25)
        client = TestClient(_app(backend))
        resp = client.post("/chat", json={"prompt": "hi", "view_context": {}, "history": []})
        assert resp.status_code == 200
        body = resp.json()
        assert body["answer"] == "hello"
        assert body["model"] == "gpt-5.4-mini"
        assert isinstance(body["latency_ms"], int)
        # 25ms sleep + overhead; keep the assertion soft to stay hermetic.
        assert body["latency_ms"] >= 20
        assert body["latency_ms"] < 5_000

    def test_disabled_backend_returns_501(self) -> None:
        client = TestClient(_app(_DisabledBackend()))
        resp = client.post("/chat", json={"prompt": "hi", "view_context": {}, "history": []})
        assert resp.status_code == 501
