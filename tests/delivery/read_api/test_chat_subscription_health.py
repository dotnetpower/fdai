from __future__ import annotations

from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.delivery.read_api.routes.chat import make_chat_route, make_chat_stream_route
from fdai.delivery.read_api.routes.chat_subscription_health import (
    SubscriptionHealthChatTools,
    needs_subscription_context,
    needs_subscription_health,
    render_subscription_health_answer,
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


class _SubscriptionProvider:
    async def __call__(
        self,
        lookback_seconds: int,
        *,
        progress_observer: Any = None,
    ) -> dict[str, Any]:
        return await _provider(
            lookback_seconds,
            progress_observer=progress_observer,
        )

    async def describe_scope(self) -> dict[str, Any]:
        return {
            "status": "matched",
            "source": "azure-resource-manager",
            "observed_at": "2026-07-31T02:00:00Z",
            "display_name": "Example Development",
            "subscription_id": "subscription-example",
            "state": "Enabled",
        }


def test_generic_service_outage_question_uses_subscription_health() -> None:
    assert needs_subscription_health("서비스 장애 나고 있는게 있어?")


def test_generic_resource_health_states_use_subscription_health() -> None:
    prompts = (
        "Which resources are failed, degraded, or unavailable?",
        "List any unavailable, failed, or degraded Azure resources.",
        "Are resources degraded or unavailable, including failures?",
        "Show failed resources plus anything unavailable or degraded.",
        "실패, 성능 저하 또는 사용 불가 상태인 Azure 리소스를 보여줘.",
    )

    assert all(needs_subscription_health(prompt) for prompt in prompts)


def test_resource_health_state_cohort_renders_requested_zero_groups() -> None:
    calls = 0

    async def health_states(
        lookback_seconds: int,
        *,
        progress_observer: Any = None,
    ) -> dict[str, Any]:
        nonlocal calls
        del progress_observer
        assert lookback_seconds == 3_600
        calls += 1
        return {
            "status": "matched",
            "source": "azure-resource-graph+resource-health",
            "observed_at": "2026-08-01T04:10:00Z",
            "resource_count": 12,
            "resource_health_unavailable": 0,
            "metric_checked": 0,
            "metric_unavailable": 0,
            "unsupported_metric_resources": 12,
            "truncated": False,
            "findings": [
                {
                    "kind": "resource_health",
                    "resource_name": "vm-batch",
                    "resource_type": "Microsoft.Compute/virtualMachines",
                    "resource_group": "rg-batch",
                    "status": "Unavailable",
                    "title": "Unavailable",
                    "reason": "Platform Initiated",
                    "observed_at": "2026-08-01T04:01:00Z",
                }
            ],
        }

    prompts = (
        "Which resources are failed, degraded, or unavailable?",
        "List any unavailable, failed, or degraded Azure resources.",
        "Are resources degraded or unavailable, including failures?",
        "Show failed resources plus anything unavailable or degraded.",
    )
    backend = _Backend()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=SubscriptionHealthChatTools(health_states),
            )
        ]
    )

    with TestClient(app) as client:
        responses = [
            client.post("/chat", json={"prompt": prompt, "view_context": {}}) for prompt in prompts
        ]

    for response in responses:
        payload = response.json()
        assert payload["verification"]["authority"] == "server_subscription_health"
        assert payload["verification"]["status"] == "verified"
        assert "**Failed**\n- Not observed in the checked evidence." in payload["answer"]
        assert "**Degraded**\n- Not observed in the checked evidence." in payload["answer"]
        assert "**Unavailable**" in payload["answer"]
        assert "vm-batch: Resource Health Unavailable" in payload["answer"]
        assert (
            "type Microsoft.Compute/virtualMachines, resource group rg-batch" in payload["answer"]
        )
    assert calls == len(prompts)
    assert backend.calls == 0


def test_specific_subscription_inventory_question_skips_health_sweep() -> None:
    prompt = "지금 구독에서 중지된 디비가 있는지 확인해봐"

    assert not needs_subscription_health(prompt)
    assert not needs_subscription_context(prompt)


def test_specific_storage_health_question_uses_filtered_subscription_health() -> None:
    prompt = "사용 불가능하거나 성능이 저하된 스토리지 계정이 있어?"

    assert needs_subscription_health(prompt)

    async def storage_health(
        lookback_seconds: int,
        *,
        progress_observer: Any = None,
    ) -> dict[str, Any]:
        del progress_observer
        assert lookback_seconds == 3_600
        return {
            "status": "matched",
            "source": "azure-resource-graph+resource-health",
            "observed_at": "2026-08-01T04:10:00Z",
            "resource_count": 12,
            "resource_health_unavailable": 0,
            "metric_checked": 1,
            "metric_unavailable": 0,
            "unsupported_metric_resources": 11,
            "truncated": False,
            "findings": [
                {
                    "kind": "resource_health",
                    "resource_name": "storage-example",
                    "resource_type": "Microsoft.Storage/storageAccounts",
                    "resource_group": "rg-example",
                    "status": "Unavailable",
                    "title": "Unavailable",
                    "reason": "Platform Initiated",
                },
                {
                    "kind": "resource_health",
                    "resource_name": "vm-example",
                    "resource_type": "Microsoft.Compute/virtualMachines",
                    "resource_group": "rg-example",
                    "status": "Degraded",
                    "title": "Degraded",
                    "reason": "Platform Initiated",
                },
            ],
        }

    backend = _Backend()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=SubscriptionHealthChatTools(storage_health),
            )
        ]
    )

    response = TestClient(app).post("/chat", json={"prompt": prompt, "view_context": {}})

    payload = response.json()
    assert payload["verification"]["authority"] == "server_subscription_health"
    assert payload["verification"]["status"] == "verified"
    assert "**성능 저하**\n- 확인한 근거에서는 관찰되지 않았습니다." in payload["answer"]
    assert "**사용 불가**" in payload["answer"]
    assert "storage-example" in payload["answer"]
    assert "vm-example" not in payload["answer"]
    assert backend.calls == 0


