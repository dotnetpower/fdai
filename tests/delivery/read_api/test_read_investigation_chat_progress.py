from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.delivery.read_api.routes.chat import make_chat_stream_route


class _Backend:
    async def answer(self, **kwargs: object) -> dict[str, str]:
        del kwargs
        return {"answer": "The resource state is observed.", "model": "test"}


class _ProgressiveDelegate:
    async def delegate(
        self,
        *,
        prompt: str,
        user_id: str,
        session_id: str,
    ) -> Mapping[str, Any] | None:
        del prompt, user_id, session_id
        return self._result()

    async def delegate_with_progress(
        self,
        *,
        prompt: str,
        user_id: str,
        session_id: str,
        progress_observer: Any,
    ) -> Mapping[str, Any] | None:
        del prompt, user_id, session_id
        await progress_observer(
            {
                "event": "activity",
                "activity_id": "resource",
                "kind": "resource.resolved",
                "status": "completed",
                "label": "Resource resolved",
                "detail": "vm-01",
                "completed": None,
                "total": None,
            }
        )
        await progress_observer(
            {
                "event": "milestone",
                "message_id": "resource-resolved",
                "text": "Resolved vm-01. Checking evidence in parallel.",
                "agent": "Bragi",
            }
        )
        return self._result()

    @staticmethod
    def _result() -> dict[str, object]:
        return {
            "primary_agent": "Heimdall",
            "answer": "The resource state is observed.",
            "facts": {
                "status": "matched",
                "evidence_refs": ("evidence:one",),
            },
            "contributors": [],
            "contributor_answers": [],
            "trace_ref": "read-investigation",
        }


async def _allow(request: Request) -> str:
    del request
    return "principal-one"


def test_chat_stream_delivers_investigation_activity_before_terminal_answer() -> None:
    app = Starlette(
        routes=[
            make_chat_stream_route(
                backend=_Backend(),
                authorize=_allow,
                agent_delegate=_ProgressiveDelegate(),
            )
        ]
    )

    with TestClient(app) as client:
        response = client.post(
            "/chat/stream",
            json={
                "prompt": "What is the current state of vm-01?",
                "view_context": {},
                "session_id": "session-one",
                "request_id": "request-one",
            },
        )

    assert response.status_code == 200
    body = response.text
    activity = body.index("event: activity")
    milestone = body.index("event: milestone")
    done = body.index("event: done")
    assert activity < milestone < done
    assert '"activity_id": "resource"' in body
    assert '"message_id": "resource-resolved"' in body
