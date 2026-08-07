"""Transport-free contracts for the conversation-turn application service."""

from __future__ import annotations

import ast
import json
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.testclient import TestClient

from fdai.delivery.operator_api.application import (
    ConversationTurnApplicationService,
    ConversationTurnExecution,
    ConversationTurnInput,
    ConversationTurnResult,
    ConversationTurnTerminalStatus,
)
from fdai.delivery.operator_api.application.conversation.backend import (
    ChatBackendUnavailableError,
    ChatContentPolicyError,
)
from fdai.delivery.operator_api.routes.chat import make_chat_route
from fdai.delivery.operator_api.routes.chat_stream import make_chat_stream_route

_ROOT = Path(__file__).resolve().parents[3]


def _request(*, streaming: bool = False) -> ConversationTurnInput:
    return ConversationTurnInput(
        principal_id="reader-1",
        conversation_id="conversation-1",
        request_id="request-1",
        correlation_id="chat:reader-1:conversation-1",
        prompt="Summarize the verified evidence.",
        response_locale="en",
        target_agent="Bragi",
        evidence_refs=("audit:event-1",),
        history_turn_count=2,
        streaming=streaming,
    )


async def test_executes_complete_verified_turn_without_starlette() -> None:
    service = ConversationTurnApplicationService()
    request = _request()
    payload = {
        "answer": "Verified answer",
        "model": "narrator-mini",
        "source": "evidence:verified",
        "verification": {
            "status": "verified",
            "authority": "server-evidence",
            "reason_code": "evidence_grounded",
            "evidence_refs": ["audit:event-1"],
            "checks_completed": 2,
            "checks_total": 2,
        },
        "presentation_artifact": {"schema_version": 1, "blocks": []},
        "delegation": {"agent": "Bragi"},
    }

    async def processor(received: ConversationTurnInput) -> dict[str, object]:
        assert received is request
        return payload

    result = await service.execute(request, processor)

    assert result.terminal_status is ConversationTurnTerminalStatus.COMPLETED
    assert result.answer == "Verified answer"
    assert result.evidence_refs == ("audit:event-1",)
    assert result.presentation_artifact == {"schema_version": 1, "blocks": ()}
    assert result.delegation == {"agent": "Bragi"}
    assert result.to_wire_payload() == payload
    with pytest.raises(TypeError):
        result.wire_payload["answer"] = "changed"  # type: ignore[index]


def test_input_has_no_authority_or_provider_scope_fields() -> None:
    names = {field.name for field in fields(ConversationTurnInput)}

    assert names == {
        "principal_id",
        "conversation_id",
        "request_id",
        "correlation_id",
        "prompt",
        "response_locale",
        "target_agent",
        "evidence_refs",
        "history_turn_count",
        "streaming",
    }
    assert not names & {
        "provider_scope",
        "credentials",
        "approval",
        "roles",
        "executor_identity",
    }


@pytest.mark.parametrize(
    "status",
    [
        ConversationTurnTerminalStatus.ABSTAINED,
        ConversationTurnTerminalStatus.UNAVAILABLE,
        ConversationTurnTerminalStatus.CANCELLED,
        ConversationTurnTerminalStatus.FAILED,
    ],
)
def test_represents_explicit_non_success_terminal_status(
    status: ConversationTurnTerminalStatus,
) -> None:
    service = ConversationTurnApplicationService()
    execution = service.start_turn(_request(streaming=True))
    wire = {
        "detail": "turn did not complete",
        "session_id": "conversation-1",
        "request_id": "request-1",
    }

    result = service.terminate_turn(
        execution,
        terminal_status=status,
        code=status.value,
        detail="turn did not complete",
        wire_payload=wire,
    )

    assert result.terminal_status is status
    assert result.failure_code == status.value
    assert result.failure_detail == "turn did not complete"
    assert result.to_wire_payload() == wire


