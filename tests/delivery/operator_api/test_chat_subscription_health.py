from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.delivery.operator_api.routes.chat import make_chat_route, make_chat_stream_route
from fdai.delivery.operator_api.routes.chat_resource_context import contextualize_resource_followup
from fdai.delivery.operator_api.routes.chat_subscription_health import (
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


async def test_planned_subscription_health_uses_typed_server_scope_arguments() -> None:
    calls: list[tuple[int, bool, bool]] = []

    class Provider:
        async def query_health(
            self,
            lookback_seconds: int,
            *,
            include_metrics: bool,
            include_service_health: bool = False,
            progress_observer: Any = None,
        ) -> dict[str, object]:
            assert progress_observer is None
            calls.append((lookback_seconds, include_metrics, include_service_health))
            return {"status": "matched", "resource_count": 3}

    tools = SubscriptionHealthChatTools(Provider())  # type: ignore[arg-type]

    descriptor = tools.turn_tools()[0]
    result = await tools.resolve_planned(
        "query_subscription_health",
        {
            "lookback_seconds": 7_200,
            "include_metrics": True,
            "include_service_health": True,
        },
        principal_id="reader",
    )

    assert descriptor.name == "query_subscription_health"
    assert descriptor.side_effect_class == "read"
    assert calls == [(7_200, True, True)]
    assert result == {
        "tool": "query_subscription_health",
        "authority": "server_subscription_health",
        "query": {
            "lookback_seconds": 7_200,
            "include_metrics": True,
            "include_service_health": True,
        },
        "result": {"status": "matched", "resource_count": 3},
    }


async def test_planned_subscription_health_rejects_unknown_arguments() -> None:
    tools = SubscriptionHealthChatTools(_SubscriptionProvider())

    with pytest.raises(ValueError, match="planned subscription health arguments"):
        await tools.resolve_planned(
            "query_subscription_health",
            {
                "lookback_seconds": 3_600,
                "include_metrics": True,
                "include_service_health": False,
                "scope": "caller-selected",
            },
            principal_id="reader",
        )


def test_generic_service_outage_question_uses_subscription_health() -> None:
    assert needs_subscription_health("서비스 장애 나고 있는게 있어?")
    assert needs_subscription_health("현재 Azure 플랫폼 장애의 영향을 받는 리소스가 있어?")
    assert needs_subscription_health("Is any managed resource affected by an active Azure outage?")


def test_platform_health_skips_semantic_turn_planner() -> None:
    class Planner:
        async def plan_turn(self, **_kwargs: object) -> Any:
            raise AssertionError("deterministic health must skip semantic planning")

    backend = _Backend()
    app = Starlette(
        routes=[
            make_chat_stream_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=SubscriptionHealthChatTools(_provider),
                turn_planner=Planner(),  # type: ignore[arg-type]
            )
        ]
    )

    with TestClient(app) as client:
        response = client.post(
            "/chat/stream",
            json={
                "prompt": "현재 Azure 플랫폼 장애의 영향을 받는 리소스가 있어?",
                "view_context": {},
            },
        )

    assert response.status_code == 200
    assert "server_subscription_health" in response.text
    assert "model fallback" not in response.text
    assert backend.calls == 0


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
            kind_tokens_by_resource_type: Mapping[str, tuple[str, ...]],
            availability_states: tuple[str, ...],
            include_metrics: bool,
            progress_observer: Any = None,
        ) -> dict[str, Any]:
            del progress_observer
            assert lookback_seconds == 3_600
            assert resource_types == ("Microsoft.Storage/storageAccounts",)
            assert kind_tokens_by_resource_type == {}
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


async def test_cache_pressure_query_renders_normal_memory_observation() -> None:
    async def cache_health(
        lookback_seconds: int,
        *,
        progress_observer: Any = None,
    ) -> dict[str, Any]:
        del progress_observer
        assert lookback_seconds == 3_600
        return {
            "status": "matched",
            "source": "azure-resource-graph+resource-health+azure-monitor-metrics",
            "observed_at": "2026-08-01T04:10:00Z",
            "resource_count": 1,
            "resource_health_unavailable": 0,
            "metrics_requested": True,
            "metric_checked": 1,
            "metric_unavailable": 0,
            "unsupported_metric_resources": 0,
            "metric_observations": [
                {
                    "resource_name": "redis-example",
                    "resource_type": "Microsoft.Cache/redisEnterprise",
                    "metric": "usedmemorypercentage",
                    "value": 0.0,
                    "threshold": 90.0,
                    "comparison": "gt",
                    "anomalous": False,
                }
            ],
            "truncated": False,
            "findings": [],
        }

    evidence = await SubscriptionHealthChatTools(cache_health).resolve(
        "Are any cache services unavailable or under memory pressure?",
        principal_id="reader",
    )

    assert evidence is not None
    answer = render_subscription_health_answer(evidence, locale="en")
    assert answer is not None
    assert "**Unavailable**" in answer
    assert "redis-example: usedmemorypercentage=0.0" in answer
    assert "threshold gt 90.0 (within threshold)" in answer