async def test_specific_storage_state_query_skips_unrequested_metrics() -> None:
    class FilteredProvider:
        async def __call__(
            self,
            lookback_seconds: int,
            *,
            progress_observer: Any = None,
        ) -> dict[str, Any]:
            raise AssertionError("typed health query must use the filtered provider path")

        async def query_resource_types(
            self,
            lookback_seconds: int,
            *,
            resource_types: tuple[str, ...],
            availability_states: tuple[str, ...],
            include_metrics: bool,
            progress_observer: Any = None,
        ) -> dict[str, Any]:
            del progress_observer
            assert lookback_seconds == 3_600
            assert resource_types == ("Microsoft.Storage/storageAccounts",)
            assert availability_states == ("degraded", "unavailable")
            assert include_metrics is False
            return {
                "status": "matched",
                "source": "azure-resource-graph+resource-health",
                "observed_at": "2026-08-01T04:10:00Z",
                "resource_count": 2,
                "resource_health_unavailable": 0,
                "metrics_requested": False,
                "metric_checked": 0,
                "metric_unavailable": 0,
                "unsupported_metric_resources": 0,
                "truncated": False,
                "findings": [],
            }

    evidence = await SubscriptionHealthChatTools(FilteredProvider()).resolve(
        "사용 불가능하거나 성능이 저하된 스토리지 계정이 있어?",
        principal_id="reader",
    )

    assert evidence is not None
    answer = render_subscription_health_answer(evidence, locale="ko")
    assert answer is not None
    assert "리소스 2개" in answer
    assert "대표 메트릭: 요청되지 않음" in answer


def test_current_subscription_question_uses_server_scope_metadata() -> None:
    backend = _Backend()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=SubscriptionHealthChatTools(_SubscriptionProvider()),
            )
        ]
    )

    prompts = (
        "현재 구독은?",
        "어느 Azure 구독을 보고 있어?",
        "구독 이름 알려줘",
        "What is the current Azure subscription?",
    )
    with TestClient(app) as client:
        responses = [
            client.post(
                "/chat",
                json={"prompt": prompt, "view_context": {}},
            )
            for prompt in prompts
        ]

    for response in responses:
        assert response.status_code == 200
        payload = response.json()
        assert payload["verification"]["authority"] == "server_subscription_scope"
        assert payload["verification"]["status"] == "verified"
        assert "Example Development" in payload["answer"]
        assert "Enabled" in payload["answer"]
        assert "subs...mple" in payload["answer"]
    assert backend.calls == 0


def test_current_subscription_question_fails_closed_without_scope_provider() -> None:
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
            json={"prompt": "현재 구독은?", "view_context": {}},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["verification"]["authority"] == "server_subscription_scope"
    assert payload["verification"]["status"] == "unverified"
    assert "조회할 수 없습니다" in payload["answer"]
    assert backend.calls == 0


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


def test_partial_requested_state_finding_completes_evidence_check() -> None:
    async def partial_requested_state(
        lookback_seconds: int,
        *,
        progress_observer: Any = None,
    ) -> dict[str, Any]:
        del progress_observer
        assert lookback_seconds == 3_600
        return {
            "status": "partial",
            "source": "azure-resource-graph+resource-health",
            "observed_at": "2026-07-22T05:00:00Z",
            "resource_count": 2,
            "resource_health_unavailable": 0,
            "metric_checked": 0,
            "metric_unavailable": 1,
            "unsupported_metric_resources": 1,
            "truncated": True,
            "findings": [
                {
                    "kind": "resource_health",
                    "resource_name": "vm-example",
                    "resource_type": "Microsoft.Compute/virtualMachines",
                    "resource_group": "rg-example",
                    "status": "Unavailable",
                    "title": "Unavailable",
                    "reason": "unknown",
                }
            ],
        }

    backend = _Backend()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=SubscriptionHealthChatTools(partial_requested_state),
            )
        ]
    )

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={
                "prompt": "Which resources are failed, degraded, or unavailable?",
                "view_context": {},
            },
        )

    payload = response.json()
    assert payload["verification"]["status"] == "verified"
    assert payload["verification"]["checks_completed"] == 1
    assert payload["verification"]["checks_total"] == 1
    assert payload["verification"]["reason_code"] == "subscription_health_findings_grounded_partial"
    assert "vm-example" in payload["answer"]
    assert "Not observed in the checked evidence." in payload["answer"]
    assert "additional resources may exist" in payload["answer"]
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
    assert body.count("event: activity") == 4
    assert body.count("event: milestone") == 2
    assert body.index("event: activity") < body.index("event: done")
    assert '"activity_id": "inventory"' in body
    assert '"tool": "FDAI server read"' in body
    assert '"input_kind": "query"' in body
    assert '\\"operation\\": \\"query_subscription_health\\"' in body
    assert '"redacted": true' in body
    assert '"message_id": "subscription-inventory-completed"' in body
    assert backend.calls == 0
