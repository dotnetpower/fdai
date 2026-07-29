from __future__ import annotations

from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.delivery.read_api.routes.chat import make_chat_route, make_chat_stream_route
from fdai.delivery.read_api.routes.chat_subscription_health import (
    SubscriptionHealthChatTools,
    needs_subscription_health,
)


class _Backend:
    def __init__(self) -> None:
        self.calls = 0

    async def answer(self, **kwargs: object) -> dict[str, str]:
        del kwargs
        self.calls += 1
        return {"answer": "model fallback", "model": "test"}


async def _allow(request: Request) -> str:
    del request
    return "reader"


async def _provider(
    lookback_seconds: int,
    *,
    progress_observer: Any = None,
) -> dict[str, Any]:
    assert lookback_seconds == 3_600
    if progress_observer is not None:
        await progress_observer(
            {
                "kind": "inventory.completed",
                "status": "completed",
                "label": "Resource discovery completed",
                "completed": 12,
                "total": 12,
            }
        )
        await progress_observer(
            {
                "kind": "evidence.correlating",
                "status": "running",
                "label": "Correlating health evidence",
                "completed": None,
                "total": None,
            }
        )
    return {
        "status": "partial",
        "source": "azure-resource-graph+azure-monitor-metrics",
        "observed_at": "2026-07-22T05:00:00Z",
        "resource_count": 12,
        "metric_checked": 5,
        "metric_unavailable": 0,
        "unsupported_metric_resources": 7,
        "truncated": False,
        "findings": [
            {
                "kind": "metric",
                "resource_name": "vm-app",
                "status": "anomalous",
                "metric": "Percentage CPU",
                "value": 95.0,
            }
        ],
    }


def test_generic_service_outage_question_uses_subscription_health() -> None:
    assert needs_subscription_health("서비스 장애 나고 있는게 있어?")


def test_partial_subscription_health_answer_fails_closed() -> None:
    backend = _Backend()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=SubscriptionHealthChatTools(_provider),
            )
        ]
    )

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={"prompt": "현재 구독 리소스 이상 상태를 확인해줘", "view_context": {}},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["verification"]["authority"] == "server_subscription_health"
    assert payload["verification"]["status"] == "unverified"
    assert payload["verification"]["checks_completed"] == 0
    assert payload["verification"]["checks_total"] == 1
    assert payload["verification"]["reason_code"] == "subscription_health_partial"
    assert "리소스 12개" in payload["answer"]
    assert "vm-app" in payload["answer"]
    assert "미지원 7개" in payload["answer"]
    assert "전체 정상 상태를 확정하지 않았습니다" in payload["answer"]
    assert backend.calls == 0


def test_matched_subscription_health_answer_completes_verification() -> None:
    async def matched(
        lookback_seconds: int,
        *,
        progress_observer: Any = None,
    ) -> dict[str, Any]:
        del progress_observer
        result = await _provider(lookback_seconds)
        return {**result, "status": "matched", "metric_unavailable": 0}

    backend = _Backend()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=SubscriptionHealthChatTools(matched),
            )
        ]
    )

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={"prompt": "Azure subscription health check", "view_context": {}},
        )

    verification = response.json()["verification"]
    assert verification["status"] == "verified"
    assert verification["checks_completed"] == 1
    assert verification["checks_total"] == 1
    assert verification["reason_code"] == "subscription_health_grounded"
    assert backend.calls == 0


def test_service_outage_answer_explains_customer_initiated_resource_health() -> None:
    async def degraded(
        lookback_seconds: int,
        *,
        progress_observer: Any = None,
    ) -> dict[str, Any]:
        del progress_observer
        assert lookback_seconds == 3_600
        return {
            "status": "matched",
            "source": "azure-resource-graph+resource-health+azure-monitor-metrics",
            "observed_at": "2026-07-22T05:00:00Z",
            "resource_count": 1,
            "resource_health_unavailable": 0,
            "metric_checked": 1,
            "metric_unavailable": 0,
            "unsupported_metric_resources": 0,
            "truncated": False,
            "findings": [
                {
                    "kind": "resource_health",
                    "resource_name": "database-app",
                    "status": "Degraded",
                    "title": "Stopped",
                    "reason": "Customer Initiated",
                    "observed_at": "2026-07-22T04:55:00Z",
                }
            ],
        }

    backend = _Backend()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=SubscriptionHealthChatTools(degraded),
            )
        ]
    )

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={"prompt": "서비스 장애 나고 있는게 있어?", "view_context": {}},
        )

    assert response.status_code == 200
    answer = response.json()["answer"]
    assert "database-app" in answer
    assert "Degraded" in answer
    assert "Stopped" in answer
    assert "사용자 또는 자동화 작업" in answer
    assert "Azure 플랫폼 장애" in answer
    assert backend.calls == 0


def test_subscription_health_provider_failure_fails_closed() -> None:
    async def unavailable(
        lookback_seconds: int,
        *,
        progress_observer: Any = None,
    ) -> dict[str, Any]:
        del lookback_seconds, progress_observer
        raise RuntimeError("provider unavailable")

    backend = _Backend()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=SubscriptionHealthChatTools(unavailable),
            )
        ]
    )

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={"prompt": "Azure subscription health check", "view_context": {}},
        )

    payload = response.json()
    assert payload["verification"]["status"] == "unverified"
    assert payload["verification"]["reason_code"] == "subscription_health_unavailable"
    assert "not confirmed" in payload["answer"]
    assert backend.calls == 0


def test_subscription_health_stream_emits_activity_and_milestones() -> None:
    backend = _Backend()
    app = Starlette(
        routes=[
            make_chat_stream_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=SubscriptionHealthChatTools(_provider),
            )
        ]
    )

    with TestClient(app) as client:
        response = client.post(
            "/chat/stream",
            json={
                "prompt": "현재 구독 리소스 이상 상태를 확인해줘",
                "view_context": {},
                "session_id": "session-one",
                "request_id": "request-one",
            },
        )

    assert response.status_code == 200
    body = response.text
    assert body.count("event: activity") == 3
    assert body.count("event: milestone") == 2
    assert body.index("event: activity") < body.index("event: done")
    assert '"activity_id": "inventory"' in body
    assert '"message_id": "subscription-inventory-completed"' in body
    assert backend.calls == 0
