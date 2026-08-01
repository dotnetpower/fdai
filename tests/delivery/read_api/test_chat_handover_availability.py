from __future__ import annotations

from starlette.applications import Starlette
from starlette.testclient import TestClient

from fdai.delivery.read_api.routes.chat import make_chat_route
from tests.delivery.read_api.test_chat_route import _allow, _RecordingBackend


class FailingAvailabilityPublisher:
    async def publish(self, *, subject_ref: str, session_id: str) -> None:
        raise RuntimeError("synthetic availability failure")


def test_availability_failure_does_not_block_chat() -> None:
    app = Starlette(
        routes=[
            make_chat_route(
                backend=_RecordingBackend(model="test", delay_ms=1),
                authorize=_allow,
                handover_availability_publisher=FailingAvailabilityPublisher(),
            )
        ]
    )

    response = TestClient(app).post(
        "/chat",
        json={
            "request_id": "handover-availability-1",
            "session_id": "session-1",
            "prompt": "Show the current status.",
        },
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "hello"