async def test_app_service_not_running_or_ready_query_preserves_zero_groups() -> None:
    class FilteredProvider:
        async def __call__(
            self,
            lookback_seconds: int,
            *,
            progress_observer: Any = None,
        ) -> dict[str, Any]:
            raise AssertionError("typed app query must use the filtered provider path")

        async def query_resource_types(
            self,
            lookback_seconds: int,
            *,
            resource_types: tuple[str, ...],
            kind_tokens_by_resource_type: Mapping[str, tuple[str, ...]],
            availability_states: tuple[str, ...],
            include_metrics: bool,
            progress_observer: Any = None,
        ) -> dict[str, Any]:
            del progress_observer
            assert lookback_seconds == 3_600
            assert resource_types == ("Microsoft.Web/sites",)
            assert kind_tokens_by_resource_type == {"Microsoft.Web/sites": ("app",)}
            assert availability_states == (
                "stopped",
                "deallocated",
                "failed",
                "degraded",
                "unavailable",
            )
            assert include_metrics is False
            return {
                "status": "matched",
                "source": "azure-resource-graph+resource-health",
                "observed_at": "2026-08-01T04:10:00Z",
                "resource_count": 0,
                "resource_health_unavailable": 0,
                "metrics_requested": False,
                "metric_checked": 0,
                "metric_unavailable": 0,
                "unsupported_metric_resources": 0,
                "truncated": False,
                "findings": [],
            }

    evidence = await SubscriptionHealthChatTools(FilteredProvider()).resolve(
        "실행 중이 아니거나 준비되지 않은 앱 서비스를 보여줘.",
        principal_id="reader",
    )

    assert evidence is not None
    answer = render_subscription_health_answer(evidence, locale="ko")
    assert answer is not None
    assert "리소스 0개" in answer
    assert "**실행 중 아님**\n- 확인한 근거에서는 관찰되지 않았습니다." in answer
    assert "**준비되지 않음**\n- 확인한 근거에서는 관찰되지 않았습니다." in answer


async def test_function_or_container_not_ready_query_scopes_kind_by_provider() -> None:
    class FilteredProvider:
        async def __call__(
            self,
            lookback_seconds: int,
            *,
            progress_observer: Any = None,
        ) -> dict[str, Any]:
            raise AssertionError("typed serverless query must use the filtered provider path")

        async def query_resource_types(
            self,
            lookback_seconds: int,
            *,
            resource_types: tuple[str, ...],
            kind_tokens_by_resource_type: Mapping[str, tuple[str, ...]],
            availability_states: tuple[str, ...],
            include_metrics: bool,
            progress_observer: Any = None,
        ) -> dict[str, Any]:
            del progress_observer
            assert lookback_seconds == 3_600
            assert resource_types == (
                "Microsoft.App/containerApps",
                "Microsoft.Web/sites",
            )
            assert kind_tokens_by_resource_type == {"Microsoft.Web/sites": ("functionapp",)}
            assert availability_states == ("failed", "degraded", "unavailable")
            assert include_metrics is False
            return {
                "status": "matched",
                "source": "azure-resource-graph+resource-health",
                "observed_at": "2026-08-01T04:10:00Z",
                "resource_count": 3,
                "resource_health_unavailable": 0,
                "metrics_requested": False,
                "metric_checked": 0,
                "metric_unavailable": 0,
                "unsupported_metric_resources": 0,
                "truncated": False,
                "findings": [],
            }

    evidence = await SubscriptionHealthChatTools(FilteredProvider()).resolve(
        "Which function or container applications are not ready?",
        principal_id="reader",
    )

    assert evidence is not None
    answer = render_subscription_health_answer(evidence, locale="en")
    assert answer is not None
    assert "Checked 3 resources" in answer
    assert "**Not ready**\n- Not observed in the checked evidence." in answer


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


