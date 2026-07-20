from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from starlette.applications import Starlette
from starlette.requests import Request

from fdai.core.conversation import (
    BusyInput,
    BusyInputCoordinator,
    BusyInputKind,
    BusyInputMode,
    InMemoryBusyInputStore,
)
from fdai.delivery.read_api.routes.chat import make_chat_route, make_chat_stream_route
from fdai.shared.providers.testing.user_context import InMemoryConversationHistoryStore
from fdai.shared.providers.user_context import ConversationTurnRole

_NOW = datetime(2026, 7, 20, 16, tzinfo=UTC)


async def _authorize(_request: Request) -> str:
    return "operator-one"


def _input(*, mode: BusyInputMode, index: int = 1) -> BusyInput:
    return BusyInput(
        input_id=f"input-{index}",
        idempotency_key=f"idempotency-{index}",
        session_id="session-one",
        principal_id="operator-one",
        content=f"guidance {index}",
        kind=BusyInputKind.PROSE,
        received_at=_NOW,
        expires_at=_NOW + timedelta(minutes=5),
    )


class _BlockingBackend:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def answer(
        self,
        *,
        prompt: str,  # noqa: ARG002
        view_context: dict[str, Any],  # noqa: ARG002
        history: list[dict[str, str]],  # noqa: ARG002
    ) -> dict[str, str]:
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        raise AssertionError("unreachable")


class _SteerBackend:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.histories: list[list[dict[str, str]]] = []

    async def answer(
        self,
        *,
        prompt: str,  # noqa: ARG002
        view_context: dict[str, Any],  # noqa: ARG002
        history: list[dict[str, str]],
    ) -> dict[str, str]:
        self.histories.append([dict(item) for item in history])
        if len(self.histories) == 1:
            self.started.set()
            await self.release.wait()
        return {"answer": f"answer-{len(self.histories)}", "model": "test"}


class _BlockingStreamBackend:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def answer(
        self,
        *,
        prompt: str,  # noqa: ARG002
        view_context: dict[str, Any],  # noqa: ARG002
        history: list[dict[str, str]],  # noqa: ARG002
    ) -> dict[str, str]:
        raise AssertionError("stream path MUST use answer_stream")

    async def answer_stream(
        self,
        *,
        prompt: str,  # noqa: ARG002
        view_context: dict[str, Any],  # noqa: ARG002
        history: list[dict[str, str]],  # noqa: ARG002
    ) -> Any:
        self.started.set()
        yield {"type": "token", "delta": "partial"}
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


class _SteerStreamBackend:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.histories: list[list[dict[str, str]]] = []

    async def answer(
        self,
        *,
        prompt: str,  # noqa: ARG002
        view_context: dict[str, Any],  # noqa: ARG002
        history: list[dict[str, str]],  # noqa: ARG002
    ) -> dict[str, str]:
        raise AssertionError("stream path MUST use answer_stream")

    async def answer_stream(
        self,
        *,
        prompt: str,  # noqa: ARG002
        view_context: dict[str, Any],  # noqa: ARG002
        history: list[dict[str, str]],
    ) -> Any:
        self.histories.append([dict(item) for item in history])
        call = len(self.histories)
        if call == 1:
            self.started.set()
            await self.release.wait()
        answer = f"stream-{call}"
        yield {"type": "token", "delta": answer}
        yield {"type": "done", "answer": answer, "model": "test"}


async def test_one_shot_interrupt_cancels_backend_and_skips_assistant_history() -> None:
    backend = _BlockingBackend()
    history = InMemoryConversationHistoryStore()
    coordinator = BusyInputCoordinator(store=InMemoryBusyInputStore())
    await coordinator.set_mode(
        session_id="session-one",
        principal_id="operator-one",
        mode=BusyInputMode.INTERRUPT,
    )
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_authorize,
                conversation_history_store=history,
                busy_input_coordinator=coordinator,
            )
        ]
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        request = asyncio.create_task(
            client.post(
                "/chat",
                json={
                    "prompt": "status",
                    "session_id": "session-one",
                    "request_id": "request-one",
                },
            )
        )
        await backend.started.wait()
        await coordinator.submit(_input(mode=BusyInputMode.INTERRUPT), now=_NOW)
        response = await request

    turns = await history.list_turns(
        principal_id="operator-one",
        conversation_id="session-one",
    )
    assert response.status_code == 409
    assert backend.cancelled.is_set()
    assert [turn.role for turn in turns] == [ConversationTurnRole.OPERATOR]
    assert coordinator.active("session-one") is None


