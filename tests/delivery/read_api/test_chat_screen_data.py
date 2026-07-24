from __future__ import annotations

import json
from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.agents import PantheonRuntime
from fdai.delivery.read_api.routes.chat import make_chat_route, make_chat_stream_route
from fdai.delivery.read_api.routes.chat_agent_delegate import PantheonChatDelegate
from fdai.delivery.read_api.routes.chat_screen_data import render_screen_data_answer
from fdai.shared.providers.testing.event_bus import InMemoryEventBus

_SCOPE = {"authority": "current_screen", "route_id": "live"}


@pytest.mark.parametrize(
    ("prompt", "context", "locale", "expected"),
    (
        ("what is the current EPS?", {"facts": [{"key": "eps", "value": "4.2"}]}, "en", "4.2"),
        ("몇 개가 주의가 필요해?", {"facts": [{"key": "attention.total", "value": 3}]}, "ko", "3"),
        ("what is the T2 tier share?", {"facts": [{"key": "tier.t2", "value": "5%"}]}, "en", "5%"),
        (
            "リンクタイプはいくつ？",
            {"facts": [{"key": "link_type_count", "value": 19}]},
            "ja",
            "19",
        ),
        (
            "how many resources are affected?",
            {"facts": [{"key": "affected_count", "value": 12}]},
            "en",
            "12",
        ),
        (
            "what was the terminal stage?",
            {"facts": [{"key": "terminal_stage", "value": "audit"}]},
            "en",
            "audit",
        ),
        (
            "who logged the latest audit entry?",
            {
                "records": {
                    "items": [
                        {
                            "seq": 42,
                            "recorded_at": "2026-01-01T00:00:00Z",
                            "actor": "thor",
                            "mode": "enforce",
                        }
                    ]
                }
            },
            "en",
            "thor",
        ),
        (
            "최근 항목은 어떤 모드야?",
            {
                "records": {
                    "items": [
                        {
                            "seq": 42,
                            "recorded_at": "2026-01-01T00:00:00Z",
                            "actor": "thor",
                            "mode": "enforce",
                        }
                    ]
                }
            },
            "ko",
            "enforce",
        ),
        (
            "가장 흔한 액션이 뭐야?",
            {
                "records": {
                    "by_action_kind": [
                        {"key": "remediate.tag-add", "count": 300},
                        {"key": "ops.restart", "count": 120},
                    ]
                }
            },
            "ko",
            "remediate.tag-add",
        ),
        (
            "which ActionType is ready to promote?",
            {
                "records": {
                    "rows": [
                        {"action_type_name": "remediate.tag-add", "ready": True},
                        {"action_type_name": "remediate.enable-tde", "ready": False},
                    ]
                }
            },
            "en",
            "remediate.tag-add",
        ),
        (
            "왜 enable-tde는 아직 준비 안됐어?",
            {
                "records": {
                    "rows": [
                        {
                            "action_type_name": "remediate.enable-tde",
                            "ready": False,
                            "gaps": ["needs 50 more shadow samples"],
                        }
                    ]
                }
            },
            "ko",
            "shadow",
        ),
        ("and how many are failed?", {"headline": "60 tiles - 4.2 eps - 3 failed"}, "en", "3"),
    ),
)
def test_renders_supported_screen_data(
    prompt: str,
    context: dict[str, object],
    locale: str,
    expected: str,
) -> None:
    answer = render_screen_data_answer(
        prompt,
        {**context, "_screen_scope": _SCOPE},
        locale=locale,
    )

    assert answer is not None
    assert expected in answer


@pytest.mark.parametrize(
    ("prompt", "context", "locale", "marker"),
    (
        ("what is the database CPU usage?", {}, "en", "does not show"),
        ("이 리소스 월 비용이 얼마야?", {}, "ko", "없습니다"),
        ("which Azure region is this deployed in?", {}, "en", "does not show"),
        ("who approved this trace?", {}, "en", "does not show"),
        (
            "영향받은 리소스 소유자가 누구야?",
            {"facts": [{"key": "affected_count", "value": 12}]},
            "ko",
            "없습니다",
        ),
    ),
)
def test_absent_screen_fields_fail_closed(
    prompt: str,
    context: dict[str, object],
    locale: str,
    marker: str,
) -> None:
    answer = render_screen_data_answer(
        prompt,
        {**context, "_screen_scope": _SCOPE},
        locale=locale,
    )

    assert answer is not None
    assert marker in answer


def test_returns_none_without_bragi_screen_scope() -> None:
    assert render_screen_data_answer("what is the eps?", {"facts": []}, locale="en") is None


class _RecordingBackend:
    def __init__(self) -> None:
        self.calls = 0

    async def answer(
        self,
        *,
        prompt: str,
        view_context: dict[str, Any],
        history: list[dict[str, str]],
    ) -> dict[str, Any]:
        del prompt, view_context, history
        self.calls += 1
        return {"answer": "model must not run", "model": "test"}


async def _allow(request: Request) -> str:
    del request
    return "operator-1"


def _done_event(body: str) -> dict[str, Any]:
    blocks = [block for block in body.split("\n\n") if block.startswith("event: done\n")]
    assert len(blocks) == 1
    data = next(
        line.removeprefix("data: ") for line in blocks[0].splitlines() if line.startswith("data: ")
    )
    return json.loads(data)


def test_json_and_stream_use_same_model_free_screen_answer() -> None:
    backend = _RecordingBackend()
    runtime = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="fdai.events",
    )
    delegate = PantheonChatDelegate(runtime)
    app = Starlette(
        routes=[
            make_chat_route(backend=backend, authorize=_allow, agent_delegate=delegate),
            make_chat_stream_route(backend=backend, authorize=_allow, agent_delegate=delegate),
        ]
    )
    request = {
        "prompt": "what is the T2 tier share?",
        "view_context": {
            "routeId": "live",
            "facts": [{"key": "tier.t2", "value": "5%"}],
        },
    }

    with TestClient(app) as client:
        json_payload = client.post("/chat", json=request).json()
        stream_payload = _done_event(client.post("/chat/stream", json=request).text)

    assert backend.calls == 0
    assert json_payload["answer"] == stream_payload["answer"]
    assert "5%" in json_payload["answer"]
    assert json_payload["model"] == "bragi-screen-t0"
    assert stream_payload["model"] == "bragi-screen-t0"
    assert json_payload["source"] == "evidence:current-screen"
    assert stream_payload["source"] == "evidence:current-screen"


def test_empty_screen_snapshot_refuses_without_model_call() -> None:
    backend = _RecordingBackend()
    runtime = PantheonRuntime.build(
        provider=InMemoryEventBus(),
        raw_event_topic="fdai.events",
    )
    delegate = PantheonChatDelegate(runtime)
    app = Starlette(
        routes=[make_chat_route(backend=backend, authorize=_allow, agent_delegate=delegate)]
    )

    with TestClient(app) as client:
        payload = client.post(
            "/chat",
            json={
                "prompt": "what is the eps?",
                "view_context": {"routeId": "live", "facts": []},
            },
        ).json()

    assert backend.calls == 0
    assert "does not show" in payload["answer"]
    assert payload["model"] == "bragi-screen-t0"
