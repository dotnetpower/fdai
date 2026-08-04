"""Twenty grounded Azure resource questions through the Command Deck route."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.core.conversation.answer_plan import AnswerIntent
from fdai.delivery.operator_api.routes.chat import make_chat_route, make_chat_stream_route
from fdai.delivery.operator_api.routes.chat_behavior_evidence import (
    RepositoryBehaviorEvidenceResolver,
)
from fdai.delivery.operator_api.routes.chat_intent_graph import (
    ActionPosture,
    EvidenceMode,
    IntentGoal,
    IntentGraph,
)
from fdai.delivery.operator_api.routes.chat_inventory import (
    InventoryChatTools,
    inventory_evidence_refs,
    inventory_execution_query,
    render_inventory_answer,
)
from fdai.delivery.operator_api.routes.chat_inventory_compiler import (
    compile_inventory_query,
    inventory_query_status_groups,
)
from fdai.delivery.operator_api.routes.chat_inventory_followup import (
    InventoryScreenScopeStatus,
    contextualize_inventory_scope_followup,
    contextualize_inventory_screen_scope,
)
from fdai.delivery.operator_api.routes.chat_inventory_query import (
    InventoryField,
    InventoryQueryKind,
    InventoryQueryScope,
)
from fdai.delivery.operator_api.routes.chat_resource_context import (
    resource_followup_answer,
    resource_followup_verification,
)
from fdai.delivery.operator_api.routes.chat_subscription_health import SubscriptionHealthChatTools
from fdai.delivery.operator_api.routes.chat_turn_plan import parse_turn_plan
from fdai.delivery.operator_api.routes.chat_verification import verify_answer

REPO_ROOT = Path(__file__).resolve().parents[3]


class RecordingBackend:
    def __init__(self) -> None:
        self.calls = 0

    async def answer(self, **kwargs: object) -> dict[str, str]:
        self.calls += 1
        return {"answer": "fallback", "model": "test"}


async def test_topology_questions_require_exact_resource_selectors() -> None:
    prompts = (
        "애플리케이션에서 데이터베이스까지 의존 관계를 보여줘.",
        "선택한 앱에서 DB까지 연결된 dependency 경로를 그려줘.",
        "애플리케이션과 데이터베이스 사이의 의존 리소스를 방향과 함께 보여줘.",
        "Map the dependencies from the application to its database.",
        "Trace the directed dependency path between the selected app and database.",
        "Show the resource relationships connecting this application to its database.",
        "앱에서 데이터베이스까지 실제로 통신할 수 있어?",
        "Can the application reach the database end to end?",
        "이 네트워크 보안 그룹이 허용하는 인바운드 포트는 뭐야?",
        "Which inbound ports are allowed by this network security group?",
        "선택한 NSG의 허용 inbound rule과 포트를 보여줘.",
        "이 네트워크 보안 그룹에서 인바운드로 열려 있는 포트를 알려줘.",
        "What inbound traffic does this network security group permit?",
        "이 가상 네트워크의 피어링 상태와 제한을 알려줘.",
        "Show this virtual network's peerings, direction, and configuration limits.",
        "What networks are peered with this VNet, and what configuration constraints apply?",
        "이 데이터베이스가 실패하면 어떤 서비스가 영향을 받아?",
        "What is the bounded impact scope if this database fails?",
        "선택한 DB 장애의 bounded impact scope를 dependency 기준으로 보여줘.",
        "이 데이터베이스에 의존해 영향받을 수 있는 서비스를 알려줘.",
        "Which dependent resources could be affected by a failure of this database?",
        "Trace the path from an app to a database.",
        "List the blast radius of the selected database.",
        "Show inbound rules for that NSG.",
    )
    calls = 0

    async def provider(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        del args, kwargs
        calls += 1
        return {}

    tools = InventoryChatTools(provider)
    for prompt in prompts:
        evidence = await tools.resolve(prompt, principal_id="reader")
        assert evidence is not None
        assert evidence["authority"] == "server_inventory_graph"
        assert evidence["result"]["reason"] == "topology_selector_required"
        answer = render_inventory_answer(evidence, locale="ko" if "이" in prompt else "en")
        assert answer is not None
        assert "exact" in answer or "정확한" in answer

    assert calls == 0


async def test_recognized_inventory_intent_does_not_fall_back_when_query_is_incomplete() -> None:
    class RejectFallback:
        async def resolve(self, prompt: str, *, principal_id: str) -> None:
            del prompt, principal_id
            raise AssertionError("recognized inventory intent must not fall back")

    async def provider(*args: Any, **kwargs: Any) -> dict[str, Any]:
        del args, kwargs
        return {
            "resources": [
                _resource(
                    "resource-1",
                    "compute.vm",
                    "example-vm",
                    group="example-group",
                    location="example-region",
                )
            ],
            "links": [],
            "freshness": "fresh",
        }

    evidence = await InventoryChatTools(
        provider,
        fallback=RejectFallback(),
    ).resolve(
        "List resources in this group with type, region, and state.",
        principal_id="reader",
    )

    assert evidence == {
        "tool": "query_inventory",
        "authority": "server_inventory_graph",
        "result": {
            "status": "unavailable",
            "reason": "inventory_query_not_compiled",
        },
    }


class StructuredPresentationBackend(RecordingBackend):
    def __init__(self, selected_format: str) -> None:
        super().__init__()
        self.selected_format = selected_format
        self.structured_calls = 0

    async def complete_structured(self, **_kwargs: object) -> dict[str, str]:
        self.structured_calls += 1
        return {"format": self.selected_format}


async def _allow(request: Request) -> str:
    return "reader"


def test_topology_hold_skips_planner_and_narrator_json_and_sse() -> None:
    class Planner:
        async def plan_turn(self, **_kwargs: object) -> object:
            raise AssertionError("topology hold must skip semantic planning")

    async def provider(*args: Any, **kwargs: Any) -> dict[str, Any]:
        del args, kwargs
        raise AssertionError("topology hold must skip inventory provider")

    backend = RecordingBackend()
    tools = InventoryChatTools(provider)
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=tools,
                turn_planner=Planner(),  # type: ignore[arg-type]
            ),
            make_chat_stream_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=tools,
                turn_planner=Planner(),  # type: ignore[arg-type]
            ),
        ]
    )
    body = {"prompt": "Which dependent resources could be affected by a failure of this database?"}

    with TestClient(app) as client:
        direct = client.post("/chat", json=body)
        streamed = client.post("/chat/stream", json=body)

    payload = direct.json()
    done = _inventory_done_event(streamed.text)
    assert done is not None
    assert payload["verification"]["authority"] == "server_inventory_graph"
    assert done["verification"] == payload["verification"]
    assert backend.calls == 0


def _resource(
    resource_id: str,
    resource_type: str,
    name: str,
    *,
    group: str | None = None,
    location: str | None = None,
    status: str = "unknown",
    provider_type: str | None = None,
    status_source: str | None = None,
) -> dict[str, Any]:
    props = {
        "resourceGroup": group,
        "location": location,
        "sensitive": "must-not-enter-chat-evidence",
        "providerType": provider_type or resource_type,
    }
    return {
        "id": resource_id,
        "type": resource_type,
        "name": name,
        "status": status,
        "status_source": status_source or ("operational" if status != "unknown" else "unknown"),
        "props": props,
    }


async def _provider(
    scope: str | None,
    depth: int,
    link_types: tuple[str, ...],
    *,
    root: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    assert scope is None
    assert depth == 4
    assert link_types == ("contains", "attached_to", "depends_on")
    assert root in {None, "azure-subscription"}
    assert limit in {500, 1_000}
    resources = [
        _resource("sub", "subscription", "Example subscription"),
        _resource("rg-app", "resource-group", "rg-app", group="rg-app"),
        _resource("rg-data", "resource-group", "rg-data", group="rg-data"),
        _resource(
            "vm-app",
            "compute.vm",
            "vm-app",
            group="rg-app",
            location="koreacentral",
            status="running",
        ),
        _resource(
            "vm-job",
            "compute.vm",
            "vm-job",
            group="rg-app",
            location="koreacentral",
            status="stopped",
        ),
        _resource(
            "storage-app", "object-storage", "storage-app", group="rg-app", location="koreacentral"
        ),
        _resource(
            "postgres-data",
            "postgresql-server",
            "postgres-data",
            group="rg-data",
            location="koreacentral",
            status="stopped",
        ),
        _resource("sql-app", "sql-database", "sql-app", group="rg-data", location="koreacentral"),
        _resource(
            "aks-app", "kubernetes-cluster", "aks-app", group="rg-app", location="koreacentral"
        ),
        _resource("vnet-app", "network.vnet", "vnet-app", group="rg-app", location="koreacentral"),
        _resource("identity-app", "managed-identity", "identity-app", group="rg-app"),
        _resource(
            "vault-app", "secret-store", "vault-app", group="rg-app", location="koreacentral"
        ),
        _resource(
            "pip-app", "network.public-ip", "pip-app", group="rg-app", location="koreacentral"
        ),
        _resource("nsg-app", "network.nsg", "nsg-app", group="rg-app", location="koreacentral"),
    ]
    return {
        "snapshot_at": "2026-07-20T10:00:00Z",
        "freshness": "fresh",
        "source": "azure-resource-graph",
        "active_view": "all-test-resources",
        "truncated": False,
        "resources": resources,
        "links": [
            {"source": "rg-app", "target": "vm-app", "type": "contains"},
            {"source": "vnet-app", "target": "vm-app", "type": "depends_on"},
            {"source": "pip-app", "target": "vm-app", "type": "attached_to"},
        ],
    }


async def _projected_provider(
    scope: str | None,
    depth: int,
    link_types: tuple[str, ...],
    *,
    root: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    graph = await _provider(scope, depth, link_types, root=root, limit=limit)
    group_ids = {
        resource["name"]: resource["id"]
        for resource in graph["resources"]
        if resource["type"] == "resource-group"
    }
    resources = []
    for resource in graph["resources"]:
        props = resource.get("props", {})
        resources.append(
            {
                **{key: value for key, value in resource.items() if key != "props"},
                "parent_id": (
                    "sub"
                    if resource["type"] == "resource-group"
                    else group_ids.get(props.get("resourceGroup"))
                ),
                "location": props.get("location"),
                "resource_group": props.get("resourceGroup"),
                "provider_type": props.get("providerType"),
            }
        )
    resources.append(
        {
            "id": "derived-subnet",
            "type": "network.subnet",
            "name": "derived-subnet",
            "status": "unknown",
            "parent_id": group_ids["rg-data"],
            "location": None,
            "resource_group": "rg-data",
            "provider_type": None,
        }
    )
    return {**graph, "resources": resources}


async def _activity_provider(
    lookback_seconds: int,
    max_events: int,
) -> dict[str, Any]:
    assert lookback_seconds == 7 * 24 * 3_600
    assert max_events == 200
    return {
        "status": "matched",
        "source": "azure-activity-log",
        "observed_at": "2026-07-29T10:00:00Z",
        "truncated": False,
        "events": [
            {
                "occurred_at": "2026-07-29T09:00:00Z",
                "event_status": "Succeeded",
                "operation": "start",
                "name": "vm-app",
                "type": "compute.vm",
                "resource_group": "rg-app",
            },
            {
                "occurred_at": "2026-07-29T08:00:00Z",
                "event_status": "Succeeded",
                "operation": "delete",
                "name": "vm-old",
                "type": "compute.vm",
                "resource_group": "rg-app",
            },
        ],
    }


async def _inventory_evidence(prompt: str) -> dict[str, Any]:
    evidence = await InventoryChatTools(_provider).resolve(prompt, principal_id="reader")
    assert evidence is not None
    return evidence


async def test_inventory_table_format_is_rendered_deterministically() -> None:
    evidence = await _inventory_evidence("현재 우리구독의 리소스그룹을 표로 보여줘")

    verification = verify_answer(
        "unsupported draft",
        {"_tool_evidence": evidence, "_answer_plan": {"format": "table"}},
        locale="ko",
    )

    assert "구독 범위에서 리소스 그룹 2개를 확인했습니다." in verification.answer
    assert "| 리소스 그룹 | 위치 | 상태 |" in verification.answer
    assert "| rg-app | - | unknown |" in verification.answer
    assert "| 형식 |" not in verification.answer
    assert "- 리소스 rg-app" not in verification.answer


def test_stream_uses_model_selected_table_for_comparable_inventory_rows() -> None:
    backend = StructuredPresentationBackend("table")
    app = Starlette(
        routes=[
            make_chat_stream_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=InventoryChatTools(_provider),
            )
        ]
    )

    response = TestClient(app).post(
        "/chat/stream",
        json={
            "request_id": "req-adaptive-presentation",
            "prompt": "현재 구독에서 사용하는 데이터베이스가 뭐야?",
            "view_context": {"_locale": "ko"},
        },
    )

    done = _inventory_done_event(response.text)
    assert done is not None
    assert done["answer_plan"]["format"] == "table"
    assert "| 이름 | 형식 | 상태 | 위치 | 리소스 그룹 |" in done["answer"]
    assert backend.structured_calls == 1
    assert backend.calls == 0


def test_stream_uses_structured_model_selection_for_inventory_chart() -> None:
    backend = StructuredPresentationBackend("chart")
    app = Starlette(
        routes=[
            make_chat_stream_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=InventoryChatTools(_provider),
            )
        ]
    )

    response = TestClient(app).post(
        "/chat/stream",
        json={
            "request_id": "req-adaptive-chart",
            "prompt": "현재 구독 데이터베이스 종류별 분포를 보기 좋게 보여줘",
            "view_context": {"_locale": "ko"},
        },
    )

    done = _inventory_done_event(response.text)
    assert done is not None
    assert done["answer_plan"]["format"] == "chart"
    chart_body = done["answer"].split("```chart\n", 1)[1].split("\n```", 1)[0]
    chart = json.loads(chart_body)
    assert chart["type"] == "bar"
    assert {item["label"] for item in chart["data"]} == {
        "postgresql-server",
        "sql-database",
    }
    assert backend.structured_calls == 1
    assert backend.calls == 0


def test_compound_korean_resource_group_request_keeps_subject_and_scope() -> None:
    query = compile_inventory_query("현재 우리구독의 리소스그룹을 표로 보여줘")

    assert query is not None
    assert query.kind is InventoryQueryKind.LIST
    assert query.scope is InventoryQueryScope.SUBSCRIPTION
    assert query.predicates[0].field is InventoryField.RESOURCE_TYPE
    assert query.predicates[0].value == "resource-group"


async def test_inventory_chart_format_emits_valid_chart_json() -> None:
    evidence = await _inventory_evidence("리소스 그룹 목록을 그래프로 보여줘")

    verification = verify_answer(
        "unsupported draft",
        {"_tool_evidence": evidence, "_answer_plan": {"format": "chart"}},
        locale="ko",
    )

    chart_body = verification.answer.split("```chart\n", 1)[1].split("\n```", 1)[0]
    chart = json.loads(chart_body)
    assert chart == {
        "type": "bar",
        "title": "위치별 리소스 그룹",
        "unit": "개",
        "data": [{"label": "unknown", "value": 2}],
    }


async def test_korean_deallocated_vm_question_uses_verified_inventory_without_model() -> None:
    async def provider(
        scope: str | None,
        depth: int,
        link_types: tuple[str, ...],
        *,
        root: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        graph = await _provider(scope, depth, link_types, root=root, limit=limit)
        resources = [
            {
                **resource,
                "status": "VM deallocated" if resource["name"] == "vm-job" else resource["status"],
            }
            for resource in graph["resources"]
        ]
        return {**graph, "resources": resources}

    backend = RecordingBackend()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=InventoryChatTools(provider),
            )
        ]
    )

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={"prompt": "할당 해제된 가상 머신을 모두 찾아줘.", "view_context": {}},
        )

    payload = response.json()
    assert payload["verification"]["status"] == "verified"
    assert payload["verification"]["reason_code"] == "inventory_snapshot_grounded"
    assert "vm-job" in payload["answer"]
    assert "vm-app" not in payload["answer"]
    assert backend.calls == 0


async def test_multiple_vm_states_render_as_disjoint_status_groups() -> None:
    async def provider(
        scope: str | None,
        depth: int,
        link_types: tuple[str, ...],
        *,
        root: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        graph = await _provider(scope, depth, link_types, root=root, limit=limit)
        resources = [
            _resource("vm-running", "compute.vm", "vm-running", status="VM running"),
            _resource("vm-stopped", "compute.vm", "vm-stopped", status="VM stopped"),
            _resource(
                "vm-deallocated",
                "compute.vm",
                "vm-deallocated",
                status="VM deallocated",
            ),
        ]
        return {**graph, "resources": resources}

    evidence = await InventoryChatTools(provider).resolve(
        "Which virtual machines are running, stopped, or deallocated?",
        principal_id="reader",
    )

    assert evidence is not None
    answer = render_inventory_answer(evidence, locale="en")
    assert answer is not None
    assert "**Stopped**\n- Resource vm-stopped" in answer
    assert "**Deallocated**\n- Resource vm-deallocated" in answer
    assert "**Running**\n- Resource vm-running" in answer
    assert answer.count("vm-deallocated") == 1


def test_korean_deallocated_vm_ignores_invalid_semantic_plan_and_web() -> None:
    class Planner:
        async def plan_turn(self, **_kwargs: object) -> Any:
            return parse_turn_plan(
                {
                    "kind": "read_tool",
                    "answer_intent": "status",
                    "tool_name": "query_inventory",
                    "action_type": None,
                    "arguments": {
                        "source": "current",
                        "kind": "list",
                        "predicates": [],
                        "lookback_seconds": 3_600,
                    },
                    "clarification": None,
                    "confidence": 0.9,
                }
            )

    class WebResolver:
        async def resolve(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("deterministic inventory must not search public web")

        async def resolve_planned(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("deterministic inventory must not use a web plan")

    async def provider(
        scope: str | None,
        depth: int,
        link_types: tuple[str, ...],
        *,
        root: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        graph = await _provider(scope, depth, link_types, root=root, limit=limit)
        return {
            **graph,
            "resources": [
                {
                    **resource,
                    "status": (
                        "VM deallocated" if resource["name"] == "vm-job" else resource["status"]
                    ),
                }
                for resource in graph["resources"]
            ]
            + [_resource("vm-stopped", "compute.vm", "vm-stopped", status="VM stopped")],
        }

    async def health_provider(
        lookback_seconds: int,
        *,
        progress_observer: Any = None,
    ) -> dict[str, Any]:
        del lookback_seconds, progress_observer
        raise AssertionError("specific VM inventory must not use subscription health")

    backend = RecordingBackend()
    inventory = InventoryChatTools(provider)
    tools = SubscriptionHealthChatTools(health_provider, fallback=inventory)
    app = Starlette(
        routes=[
            make_chat_stream_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=tools,
                planned_tool_resolver=inventory,
                web_search_resolver=WebResolver(),  # type: ignore[arg-type]
                turn_planner=Planner(),  # type: ignore[arg-type]
                turn_tools=inventory.turn_tools(),
            )
        ]
    )

    response = TestClient(app).post(
        "/chat/stream",
        json={"prompt": "할당 해제된 가상 머신을 모두 찾아줘.", "view_context": {}},
    )

    done = _inventory_done_event(response.text)
    assert done is not None
    assert done["verification"]["status"] == "verified"
    assert done["verification"]["reason_code"] == "inventory_snapshot_grounded"
    assert "vm-job" in done["answer"]
    assert "vm-app" not in done["answer"]
    assert "vm-stopped" not in done["answer"]
    assert "public_web" not in response.text
    assert backend.calls == 0


async def test_korean_database_grouping_uses_only_matched_stopped_types() -> None:
    async def provider(
        scope: str | None,
        depth: int,
        link_types: tuple[str, ...],
        *,
        root: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        assert scope is None
        assert depth == 4
        assert link_types == ("contains", "attached_to", "depends_on")
        assert root == "azure-subscription"
        assert limit == 1_000
        return {
            "snapshot_at": "2026-07-20T10:00:00Z",
            "freshness": "fresh",
            "source": "azure-resource-graph",
            "active_view": "all-test-resources",
            "truncated": False,
            "resources": [
                _resource("mysql", "mysql-server", "mysql-data", status="Stopped"),
                _resource("postgres", "postgresql-server", "postgres-data", status="Stopped"),
                _resource("sql", "sql-database", "sql-data", status="Paused"),
                _resource("vm", "compute.vm", "vm-data", status="Stopped"),
            ],
            "links": [],
        }

    evidence = await InventoryChatTools(provider).resolve(
        "현재 멈춰 있는 DB를 종류별로 보여줘.",
        principal_id="reader",
    )

    assert evidence is not None
    answer = render_inventory_answer(evidence, locale="ko")
    assert answer is not None
    assert "mysql-server: 1개" in answer
    assert "postgresql-server: 1개" in answer
    assert "sql-database: 1개" in answer
    assert "compute.vm" not in answer
    assert evidence["result"]["matched_count"] == 3


async def test_explicit_database_states_render_separately_with_grounded_zero_group() -> None:
    async def provider(
        scope: str | None,
        depth: int,
        link_types: tuple[str, ...],
        *,
        root: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        assert scope is None
        assert depth == 4
        assert link_types == ("contains", "attached_to", "depends_on")
        assert root == "azure-subscription"
        assert limit == 1_000
        return {
            "snapshot_at": "2026-07-20T10:00:00Z",
            "freshness": "fresh",
            "source": "azure-resource-graph",
            "active_view": "all-test-resources",
            "truncated": False,
            "resources": [
                _resource("mysql", "mysql-server", "mysql-data", status="Stopped"),
            ],
            "links": [],
        }

    evidence = await InventoryChatTools(provider).resolve(
        "List stopped and paused database services separately.",
        principal_id="reader",
    )

    assert evidence is not None
    answer = render_inventory_answer(evidence, locale="en")
    assert answer is not None
    assert "**Stopped**" in answer
    assert "Resource mysql-data: mysql-server, Stopped" in answer
    assert "**Paused**" in answer
    assert "No matching resources in this scope." in answer
    assert evidence["result"]["status_filter"] == ["stopped", "paused"]


async def test_current_state_query_waits_for_fresh_inventory() -> None:
    class RefreshingProvider:
        def __init__(self) -> None:
            self.fresh = False
            self.calls = 0
            self.waits = 0

        async def __call__(
            self,
            scope: str | None,
            depth: int,
            link_types: tuple[str, ...],
            *,
            root: str | None = None,
            limit: int = 500,
        ) -> dict[str, Any]:
            del scope, depth, link_types, root, limit
            self.calls += 1
            return {
                "snapshot_at": "2026-07-20T10:00:00Z",
                "freshness": "fresh" if self.fresh else "stale",
                "source": "test-inventory",
                "active_view": "all-test-resources",
                "truncated": False,
                "resources": [
                    _resource("mysql", "mysql-server", "mysql-data", status="Stopped"),
                ],
                "links": [],
            }

        async def wait_for_refresh(self) -> None:
            self.waits += 1
            self.fresh = True

    provider = RefreshingProvider()

    evidence = await InventoryChatTools(provider).resolve(
        "Are any databases stopped right now?",
        principal_id="reader",
    )

    assert evidence is not None
    assert evidence["result"]["freshness"] == "fresh"
    assert evidence["result"]["matched_count"] == 1
    assert provider.calls == 2
    assert provider.waits == 1


async def test_current_state_query_without_refresh_barrier_fails_closed() -> None:
    async def stale_provider(
        scope: str | None,
        depth: int,
        link_types: tuple[str, ...],
        *,
        root: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        del scope, depth, link_types, root, limit
        return {
            "snapshot_at": "2026-07-20T10:00:00Z",
            "freshness": "stale",
            "source": "test-inventory",
            "active_view": "all-test-resources",
            "truncated": False,
            "resources": [],
            "links": [],
        }

    evidence = await InventoryChatTools(stale_provider).resolve(
        "Are any databases stopped right now?",
        principal_id="reader",
    )

    assert evidence is not None
    assert evidence["result"] == {
        "status": "unavailable",
        "reason": "fresh_inventory_required",
        "query_source": "current",
        "query": {
            "source": "current",
            "kind": "list",
            "predicates": [
                {
                    "field": "resource_type",
                    "operator": "in",
                    "value": [
                        "cache",
                        "mysql-server",
                        "nosql-database",
                        "postgresql-server",
                        "redis-enterprise",
                        "sql-database",
                    ],
                },
                {"field": "status", "operator": "in", "value": ["stopped", "deallocated"]},
            ],
            "lookback_seconds": None,
            "scope": "subscription",
            "group_by": "none",
            "projection": "details",
            "require_fresh": True,
            "include_workloads": False,
            "require_state_history": False,
        },
        "freshness": "stale",
    }


async def test_failed_state_answer_discloses_status_coverage_boundary() -> None:
    evidence = await _inventory_evidence("실패 상태인 Azure 리소스가 있어?")

    answer = render_inventory_answer(evidence, locale="ko")

    assert answer is not None
    assert "질문과 일치하는 리소스는 0개" in answer
    assert "현재 operational status만 확인" in answer
    assert "Activity Log 작업이 없다는 뜻은 아닙니다" in answer
    assert evidence["result"]["status_coverage"] == {
        "included": ["normalized_current_operational_status"],
        "excluded": ["deployment_failures", "activity_failures"],
    }


async def test_subscription_type_summary_uses_provider_types_and_separates_groups() -> None:
    evidence = await _inventory_evidence("이 구독에서 관리 중인 리소스를 유형별로 요약해줘.")

    answer = render_inventory_answer(evidence, locale="ko")

    assert answer is not None
    assert "Azure 리소스 11개를 10개 provider type으로 확인" in answer
    assert "compute.vm: 2개" in answer
    assert "Resource group 2개는 리소스 합계와 분리" in answer
    assert "파생된 하위 리소스 0개" in answer
    assert evidence["result"]["matched_count"] == 11
    assert evidence["result"]["resource_group_count"] == 2
    assert evidence["result"]["derived_resource_count"] == 0


async def test_scope_counts_report_resources_and_groups_from_one_snapshot() -> None:
    evidence = await _inventory_evidence(
        "How many resources and resource groups are in the managed scope?"
    )

    answer = render_inventory_answer(evidence, locale="en")

    assert answer is not None
    assert "contains 11 Azure resources and 2 resource groups" in answer
    assert "0 topology-derived child resources" in answer
    assert evidence["result"]["matched_count"] == 11
    assert evidence["result"]["resource_group_count"] == 2
    assert evidence["result"]["query_kind"] == "scope_counts"


@pytest.mark.parametrize(
    "prompt",
    (
        "중지된 VM은?",
        "resource group rg-data resources?",
        "이름이 vm-job인 Azure 리소스를 찾아줘",
        "resources in koreacentral?",
    ),
)
async def test_inventory_execution_evidence_preserves_the_verified_query(prompt: str) -> None:
    evidence = await _inventory_evidence(prompt)

    projected = json.loads(inventory_execution_query(evidence))

    assert projected["authority"] == "server_inventory_graph"
    assert projected["query_language"] == "IQL"
    assert projected["query"] == evidence["result"]["query"]
    assert projected["snapshot"]["source"] == "azure-resource-graph"
    assert not inventory_execution_query(evidence).lstrip().startswith("az ")


async def test_inventory_execution_evidence_separates_actual_provider_receipt() -> None:
    async def provider_with_receipt(*args: object, **kwargs: object) -> dict[str, Any]:
        graph = await _provider(*args, **kwargs)
        return {
            **graph,
            "provider_execution": {
                "transport": "azure_cli",
                "backend": "azure_resource_graph",
                "executed": True,
                "redacted": True,
                "page_count": 1,
                "commands": [
                    {
                        "label": "resources",
                        "language": "azure_cli",
                        "command": "az graph query --subscriptions <subscription-id>",
                    }
                ],
            },
        }

    evidence = await InventoryChatTools(provider_with_receipt).resolve(
        "중지된 VM은?",
        principal_id="reader",
    )
    assert evidence is not None

    projected = json.loads(inventory_execution_query(evidence))

    assert "provider_execution" not in projected
    assert evidence["result"]["provider_execution"]["backend"] == "azure_resource_graph"
    assert evidence["result"]["provider_execution"]["commands"] == [
        {
            "label": "resources",
            "language": "azure_cli",
            "command": "az graph query --subscriptions <subscription-id>",
        }
    ]


async def test_activity_execution_evidence_preserves_lookback_and_predicates() -> None:
    evidence = await InventoryChatTools(
        _provider,
        activity_provider=_activity_provider,
    ).resolve("최근 7일 변경된 Azure 리소스는?", principal_id="reader")
    assert evidence is not None

    projected = json.loads(inventory_execution_query(evidence))

    assert projected["authority"] == "server_inventory_activity"
    assert projected["query"]["source"] == "activity"
    assert projected["query"]["lookback_seconds"] == 7 * 24 * 3_600
    assert projected["query"]["predicates"] == evidence["result"]["query"]["predicates"]


@dataclass(frozen=True, slots=True)
class AzureQuestion:
    prompt: str
    expected: tuple[str, ...]
    excluded: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class InventoryWeaknessCase:
    prompt: str
    expects_inventory: bool
    expected: tuple[str, ...] = ()
    korean: bool = False


CASES = (
    AzureQuestion(
        "Azure 리소스는 몇 개야?",
        ("view 'all-test-resources'", "13개 중", "13개입니다"),
    ),
    AzureQuestion("Azure 인벤토리 목록을 보여줘", ("vm-app", "storage-app", "postgres-data")),
    AzureQuestion("가상 머신은 몇 개야?", ("2개입니다",)),
    AzureQuestion("VM 목록을 보여줘", ("vm-app", "vm-job"), ("storage-app",)),
    AzureQuestion("가상 머신은 어느 위치에 있어?", ("koreacentral", "vm-app")),
    AzureQuestion("VM 상태를 보여줘", ("running", "stopped")),
    AzureQuestion("스토리지 계정은 몇 개야?", ("1개입니다",)),
    AzureQuestion("PostgreSQL 리소스 목록은?", ("postgres-data",), ("sql-app",)),
    AzureQuestion("SQL 데이터베이스 목록을 보여줘", ("sql-app",), ("postgres-data",)),
    AzureQuestion("AKS 클러스터는 몇 개야?", ("1개입니다",)),
    AzureQuestion("가상 네트워크 목록은?", ("vnet-app",)),
    AzureQuestion("관리형 ID 목록을 보여줘", ("identity-app",)),
    AzureQuestion("키 볼트는 어디에 있어?", ("vault-app", "koreacentral")),
    AzureQuestion("리소스 그룹 목록을 보여줘", ("rg-app", "rg-data")),
    AzureQuestion(
        "resource group rg-data Azure 리소스 목록", ("postgres-data", "sql-app"), ("vm-app",)
    ),
    AzureQuestion(
        "Azure 리소스 종류를 보여줘",
        ("compute.vm: 2개", "Resource group 2개는 리소스 합계와 분리"),
    ),
    AzureQuestion("공인 IP 목록을 보여줘", ("pip-app",)),
    AzureQuestion("네트워크 보안 그룹 목록은?", ("nsg-app",)),
    AzureQuestion(
        "vm-app과 연결된 Azure 리소스는?",
        ("vnet-app --depends_on--> vm-app", "pip-app --attached_to--> vm-app"),
    ),
    AzureQuestion("이름이 vm-job인 Azure 리소스를 찾아줘", ("vm-job", "stopped"), ("vm-app",)),
)

INVENTORY_WEAKNESS_CASES = (
    InventoryWeaknessCase("what Azure assets exist?", True, ("vm-app", "storage-app")),
    InventoryWeaknessCase("Azure resource inventory?", True, ("13 of 13 resources",)),
    InventoryWeaknessCase("Azure 리소스 뭐 있어?", True, ("vm-app",), korean=True),
    InventoryWeaknessCase("show postgres servers", True, ("postgres-data",)),
    InventoryWeaknessCase("where are storage accounts?", True, ("storage-app",)),
    InventoryWeaknessCase("how many Kubernetes clusters?", True, ("1 of 13",)),
    InventoryWeaknessCase("list VMs in resource group rg-app", True, ("vm-app", "vm-job")),
    InventoryWeaknessCase("resource inventory summary", True, ("compute.vm",)),
    InventoryWeaknessCase("show key vaults", True, ("vault-app",)),
    InventoryWeaknessCase("managed identity count", True, ("1 of 13",)),
    InventoryWeaknessCase("public IPs?", True, ("pip-app",)),
    InventoryWeaknessCase("NSG list", True, ("nsg-app",)),
    InventoryWeaknessCase("what is Kubernetes?", False),
    InventoryWeaknessCase("explain managed identity", False),
    InventoryWeaknessCase("restart the VM", False),
    InventoryWeaknessCase("create a resource group", False),
    InventoryWeaknessCase("why is the database slow?", False),
    InventoryWeaknessCase("database backup policy", False),
    InventoryWeaknessCase("storage account encryption policy", False),
    InventoryWeaknessCase("compare VM and storage architecture", False),
    InventoryWeaknessCase("how many resources are affected?", False),
    InventoryWeaknessCase("what is the database CPU usage?", False),
)

GENERALIZED_RESOURCE_CASES = (
    InventoryWeaknessCase("running resources?", True, ("vm-app",), korean=False),
    InventoryWeaknessCase("실행 중인 리소스 있어?", True, ("vm-app",), korean=True),
    InventoryWeaknessCase("deallocated VMs?", True, ("vm-job",), korean=False),
    InventoryWeaknessCase("중지된 VM은?", True, ("vm-job",), korean=True),
    InventoryWeaknessCase("resources in koreacentral?", True, ("vm-app",), korean=False),
    InventoryWeaknessCase("resource group rg-data resources?", True, ("postgres-data", "sql-app")),
)

INVENTORY_RUBRIC_NAMES = (
    "intent-classification",
    "json-http-success",
    "authority-selection",
    "reason-code",
    "terminal-trust",
    "model-routing",
    "nonempty-answer",
    "locale-aligned",
    "matched-count-bounded",
    "active-view-present",
    "source-present",
    "snapshot-present",
    "freshness-present",
    "requested-resource-relevant",
    "sensitive-fields-excluded",
    "evidence-ref-count",
    "evidence-ref-prefix",
    "no-execution-claim",
    "bounded-answer",
    "json-sse-parity",
)


@pytest.mark.parametrize(
    "prompt,expected_name",
    [
        ("Web App 목록을 보여줘", "web-example"),
        ("함수 앱 목록을 보여줘", "function-example"),
        ("Logic App 목록을 보여줘", "logic-example"),
        ("NSG 목록을 보여줘", "nsg-example"),
        ("Azure Firewall 목록을 보여줘", "firewall-example"),
        ("DCR 목록을 보여줘", "dcr-example"),
    ],
)
async def test_common_azure_resource_queries_filter_inventory_graph(
    prompt: str,
    expected_name: str,
) -> None:
    resources = [
        _resource("web", "compute.web-app", "web-example"),
        _resource("function", "compute.function", "function-example"),
        _resource("logic", "workflow.logic-app", "logic-example"),
        _resource("nsg", "network.nsg", "nsg-example"),
        _resource("firewall", "network.firewall", "firewall-example"),
        _resource("dcr", "data-collection-rule", "dcr-example"),
    ]

    async def provider(
        scope: str | None,
        depth: int,
        link_types: tuple[str, ...],
        *,
        root: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        assert scope is None
        assert depth == 4
        assert link_types == ("contains", "attached_to", "depends_on")
        assert root == "azure-subscription"
        assert limit == 1_000
        return {
            "resources": resources,
            "links": [],
            "freshness": "fresh",
            "source": "test-inventory",
            "snapshot": {"id": "snapshot"},
        }

    evidence = await InventoryChatTools(provider).resolve(prompt, principal_id="reader")

    assert evidence is not None
    assert [item["name"] for item in evidence["result"]["resources"]] == [expected_name]


def test_twenty_azure_resource_questions_are_grounded_and_deterministic() -> None:
    backend = RecordingBackend()
    tools = InventoryChatTools(_provider)
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                behavior_resolver=RepositoryBehaviorEvidenceResolver(REPO_ROOT),
                tool_resolver=tools,
            )
        ]
    )

    with TestClient(app) as client:
        for case in CASES:
            response = client.post(
                "/chat",
                json={"prompt": case.prompt, "view_context": {}},
            )
            assert response.status_code == 200
            payload = response.json()
            answer = payload["answer"]
            verification = payload["verification"]
            assert verification["authority"] == "server_inventory_graph"
            assert verification["status"] == "verified"
            assert verification["reason_code"] == "inventory_snapshot_grounded"
            assert verification["evidence_refs"] == [
                "inventory:azure-resource-graph@2026-07-20T10:00:00Z"
            ]
            assert all(value in answer for value in case.expected)
            assert all(value not in answer for value in case.excluded)
            assert "must-not-enter-chat-evidence" not in answer
            assert "근거: azure-resource-graph" in answer

    assert backend.calls == 0


async def test_twenty_inventory_questions_emit_lossless_typed_queries() -> None:
    tools = InventoryChatTools(_provider)

    for case in CASES:
        evidence = await tools.resolve(case.prompt, principal_id="reader")
        assert evidence is not None, case.prompt
        result = evidence["result"]
        projected = json.loads(inventory_execution_query(evidence))

        assert projected["operation"] == "query_inventory", case.prompt
        assert projected["authority"] == "server_inventory_graph", case.prompt
        assert projected["query"] == result["query"], case.prompt
        assert projected["result"]["status"] == result["status"], case.prompt
        assert projected["result"]["matched_count"] == result["matched_count"], case.prompt
        assert projected["snapshot"] == {
            "active_view": "all-test-resources",
            "at": "2026-07-20T10:00:00Z",
            "freshness": "fresh",
            "source": "azure-resource-graph",
        }, case.prompt
        assert "az " not in inventory_execution_query(evidence), case.prompt


@pytest.mark.parametrize(
    "prompt",
    (
        "중지된 AKS 클러스터 이름 목록으로 보여줄래?",
        "중지 상태인 AKS 클러스터 이름을 보여줘",
        "AKS 중 멈춰 있는 클러스터 목록은?",
        "가동 중지된 쿠버네티스 클러스터 이름만 알려줘",
    ),
)
async def test_stopped_aks_name_list_keeps_type_and_status_scoped_together(
    prompt: str,
) -> None:
    async def aks_inventory(
        scope: str | None,
        depth: int,
        link_types: tuple[str, ...],
        *,
        root: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        graph = await _provider(scope, depth, link_types, root=root, limit=limit)
        resources = [
            {
                **resource,
                "status": "stopped" if resource["name"] == "aks-app" else resource["status"],
            }
            for resource in graph["resources"]
        ]
        resources.append(
            _resource(
                "aks-running",
                "kubernetes-cluster",
                "aks-running",
                group="rg-app",
                location="koreacentral",
                status="running",
            )
        )
        return {**graph, "resources": resources}

    evidence = await InventoryChatTools(aks_inventory).resolve(
        prompt,
        principal_id="reader",
    )
    assert evidence is not None

    answer = render_inventory_answer(evidence, locale="ko")

    assert "aks-app" in answer
    assert "aks-running" not in answer
    assert "vm-job" not in answer
    if "이름" in prompt:
        assert "- aks-app" in answer
        assert "kubernetes-cluster" not in answer
    assert evidence["result"]["query"]["predicates"] == [
        {
            "field": "resource_type",
            "operator": "eq",
            "value": "kubernetes-cluster",
        },
        {"field": "status", "operator": "eq", "value": "stopped"},
    ]


@pytest.mark.parametrize(
    "fragment",
    (
        "구독에서",
        "구독 전체에서",
        "전체 구독 범위로",
    ),
)
def test_subscription_scope_followup_reuses_prior_inventory_intent(fragment: str) -> None:
    provider_calls: list[dict[str, object]] = []

    async def subscription_inventory(
        scope: str | None,
        depth: int,
        link_types: tuple[str, ...],
        *,
        root: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        provider_calls.append({"scope": scope, "root": root, "limit": limit})
        graph = await _provider(scope, depth, link_types)
        resources = [
            {
                **resource,
                "status": "stopped" if resource["name"] == "aks-app" else resource["status"],
            }
            for resource in graph["resources"]
        ]
        resources.append(
            _resource(
                "aks-running",
                "kubernetes-cluster",
                "aks-running",
                group="rg-app",
                location="koreacentral",
                status="running",
            )
        )
        return {
            **graph,
            "active_view": "resource:azure-subscription",
            "resources": resources,
        }

    class Planner:
        async def plan_turn(self, **_kwargs: object) -> Any:
            raise AssertionError("deterministic scope follow-up must not invoke planning")

    class WebResolver:
        async def resolve(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("deterministic scope follow-up must not search the web")

        async def resolve_planned(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("deterministic scope follow-up must not search the web")

    backend = RecordingBackend()
    tools = InventoryChatTools(subscription_inventory)
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=tools,
                planned_tool_resolver=tools,
                turn_planner=Planner(),
                turn_tools=tools.turn_tools(),
                web_search_resolver=WebResolver(),  # type: ignore[arg-type]
            )
        ]
    )

    response = TestClient(app).post(
        "/chat",
        json={
            "prompt": fragment,
            "view_context": {},
            "history": [
                {
                    "role": "user",
                    "content": "중지된 AKS 클러스터 이름 목록으로 보여줄래?",
                },
                {
                    "role": "assistant",
                    "content": "현재 view에서 중지된 AKS 클러스터 이름을 확인했습니다.",
                },
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "aks-app" in payload["answer"]
    assert "aks-running" not in payload["answer"]
    assert "kubernetes-cluster" not in payload["answer"]
    assert provider_calls == [{"scope": None, "root": "azure-subscription", "limit": 1000}]
    assert payload["verification"]["authority"] == "server_inventory_graph"
    assert backend.calls == 0


def test_subscription_fragment_does_not_reuse_missing_or_stale_inventory_intent() -> None:
    assert contextualize_inventory_scope_followup("구독에서", ()) == ("구독에서", False)
    assert contextualize_inventory_scope_followup(
        "구독에서",
        (
            {
                "role": "user",
                "content": "중지된 AKS 클러스터 이름 목록으로 보여줄래?",
            },
            {"role": "assistant", "content": "두 개를 확인했습니다."},
            {"role": "user", "content": "고마워"},
            {"role": "assistant", "content": "도움이 되어 기쁩니다."},
        ),
    ) == ("구독에서", False)
    assert contextualize_inventory_scope_followup(
        "구독에서 장애가 있어?",
        ({"role": "user", "content": "중지된 AKS 클러스터 목록"},),
    ) == ("구독에서 장애가 있어?", False)


def test_architecture_selection_contextualizes_current_screen_inventory() -> None:
    prompt, contextualized = contextualize_inventory_screen_scope(
        "현재 화면의 리소스 그룹에 어떤 서비스가 있어?",
        {
            "routeId": "architecture",
            "records": {
                "selected_resource": [
                    {
                        "id": "rg-app",
                        "name": "rg-app",
                        "type": "resource-group",
                    }
                ]
            },
        },
    )

    assert contextualized is not None
    assert contextualized.status is InventoryScreenScopeStatus.RESOLVED
    query = compile_inventory_query(
        prompt,
        resources=(
            {"type": "resource-group", "name": "rg-app", "resource_group": "rg-app"},
            {"type": "compute.vm", "name": "vm-app", "resource_group": "rg-app"},
        ),
    )
    assert query is not None
    assert query.kind.value == "types"
    assert query.predicates[0].field.value == "resource_group"
    assert query.predicates[0].value == "rg-app"


def test_this_group_contextualizes_selected_resource_details() -> None:
    prompt, contextualized = contextualize_inventory_screen_scope(
        "List resources in this group with type, region, and state.",
        {
            "routeId": "architecture",
            "records": {
                "selected_resource": [
                    {
                        "id": "rg-data",
                        "name": "rg-data",
                        "type": "resource-group",
                    }
                ]
            },
        },
    )

    assert contextualized is not None
    assert contextualized.status is InventoryScreenScopeStatus.RESOLVED
    query = compile_inventory_query(
        prompt,
        resources=(
            {"type": "resource-group", "name": "rg-data", "resource_group": "rg-data"},
            {"type": "postgresql-server", "name": "db", "resource_group": "rg-data"},
        ),
    )
    assert query is not None
    assert query.kind.value == "list"
    assert [predicate.to_dict() for predicate in query.predicates] == [
        {"field": "resource_group", "operator": "eq", "value": "rg-data"},
        {"field": "resource_type", "operator": "ne", "value": "resource-group"},
        {"field": "provider_type", "operator": "exists", "value": None},
    ]


@pytest.mark.parametrize(
    "prompt",
    (
        "현재 화면의 리소스 그룹에 어떤 서비스가 있어?",
        "지금 보고 있는 리소스 그룹의 서비스 목록을 보여줘.",
        "현재 화면에 선택된 리소스 그룹에는 어떤 리소스 유형이 있나?",
        "List resources in this group with type, region, and state.",
        "Show this group's resources with their type, location, and current state.",
        "For the current group, list each resource's name, type, region, and status.",
    ),
)
def test_current_group_cohort_requires_selected_architecture_group(prompt: str) -> None:
    unchanged, contextualized = contextualize_inventory_screen_scope(
        prompt,
        {"routeId": "architecture", "records": {}},
    )

    assert unchanged == prompt
    assert contextualized is not None
    assert contextualized.status is InventoryScreenScopeStatus.UNAVAILABLE


def test_continuation_contextualizes_selected_state_coverage() -> None:
    prompt, contextualized = contextualize_inventory_screen_scope(
        "상태를 확인할 수 없는 리소스 유형도 함께 알려줘.",
        {
            "routeId": "architecture",
            "records": {
                "selected_resource": [
                    {
                        "id": "rg-data",
                        "name": "rg-data",
                        "type": "resource-group",
                    }
                ]
            },
        },
    )

    assert contextualized is not None
    assert contextualized.status is InventoryScreenScopeStatus.RESOLVED
    query = compile_inventory_query(
        prompt,
        resources=(
            {"type": "resource-group", "name": "rg-data", "resource_group": "rg-data"},
            {"type": "sql-database", "name": "rg-data", "resource_group": "RG-DATA"},
        ),
    )
    assert query is not None
    assert query.kind.value == "state_coverage"
    assert query.predicates[0].value == "rg-data"


def test_inventory_coverage_continuation_keeps_selected_group() -> None:
    prompt, contextualized = contextualize_inventory_screen_scope(
        "What inventory types did you check, skip, or fail to read?",
        {
            "routeId": "architecture",
            "records": {
                "selected_resource": [
                    {
                        "id": "rg-data",
                        "name": "rg-data",
                        "type": "resource-group",
                    }
                ]
            },
        },
    )

    assert contextualized is not None
    assert contextualized.status is InventoryScreenScopeStatus.RESOLVED
    query = compile_inventory_query(
        prompt,
        resources=(
            {"type": "resource-group", "name": "rg-data", "resource_group": "rg-data"},
            {"type": "sql-database", "name": "db", "resource_group": "rg-data"},
        ),
    )
    assert query is not None
    assert query.kind.value == "inventory_coverage"
    assert query.predicates[0].value == "rg-data"
    assert all(predicate.field.value != "name" for predicate in query.predicates)


@pytest.mark.parametrize(
    "prompt",
    (
        "현재 관리 범위의 리소스를 이름, 유형, 상태와 함께 보여줘.",
        "현재 관리 범위에서 상태가 확인된 리소스를 근거와 함께 하나 보여줘.",
        "관리 범위 리소스의 이름과 현재 상태를 목록으로 알려줘.",
        "List current managed resources with name, type, and status.",
        "Show resources in managed scope with their current state.",
    ),
)
def test_managed_scope_resource_lists_compile_deterministically(prompt: str) -> None:
    query = compile_inventory_query(prompt)

    assert query is not None
    assert query.kind.value == "list"
    assert query.scope.value == "subscription"
    assert query.require_fresh is True


def test_selected_architecture_group_routes_to_verified_service_types() -> None:
    backend = RecordingBackend()

    class RecordingOperationalResolver:
        calls = 0

        async def resolve(
            self,
            prompt: str,
            *,
            conversation_context: dict[str, str] | None = None,
        ) -> None:
            del prompt, conversation_context
            self.calls += 1

    operational = RecordingOperationalResolver()

    tools = InventoryChatTools(_projected_provider)
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                evidence_resolver=operational,
                tool_resolver=tools,
            ),
            make_chat_stream_route(
                backend=backend,
                authorize=_allow,
                evidence_resolver=operational,
                tool_resolver=tools,
            ),
        ]
    )
    body = {
        "prompt": "현재 화면의 리소스 그룹에 어떤 서비스가 있어?",
        "view_context": {
            "routeId": "architecture",
            "records": {
                "selected_resource": [
                    {
                        "id": "rg-app",
                        "name": "rg-app",
                        "type": "resource-group",
                    }
                ]
            },
        },
    }

    with TestClient(app) as client:
        response = client.post("/chat", json=body)
        stream = client.post("/chat/stream", json=body)

    assert response.status_code == 200
    answer = response.json()["answer"]
    assert "compute.vm: 2개" in answer
    assert "object-storage: 1개" in answer
    assert "postgresql-server" not in answer
    assert "resource-group" not in answer
    done = _inventory_done_event(stream.text)
    assert done is not None
    assert done["answer"] == answer
    assert "operational evidence unavailable" not in stream.text
    assert operational.calls == 0
    assert backend.calls == 0


@pytest.mark.parametrize(
    ("prompt", "expected"),
    (
        ("현재 화면의 리소스 그룹에 어떤 서비스가 있어?", "리소스 그룹을 선택"),
        ("이 화면에서 선택한 리소스 그룹의 서비스 목록을 보여줘.", "리소스 그룹을 선택"),
        ("Show services in the resource group selected on this screen.", "Select a resource group"),
        ("지금 화면에서 보고 있는 그룹엔 뭐가 있어?", "리소스 그룹을 선택"),
    ),
)
def test_current_screen_group_without_selection_holds_for_scope(
    prompt: str,
    expected: str,
) -> None:
    provider_calls = 0
    agent_calls = 0

    class AgentDelegate:
        async def delegate(
            self,
            *,
            prompt: str,
            user_id: str,
            session_id: str,
        ) -> dict[str, Any] | None:
            nonlocal agent_calls
            del prompt, user_id, session_id
            agent_calls += 1
            return None

    async def provider(
        scope: str | None,
        depth: int,
        link_types: tuple[str, ...],
        *,
        root: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        nonlocal provider_calls
        provider_calls += 1
        return await _projected_provider(scope, depth, link_types, root=root, limit=limit)

    backend = RecordingBackend()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                agent_delegate=AgentDelegate(),
                tool_resolver=InventoryChatTools(provider),
            ),
            make_chat_stream_route(
                backend=backend,
                authorize=_allow,
                agent_delegate=AgentDelegate(),
                tool_resolver=InventoryChatTools(provider),
            ),
        ]
    )
    body = {
        "prompt": prompt,
        "view_context": {"routeId": "architecture", "records": {}},
    }

    with TestClient(app) as client:
        response = client.post("/chat", json=body)
        stream = client.post("/chat/stream", json=body)

    payload = response.json()
    done = _inventory_done_event(stream.text)
    assert response.status_code == 200
    assert done is not None
    assert expected in payload["answer"]
    assert done["answer"] == payload["answer"]
    assert payload["verification"]["status"] == "unverified"
    assert payload["verification"]["reason_code"] == "inventory_evidence_unavailable"
    assert provider_calls == 0
    assert agent_calls == 0
    assert backend.calls == 0


def test_selected_group_details_include_type_region_and_state() -> None:
    backend = RecordingBackend()
    app = Starlette(
        routes=[
            make_chat_stream_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=InventoryChatTools(_projected_provider),
            )
        ]
    )
    body = {
        "prompt": "List resources in this group with type, region, and state.",
        "view_context": {
            "routeId": "architecture",
            "records": {
                "selected_resource": [
                    {
                        "id": "rg-data",
                        "name": "rg-data",
                        "type": "resource-group",
                    }
                ]
            },
        },
    }

    with TestClient(app) as client:
        stream = client.post("/chat/stream", json=body)

    done = _inventory_done_event(stream.text)
    assert done is not None
    answer = done["answer"]
    assert "| postgres-data | postgresql-server | stopped | koreacentral | rg-data |" in answer
    assert "| sql-app | sql-database | unknown | koreacentral | rg-data |" in answer
    assert "derived-subnet" not in answer
    assert "resource-group" not in answer
    assert backend.calls == 0


def test_selected_group_state_coverage_separates_status_provenance() -> None:
    backend = RecordingBackend()
    app = Starlette(
        routes=[
            make_chat_stream_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=InventoryChatTools(_projected_provider),
            )
        ]
    )
    body = {
        "prompt": "상태를 확인할 수 없는 리소스 유형도 함께 알려줘.",
        "view_context": {
            "routeId": "architecture",
            "records": {
                "selected_resource": [
                    {
                        "id": "rg-data",
                        "name": "rg-data",
                        "type": "resource-group",
                    }
                ]
            },
        },
    }

    with TestClient(app) as client:
        stream = client.post("/chat/stream", json=body)

    done = _inventory_done_event(stream.text)
    assert done is not None
    answer = done["answer"]
    assert "운영 상태 직접 확인 가능 유형" in answer
    assert "postgresql-server: 1개" in answer
    assert "운영 상태 직접 확인 불가 유형" in answer
    assert "sql-database: 1개" in answer
    assert backend.calls == 0


def test_selected_group_inventory_coverage_separates_skips_and_failures() -> None:
    backend = RecordingBackend()
    app = Starlette(
        routes=[
            make_chat_stream_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=InventoryChatTools(_projected_provider),
            )
        ]
    )
    body = {
        "prompt": "What inventory types did you check, skip, or fail to read?",
        "view_context": {
            "routeId": "architecture",
            "records": {
                "selected_resource": [
                    {
                        "id": "rg-data",
                        "name": "rg-data",
                        "type": "resource-group",
                    }
                ]
            },
        },
    }

    with TestClient(app) as client:
        stream = client.post("/chat/stream", json=body)

    done = _inventory_done_event(stream.text)
    assert done is not None
    answer = done["answer"]
    assert "Checked 2 provider inventory resources across 2 types" in answer
    assert "postgresql-server: 1" in answer
    assert "sql-database: 1" in answer
    assert "**Skipped types**: none" in answer
    assert "**Failed-to-read types**: 0" in answer
    assert "Operational state unavailable for 1 types" in answer
    assert backend.calls == 0


def test_subscription_scope_followup_stream_uses_subscription_root() -> None:
    provider_calls: list[dict[str, object]] = []

    async def subscription_inventory(
        scope: str | None,
        depth: int,
        link_types: tuple[str, ...],
        *,
        root: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        provider_calls.append({"scope": scope, "root": root, "limit": limit})
        graph = await _provider(scope, depth, link_types)
        return {
            **graph,
            "active_view": "resource:azure-subscription",
            "resources": [
                {
                    **resource,
                    "status": ("stopped" if resource["name"] == "aks-app" else resource["status"]),
                }
                for resource in graph["resources"]
            ],
        }

    class Planner:
        async def plan_turn(self, **_kwargs: object) -> Any:
            raise AssertionError("deterministic scope follow-up must not invoke planning")

    backend = RecordingBackend()
    tools = InventoryChatTools(subscription_inventory)
    app = Starlette(
        routes=[
            make_chat_stream_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=tools,
                planned_tool_resolver=tools,
                turn_planner=Planner(),  # type: ignore[arg-type]
                turn_tools=tools.turn_tools(),
            )
        ]
    )

    response = TestClient(app).post(
        "/chat/stream",
        json={
            "prompt": "구독에서",
            "view_context": {},
            "history": [
                {
                    "role": "user",
                    "content": "중지된 AKS 클러스터 이름 목록으로 보여줄래?",
                },
                {"role": "assistant", "content": "두 개를 확인했습니다."},
            ],
        },
    )

    assert response.status_code == 200
    done = _inventory_done_event(response.text)
    assert done is not None
    assert "aks-app" in done["answer"]
    assert "kubernetes-cluster" not in done["answer"]
    assert provider_calls == [{"scope": None, "root": "azure-subscription", "limit": 1000}]
    assert done["verification"]["authority"] == "server_inventory_graph"
    assert backend.calls == 0


def test_inventory_provider_failure_is_unverified_and_fail_closed() -> None:
    async def unavailable(
        scope: str | None,
        depth: int,
        link_types: tuple[str, ...],
    ) -> dict[str, Any]:
        del scope, depth, link_types
        raise RuntimeError("provider unavailable")

    backend = RecordingBackend()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=InventoryChatTools(unavailable),
            )
        ]
    )
    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={"prompt": "Azure 리소스 목록을 보여줘", "view_context": {}},
        )
    payload = response.json()
    assert payload["verification"]["status"] == "unverified"
    assert payload["verification"]["reason_code"] == "inventory_evidence_unavailable"
    assert "확정하지 않았습니다" in payload["answer"]
    assert backend.calls == 0


async def test_activity_collection_filters_and_verifies_server_scoped_changes() -> None:
    evidence = await InventoryChatTools(
        _provider,
        activity_provider=_activity_provider,
    ).resolve("최근 7일 시작된 리소스", principal_id="reader")

    assert evidence is not None
    assert evidence["authority"] == "server_inventory_activity"
    assert evidence["result"]["matched_count"] == 1
    assert evidence["result"]["events"][0]["name"] == "vm-app"
    assert "vm-old" not in repr(evidence)
    answer = render_inventory_answer(evidence, locale="ko")
    assert answer is not None
    assert "vm-app" in answer
    assert "start" in answer
    assert "2026-07-29T09:00:00Z" in answer
    verification = verify_answer("", {"_tool_evidence": evidence}, locale="ko")
    assert verification.status == "corrected"
    assert verification.authority == "server_inventory_activity"
    assert verification.reason_code == "inventory_activity_grounded"
    assert inventory_evidence_refs(evidence) == (
        "activity:azure-activity-log@2026-07-29T10:00:00Z",
    )


async def test_activity_collection_is_explicitly_unavailable_without_provider() -> None:
    evidence = await InventoryChatTools(_provider).resolve(
        "변경된 리소스 보여줘",
        principal_id="reader",
    )

    assert evidence is not None
    assert evidence["result"]["status"] == "unavailable"
    answer = render_inventory_answer(evidence, locale="ko")
    assert answer is not None
    assert "Activity Log 근거를 사용할 수 없어" in answer


async def test_aks_workload_question_reports_cluster_only_coverage() -> None:
    evidence = await InventoryChatTools(_provider).resolve(
        "지금 AKS에 배포되고 있는 게 있어?",
        principal_id="reader",
    )

    assert evidence is not None
    assert evidence["result"]["status"] == "partial"
    assert evidence["result"]["coverage_gap"] == "kubernetes_workloads"
    answer = render_inventory_answer(evidence, locale="ko")
    assert answer is not None
    assert "aks-app" in answer
    assert "Node readiness, Deployment와 Pod는 포함하지 않습니다" in answer
    verification = verify_answer("", {"_tool_evidence": evidence}, locale="ko")
    assert verification.status == "unverified"
    assert verification.reason_code == "inventory_workload_coverage_gap"
    assert verification.answer == answer


async def test_unhealthy_aks_node_question_filters_clusters_and_holds_node_claim() -> None:
    async def provider(
        scope: str | None,
        depth: int,
        link_types: tuple[str, ...],
        *,
        root: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        graph = await _provider(scope, depth, link_types, root=root, limit=limit)
        resources = [
            _resource("aks-stopped", "kubernetes-cluster", "aks-stopped", status="Stopped"),
            _resource("aks-running", "kubernetes-cluster", "aks-running", status="Running"),
        ]
        return {**graph, "resources": resources}

    evidence = await InventoryChatTools(provider).resolve(
        "비정상 상태인 AKS 클러스터나 노드가 있어?",
        principal_id="reader",
    )

    assert evidence is not None
    assert evidence["result"]["status"] == "partial"
    assert evidence["result"]["matched_count"] == 1
    answer = render_inventory_answer(evidence, locale="ko")
    assert answer is not None
    assert "aks-stopped" in answer
    assert "aks-running" not in answer
    assert "Node readiness" in answer
    verification = verify_answer("", {"_tool_evidence": evidence}, locale="ko")
    assert verification.status == "corrected"
    assert verification.checks_completed == 1
    assert verification.checks_total == 1
    assert verification.reason_code == "inventory_findings_grounded_partial"


async def test_unhealthy_kubernetes_workload_question_holds_transition_time() -> None:
    async def provider(
        scope: str | None,
        depth: int,
        link_types: tuple[str, ...],
        *,
        root: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        graph = await _provider(scope, depth, link_types, root=root, limit=limit)
        graph["resources"] = [
            _resource("aks-stopped", "kubernetes-cluster", "aks-stopped", status="Stopped"),
            _resource("solution", "log-analytics-solution", "kubernetes"),
        ]
        return graph

    evidence = await InventoryChatTools(provider).resolve(
        "Show unhealthy Kubernetes workloads and when they became unhealthy.",
        principal_id="reader",
    )

    assert evidence is not None
    assert evidence["result"]["matched_count"] == 1
    assert evidence["result"]["state_history_requested"] is True
    answer = render_inventory_answer(evidence, locale="en")
    assert answer is not None
    assert "aks-stopped" in answer
    assert "State-transition time remains unconfirmed" in answer
    verification = verify_answer("", {"_tool_evidence": evidence}, locale="en")
    assert verification.status == "corrected"
    assert verification.reason_code == "inventory_findings_grounded_partial"


async def test_aks_workload_question_uses_bound_kubernetes_evidence() -> None:
    async def workloads() -> dict[str, Any]:
        return {
            "status": "matched",
            "cluster_name": "aks-app",
            "source": "kubernetes_apiserver",
            "observed_at": "2026-07-28T15:00:00Z",
            "deployments": [
                {
                    "namespace": "benchmark",
                    "name": "runner",
                    "desired": 2,
                    "ready": 2,
                    "available": 2,
                }
            ],
            "pods": [
                {
                    "namespace": "benchmark",
                    "name": "runner-abc",
                    "phase": "Running",
                    "ready": 1,
                    "containers": 1,
                }
            ],
            "truncated": False,
        }

    evidence = await InventoryChatTools(_provider, workload_provider=workloads).resolve(
        "지금 AKS에 배포되고 있는 게 있어?",
        principal_id="reader",
    )

    assert evidence is not None
    assert evidence["result"]["status"] == "matched"
    assert evidence["result"]["coverage_gap"] is None
    answer = render_inventory_answer(evidence, locale="ko")
    assert answer is not None
    assert "benchmark/runner" in answer
    assert "ready 2/2" in answer
    assert "benchmark/runner-abc" in answer
    assert "Running" in answer
    verification = verify_answer("", {"_tool_evidence": evidence}, locale="ko")
    assert verification.status == "corrected"
    assert verification.answer == answer
    assert inventory_evidence_refs(evidence) == (
        "inventory:azure-resource-graph@2026-07-20T10:00:00Z",
        "kubernetes:kubernetes_apiserver@2026-07-28T15:00:00Z",
    )


async def test_bound_kubernetes_evidence_does_not_cover_other_clusters() -> None:
    async def multiple_clusters(
        scope: str | None,
        depth: int,
        link_types: tuple[str, ...],
        *,
        root: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        graph = await _provider(scope, depth, link_types, root=root, limit=limit)
        graph["resources"].append(
            _resource(
                "aks-other",
                "kubernetes-cluster",
                "aks-other",
                group="rg-other",
                location="koreacentral",
            )
        )
        return graph

    async def workloads() -> dict[str, Any]:
        return {
            "status": "matched",
            "cluster_name": "aks-app",
            "source": "kubernetes_apiserver",
            "observed_at": "2026-07-28T15:00:00Z",
            "deployments": [],
            "pods": [],
            "truncated": False,
        }

    evidence = await InventoryChatTools(
        multiple_clusters,
        workload_provider=workloads,
    ).resolve("AKS에 배포된 앱이 있어?", principal_id="reader")

    assert evidence is not None
    assert evidence["result"]["status"] == "partial"
    assert evidence["result"]["coverage_gap"] == "kubernetes_workloads"
    assert evidence["result"]["uncovered_cluster_count"] == 1
    assert evidence["result"]["workload"]["cluster_name"] == "aks-app"
    answer = render_inventory_answer(evidence, locale="ko")
    assert answer is not None
    assert "aks-app" in answer
    assert "다른 AKS 클러스터 1개" in answer


def test_aks_workload_stream_overrides_semantic_web_plan() -> None:
    class PlanningDelegate:
        calls = 0

        def route_answer_planning(self, _prompt: str):
            self.calls += 1
            raise AssertionError("deterministic AKS evidence must not start answer planning")

    class Planner:
        async def plan_turn(self, **_kwargs: object) -> Any:
            return parse_turn_plan(
                {
                    "kind": "read_tool",
                    "answer_intent": "status",
                    "tool_name": "web_search",
                    "action_type": None,
                    "arguments": {"query": "AKS deployments", "goal": "current_fact"},
                    "clarification": None,
                    "confidence": 0.8,
                }
            )

    class WebResolver:
        async def resolve(self, *_args: object, **_kwargs: object):
            raise AssertionError("local AKS status must not search the public web")

        async def resolve_planned(self, *_args: object, **_kwargs: object):
            raise AssertionError("local AKS status must not search the public web")

    planning = PlanningDelegate()
    app = Starlette(
        routes=[
            make_chat_stream_route(
                backend=RecordingBackend(),
                authorize=_allow,
                tool_resolver=InventoryChatTools(_provider),
                web_search_resolver=WebResolver(),  # type: ignore[arg-type]
                turn_planner=Planner(),  # type: ignore[arg-type]
                answer_planning_delegate=planning,  # type: ignore[arg-type]
            )
        ]
    )

    response = TestClient(app).post(
        "/chat/stream",
        json={
            "prompt": "지금 AKS 에 배포되고 있는게 있어?",
            "view_context": {"routeId": "operating-outcomes"},
        },
    )

    assert response.status_code == 200
    done = _inventory_done_event(response.text)
    assert done is not None
    assert done["verification"]["reason_code"] == "inventory_workload_coverage_gap"
    assert "Deployment와 Pod는 포함하지 않습니다" in done["answer"]
    assert "public_web" not in response.text
    assert planning.calls == 0


@pytest.mark.parametrize(
    ("prompt", "includes_sql"),
    [
        ("중지된 db 도 있어?", False),
        ("DB 는 정상인가? 상태확인해봐", True),
    ],
)
def test_stopped_db_stream_overrides_semantic_web_plan(
    prompt: str,
    includes_sql: bool,
) -> None:
    class Planner:
        async def plan_turn(self, **_kwargs: object) -> Any:
            return parse_turn_plan(
                {
                    "kind": "read_tool",
                    "answer_intent": "status",
                    "tool_name": "web_search",
                    "action_type": None,
                    "arguments": {"query": "stopped databases", "goal": "current_fact"},
                    "clarification": None,
                    "confidence": 0.8,
                }
            )

    class WebResolver:
        async def resolve(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("local database status must not search the public web")

        async def resolve_planned(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("local database status must not search the public web")

    app = Starlette(
        routes=[
            make_chat_stream_route(
                backend=RecordingBackend(),
                authorize=_allow,
                tool_resolver=InventoryChatTools(_provider),
                web_search_resolver=WebResolver(),  # type: ignore[arg-type]
                turn_planner=Planner(),  # type: ignore[arg-type]
            )
        ]
    )

    response = TestClient(app).post(
        "/chat/stream",
        json={
            "prompt": prompt,
            "view_context": {
                "routeId": "agents",
                "facts": [{"key": "status", "value": "in-progress"}],
            },
        },
    )

    assert response.status_code == 200
    done = _inventory_done_event(response.text)
    assert done is not None
    assert done["verification"]["reason_code"] == "inventory_snapshot_grounded"
    assert "postgres-data" in done["answer"]
    assert "stopped" in done["answer"]
    assert ("sql-app" in done["answer"]) is includes_sql
    assert "public_web" not in response.text
    assert '"branch_kind": "agent"' not in response.text
    activity = _stream_event(response.text, "activity")
    assert activity is not None
    assert activity["label"] == "Applied inventory query"
    assert activity["detail"] == ("2 matching resources" if includes_sql else "1 matching resource")
    execution = activity["execution"]
    assert execution["tool"] == "FDAI IQL"
    assert execution["input_kind"] == "query"
    projected = json.loads(execution["command"])
    assert projected["query"]["source"] == "current"
    assert not execution["command"].lstrip().startswith("az ")
    if includes_sql:
        assert "resource_context" not in done
    else:
        assert done["resource_context"] == {
            "name": "postgres-data",
            "resource_type": "postgresql-server",
            "evidence_ref": "inventory:azure-resource-graph@2026-07-20T10:00:00Z",
        }


def test_subscription_stopped_db_ignores_invalid_semantic_lookback_plan() -> None:
    class Planner:
        async def plan_turn(self, **_kwargs: object) -> Any:
            return parse_turn_plan(
                {
                    "kind": "read_tool",
                    "answer_intent": "status",
                    "tool_name": "query_inventory",
                    "action_type": None,
                    "arguments": {
                        "source": "current",
                        "kind": "list",
                        "predicates": [
                            {
                                "field": "status",
                                "operator": "in",
                                "value": ["stopped", "deallocated"],
                            }
                        ],
                        "lookback_seconds": 3_600,
                    },
                    "clarification": None,
                    "confidence": 0.9,
                }
            )

    async def subscription_provider(
        scope: str | None,
        depth: int,
        link_types: tuple[str, ...],
        *,
        root: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        assert root == "azure-subscription"
        assert limit == 1_000
        return await _provider(scope, depth, link_types)

    async def health_provider(
        lookback_seconds: int,
        *,
        progress_observer: Any = None,
    ) -> dict[str, Any]:
        del lookback_seconds, progress_observer
        raise AssertionError("specific inventory request must not use subscription health")

    backend = RecordingBackend()
    tools = InventoryChatTools(subscription_provider)
    app = Starlette(
        routes=[
            make_chat_stream_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=SubscriptionHealthChatTools(health_provider, fallback=tools),
                planned_tool_resolver=tools,
                turn_planner=Planner(),  # type: ignore[arg-type]
                turn_tools=tools.turn_tools(),
            )
        ]
    )

    response = TestClient(app).post(
        "/chat/stream",
        json={
            "prompt": "지금 구독에서 중지된 디비가 있는지 확인해봐",
            "view_context": {
                "routeId": "agents",
                "facts": [{"key": "status", "value": "in-progress"}],
            },
        },
    )

    assert response.status_code == 200
    done = _inventory_done_event(response.text)
    assert done is not None
    assert done["verification"]["reason_code"] == "inventory_snapshot_grounded"
    assert "postgres-data" in done["answer"]
    assert "stopped" in done["answer"]
    assert "sql-app" not in done["answer"]
    assert '"branch_kind": "agent"' not in response.text
    assert '"branch_kind": "public_web"' not in response.text
    assert "event: activity" in response.text
    activity = _stream_event(response.text, "activity")
    assert activity is not None
    execution = activity["execution"]
    assert execution["tool"] == "FDAI IQL"
    assert execution["input_kind"] == "query"
    assert json.loads(execution["command"])["query"]["source"] == "current"
    assert "query_inventory --scope" not in response.text
    assert '"redacted": true' in response.text
    activity = _stream_event(response.text, "activity")
    assert activity is not None
    execution = activity["execution"]
    assert isinstance(execution, dict)
    output = json.loads(execution["output"])
    assert output["matched_count"] == 1
    assert output["status"] == "matched"
    assert output["total_resources"] == 13
    assert any(resource.get("name") == "postgres-data" for resource in output["resources"])
    assert all("id" not in resource for resource in output["resources"])
    assert backend.calls == 0


def test_semantic_inventory_plan_executes_verified_long_tail_predicate() -> None:
    class Planner:
        async def plan_turn(self, **_kwargs: object) -> Any:
            return parse_turn_plan(
                {
                    "kind": "read_tool",
                    "answer_intent": "status",
                    "tool_name": "query_inventory",
                    "action_type": None,
                    "arguments": {
                        "source": "current",
                        "kind": "list",
                        "predicates": [{"field": "status", "operator": "eq", "value": "stopped"}],
                        "lookback_seconds": None,
                    },
                    "clarification": None,
                    "confidence": 0.9,
                }
            )

    tools = InventoryChatTools(_provider)
    app = Starlette(
        routes=[
            make_chat_route(
                backend=RecordingBackend(),
                authorize=_allow,
                tool_resolver=tools,
                planned_tool_resolver=tools,
                turn_planner=Planner(),  # type: ignore[arg-type]
                turn_tools=tools.turn_tools(),
            )
        ]
    )

    response = TestClient(app).post(
        "/chat",
        json={"prompt": "Which Azure assets are dormant?", "view_context": {}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "vm-job" in payload["answer"]
    assert "postgres-data" in payload["answer"]
    assert "vm-app" not in payload["answer"]
    assert payload["verification"]["reason_code"] == "inventory_snapshot_grounded"


def test_deterministic_inventory_filter_precedes_semantic_inventory_plan() -> None:
    class Planner:
        async def plan_turn(self, **_kwargs: object) -> Any:
            return parse_turn_plan(
                {
                    "kind": "read_tool",
                    "answer_intent": "status",
                    "tool_name": "query_inventory",
                    "action_type": None,
                    "arguments": {
                        "source": "current",
                        "kind": "list",
                        "predicates": [],
                        "lookback_seconds": None,
                    },
                    "clarification": None,
                    "confidence": 0.9,
                }
            )

    tools = InventoryChatTools(_provider)
    app = Starlette(
        routes=[
            make_chat_route(
                backend=RecordingBackend(),
                authorize=_allow,
                tool_resolver=tools,
                planned_tool_resolver=tools,
                turn_planner=Planner(),  # type: ignore[arg-type]
                turn_tools=tools.turn_tools(),
            )
        ]
    )

    response = TestClient(app).post(
        "/chat",
        json={"prompt": "중지된 VM은?", "view_context": {}},
    )

    payload = response.json()
    assert "vm-job" in payload["answer"]
    assert "vm-app" not in payload["answer"]
    assert payload["verification"]["authority"] == "server_inventory_graph"


@pytest.mark.parametrize(
    "prompt",
    (
        "지금 켜져있는 vm 목록",
        "현재 켜져 있는 VM만 알려줘",
        "전원이 들어와 있는 가상 머신은?",
        "가동 중인 VM 보여줘",
        "VM 중에 지금 돌아가는 것만 알려줘",
    ),
)
def test_semantic_status_hint_completes_unknown_korean_inventory_inflection(
    prompt: str,
) -> None:
    class Planner:
        async def plan_turn(self, **_kwargs: object) -> Any:
            return parse_turn_plan(
                {
                    "kind": "read_tool",
                    "answer_intent": "list",
                    "tool_name": "query_inventory",
                    "action_type": None,
                    "arguments": {
                        "source": "current",
                        "kind": "list",
                        "predicates": [
                            {"field": "resource_type", "operator": "eq", "value": "vm"},
                            {"field": "status", "operator": "eq", "value": "running"},
                        ],
                        "lookback_seconds": 3_600,
                    },
                    "clarification": None,
                    "confidence": 0.99,
                }
            )

    backend = RecordingBackend()
    tools = InventoryChatTools(_provider)
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=tools,
                planned_tool_resolver=tools,
                turn_planner=Planner(),  # type: ignore[arg-type]
                turn_tools=tools.turn_tools(),
            )
        ]
    )

    response = TestClient(app).post(
        "/chat",
        json={"prompt": prompt, "view_context": {}},
    )

    payload = response.json()
    assert "vm-app" in payload["answer"]
    assert "vm-job" not in payload["answer"]
    assert payload["verification"]["authority"] == "server_inventory_graph"
    assert backend.calls == 0


def test_intent_graph_status_hint_completes_unknown_korean_inventory_inflection() -> None:
    class Planner:
        async def plan_turn(self, **_kwargs: object) -> IntentGraph:
            return IntentGraph(
                schema_version=2,
                goals=(
                    IntentGoal(
                        goal_id="running_vms",
                        intent=AnswerIntent.LIST,
                        capability="query_inventory",
                        arguments={
                            "source": "current",
                            "kind": "list",
                            "predicates": [
                                {"field": "resource_type", "operator": "eq", "value": "vm"},
                                {"field": "status", "operator": "eq", "value": "running"},
                            ],
                            "lookback_seconds": 3_600,
                        },
                        depends_on=(),
                        evidence_mode=EvidenceMode.OPERATIONAL,
                        freshness_required=True,
                        confidence=0.99,
                        alternatives=(),
                        side_effect_class="read",
                    ),
                ),
                clarification=None,
                confidence=0.99,
                action_posture=ActionPosture.ADVISE_ONLY,
            )

    tools = InventoryChatTools(_provider)
    payload = (
        TestClient(
            Starlette(
                routes=[
                    make_chat_route(
                        backend=RecordingBackend(),
                        authorize=_allow,
                        tool_resolver=tools,
                        planned_tool_resolver=tools,
                        turn_planner=Planner(),  # type: ignore[arg-type]
                        turn_tools=tools.turn_tools(),
                    )
                ]
            )
        )
        .post(
            "/chat",
            json={"prompt": "지금 켜져있는 vm 목록", "view_context": {}},
        )
        .json()
    )

    assert payload["verification"]["status"] == "verified"
    assert "vm-app" in payload["answer"]
    assert "vm-job" not in payload["answer"]


def test_noncanonical_semantic_inventory_status_fails_closed() -> None:
    # Deliberately whimsical slang that the deterministic catalog does NOT
    # (and should never trivially) recognize as a canonical state, so the
    # planner's non-canonical "alive" guess is the only status signal and
    # must fail closed. If a future catalog addition starts recognizing this
    # phrase, swap in a different unrecognized phrase rather than loosening
    # the assertion below - this test exists to prove the fail-closed
    # contract, not to pin one specific sentence.
    prompt = "VM 중에 요즘 팔팔한 애들만 알려줘"
    assert inventory_query_status_groups(prompt) == ()

    class Planner:
        async def plan_turn(self, **_kwargs: object) -> Any:
            return parse_turn_plan(
                {
                    "kind": "read_tool",
                    "answer_intent": "list",
                    "tool_name": "query_inventory",
                    "action_type": None,
                    "arguments": {
                        "source": "current",
                        "kind": "list",
                        "predicates": [{"field": "status", "operator": "eq", "value": "alive"}],
                        "lookback_seconds": None,
                    },
                    "clarification": None,
                    "confidence": 0.99,
                }
            )

    tools = InventoryChatTools(_provider)
    app = Starlette(
        routes=[
            make_chat_route(
                backend=RecordingBackend(),
                authorize=_allow,
                tool_resolver=tools,
                planned_tool_resolver=tools,
                turn_planner=Planner(),  # type: ignore[arg-type]
                turn_tools=tools.turn_tools(),
            )
        ]
    )

    payload = (
        TestClient(app)
        .post(
            "/chat",
            json={"prompt": prompt, "view_context": {}},
        )
        .json()
    )

    assert payload["verification"]["status"] == "unverified"
    assert "vm-app" not in payload["answer"]
    assert "vm-job" not in payload["answer"]


def test_semantic_plan_without_status_preserves_unfiltered_inventory() -> None:
    class Planner:
        async def plan_turn(self, **_kwargs: object) -> Any:
            return parse_turn_plan(
                {
                    "kind": "read_tool",
                    "answer_intent": "list",
                    "tool_name": "query_inventory",
                    "action_type": None,
                    "arguments": {
                        "source": "current",
                        "kind": "list",
                        "predicates": [{"field": "resource_type", "operator": "eq", "value": "vm"}],
                        "lookback_seconds": 3_600,
                    },
                    "clarification": None,
                    "confidence": 0.99,
                }
            )

    tools = InventoryChatTools(_provider)
    app = Starlette(
        routes=[
            make_chat_route(
                backend=RecordingBackend(),
                authorize=_allow,
                tool_resolver=tools,
                planned_tool_resolver=tools,
                turn_planner=Planner(),  # type: ignore[arg-type]
                turn_tools=tools.turn_tools(),
            )
        ]
    )

    payload = (
        TestClient(app)
        .post(
            "/chat",
            json={"prompt": "VM 목록 알려줘", "view_context": {}},
        )
        .json()
    )

    assert payload["verification"]["status"] == "verified"
    assert "vm-app" in payload["answer"]
    assert "vm-job" in payload["answer"]


@pytest.mark.parametrize("stream", [False, True])
def test_complete_resource_group_table_skips_semantic_planner(stream: bool) -> None:
    class Planner:
        async def plan_turn(self, **_kwargs: object) -> Any:
            raise AssertionError("complete inventory query must not invoke semantic planning")

    tools = InventoryChatTools(_provider)
    route = (
        make_chat_stream_route(
            backend=RecordingBackend(),
            authorize=_allow,
            tool_resolver=tools,
            planned_tool_resolver=tools,
            turn_planner=Planner(),  # type: ignore[arg-type]
            turn_tools=tools.turn_tools(),
        )
        if stream
        else make_chat_route(
            backend=RecordingBackend(),
            authorize=_allow,
            tool_resolver=tools,
            planned_tool_resolver=tools,
            turn_planner=Planner(),  # type: ignore[arg-type]
            turn_tools=tools.turn_tools(),
        )
    )
    response = TestClient(Starlette(routes=[route])).post(
        "/chat/stream" if stream else "/chat",
        json={"prompt": "현재 우리구독의 리소스그룹을 표로 보여줘", "view_context": {}},
    )

    assert response.status_code == 200
    payload = _inventory_done_event(response.text) if stream else response.json()
    assert payload is not None
    assert "| 리소스 그룹 | 위치 | 상태 |" in payload["answer"]
    assert payload["verification"]["authority"] == "server_inventory_graph"


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "prompt",
    (
        "현재 관리 범위의 리소스를 이름, 유형, 상태와 함께 보여줘.",
        "Show resources in managed scope with their current state.",
    ),
)
def test_managed_scope_inventory_skips_semantic_planner(stream: bool, prompt: str) -> None:
    class Planner:
        async def plan_turn(self, **_kwargs: object) -> Any:
            raise AssertionError("complete managed-scope query must not invoke semantic planning")

    tools = InventoryChatTools(_provider)
    route = (
        make_chat_stream_route(
            backend=RecordingBackend(),
            authorize=_allow,
            tool_resolver=tools,
            planned_tool_resolver=tools,
            turn_planner=Planner(),  # type: ignore[arg-type]
            turn_tools=tools.turn_tools(),
        )
        if stream
        else make_chat_route(
            backend=RecordingBackend(),
            authorize=_allow,
            tool_resolver=tools,
            planned_tool_resolver=tools,
            turn_planner=Planner(),  # type: ignore[arg-type]
            turn_tools=tools.turn_tools(),
        )
    )

    response = TestClient(Starlette(routes=[route])).post(
        "/chat/stream" if stream else "/chat",
        json={"prompt": prompt, "view_context": {}},
    )

    assert response.status_code == 200
    payload = _inventory_done_event(response.text) if stream else response.json()
    assert payload is not None
    assert payload["verification"]["authority"] == "server_inventory_graph"
    assert payload["verification"]["reason_code"] == "inventory_snapshot_grounded"
    result_context = payload["resource_result_context"]
    assert result_context["schema_version"] == 1
    assert result_context["freshness"] == "fresh"
    assert len(result_context["resources"]) >= 2
    assert all("id" not in resource for resource in result_context["resources"])


def test_resource_followup_reuses_verified_selector_without_planner_or_web() -> None:
    delegated: list[str] = []

    class Planner:
        async def plan_turn(self, **_kwargs: object) -> Any:
            raise AssertionError("contextual resource follow-up must not invoke semantic planning")

    class AgentDelegate:
        async def delegate(self, *, prompt: str, user_id: str, session_id: str):
            del user_id, session_id
            delegated.append(prompt)
            return {
                "primary_agent": "Heimdall",
                "answer": "postgres-data의 최근 성공한 중지 작업은 확인된 시각부터 이어졌습니다.",
                "facts": {
                    "status": "matched",
                    "resource_name": "postgres-data",
                    "evidence_refs": ["azure-activity:sha256:test"],
                },
                "contributors": [],
                "contributor_answers": [],
                "trace_ref": "read-investigation",
            }

    class WebResolver:
        async def resolve(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("contextual resource follow-up must not search the public web")

        async def resolve_planned(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("contextual resource follow-up must not search the public web")

    backend = RecordingBackend()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                agent_delegate=AgentDelegate(),  # type: ignore[arg-type]
                web_search_resolver=WebResolver(),  # type: ignore[arg-type]
                turn_planner=Planner(),  # type: ignore[arg-type]
            )
        ]
    )

    response = TestClient(app).post(
        "/chat",
        json={
            "prompt": "언제부터 중지되어 있었어?",
            "session_id": "session-db",
            "resource_context": {
                "name": "postgres-data",
                "resource_type": "postgresql-server",
                "evidence_ref": "inventory:azure-resource-graph@2026-07-20T10:00:00Z",
            },
            "view_context": {},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert delegated == ["postgres-data 변경 이력: 언제부터 중지되어 있었어?"]
    assert payload["resource_context"]["name"] == "postgres-data"
    assert "postgres-data" in payload["answer"]
    assert payload["verification"]["status"] == "verified"
    assert payload["verification"]["authority"] == "server_read_investigation"
    assert payload["verification"]["reason_code"] == "resource_history_grounded"
    assert backend.calls == 0


def test_resource_followup_stream_returns_matching_heimdall_evidence_directly() -> None:
    delegated: list[str] = []

    class AgentDelegate:
        async def delegate(self, *, prompt: str, user_id: str, session_id: str):
            del user_id, session_id
            delegated.append(prompt)
            return {
                "primary_agent": "Heimdall",
                "answer": "postgres-data의 최근 성공한 중지 작업은 확인된 시각부터 이어졌습니다.",
                "facts": {
                    "status": "matched",
                    "resource_name": "postgres-data",
                    "evidence_refs": ["azure-activity:sha256:test"],
                },
                "contributors": [],
                "contributor_answers": [],
                "trace_ref": "read-investigation",
            }

    backend = RecordingBackend()
    app = Starlette(
        routes=[
            make_chat_stream_route(
                backend=backend,
                authorize=_allow,
                agent_delegate=AgentDelegate(),  # type: ignore[arg-type]
            )
        ]
    )

    response = TestClient(app).post(
        "/chat/stream",
        json={
            "prompt": "언제부터 중지되어 있었어?",
            "session_id": "session-db",
            "resource_context": {
                "name": "postgres-data",
                "resource_type": "postgresql-server",
                "evidence_ref": "inventory:azure-resource-graph@2026-07-20T10:00:00Z",
            },
            "view_context": {},
        },
    )

    assert response.status_code == 200
    done = _inventory_done_event(response.text)
    assert done is not None
    assert delegated == ["postgres-data 변경 이력: 언제부터 중지되어 있었어?"]
    assert done["model"] == "heimdall-read-investigation"
    assert done["source"] == "evidence:read-investigation"
    assert done["resource_context"]["name"] == "postgres-data"
    assert "postgres-data" in done["answer"]
    assert done["verification"]["status"] == "verified"
    assert done["verification"]["authority"] == "server_read_investigation"
    assert done["verification"]["reason_code"] == "resource_history_grounded"
    assert backend.calls == 0


def test_resource_followup_stream_returns_missing_anchor_without_narrator() -> None:
    delegated: list[str] = []

    class AgentDelegate:
        async def delegate(self, *, prompt: str, user_id: str, session_id: str):
            del user_id, session_id
            delegated.append(prompt)
            return {
                "primary_agent": "Heimdall",
                "answer": (
                    "Azure Activity Log 근거를 사용할 수 없어 장애 직전 변경을 확정하지 않았습니다."
                ),
                "facts": {
                    "status": "unavailable",
                    "intent": "pre_incident_changes",
                    "resource_name": "postgres-data",
                    "reason": "incident_anchor_unavailable",
                    "evidence_refs": [],
                },
                "contributors": [],
                "contributor_answers": [],
                "trace_ref": "read-investigation",
            }

    backend = RecordingBackend()
    app = Starlette(
        routes=[
            make_chat_stream_route(
                backend=backend,
                authorize=_allow,
                agent_delegate=AgentDelegate(),  # type: ignore[arg-type]
            )
        ]
    )

    response = TestClient(app).post(
        "/chat/stream",
        json={
            "prompt": "장애 직전에 발생한 배포와 설정 변경을 찾아줘.",
            "session_id": "session-db",
            "resource_context": {
                "name": "postgres-data",
                "resource_type": "postgresql-server",
                "evidence_ref": "subscription-health:resource-health@2026-08-01T02:05:00Z",
            },
            "view_context": {},
        },
    )

    assert response.status_code == 200
    done = _inventory_done_event(response.text)
    assert done is not None
    assert delegated == [
        "postgres-data change history: pre-incident activity anchor=unavailable locale=ko"
    ]
    assert done["model"] == "heimdall-read-investigation"
    assert done["source"] == "evidence:read-investigation"
    assert done["verification"]["status"] == "unverified"
    assert done["verification"]["reason_code"] == "incident_anchor_unavailable"
    assert backend.calls == 0


@pytest.mark.parametrize(
    "prompt",
    (
        "누가 이 리소스를 중지했어?",
        "이 리소스를 중지한 주체와 작업 시각을 알려줘.",
        "Who stopped this resource?",
        "이거 누가 껐어?",
    ),
)
def test_resource_attribution_unavailable_is_exclusive_and_terminal(prompt: str) -> None:
    delegated: list[str] = []

    class ToolResolver:
        async def resolve(self, prompt: str, *, principal_id: str) -> None:
            del prompt, principal_id
            raise AssertionError("resource follow-up must not run an inventory tool")

    class OperationalResolver:
        async def resolve(
            self,
            prompt: str,
            *,
            conversation_context: dict[str, str] | None = None,
        ) -> None:
            del prompt, conversation_context
            raise AssertionError("resource follow-up must not run operational lookup")

    class WebResolver:
        async def resolve(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("resource follow-up must not search public web")

        async def resolve_planned(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("resource follow-up must not use a web plan")

    class AgentDelegate:
        async def delegate(
            self,
            *,
            prompt: str,
            user_id: str,
            session_id: str,
        ) -> dict[str, Any]:
            del user_id, session_id
            delegated.append(prompt)
            return {
                "primary_agent": "Heimdall",
                "answer": "The selected resource is unavailable in the configured read scope.",
                "facts": {
                    "status": "none",
                    "intent": "change_attribution",
                    "resource_name": "postgres-data",
                    "reason": "resource_not_found",
                    "evidence_refs": [],
                },
                "contributors": [],
                "contributor_answers": [],
                "trace_ref": "read-investigation",
            }

    backend = RecordingBackend()
    agent = AgentDelegate()
    routes = [
        make_chat_route(
            backend=backend,
            authorize=_allow,
            tool_resolver=ToolResolver(),  # type: ignore[arg-type]
            evidence_resolver=OperationalResolver(),  # type: ignore[arg-type]
            agent_delegate=agent,  # type: ignore[arg-type]
            web_search_resolver=WebResolver(),  # type: ignore[arg-type]
        ),
        make_chat_stream_route(
            backend=backend,
            authorize=_allow,
            tool_resolver=ToolResolver(),  # type: ignore[arg-type]
            evidence_resolver=OperationalResolver(),  # type: ignore[arg-type]
            agent_delegate=agent,  # type: ignore[arg-type]
            web_search_resolver=WebResolver(),  # type: ignore[arg-type]
        ),
    ]
    body = {
        "prompt": prompt,
        "resource_context": {
            "name": "postgres-data",
            "resource_type": "postgresql-server",
            "evidence_ref": "subscription-health:resource-health@2026-08-02T08:00:00Z",
        },
        "view_context": {},
    }

    with TestClient(Starlette(routes=routes)) as client:
        response = client.post("/chat", json=body)
        stream = client.post("/chat/stream", json=body)

    payload = response.json()
    done = _inventory_done_event(stream.text)
    assert response.status_code == 200
    assert done is not None
    assert payload["answer"] == "The selected resource is unavailable in the configured read scope."
    assert done["answer"] == payload["answer"]
    assert payload["verification"]["status"] == "unverified"
    assert payload["verification"]["authority"] == "server_read_investigation"
    assert payload["verification"]["reason_code"] == "resource_history_unavailable"
    assert done["verification"] == payload["verification"]
    assert len(delegated) == 2
    assert backend.calls == 0


@pytest.mark.parametrize(
    "prompt",
    (
        "운영 체제가 내부에서 종료된 흔적이 있어?",
        "Was the shutdown initiated inside the guest operating system?",
        "이 리소스의 게스트 OS에서 종료 이벤트가 발생했는지 확인해줘.",
        "Did the guest OS shut this resource down?",
        "이거 OS 안에서 꺼진 거야?",
    ),
)
def test_guest_shutdown_followup_uses_resource_context_exclusively(prompt: str) -> None:
    delegated: list[str] = []

    class Planner:
        async def plan_turn(self, **_kwargs: object) -> Any:
            raise AssertionError("guest shutdown follow-up must not invoke semantic planning")

    class ToolResolver:
        async def resolve(self, prompt: str, *, principal_id: str) -> None:
            del prompt, principal_id
            raise AssertionError("guest shutdown follow-up must not run an inventory tool")

    class OperationalResolver:
        async def resolve(
            self,
            prompt: str,
            *,
            conversation_context: dict[str, str] | None = None,
        ) -> None:
            del prompt, conversation_context
            raise AssertionError("guest shutdown follow-up must not run operational lookup")

    class WebResolver:
        async def resolve(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("guest shutdown follow-up must not search public web")

        async def resolve_planned(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("guest shutdown follow-up must not use a web plan")

    class AgentDelegate:
        async def delegate(
            self,
            *,
            prompt: str,
            user_id: str,
            session_id: str,
        ) -> dict[str, Any]:
            del user_id, session_id
            delegated.append(prompt)
            return {
                "primary_agent": "Heimdall",
                "answer": "Guest shutdown requires a durable task, but no submitter is configured.",
                "facts": {
                    "status": "handoff_required",
                    "mode": "detached",
                    "intent": "guest_shutdown",
                    "resource_name": "vm-primary",
                    "estimated_upper_ms": 45_000,
                },
                "contributors": [],
                "contributor_answers": [],
                "trace_ref": "read-investigation",
            }

    backend = RecordingBackend()
    agent = AgentDelegate()
    routes = [
        make_chat_route(
            backend=backend,
            authorize=_allow,
            tool_resolver=ToolResolver(),  # type: ignore[arg-type]
            evidence_resolver=OperationalResolver(),  # type: ignore[arg-type]
            agent_delegate=agent,  # type: ignore[arg-type]
            web_search_resolver=WebResolver(),  # type: ignore[arg-type]
            turn_planner=Planner(),  # type: ignore[arg-type]
        ),
        make_chat_stream_route(
            backend=backend,
            authorize=_allow,
            tool_resolver=ToolResolver(),  # type: ignore[arg-type]
            evidence_resolver=OperationalResolver(),  # type: ignore[arg-type]
            agent_delegate=agent,  # type: ignore[arg-type]
            web_search_resolver=WebResolver(),  # type: ignore[arg-type]
            turn_planner=Planner(),  # type: ignore[arg-type]
        ),
    ]
    body = {
        "prompt": prompt,
        "resource_context": {
            "name": "vm-primary",
            "resource_type": "microsoft.compute.virtualmachines",
            "evidence_ref": "subscription-health:resource-health@2026-08-02T08:00:00Z",
        },
        "view_context": {},
    }

    with TestClient(Starlette(routes=routes)) as client:
        response = client.post("/chat", json=body)
        stream = client.post("/chat/stream", json=body)

    payload = response.json()
    done = _inventory_done_event(stream.text)
    assert response.status_code == 200
    assert done is not None
    assert payload["answer"] == (
        "Guest shutdown requires a durable task, but no submitter is configured."
    )
    assert done["answer"] == payload["answer"]
    assert payload["verification"]["status"] == "unverified"
    assert payload["verification"]["authority"] == "server_read_investigation"
    assert payload["verification"]["reason_code"] == "background_task_unavailable"
    assert done["verification"] == payload["verification"]
    assert all(item.startswith("vm-primary guest shutdown: ") for item in delegated)
    assert len(delegated) == 2
    assert backend.calls == 0


@pytest.mark.parametrize(
    "prompt",
    (
        "누가 이 리소스를 중지했어?",
        "이 리소스의 중지 작업을 시작한 주체는 누구야?",
        "누가 또는 어떤 자동화가 이 리소스를 멈췄는지 알려줘.",
        "Who changed this resource most recently, and what did they do?",
        "Identify the latest actor who changed this resource and the operation performed.",
        "What was the most recent change to this resource, and who initiated it?",
        "장애 직전에 발생한 배포와 설정 변경을 찾아줘.",
        "인시던트 바로 전에 있었던 배포 또는 구성 변경을 보여줘.",
        "장애 발생 전의 최근 배포와 설정 변경 이력을 찾아줘.",
        "Build a change timeline for the hour before the incident.",
        "Show an ordered timeline of changes during the hour preceding the incident.",
        "List deployments and configuration changes from the 60 minutes before the incident.",
        "운영 체제가 내부에서 종료된 흔적이 있어?",
        "게스트 OS 안에서 종료가 시작됐다는 근거가 있나?",
        "이 리소스가 운영 체제 내부 명령으로 종료됐는지 확인해줘.",
        "Was the shutdown initiated inside the guest operating system?",
        "Is there evidence that the guest OS initiated the shutdown?",
        "Determine whether the shutdown came from inside the virtual machine.",
        "왜 이 리소스 상태를 읽을 수 없어?",
        "이 리소스 상태 조회가 불가능한 이유를 알려줘.",
        "권한, 범위, 원본 중 무엇 때문에 상태를 읽지 못했어?",
    ),
)
def test_resource_investigation_cohort_requires_exact_selector(prompt: str) -> None:
    class Planner:
        async def plan_turn(self, **_kwargs: object) -> Any:
            raise AssertionError("selector hold must skip semantic planning")

    class ToolResolver:
        async def resolve(self, prompt: str, *, principal_id: str) -> None:
            del prompt, principal_id
            raise AssertionError("selector hold must skip tool resolution")

    class OperationalResolver:
        async def resolve(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("selector hold must skip operational evidence")

    class AgentDelegate:
        async def delegate(self, **_kwargs: object) -> None:
            raise AssertionError("selector hold must skip agent evidence")

    backend = RecordingBackend()
    routes = [
        make_chat_route(
            backend=backend,
            authorize=_allow,
            tool_resolver=ToolResolver(),  # type: ignore[arg-type]
            evidence_resolver=OperationalResolver(),  # type: ignore[arg-type]
            agent_delegate=AgentDelegate(),  # type: ignore[arg-type]
            turn_planner=Planner(),  # type: ignore[arg-type]
        ),
        make_chat_stream_route(
            backend=backend,
            authorize=_allow,
            tool_resolver=ToolResolver(),  # type: ignore[arg-type]
            evidence_resolver=OperationalResolver(),  # type: ignore[arg-type]
            agent_delegate=AgentDelegate(),  # type: ignore[arg-type]
            turn_planner=Planner(),  # type: ignore[arg-type]
        ),
    ]

    with TestClient(Starlette(routes=routes)) as client:
        response = client.post("/chat", json={"prompt": prompt, "view_context": {}})
        stream = client.post("/chat/stream", json={"prompt": prompt, "view_context": {}})

    payload = response.json()
    done = _inventory_done_event(stream.text)
    assert done is not None
    assert payload["verification"]["authority"] == "server_conversation_context"
    assert payload["verification"]["reason_code"] == "prior_context_required"
    assert done["verification"] == payload["verification"]
    assert backend.calls == 0


def test_resource_followup_accepts_bounded_queued_handoff() -> None:
    verification = resource_followup_verification(
        {
            "_agent_evidence": {
                "primary_agent": "Heimdall",
                "answer": "The investigation was queued.",
                "facts": {
                    "status": "queued",
                    "resource_name": "vm-primary",
                    "task_id": "task-guest-shutdown",
                    "message_id": "read-message:sha256:guest-shutdown-test",
                },
            }
        },
        {
            "name": "vm-primary",
            "resource_type": "microsoft.compute.virtualmachines",
            "evidence_ref": "subscription-health:resource-health@2026-08-02T08:00:00Z",
        },
    )

    assert verification is not None
    assert verification.status == "unverified"
    assert verification.reason_code == "background_task_queued"


@pytest.mark.parametrize(
    "prompt",
    (
        "왜 이 리소스 상태를 읽을 수 없어?",
        "이 리소스의 읽기 권한이나 범위 제한을 설명해줘.",
        "Why is this health evidence unavailable?",
        "뭐가 권한 때문에 막힌 거야?",
    ),
)
def test_read_availability_followup_uses_resource_context_exclusively(prompt: str) -> None:
    delegated: list[str] = []

    class Planner:
        async def plan_turn(self, **_kwargs: object) -> Any:
            raise AssertionError("read availability follow-up must not invoke semantic planning")

    class ToolResolver:
        async def resolve(self, prompt: str, *, principal_id: str) -> None:
            del prompt, principal_id
            raise AssertionError("read availability follow-up must not run an inventory tool")

    class OperationalResolver:
        async def resolve(
            self,
            prompt: str,
            *,
            conversation_context: dict[str, str] | None = None,
        ) -> None:
            del prompt, conversation_context
            raise AssertionError("read availability follow-up must not run operational lookup")

    class WebResolver:
        async def resolve(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("read availability follow-up must not search public web")

        async def resolve_planned(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("read availability follow-up must not use a web plan")

    class AgentDelegate:
        async def delegate(
            self,
            *,
            prompt: str,
            user_id: str,
            session_id: str,
        ) -> dict[str, Any]:
            del user_id, session_id
            delegated.append(prompt)
            return {
                "primary_agent": "Heimdall",
                "answer": (
                    "The state read was unavailable; scope and authorization remain distinct."
                ),
                "facts": {
                    "status": "unavailable",
                    "intent": "resource_state",
                    "resource_name": "vm-primary",
                    "read_availability_explanation": True,
                    "evidence_sources": ["azure.resource_state"],
                    "evidence_refs": [],
                },
                "contributors": [],
                "contributor_answers": [],
                "trace_ref": "read-investigation",
            }

    backend = RecordingBackend()
    agent = AgentDelegate()
    routes = [
        make_chat_route(
            backend=backend,
            authorize=_allow,
            tool_resolver=ToolResolver(),  # type: ignore[arg-type]
            evidence_resolver=OperationalResolver(),  # type: ignore[arg-type]
            agent_delegate=agent,  # type: ignore[arg-type]
            web_search_resolver=WebResolver(),  # type: ignore[arg-type]
            turn_planner=Planner(),  # type: ignore[arg-type]
        ),
        make_chat_stream_route(
            backend=backend,
            authorize=_allow,
            tool_resolver=ToolResolver(),  # type: ignore[arg-type]
            evidence_resolver=OperationalResolver(),  # type: ignore[arg-type]
            agent_delegate=agent,  # type: ignore[arg-type]
            web_search_resolver=WebResolver(),  # type: ignore[arg-type]
            turn_planner=Planner(),  # type: ignore[arg-type]
        ),
    ]
    body = {
        "prompt": prompt,
        "resource_context": {
            "name": "vm-primary",
            "resource_type": "microsoft.compute.virtualmachines",
            "evidence_ref": "subscription-health:resource-health@2026-08-02T08:00:00Z",
        },
        "view_context": {},
    }

    with TestClient(Starlette(routes=routes)) as client:
        response = client.post("/chat", json=body)
        stream = client.post("/chat/stream", json=body)

    payload = response.json()
    done = _inventory_done_event(stream.text)
    assert response.status_code == 200
    assert done is not None
    assert payload["answer"] == (
        "The state read was unavailable; scope and authorization remain distinct."
    )
    assert done["answer"] == payload["answer"]
    assert payload["verification"]["status"] == "unverified"
    assert payload["verification"]["authority"] == "server_read_investigation"
    assert payload["verification"]["reason_code"] == "read_authority_unavailable"
    assert done["verification"] == payload["verification"]
    assert all(
        item.startswith("vm-primary current state: explain read availability") for item in delegated
    )
    assert len(delegated) == 2
    assert backend.calls == 0


def test_resource_followup_does_not_trust_mismatched_agent_evidence() -> None:
    answer = resource_followup_answer(
        {
            "_agent_evidence": {
                "primary_agent": "Heimdall",
                "answer": "Evidence for another resource.",
                "facts": {"resource_name": "db-other"},
            }
        },
        {
            "name": "db-current",
            "resource_type": "postgresql-server",
            "evidence_ref": "inventory:azure-resource-graph@2026-07-20T10:00:00Z",
        },
    )

    assert answer is None


def test_resource_followup_rejects_non_inventory_context() -> None:
    app = Starlette(routes=[make_chat_route(backend=RecordingBackend(), authorize=_allow)])

    response = TestClient(app).post(
        "/chat",
        json={
            "prompt": "언제부터 중지되어 있었어?",
            "resource_context": {
                "name": "db-current",
                "resource_type": "postgresql-server",
                "evidence_ref": "client-asserted:db-current",
            },
            "view_context": {},
        },
    )

    assert response.status_code == 400
    assert response.text == "resource_context.evidence_ref MUST be an inventory reference"


def test_twenty_inventory_weaknesses_pass_twenty_answer_rubrics() -> None:
    backend = RecordingBackend()
    tools = InventoryChatTools(_provider)
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                behavior_resolver=RepositoryBehaviorEvidenceResolver(REPO_ROOT),
                tool_resolver=tools,
            ),
            make_chat_stream_route(
                backend=backend,
                authorize=_allow,
                behavior_resolver=RepositoryBehaviorEvidenceResolver(REPO_ROOT),
                tool_resolver=tools,
            ),
        ]
    )
    failures: list[str] = []
    passed = 0
    total = len(INVENTORY_WEAKNESS_CASES) * len(INVENTORY_RUBRIC_NAMES)

    with TestClient(app) as client:
        for case_number, case in enumerate(INVENTORY_WEAKNESS_CASES, 1):
            calls_before = backend.calls
            response = client.post(
                "/chat",
                json={"prompt": case.prompt, "view_context": {}},
            )
            payload = response.json()
            done = None
            if case.expects_inventory:
                stream_response = client.post(
                    "/chat/stream",
                    json={"prompt": case.prompt, "view_context": {}},
                )
                done = _inventory_done_event(stream_response.text)
            results = _score_inventory_answer(
                case,
                status_code=response.status_code,
                payload=payload,
                stream_done=done,
                model_calls=backend.calls - calls_before,
            )
            assert len(results) == len(INVENTORY_RUBRIC_NAMES)
            for rubric, result in zip(INVENTORY_RUBRIC_NAMES, results, strict=True):
                if result:
                    passed += 1
                else:
                    failures.append(f"Q{case_number:02d} {rubric}: {case.prompt}")

    assert not failures, f"inventory rubric score {passed}/{total}\n" + "\n".join(failures)


def test_generalized_resource_conditions_stay_deterministic_and_local() -> None:
    async def provider(
        scope: str | None,
        depth: int,
        link_types: tuple[str, ...],
        *,
        root: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        graph = await _provider(scope, depth, link_types, root=root, limit=limit)
        return {
            **graph,
            "resources": [
                {
                    **resource,
                    "status": (
                        "VM deallocated" if resource["name"] == "vm-job" else resource["status"]
                    ),
                }
                for resource in graph["resources"]
            ],
        }

    backend = RecordingBackend()
    app = Starlette(
        routes=[
            make_chat_route(
                backend=backend,
                authorize=_allow,
                tool_resolver=InventoryChatTools(provider),
            )
        ]
    )

    with TestClient(app) as client:
        for case in GENERALIZED_RESOURCE_CASES:
            calls_before = backend.calls
            response = client.post("/chat", json={"prompt": case.prompt, "view_context": {}})
            payload = response.json()
            assert response.status_code == 200, case.prompt
            assert payload["verification"]["authority"] == "server_inventory_graph", case.prompt
            assert payload["verification"]["status"] == "verified", case.prompt
            assert backend.calls == calls_before, case.prompt
            assert all(value in payload["answer"] for value in case.expected), case.prompt


@pytest.mark.parametrize(
    "prompt,expected_operation,expected_name",
    [
        ("최근 7일 시작된 리소스", "start", "vm-app"),
        ("resources deleted in the last 7 days", "delete", "vm-old"),
    ],
)
async def test_generalized_activity_conditions_use_activity_authority(
    prompt: str,
    expected_operation: str,
    expected_name: str,
) -> None:
    evidence = await InventoryChatTools(
        _provider,
        activity_provider=_activity_provider,
    ).resolve(prompt, principal_id="reader")

    assert evidence is not None
    assert evidence["authority"] == "server_inventory_activity"
    assert evidence["result"]["matched_count"] == 1
    assert evidence["result"]["events"][0]["operation"] == expected_operation
    assert evidence["result"]["events"][0]["name"] == expected_name


def _score_inventory_answer(
    case: InventoryWeaknessCase,
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
    refs = verification.get("evidence_refs")
    safe_refs = refs if isinstance(refs, list) else []
    is_inventory = authority == "server_inventory_graph"
    applicable = case.expects_inventory
    stream_verification = stream_done.get("verification") if stream_done is not None else None
    return (
        is_inventory == applicable,
        status_code == 200,
        is_inventory == applicable,
        not applicable or verification.get("reason_code") == "inventory_snapshot_grounded",
        not applicable or verification.get("status") in {"verified", "corrected"},
        not applicable or model_calls == 0,
        bool(answer.strip()),
        not applicable or ("근거:" in answer) == case.korean,
        not applicable or ("of 13" in answer or "13개 중" in answer),
        not applicable or "all-test-resources" in answer,
        not applicable or "azure-resource-graph" in answer,
        not applicable or "2026-07-20T10:00:00Z" in answer,
        not applicable or "fresh" in answer,
        not applicable or all(value in answer for value in case.expected),
        "must-not-enter-chat-evidence" not in answer,
        not applicable or len(safe_refs) == 1,
        not applicable or all(str(ref).startswith("inventory:") for ref in safe_refs),
        "executed" not in answer.casefold() and "실행했습니다" not in answer,
        len(answer) <= 5_000,
        not applicable
        or (
            isinstance(stream_verification, dict)
            and stream_verification.get("authority") == authority
            and stream_done.get("answer") == answer
        ),
    )


def _inventory_done_event(body: str) -> dict[str, Any] | None:
    return _stream_event(body, "done")


def _stream_event(body: str, event_name: str) -> dict[str, Any] | None:
    for block in body.split("\n\n"):
        if not block.startswith(f"event: {event_name}\n"):
            continue
        data = next(line[6:] for line in block.splitlines() if line.startswith("data: "))
        payload = json.loads(data)
        assert isinstance(payload, dict)
        return payload
    return None
