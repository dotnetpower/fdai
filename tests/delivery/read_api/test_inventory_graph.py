"""Integration tests for the ``/inventory/graph`` GET route."""

from __future__ import annotations

from typing import Any

import pytest
from starlette.testclient import TestClient

from fdai.delivery.read_api.auth import build_authenticator
from fdai.delivery.read_api.main import ReadApiConfig, build_app
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.read_api.routes.demo_inventory_graph import demo_inventory_graph_provider
from fdai.shared.providers.inventory import InventoryGraphViewNotFoundError


@pytest.fixture(autouse=True)
def _dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FDAI_READ_API_DEV_MODE", "1")


async def _provider(
    scope: str | None,
    depth: int,
    links: tuple[str, ...],
    *,
    root: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
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
                "classification": "ownership_tag",
                "description": "FDAI runtime",
                "root_resource_id": "sub-example",
            }
        ],
        "truncated": False,
        "provider_echo": {
            "scope": scope,
            "depth": depth,
            "links": list(links),
            "root": root,
            "limit": limit,
        },
    }


def _client(*, wired: bool) -> TestClient:
    auth = build_authenticator(verifier=lambda token: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(dev_mode=True, inventory_graph_provider=_provider if wired else None),
    )
    return TestClient(app)


def _client_with_provider(provider: Any) -> TestClient:
    auth = build_authenticator(verifier=lambda token: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(dev_mode=True, inventory_graph_provider=provider),
    )
    return TestClient(app, raise_server_exceptions=False)


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


def test_inventory_graph_forwards_bounded_root_query() -> None:
    response = _client(wired=True).get(
        "/inventory/graph",
        params={
            "root": "resource-root",
            "depth": "2",
            "limit": "25",
            "include": "contains,attached_to",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["root"] == "resource-root"
    assert body["limit"] == 25
    assert body["provider_echo"]["root"] == "resource-root"
    assert body["provider_echo"]["limit"] == 25


def test_inventory_graph_preserves_legacy_provider_for_named_views() -> None:
    async def legacy_provider(
        scope: str | None,
        depth: int,
        links: tuple[str, ...],
    ) -> dict[str, Any]:
        return await _provider(scope, depth, links)

    response = _client_with_provider(legacy_provider).get("/inventory/graph")

    assert response.status_code == 200, response.text
    assert response.json()["active_view"] == "fdai-control-plane"


@pytest.mark.parametrize("depth", ["zero", "0", "9"])
def test_inventory_graph_rejects_invalid_depth(depth: str) -> None:
    response = _client(wired=True).get("/inventory/graph", params={"depth": depth})
    assert response.status_code == 400


@pytest.mark.parametrize("limit", ["many", "0", "1001"])
def test_inventory_graph_rejects_invalid_limit(limit: str) -> None:
    response = _client(wired=True).get(
        "/inventory/graph",
        params={"root": "resource-root", "limit": limit},
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    "params",
    [
        {"limit": "25"},
        {"scope": "service-a", "root": "resource-root"},
    ],
)
def test_inventory_graph_rejects_ambiguous_query_modes(params: dict[str, str]) -> None:
    response = _client(wired=True).get("/inventory/graph", params=params)
    assert response.status_code == 400


def test_inventory_graph_rejects_unknown_link_type() -> None:
    response = _client(wired=True).get("/inventory/graph", params={"include": "contains,unknown"})
    assert response.status_code == 400


@pytest.mark.parametrize(
    "params",
    [
        {"include": "contains," + "x" * 504},
        [("link", "contains")] * 65,
    ],
)
def test_inventory_graph_rejects_oversized_link_filters(params: Any) -> None:
    response = _client(wired=True).get("/inventory/graph", params=params)
    assert response.status_code == 400


@pytest.mark.parametrize(
    "payload",
    [
        {
            "resources": [{"id": "resource-a"}],
            "links": [],
            "truncated": False,
        },
        {
            "resources": [{"id": "resource-a", "type": "test"}],
            "links": [{"source": "resource-a", "target": "missing", "type": "depends_on"}],
            "truncated": False,
        },
        {
            "resources": [{"id": "resource-a", "type": "test"}],
            "links": [],
            "truncated": "false",
        },
        {
            "resources": [{"id": f"resource-{index}", "type": "test"} for index in range(5001)],
            "links": [],
            "truncated": True,
        },
        {
            "resources": [{"id": "resource-a", "type": "test"}],
            "links": [],
            "truncated": True,
            "truncation_reasons": ["unknown_limit"],
        },
        {
            "resources": [{"id": "resource-a", "type": "test"}],
            "links": [],
            "truncated": False,
            "truncation_reasons": ["resource_limit"],
        },
    ],
)
def test_inventory_graph_rejects_invalid_provider_payload(payload: dict[str, Any]) -> None:
    async def invalid_provider(
        scope: str | None,
        depth: int,
        links: tuple[str, ...],
    ) -> dict[str, Any]:
        del scope, depth, links
        return payload

    response = _client_with_provider(invalid_provider).get("/inventory/graph")

    assert response.status_code == 500
    assert (
        response.json()["error"]["message"]
        == "inventory graph provider returned an invalid payload"
    )


def test_inventory_graph_route_is_opt_in_and_get_only() -> None:
    assert _client(wired=False).get("/inventory/graph").status_code == 404
    assert _client(wired=True).post("/inventory/graph").status_code == 405


def test_demo_inventory_graph_rejects_unknown_named_view() -> None:
    auth = build_authenticator(verifier=lambda token: {"oid": "u"}, resolver=lambda claims: None)
    app = build_app(
        authenticator=auth,
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(
            dev_mode=True,
            inventory_graph_provider=demo_inventory_graph_provider,
        ),
    )

    response = TestClient(app).get("/inventory/graph", params={"scope": "production"})

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "architecture view not found: production"


async def test_demo_provider_defaults_to_fdai_and_separates_application_views() -> None:
    fdai = await demo_inventory_graph_provider(None, 4, ("contains", "depends_on"))
    commerce = await demo_inventory_graph_provider("commerce-api", 4, ("contains", "depends_on"))
    operations = await demo_inventory_graph_provider(
        "operations-portal", 4, ("contains", "depends_on")
    )
    assert fdai["active_view"] == "fdai-control-plane"
    assert [view["kind"] for view in fdai["views"]] == ["fdai", "service", "service"]
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


async def test_demo_provider_bounds_rooted_neighborhood() -> None:
    graph = await demo_inventory_graph_provider(
        None,
        1,
        ("depends_on",),
        root="web-api",
        limit=2,
    )

    assert [resource["id"] for resource in graph["resources"]] == ["web-api", "event-hub"]
    assert graph["links"] == [{"source": "web-api", "target": "event-hub", "type": "depends_on"}]
    assert graph["truncated"] is True


async def test_demo_provider_rejects_unknown_root() -> None:
    with pytest.raises(InventoryGraphViewNotFoundError, match="missing-root"):
        await demo_inventory_graph_provider(
            None,
            1,
            ("contains",),
            root="missing-root",
            limit=10,
        )
