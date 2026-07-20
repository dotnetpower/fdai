"""Twenty grounded Azure resource questions through the Command Deck route."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.delivery.read_api.routes.chat import make_chat_route
from fdai.delivery.read_api.routes.chat_behavior_evidence import (
    RepositoryBehaviorEvidenceResolver,
)
from fdai.delivery.read_api.routes.chat_inventory import InventoryChatTools

REPO_ROOT = Path(__file__).resolve().parents[3]


class RecordingBackend:
    def __init__(self) -> None:
        self.calls = 0

    async def answer(self, **kwargs: object) -> dict[str, str]:
        self.calls += 1
        return {"answer": "fallback", "model": "test"}


async def _allow(request: Request) -> str:
    return "reader"


def _resource(
    resource_id: str,
    resource_type: str,
    name: str,
    *,
    group: str | None = None,
    location: str | None = None,
    status: str = "unknown",
) -> dict[str, Any]:
    props = {
        "resourceGroup": group,
        "location": location,
        "sensitive": "must-not-enter-chat-evidence",
    }
    return {
        "id": resource_id,
        "type": resource_type,
        "name": name,
        "status": status,
        "props": props,
    }


async def _provider(
    scope: str | None,
    depth: int,
    link_types: tuple[str, ...],
) -> dict[str, Any]:
    assert scope is None
    assert depth == 4
    assert link_types == ("contains", "attached_to", "depends_on")
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


@dataclass(frozen=True, slots=True)
class AzureQuestion:
    prompt: str
    expected: tuple[str, ...]
    excluded: tuple[str, ...] = ()


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
    AzureQuestion("Azure 리소스 종류를 보여줘", ("compute.vm: 2개", "resource-group: 2개")),
    AzureQuestion("공인 IP 목록을 보여줘", ("pip-app",)),
    AzureQuestion("네트워크 보안 그룹 목록은?", ("nsg-app",)),
    AzureQuestion(
        "vm-app과 연결된 Azure 리소스는?",
        ("vnet-app --depends_on--> vm-app", "pip-app --attached_to--> vm-app"),
    ),
    AzureQuestion("이름이 vm-job인 Azure 리소스를 찾아줘", ("vm-job", "stopped"), ("vm-app",)),
)


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
