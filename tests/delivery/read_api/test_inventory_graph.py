"""Integration tests for the ``/inventory/graph`` GET route."""

from __future__ import annotations

from typing import Any

import pytest
from starlette.testclient import TestClient

from fdai.delivery.read_api.auth import build_authenticator
from fdai.delivery.read_api.main import ReadApiConfig, build_app
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.read_api.routes.demo_inventory_graph import demo_inventory_graph_provider


@pytest.fixture(autouse=True)
def _dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FDAI_READ_API_DEV_MODE", "1")


async def _provider(scope: str | None, depth: int, links: tuple[str, ...]) -> dict[str, Any]:
    return {
        "snapshot_at": "2026-07-13T00:00:00Z",
        "freshness": "fresh",
        "resources": [{"id": "sub-example", "type": "subscription", "name": "Example"}],
        "links": [],
        "active_view": scope or "fdai-control-plane",
        "views": [
            {
                "id": "fdai-control-plane",
                "label": "FDAI control plane",
                "kind": "fdai",
                "description": "FDAI runtime",
                "root_resource_id": "sub-example",
            }
        ],
        "truncated": False,
        "provider_echo": {"scope": scope, "depth": depth, "links": list(links)},
    }


def _client(*, wired: bool) -> TestClient:
    auth = build_authenticator(verifier=lambda token: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(dev_mode=True, inventory_graph_provider=_provider if wired else None),
    )
    return TestClient(app)


def test_inventory_graph_returns_projection_and_query_manifest() -> None:
    response = _client(wired=True).get(
        "/inventory/graph",
        params={"scope": "sub-example", "depth": "3", "include": "contains,depends_on"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scope"] == "sub-example"
    assert body["depth"] == 3
    assert body["included_link_types"] == ["contains", "depends_on"]
    assert body["freshness"] == "fresh"
    assert body["resources"][0]["id"] == "sub-example"
    assert body["active_view"] == "sub-example"
    assert body["views"][0]["kind"] == "fdai"


@pytest.mark.parametrize("depth", ["zero", "0", "9"])
def test_inventory_graph_rejects_invalid_depth(depth: str) -> None:
    response = _client(wired=True).get("/inventory/graph", params={"depth": depth})
    assert response.status_code == 400


def test_inventory_graph_rejects_unknown_link_type() -> None:
    response = _client(wired=True).get("/inventory/graph", params={"include": "contains,unknown"})
    assert response.status_code == 400


def test_inventory_graph_route_is_opt_in_and_get_only() -> None:
    assert _client(wired=False).get("/inventory/graph").status_code == 404
    assert _client(wired=True).post("/inventory/graph").status_code == 405


async def test_demo_provider_defaults_to_fdai_and_separates_application_views() -> None:
    fdai = await demo_inventory_graph_provider(None, 4, ("contains", "depends_on"))
    commerce = await demo_inventory_graph_provider("commerce-api", 4, ("contains", "depends_on"))
    operations = await demo_inventory_graph_provider(
        "operations-portal", 4, ("contains", "depends_on")
    )
    assert fdai["active_view"] == "fdai-control-plane"
    assert [view["kind"] for view in fdai["views"]] == ["fdai", "application", "application"]
    id_sets = [
        {resource["id"] for resource in graph["resources"]}
        for graph in (fdai, commerce, operations)
    ]
    assert all(
        first.isdisjoint(second)
        for index, first in enumerate(id_sets)
        for second in id_sets[index + 1 :]
    )
    assert any(resource["type"] == "event-hub" for resource in fdai["resources"])
    assert {(link["source"], link["target"]) for link in fdai["links"]} >= {
        ("web-api", "event-hub"),
        ("event-hub", "event-worker"),
    }
