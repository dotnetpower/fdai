"""JSON and SSE route integration for bounded narrator prose review."""

from __future__ import annotations

import json
import re
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.delivery.operator_api.routes.chat import make_chat_route, make_chat_stream_route
from fdai.shared.telemetry.conversation_progress import ConversationProgressMetrics


async def _allow(_request: Request) -> str:
    return "reader-one"


class _QualityBackend:
    def __init__(self, draft: str, rewritten_template: str) -> None:
        self._draft = draft
        self._rewritten_template = rewritten_template
        self.calls = 0

    async def answer(
        self,
        *,
        prompt: str,  # noqa: ARG002 - protocol parity
        view_context: dict[str, Any],
        history: list[dict[str, str]],  # noqa: ARG002 - protocol parity
    ) -> dict[str, Any]:
        self.calls += 1
        if view_context.get("_answer_quality_review") is not True:
            return {"answer": self._draft, "model": "narrator-mini"}
        protected = str(view_context["records"]["draft"][0]["text"])
        token = re.search(r"\{\{FDAI_EVIDENCE_[^}]+\}\}", protected)
        assert token is not None
        return {
            "answer": json.dumps(
                {
                    "status": "rewrite",
                    "reason": "malformed_word",
                    "answer": self._rewritten_template.format(token=token.group(0)),
                },
                ensure_ascii=False,
            ),
            "model": "narrator-mini",
        }


def test_json_route_rewrites_korean_prose_and_preserves_evidence() -> None:
    backend = _QualityBackend(
        "현재 춯저귀죤은 postgres-audit입니다.",
        "현재 저장 위치는 {token}입니다.",
    )
    app = Starlette(routes=[make_chat_route(backend=backend, authorize=_allow)])

    response = TestClient(app).post(
        "/chat",
        json={
            "prompt": "이 화면을 설명해줘",
            "view_context": {
                "routeId": "dashboard",
                "records": {"storage": [{"name": "postgres-audit"}]},
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "현재 저장 위치는 postgres-audit입니다."
    assert payload["answer_quality"]["status"] == "rewritten"
    assert payload["answer_quality"]["protected_spans"] == 1
    assert backend.calls == 2


def test_json_route_english_answer_does_not_add_model_call() -> None:
    backend = _QualityBackend("The screen is ready.", "{token}")
    app = Starlette(routes=[make_chat_route(backend=backend, authorize=_allow)])

    response = TestClient(app).post(
        "/chat",
        json={"prompt": "Explain this screen", "view_context": {"routeId": "dashboard"}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "The screen is ready."
    assert payload["answer_quality"]["status"] == "not_applicable"
    assert backend.calls == 1


def test_stream_route_revises_visible_draft_after_quality_rewrite() -> None:
    backend = _QualityBackend(
        "현재 춯저귀죤은 postgres-audit입니다.",
        "현재 저장 위치는 {token}입니다.",
    )
    metrics = ConversationProgressMetrics()
    app = Starlette(
        routes=[
            make_chat_stream_route(
                backend=backend,
                authorize=_allow,
                progress_metrics=metrics,
            )
        ]
    )

    response = TestClient(app).post(
        "/chat/stream",
        json={
            "request_id": "quality-stream-1",
            "prompt": "이 화면을 설명해줘",
            "view_context": {
                "routeId": "dashboard",
                "records": {"storage": [{"name": "postgres-audit"}]},
            },
        },
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    revision = next(payload for name, payload in events if name == "revision")
    done = events[-1][1]
    assert revision["answer"] == "현재 저장 위치는 postgres-audit입니다."
    assert done["answer"] == revision["answer"]
    assert done["answer_quality"]["status"] == "rewritten"
    assert done["revision"] == 1
    assert backend.calls == 2
    snapshot = metrics.snapshot()
    assert snapshot.counts["corrections"] == 1
    assert snapshot.counts["terminal_completed"] == 1
    assert snapshot.counts["branch.agent.unavailable"] == 1
    assert snapshot.latency_ms["time_to_first_progress"].count == 1
    assert snapshot.latency_ms["time_to_first_confirmed"].count == 1


def _parse_sse(raw: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for frame in raw.strip().split("\n\n"):
        event = "message"
        data = ""
        for line in frame.splitlines():
            if line.startswith("event:"):
                event = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data += line.removeprefix("data:").strip()
        if data:
            events.append((event, json.loads(data)))
    return events