async def test_one_shot_steer_is_added_once_and_reruns_narrator() -> None:
    backend = _SteerBackend()
    coordinator = BusyInputCoordinator(store=InMemoryBusyInputStore())
    await coordinator.set_mode(
        session_id="session-one",
        principal_id="operator-one",
        mode=BusyInputMode.STEER,
    )
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_authorize,
                busy_input_coordinator=coordinator,
            )
        ]
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        request = asyncio.create_task(
            client.post(
                "/chat",
                json={
                    "prompt": "status",
                    "session_id": "session-one",
                    "request_id": "request-one",
                },
            )
        )
        await backend.started.wait()
        await coordinator.submit(_input(mode=BusyInputMode.STEER), now=_NOW)
        backend.release.set()
        response = await request

    assert response.status_code == 200
    assert response.json()["answer"] == "answer-2"
    assert len(backend.histories) == 2
    assert backend.histories[0] == []
    assert backend.histories[1] == [{"role": "user", "content": "guidance 1"}]
    assert (
        await coordinator.pending(
            session_id="session-one",
            principal_id="operator-one",
        )
        == ()
    )


async def test_stream_interrupt_emits_no_done_and_skips_assistant_history() -> None:
    backend = _BlockingStreamBackend()
    history = InMemoryConversationHistoryStore()
    coordinator = BusyInputCoordinator(store=InMemoryBusyInputStore())
    await coordinator.set_mode(
        session_id="session-one",
        principal_id="operator-one",
        mode=BusyInputMode.INTERRUPT,
    )
    app = Starlette(
        routes=[
            make_chat_stream_route(
                backend=backend,
                authorize=_authorize,
                conversation_history_store=history,
                busy_input_coordinator=coordinator,
            )
        ]
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        request = asyncio.create_task(
            client.post(
                "/chat/stream",
                json={
                    "prompt": "status",
                    "session_id": "session-one",
                    "request_id": "request-one",
                },
            )
        )
        await backend.started.wait()
        await coordinator.submit(_input(mode=BusyInputMode.INTERRUPT), now=_NOW)
        response = await request

    turns = await history.list_turns(
        principal_id="operator-one",
        conversation_id="session-one",
    )
    assert response.status_code == 200
    assert "event: interrupted" in response.text
    assert "event: done" not in response.text
    assert backend.cancelled.is_set()
    assert [turn.role for turn in turns] == [ConversationTurnRole.OPERATOR]
    assert coordinator.active("session-one") is None


async def test_stream_steer_is_consumed_once_and_reruns_narrator() -> None:
    backend = _SteerStreamBackend()
    coordinator = BusyInputCoordinator(store=InMemoryBusyInputStore())
    await coordinator.set_mode(
        session_id="session-one",
        principal_id="operator-one",
        mode=BusyInputMode.STEER,
    )
    app = Starlette(
        routes=[
            make_chat_stream_route(
                backend=backend,
                authorize=_authorize,
                busy_input_coordinator=coordinator,
            )
        ]
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        request = asyncio.create_task(
            client.post(
                "/chat/stream",
                json={
                    "prompt": "status",
                    "session_id": "session-one",
                    "request_id": "request-one",
                },
            )
        )
        await backend.started.wait()
        await coordinator.submit(_input(mode=BusyInputMode.STEER), now=_NOW)
        backend.release.set()
        response = await request

    assert response.status_code == 200
    assert len(backend.histories) == 2
    assert backend.histories[0] == []
    assert backend.histories[1] == [{"role": "user", "content": "guidance 1"}]
    assert "event: done" in response.text
    assert '"stream-2"' in response.text
    assert (
        await coordinator.pending(
            session_id="session-one",
            principal_id="operator-one",
        )
        == ()
    )