def test_platform_health_reports_cause_counts_without_metrics() -> None:
    class Provider:
        async def __call__(
            self,
            lookback_seconds: int,
            *,
            progress_observer: Any = None,
        ) -> dict[str, Any]:
            raise AssertionError("platform health must use configurable broad query")

        async def query_health(
            self,
            lookback_seconds: int,
            *,
            include_metrics: bool,
            include_service_health: bool = False,
            progress_observer: Any = None,
        ) -> dict[str, Any]:
            del progress_observer
            assert lookback_seconds == 3_600
            assert include_metrics is False
            assert include_service_health is True
            return {
                "status": "matched",
                "source": "azure-resource-graph+resource-health+service-health",
                "observed_at": "2026-07-22T05:00:00Z",
                "resource_count": 3,
                "resource_health_unavailable": 0,
                "service_health_requested": True,
                "service_health_unavailable": 0,
                "active_service_issue_count": 0,
                "active_service_issue_resource_count": 0,
                "active_planned_maintenance_count": 1,
                "active_planned_maintenance_resource_count": 1,
                "active_health_advisory_count": 0,
                "active_health_advisory_resource_count": 0,
                "service_health_events": [
                    {
                        "event_type": "PlannedMaintenance",
                        "title": "Example maintenance",
                        "impacted_resources": [{"name": "database-app"}],
                    }
                ],
                "metrics_requested": False,
                "metric_checked": 0,
                "metric_unavailable": 0,
                "unsupported_metric_resources": 0,
                "truncated": False,
                "findings": [
                    {
                        "kind": "resource_health",
                        "resource_name": "vm-customer",
                        "status": "Unavailable",
                        "reason": "Customer Initiated",
                    },
                    {
                        "kind": "resource_health",
                        "resource_name": "vm-platform",
                        "status": "Degraded",
                        "reason": "Platform Initiated",
                    },
                    {
                        "kind": "resource_health",
                        "resource_name": "vm-unknown",
                        "status": "Unknown",
                        "reason": "unknown",
                    },
                ],
            }

    backend = _Backend()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=SubscriptionHealthChatTools(Provider()),
            )
        ]
    )

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={
                "prompt": "현재 Azure 플랫폼 장애의 영향을 받는 리소스가 있어?",
                "view_context": {},
            },
        )

    answer = response.json()["answer"]
    assert "활성 Azure 장애 이벤트 0개" in answer
    assert "활성 계획 유지 관리 1개" in answer
    assert "Service Health PlannedMaintenance" in answer
    assert "Azure 플랫폼 영향 1개" in answer
    assert "Customer-initiated 1개" in answer
    assert "원인 미확정 1개" in answer
    assert "대표 메트릭: 요청되지 않음" in answer
    assert backend.calls == 0


def test_active_azure_outage_does_not_compile_running_state_or_metrics() -> None:
    calls: list[dict[str, object]] = []

    class Provider:
        async def __call__(
            self,
            lookback_seconds: int,
            *,
            progress_observer: Any = None,
        ) -> dict[str, Any]:
            raise AssertionError("platform health must use configurable broad query")

        async def query_health(
            self,
            lookback_seconds: int,
            *,
            include_metrics: bool,
            include_service_health: bool = False,
            progress_observer: Any = None,
        ) -> dict[str, Any]:
            del progress_observer
            calls.append(
                {
                    "lookback_seconds": lookback_seconds,
                    "include_metrics": include_metrics,
                    "include_service_health": include_service_health,
                }
            )
            return {
                "status": "matched",
                "source": "azure-resource-graph+resource-health+service-health",
                "observed_at": "2026-07-22T05:00:00Z",
                "resource_count": 1,
                "resource_health_unavailable": 0,
                "service_health_requested": include_service_health,
                "service_health_unavailable": 0,
                "metrics_requested": include_metrics,
                "metric_checked": 0,
                "metric_unavailable": 0,
                "unsupported_metric_resources": 0,
                "truncated": False,
                "findings": [],
            }

    backend = _Backend()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=SubscriptionHealthChatTools(Provider()),
            )
        ]
    )

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={
                "prompt": "Is any managed resource affected by an active Azure outage?",
                "view_context": {},
            },
        )

    payload = response.json()
    assert calls == [
        {
            "lookback_seconds": 3_600,
            "include_metrics": False,
            "include_service_health": True,
        }
    ]
    assert "0 active Azure outage event(s) affecting 0 managed resource(s)" in payload["answer"]
    assert "running" not in payload["answer"]
    assert backend.calls == 0