def test_execution_rejects_double_or_contradictory_terminal_closure() -> None:
    service = ConversationTurnApplicationService()
    execution = service.start_turn(_request())
    service.complete_turn(execution, {"answer": "completed"})

    with pytest.raises(RuntimeError, match="already closed"):
        service.terminate_turn(
            execution,
            terminal_status=ConversationTurnTerminalStatus.FAILED,
            code="late_failure",
            detail="late failure",
            wire_payload={"detail": "late failure"},
        )

    open_execution = service.start_turn(_request())
    with pytest.raises(ValueError, match="cannot advertise success"):
        service.terminate_turn(
            open_execution,
            terminal_status=ConversationTurnTerminalStatus.FAILED,
            code="failed",
            detail="failed",
            wire_payload={"answer": "false success"},
        )

    other_execution = service.start_turn(
        ConversationTurnInput(
            principal_id="reader-1",
            conversation_id="conversation-2",
            request_id="request-2",
            correlation_id="chat:reader-1:conversation-2",
            prompt="Summarize evidence.",
        )
    )
    foreign_result = service.validate_turn_result(other_execution, {"answer": "foreign"})
    with pytest.raises(ValueError, match="identity conflicts"):
        open_execution.close(foreign_result)
    with pytest.raises(AttributeError):
        execution.request = other_execution.request  # type: ignore[misc]


def test_rejects_unbounded_or_non_json_terminal_payload() -> None:
    service = ConversationTurnApplicationService()
    execution = service.start_turn(_request())

    with pytest.raises(ValueError, match="finite"):
        service.complete_turn(execution, {"answer": "x", "latency_ms": float("nan")})
    with pytest.raises(ValueError, match="unsupported"):
        service.complete_turn(execution, {"answer": object()})


def test_rejects_inconsistent_status_evidence_and_wire_identity() -> None:
    service = ConversationTurnApplicationService()
    execution = service.start_turn(_request())

    with pytest.raises(ValueError, match="conflicts with verification"):
        service.complete_turn(
            execution,
            {"answer": "answer"},
            terminal_status=ConversationTurnTerminalStatus.COMPLETED,
        )
    corrected = service.complete_turn(
        execution,
        {
            "answer": "corrected answer",
            "verification": {
                "status": "corrected",
                "evidence_refs": [],
                "checks_completed": 1,
                "checks_total": 1,
            },
        },
        terminal_status=ConversationTurnTerminalStatus.CORRECTED,
    )
    assert corrected.terminal_status is ConversationTurnTerminalStatus.CORRECTED
    with pytest.raises(ValueError, match="status is invalid"):
        service.complete_turn(
            execution,
            {
                "answer": "answer",
                "verification": {
                    "status": "mystery",
                    "evidence_refs": [],
                    "checks_completed": 0,
                    "checks_total": 0,
                },
            },
        )
    with pytest.raises(ValueError, match="contain strings"):
        service.complete_turn(
            execution,
            {
                "answer": "answer",
                "verification": {
                    "status": "verified",
                    "evidence_refs": [42],
                    "checks_completed": 1,
                    "checks_total": 1,
                },
            },
        )
    with pytest.raises(ValueError, match="request_id conflicts"):
        service.complete_turn(
            execution,
            {"answer": "answer", "request_id": "another-request"},
        )


def test_input_normalizes_evidence_refs_to_an_immutable_tuple() -> None:
    mutable_refs = ["audit:event-1"]
    request = ConversationTurnInput(
        principal_id="reader-1",
        conversation_id="conversation-1",
        request_id="request-1",
        correlation_id="chat:reader-1:conversation-1",
        prompt="Summarize the verified evidence.",
        evidence_refs=mutable_refs,  # type: ignore[arg-type]
    )

    mutable_refs.append("audit:event-2")

    assert request.evidence_refs == ("audit:event-1",)


def test_input_rejects_scalar_evidence_refs() -> None:
    with pytest.raises(ValueError, match="sequence of strings"):
        ConversationTurnInput(
            principal_id="reader-1",
            conversation_id="conversation-1",
            request_id="request-1",
            correlation_id="chat:reader-1:conversation-1",
            prompt="Summarize the verified evidence.",
            evidence_refs="audit:event-1",  # type: ignore[arg-type]
        )


