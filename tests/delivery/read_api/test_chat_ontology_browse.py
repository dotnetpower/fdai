"""Deterministic ontology browse answers for JSON and SSE chat routes."""

from __future__ import annotations

import json
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.delivery.read_api.routes.chat import make_chat_route, make_chat_stream_route


class NoCallBackend:
    def __init__(self) -> None:
        self.calls = 0

    async def answer(self, **kwargs: object) -> dict[str, str]:
        self.calls += 1
        raise AssertionError("ontology browse fast path must not call the narrator")


async def _allow(_: Request) -> str:
    return "reader"


def _done_event(body: str) -> dict[str, Any]:
    for block in body.split("\n\n"):
        if not block.startswith("event: done\n"):
            continue
        data = next(line[6:] for line in block.splitlines() if line.startswith("data: "))
        payload = json.loads(data)
        assert isinstance(payload, dict)
        return payload
    raise AssertionError("done event missing")


def test_ontology_browse_question_uses_snapshot_without_narrator() -> None:
    backend = NoCallBackend()
    app = Starlette(
        routes=[
            make_chat_route(backend=backend, authorize=_allow),
            make_chat_stream_route(backend=backend, authorize=_allow),
        ]
    )
    view_context = {
        "routeId": "ontology",
        "routeLabel": "Ontology",
        "purpose": "Browse registered ontology contracts.",
        "headline": "28 ObjectTypes - 45 LinkTypes - 40 ActionTypes",
        "capturedAt": "2026-07-21T00:00:00Z",
        "facts": [
            {"key": "selected_object_type", "value": "Agent"},
            {"key": "object_type_count", "value": 28},
            {"key": "link_type_count", "value": 45},
            {"key": "action_type_count", "value": 40},
        ],
        "records": {
            "object_types": [{"name": "Agent"}, {"name": "Issue"}],
            "relationships": [{"link": "owns", "from": "Agent", "to": "Resource"}],
            "action_types": [{"name": "restart-service"}],
        },
    }
    prompt = "온톨로지 데이터를 조회할수 있는 방법이 있어?"

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={"prompt": prompt, "view_context": view_context},
        )
        stream_response = client.post(
            "/chat/stream",
            json={"prompt": prompt, "view_context": view_context},
        )

    assert response.status_code == 200
    payload = response.json()
    done = _done_event(stream_response.text)
    assert payload["model"] == "ontology-snapshot"
    assert payload["source"] == "evidence:ontology-snapshot"
    assert "ObjectType 28개" in payload["answer"]
    assert "LinkType 45개" in payload["answer"]
    assert "ActionType 40개" in payload["answer"]
    assert "Agent" in payload["answer"]
    assert payload["answer"] == done["answer"]
    assert done["model"] == "ontology-snapshot"
    assert done["source"] == "evidence:ontology-snapshot"
    assert backend.calls == 0
