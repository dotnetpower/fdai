"""System-health evidence routing for Command Deck chat."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.read_api.routes.chat import (
    make_chat_route,
    make_chat_stream_route,
)
from fdai.delivery.read_api.routes.chat_claims import verify_screen_claims
from fdai.delivery.read_api.routes.chat_evidence_enrichment import _with_tool_evidence
from fdai.delivery.read_api.routes.chat_system_health import (
    SystemHealthChatTools,
    render_system_health_answer,
)


def _model() -> InMemoryConsoleReadModel:
    model = InMemoryConsoleReadModel()
    model.record_audit_entry(
        {
            "event_id": "event-1",
            "correlation_id": "corr-1",
            "outcome": "auto",
            "tier": "t0",
        },
        actor="Thor",
        action_kind="ops.restart-service",
        mode="shadow",
    )
    return model


class _NoCallBackend:
    def __init__(self) -> None:
        self.calls = 0

    async def answer(
        self,
        *,
        prompt: str,  # noqa: ARG002
        view_context: dict[str, Any],  # noqa: ARG002
        history: list[dict[str, str]],  # noqa: ARG002
    ) -> dict[str, Any]:
        self.calls += 1
        raise AssertionError("system-health fast path must not call the model backend")


class _RecordingBackend:
    def __init__(self) -> None:
        self.calls = 0

    async def answer(self, **kwargs: object) -> dict[str, str]:
        self.calls += 1
        return {"answer": "fallback", "model": "test"}


@dataclass(frozen=True, slots=True)
class HealthWeaknessCase:
    prompt: str
    expects_health: bool
    korean: bool = False


HEALTH_WEAKNESS_CASES = (
    HealthWeaknessCase("Is the overall system healthy?", True),
    HealthWeaknessCase("Is everything working?", True),
    HealthWeaknessCase("control plane status", True),
    HealthWeaknessCase("system health", True),
    HealthWeaknessCase("overall status", True),
    HealthWeaknessCase("Is the system running?", True),
    HealthWeaknessCase("전체 시스템 상태 어때?", True, korean=True),
    HealthWeaknessCase("전반적인 동작 상태는?", True, korean=True),
    HealthWeaknessCase("시스템 정상 작동해?", True, korean=True),
    HealthWeaknessCase("control plane operating?", True),
    HealthWeaknessCase("everything running?", True),
    HealthWeaknessCase("overall health?", True),
    HealthWeaknessCase("Is this upload button working?", False),
    HealthWeaknessCase("VM status", False),
    HealthWeaknessCase("database health", False),
    HealthWeaknessCase("storage account status", False),
    HealthWeaknessCase("system architecture overview", False),
    HealthWeaknessCase("restart system", False),
    HealthWeaknessCase("system health policy", False),
    HealthWeaknessCase("overall cost status", False),
)

HEALTH_RUBRIC_NAMES = (
    "intent-classification",
    "json-http-success",
    "authority-selection",
    "health-model-selection",
    "terminal-trust",
    "model-skipped",
    "nonempty-answer",
    "locale-aligned",
    "event-count-present",
    "approval-backlog-present",
    "shadow-share-present",
    "enforce-share-present",
    "latest-record-present",
    "bounded-evidence-claim",
    "no-global-health-inference",
    "no-failure-inference",
    "no-execution-claim",
    "bounded-answer",
    "source-label",
    "json-sse-parity",
)


async def _allow(_: Request) -> str:
    return "test-reader"


def _done_event(body: str) -> dict[str, Any]:
    for block in body.split("\n\n"):
        if not block.startswith("event: done\n"):
            continue
        data = next(line[6:] for line in block.splitlines() if line.startswith("data: "))
        return json.loads(data)  # type: ignore[no-any-return]
    raise AssertionError("done event missing")


async def test_broad_health_query_uses_server_metrics_from_any_screen() -> None:
    resolver = SystemHealthChatTools(_model())
    context = await _with_tool_evidence(
        "전반적인 동작이 잘 하고 있어?",
        {
            "routeId": "documents",
            "facts": [{"key": "selected_files", "value": 0}],
        },
        resolver,
        principal_id="test-reader",
    )

    evidence = context["_tool_evidence"]
    assert evidence["tool"] == "get_system_health"
    assert evidence["authority"] == "server_read_model"
    assert evidence["result"]["event_count"] == 1

    answer = render_system_health_answer(context, locale="ko")
    assert answer is not None
    assert "감사 이벤트 수(event count) 1건" in answer
    assert ("모든 구성요소가 정상이라고 단정") in answer

    verification = verify_screen_claims(
        answer,
        context,
    )
    assert verification.supported is True
    assert verification.manifest.authority == "server_read_model"
    assert verification.claims[0].evidence_refs == ("tool:result:event_count",)


async def test_route_local_control_question_stays_with_the_screen() -> None:
    resolver = SystemHealthChatTools(_model())
    context = await _with_tool_evidence(
        "Is this upload button working?",
        {"routeId": "documents", "facts": []},
        resolver,
        principal_id="test-reader",
    )

    assert "_tool_evidence" not in context


def test_empty_health_sample_abstains_without_claiming_failure() -> None:
    answer = render_system_health_answer(
        {
            "_tool_evidence": {
                "tool": "get_system_health",
                "authority": "server_read_model",
                "result": {
                    "event_count": 0,
                    "hil_pending": 0,
                    "shadow_share": 0.0,
                    "enforce_share": 0.0,
                    "last_recorded_at": None,
                },
            }
        },
        locale="en",
    )

    assert answer is not None
    assert "overall system health cannot be confirmed" in answer
    assert "does not prove a failure" in answer


def test_sync_route_returns_canonical_health_without_model_call() -> None:
    backend = _NoCallBackend()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=SystemHealthChatTools(_model()),
            )
        ]
    )

    response = TestClient(app).post(
        "/chat",
        json={
            "prompt": "Is the overall system working properly?",
            "view_context": {"routeId": "documents", "facts": []},
        },
    )

    assert response.status_code == 200
    assert response.json()["model"] == "read-model-health"
    assert response.json()["verification"]["authority"] == "server_read_model"
    assert response.json()["verification"]["status"] != "unverified"
    assert backend.calls == 0


def test_stream_route_returns_canonical_health_without_model_call() -> None:
    backend = _NoCallBackend()
    app = Starlette(
        routes=[
            make_chat_stream_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=SystemHealthChatTools(_model()),
            )
        ]
    )

    response = TestClient(app).post(
        "/chat/stream",
        json={
            "prompt": ("전체 시스템이 정상 작동하고 있어?"),
            "view_context": {"routeId": "documents", "facts": []},
        },
    )
    done = _done_event(response.text)

    assert response.status_code == 200
    assert done["model"] == "read-model-health"
    assert done["source"] == "evidence:system-health"
    assert done["verification"]["authority"] == "server_read_model"
    assert done["verification"]["status"] != "unverified"
    assert backend.calls == 0


def test_twenty_health_weaknesses_pass_twenty_answer_rubrics() -> None:
    backend = _RecordingBackend()
    tools = SystemHealthChatTools(_model())
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=tools,
            ),
            make_chat_stream_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=tools,
            ),
        ]
    )
    failures: list[str] = []
    passed = 0
    total = len(HEALTH_WEAKNESS_CASES) * len(HEALTH_RUBRIC_NAMES)

    with TestClient(app) as client:
        for case_number, case in enumerate(HEALTH_WEAKNESS_CASES, 1):
            calls_before = backend.calls
            response = client.post(
                "/chat",
                json={"prompt": case.prompt, "view_context": {}},
            )
            payload = response.json()
            done = None
            if case.expects_health:
                stream_response = client.post(
                    "/chat/stream",
                    json={"prompt": case.prompt, "view_context": {}},
                )
                done = _done_event(stream_response.text)
            results = _score_health_answer(
                case,
                status_code=response.status_code,
                payload=payload,
                stream_done=done,
                model_calls=backend.calls - calls_before,
            )
            assert len(results) == len(HEALTH_RUBRIC_NAMES)
            for rubric, result in zip(HEALTH_RUBRIC_NAMES, results, strict=True):
                if result:
                    passed += 1
                else:
                    failures.append(f"Q{case_number:02d} {rubric}: {case.prompt}")

    assert not failures, f"health rubric score {passed}/{total}\n" + "\n".join(failures)


def _score_health_answer(
    case: HealthWeaknessCase,
    *,
    status_code: int,
    payload: dict[str, Any],
    stream_done: dict[str, Any] | None,
    model_calls: int,
) -> tuple[bool, ...]:
    raw_verification = payload.get("verification")
    verification = raw_verification if isinstance(raw_verification, dict) else {}
    raw_answer = payload.get("answer")
    answer = raw_answer if isinstance(raw_answer, str) else ""
    authority = verification.get("authority")
    is_health = payload.get("model") == "read-model-health"
    applicable = case.expects_health
    korean_rendered = "감사 이벤트 수" in answer
    bounded_claim = "complete health probe" in answer or "모든 구성요소가 정상이라고 단정" in answer
    no_global_claim = "all components are healthy" not in answer.casefold()
    stream_verification = stream_done.get("verification") if stream_done is not None else None
    return (
        is_health == applicable,
        status_code == 200,
        (authority == "server_read_model") == applicable,
        is_health == applicable,
        not applicable or verification.get("status") != "unverified",
        not applicable or model_calls == 0,
        bool(answer.strip()),
        not applicable or korean_rendered == case.korean,
        not applicable or ("1 audit events" in answer or "event count) 1건" in answer),
        not applicable or ("pending approvals" in answer or "HIL pending" in answer),
        not applicable or ("100.0% shadow" in answer or "shadow 100.0%" in answer),
        not applicable or ("0.0% enforce" in answer or "enforce 0.0%" in answer),
        not applicable or ("latest audit record" in answer or "마지막 감사 기록 시각" in answer),
        bounded_claim == applicable,
        no_global_claim,
        "failure" not in answer.casefold() and "장애가 확인" not in answer,
        "executed" not in answer.casefold() and "실행했습니다" not in answer,
        len(answer) <= 2_000,
        (payload.get("source") == "evidence:system-health") == applicable,
        not applicable
        or (
            isinstance(stream_verification, dict)
            and stream_verification.get("authority") == authority
            and stream_done.get("answer") == answer
            and stream_done.get("source") == payload.get("source")
        ),
    )