def test_input_accepts_bounded_multiline_prompt() -> None:
    request = ConversationTurnInput(
        principal_id="reader-1",
        conversation_id="conversation-1",
        request_id="request-1",
        correlation_id="chat:reader-1:conversation-1",
        prompt="show\nthe tables\nin database",
    )

    assert request.prompt == "show\nthe tables\nin database"


def test_rejects_cyclic_or_excessively_nested_terminal_payload() -> None:
    service = ConversationTurnApplicationService()
    execution = service.start_turn(_request())
    cyclic: list[object] = []
    cyclic.append(cyclic)
    nested: object = "leaf"
    for _ in range(66):
        nested = {"next": nested}

    with pytest.raises(ValueError, match="cyclic"):
        service.complete_turn(execution, {"answer": "answer", "metadata": cyclic})
    with pytest.raises(ValueError, match="depth bound"):
        service.complete_turn(execution, {"answer": "answer", "metadata": nested})


class _Backend:
    async def answer(
        self,
        *,
        prompt: str,
        view_context: dict[str, Any],
        history: list[dict[str, str]],
    ) -> dict[str, Any]:
        return {"answer": "typed route answer", "model": "test-model"}


class _ReservedFieldBackend(_Backend):
    async def answer(
        self,
        *,
        prompt: str,
        view_context: dict[str, Any],
        history: list[dict[str, str]],
    ) -> dict[str, Any]:
        return {
            "answer": "typed route answer",
            "model": "test-model",
            "v": 99,
            "seq": 999,
            "revision": 999,
        }


class _UnavailableBackend(_Backend):
    async def answer(
        self,
        *,
        prompt: str,
        view_context: dict[str, Any],
        history: list[dict[str, str]],
    ) -> dict[str, Any]:
        raise ChatBackendUnavailableError("disabled for test")


class _PolicyBackend(_Backend):
    async def answer(
        self,
        *,
        prompt: str,
        view_context: dict[str, Any],
        history: list[dict[str, str]],
    ) -> dict[str, Any]:
        raise ChatContentPolicyError(stage="output")


class _HttpFailureBackend(_Backend):
    async def answer(
        self,
        *,
        prompt: str,
        view_context: dict[str, Any],
        history: list[dict[str, str]],
    ) -> dict[str, Any]:
        raise HTTPException(status_code=429, detail="bounded upstream reason")


class _GenericFailureBackend(_Backend):
    async def answer(
        self,
        *,
        prompt: str,
        view_context: dict[str, Any],
        history: list[dict[str, str]],
    ) -> dict[str, Any]:
        raise RuntimeError("unexpected backend failure")


class _OversizedBackend(_Backend):
    async def answer(
        self,
        *,
        prompt: str,
        view_context: dict[str, Any],
        history: list[dict[str, str]],
    ) -> dict[str, Any]:
        return {"answer": "x" * (256 * 1024), "model": "test-model"}


class _BusyCoordinator:
    async def begin_turn(self, **_kwargs: object) -> None:
        raise RuntimeError("busy")


class _RecordingService(ConversationTurnApplicationService):
    def __init__(self) -> None:
        self.started: list[ConversationTurnInput] = []
        self.completed: list[ConversationTurnResult] = []
        self.terminated: list[ConversationTurnResult] = []

    def start_turn(self, request: ConversationTurnInput) -> ConversationTurnExecution:
        self.started.append(request)
        return super().start_turn(request)

    def complete_turn(
        self,
        execution: ConversationTurnExecution,
        payload: dict[str, object],
        *,
        terminal_status: ConversationTurnTerminalStatus | None = None,
    ) -> ConversationTurnResult:
        result = super().complete_turn(
            execution,
            payload,
            terminal_status=terminal_status,
        )
        self.completed.append(result)
        return result

    def terminate_turn(
        self,
        execution: ConversationTurnExecution,
        *,
        terminal_status: ConversationTurnTerminalStatus,
        code: str,
        detail: str,
        wire_payload: dict[str, object],
    ) -> ConversationTurnResult:
        result = super().terminate_turn(
            execution,
            terminal_status=terminal_status,
            code=code,
            detail=detail,
            wire_payload=wire_payload,
        )
        self.terminated.append(result)
        return result