def test_platform_cause_comparisons_suppress_customer_state_groups() -> None:
    calls: list[dict[str, object]] = []

    class Provider:
        async def __call__(
            self,
            lookback_seconds: int,
            *,
            progress_observer: Any = None,
        ) -> dict[str, Any]:
            raise AssertionError("platform health must use configurable broad query")

        async def query_health(
            self,
            lookback_seconds: int,
            *,
            include_metrics: bool,
            include_service_health: bool = False,
            progress_observer: Any = None,
        ) -> dict[str, Any]:
            del progress_observer
            calls.append(
                {
                    "lookback_seconds": lookback_seconds,
                    "include_metrics": include_metrics,
                    "include_service_health": include_service_health,
                }
            )
            return {
                "status": "matched",
                "source": "azure-resource-graph+resource-health+service-health",
                "observed_at": "2026-07-22T05:00:00Z",
                "resource_count": 1,
                "resource_health_unavailable": 0,
                "service_health_requested": include_service_health,
                "service_health_unavailable": 0,
                "metrics_requested": include_metrics,
                "metric_checked": 0,
                "metric_unavailable": 0,
                "unsupported_metric_resources": 0,
                "truncated": False,
                "findings": [],
            }

    backend = _Backend()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=SubscriptionHealthChatTools(Provider()),
            )
        ]
    )

    prompts = (
        ("플랫폼 문제와 고객이 시작한 중지를 구분해줘.", "활성 Azure 장애 이벤트"),
        (
            "Separate platform-initiated impact from customer-initiated changes.",
            "active Azure outage event(s)",
        ),
    )
    with TestClient(app) as client:
        payloads = [
            client.post(
                "/chat",
                json={"prompt": prompt, "view_context": {}},
            ).json()
            for prompt, _summary in prompts
        ]

    assert calls == [
        {
            "lookback_seconds": 3_600,
            "include_metrics": False,
            "include_service_health": True,
        },
        {
            "lookback_seconds": 3_600,
            "include_metrics": False,
            "include_service_health": True,
        },
    ]
    for payload, (_prompt, summary) in zip(payloads, prompts, strict=True):
        assert summary in payload["answer"]
        assert "**stopped**" not in payload["answer"]
    assert backend.calls == 0


def test_resource_health_history_uses_typed_lookback_and_chronological_order() -> None:
    calls: list[int] = []

    class Provider:
        async def __call__(
            self,
            lookback_seconds: int,
            *,
            progress_observer: Any = None,
        ) -> dict[str, Any]:
            raise AssertionError("health history must use the historical provider")

        async def query_health_history(
            self,
            lookback_seconds: int,
            *,
            progress_observer: Any = None,
        ) -> dict[str, Any]:
            del progress_observer
            calls.append(lookback_seconds)
            return {
                "status": "matched",
                "source": "azure-resource-graph+resource-health-history",
                "observed_at": "2026-07-22T05:00:00Z",
                "resource_count": 2,
                "resource_health_unavailable": 0,
                "metrics_requested": False,
                "metric_checked": 0,
                "metric_unavailable": 0,
                "unsupported_metric_resources": 0,
                "truncated": False,
                "findings": [],
                "health_history_events": [
                    {
                        "resource_name": "database-later",
                        "resource_type": "Microsoft.DBforPostgreSQL/flexibleServers",
                        "resource_group": "rg-example",
                        "kind": "availability_status",
                        "status": "Unavailable",
                        "reason": "Platform Initiated",
                        "classification": "platform-initiated",
                        "observed_at": "2026-07-22T04:30:00Z",
                    },
                    {
                        "resource_name": "vm-earlier",
                        "status": "Unavailable",
                        "reason": "Customer Initiated",
                        "classification": "customer-initiated",
                        "observed_at": "2026-07-22T03:00:00Z",
                    },
                ],
            }

    backend = _Backend()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=SubscriptionHealthChatTools(Provider()),
            )
        ]
    )

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={
                "prompt": "지난 24시간의 리소스 상태 이벤트를 시간순으로 보여줘.",
                "view_context": {},
            },
        )

    answer = response.json()["answer"]
    resource_context = response.json()["resource_context"]
    assert calls == [86_400]
    assert answer.index("vm-earlier") < answer.index("database-later")
    assert "지난 24시간의 리소스 상태 이벤트 2개" in answer
    assert "customer-initiated 1건" in answer
    assert "platform-initiated 1건" in answer
    assert resource_context == {
        "name": "database-later",
        "resource_type": "microsoft.dbforpostgresql.flexibleservers",
        "evidence_ref": (
            "subscription-health:azure-resource-graph+resource-health-history@2026-07-22T05:00:00Z"
        ),
        "resource_group": "rg-example",
        "event_at": "2026-07-22T04:30:00Z",
        "event_status": "Unavailable",
    }
    contextualized, used_context = contextualize_resource_followup(
        "Who changed this resource most recently, and what did they do?",
        resource_context,
    )
    assert used_context is True
    assert contextualized == (
        "database-later change history: show the most recent successful operation"
    )
    contextualized, used_context = contextualize_resource_followup(
        "장애 직전에 발생한 배포와 설정 변경을 찾아줘.",
        resource_context,
    )
    assert used_context is True
    assert contextualized == (
        "database-later change history: pre-incident activity "
        "group=rg-example before=2026-07-22T04:30:00Z locale=ko"
    )
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