async def _authorize(_request: object) -> str:
    return "reader-1"


def test_json_and_sse_routes_invoke_same_typed_service() -> None:
    service = _RecordingService()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=_Backend(),
                authorize=_authorize,  # type: ignore[arg-type]
                turn_service=service,
            ),
            make_chat_stream_route(
                backend=_Backend(),
                authorize=_authorize,  # type: ignore[arg-type]
                turn_service=service,
            ),
        ]
    )
    client = TestClient(app)

    assert (
        client.post(
            "/chat",
            json={"prompt": "summarize", "session_id": "conversation-json"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/chat/stream",
            json={"prompt": "summarize", "session_id": "conversation-stream"},
        ).status_code
        == 200
    )

    assert [request.streaming for request in service.started] == [False, True]
    assert [result.answer for result in service.completed] == [
        "typed route answer",
        "typed route answer",
    ]
    assert all(result.verification is not None for result in service.completed)


def test_falsey_injected_service_identity_is_preserved() -> None:
    class FalseyService(_RecordingService):
        def __bool__(self) -> bool:
            return False

    service = FalseyService()
    app = Starlette(
        routes=[
            make_chat_route(backend=_Backend(), authorize=_authorize, turn_service=service),
            make_chat_stream_route(backend=_Backend(), authorize=_authorize, turn_service=service),
        ]
    )
    client = TestClient(app)

    assert client.post("/chat", json={"prompt": "summarize"}).status_code == 200
    assert client.post("/chat/stream", json={"prompt": "summarize"}).status_code == 200
    assert [request.streaming for request in service.started] == [False, True]


@pytest.mark.parametrize(
    ("backend", "expected_status", "terminal_status"),
    [
        (_UnavailableBackend(), 501, ConversationTurnTerminalStatus.UNAVAILABLE),
        (_PolicyBackend(), 422, ConversationTurnTerminalStatus.ABSTAINED),
    ],
)
def test_json_failure_paths_close_typed_turn(
    backend: _Backend,
    expected_status: int,
    terminal_status: ConversationTurnTerminalStatus,
) -> None:
    service = _RecordingService()
    app = Starlette(
        routes=[make_chat_route(backend=backend, authorize=_authorize, turn_service=service)]
    )

    response = TestClient(app).post("/chat", json={"prompt": "summarize"})

    assert response.status_code == expected_status
    assert service.terminated[-1].terminal_status is terminal_status


@pytest.mark.parametrize(
    ("backend", "terminal_status"),
    [
        (_UnavailableBackend(), ConversationTurnTerminalStatus.UNAVAILABLE),
        (_PolicyBackend(), ConversationTurnTerminalStatus.ABSTAINED),
    ],
)
def test_sse_failure_paths_close_typed_turn(
    backend: _Backend,
    terminal_status: ConversationTurnTerminalStatus,
) -> None:
    service = _RecordingService()
    app = Starlette(
        routes=[
            make_chat_stream_route(
                backend=backend,
                authorize=_authorize,
                turn_service=service,
            )
        ]
    )

    response = TestClient(app).post("/chat/stream", json={"prompt": "summarize"})

    assert response.status_code == 200
    assert service.terminated[-1].terminal_status is terminal_status


def test_sse_transport_envelope_overrides_backend_reserved_fields() -> None:
    app = Starlette(
        routes=[make_chat_stream_route(backend=_ReservedFieldBackend(), authorize=_authorize)]
    )

    response = TestClient(app).post(
        "/chat/stream",
        json={"prompt": "summarize", "request_id": "request-owned-by-route"},
    )
    done_frame = next(
        frame for frame in response.text.split("\n\n") if frame.startswith("event: done")
    )
    data_line = next(line[6:] for line in done_frame.splitlines() if line.startswith("data: "))
    payload = json.loads(data_line)

    assert payload["v"] == 1
    assert payload["request_id"] == "request-owned-by-route"
    assert payload["seq"] != 999
    assert payload["revision"] != 999


def test_sse_known_http_failure_retains_bounded_status_and_reason() -> None:
    app = Starlette(
        routes=[make_chat_stream_route(backend=_HttpFailureBackend(), authorize=_authorize)]
    )

    response = TestClient(app).post("/chat/stream", json={"prompt": "summarize"})
    error_frame = next(
        frame for frame in response.text.split("\n\n") if frame.startswith("event: error")
    )
    data_line = next(line[6:] for line in error_frame.splitlines() if line.startswith("data: "))
    payload = json.loads(data_line)

    assert payload["code"] == "chat_stream_failed"
    assert payload["status"] == 429
    assert payload["reason"] == "upstream HTTP 429"
    assert "bounded upstream reason" not in response.text


@pytest.mark.parametrize("streaming", [False, True])
def test_unexpected_backend_failure_closes_typed_failed_turn(streaming: bool) -> None:
    service = _RecordingService()
    route = (
        make_chat_stream_route(
            backend=_GenericFailureBackend(),
            authorize=_authorize,
            turn_service=service,
        )
        if streaming
        else make_chat_route(
            backend=_GenericFailureBackend(),
            authorize=_authorize,
            turn_service=service,
        )
    )

    response = TestClient(
        Starlette(routes=[route]),
        raise_server_exceptions=False,
    ).post("/chat/stream" if streaming else "/chat", json={"prompt": "summarize"})

    assert response.status_code == (200 if streaming else 500)
    assert service.terminated[-1].terminal_status is ConversationTurnTerminalStatus.FAILED


@pytest.mark.parametrize("streaming", [False, True])
def test_busy_session_setup_closes_typed_failed_turn(streaming: bool) -> None:
    service = _RecordingService()
    route = (
        make_chat_stream_route(
            backend=_Backend(),
            authorize=_authorize,
            turn_service=service,
            busy_input_coordinator=_BusyCoordinator(),  # type: ignore[arg-type]
        )
        if streaming
        else make_chat_route(
            backend=_Backend(),
            authorize=_authorize,
            turn_service=service,
            busy_input_coordinator=_BusyCoordinator(),  # type: ignore[arg-type]
        )
    )

    response = TestClient(Starlette(routes=[route])).post(
        "/chat/stream" if streaming else "/chat",
        json={"prompt": "summarize"},
    )

    assert response.status_code == 409
    assert service.terminated[-1].terminal_status is ConversationTurnTerminalStatus.FAILED


def test_oversized_sse_terminal_fails_before_successful_closure() -> None:
    service = _RecordingService()
    route = make_chat_stream_route(
        backend=_OversizedBackend(),
        authorize=_authorize,
        turn_service=service,
    )

    response = TestClient(Starlette(routes=[route])).post(
        "/chat/stream",
        json={"prompt": "summarize"},
    )

    assert "event: error" in response.text
    assert "event: done" not in response.text
    assert service.completed == []
    assert service.terminated[-1].terminal_status is ConversationTurnTerminalStatus.FAILED


def test_http_adapters_depend_on_application_service_not_reverse() -> None:
    application = _ROOT / "src/fdai/delivery/operator_api/application"
    route_paths = (
        _ROOT / "src/fdai/delivery/operator_api/routes/chat.py",
        _ROOT / "src/fdai/delivery/operator_api/routes/chat_stream.py",
    )

    for path in application.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "starlette" not in source
        assert "fdai.delivery.operator_api.routes" not in source
    for path in route_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        assert "fdai.delivery.operator_api.application" in imports
