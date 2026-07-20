"""Unit tests for deterministic architecture view classification."""

from __future__ import annotations

import pytest

from fdai.delivery.read_api.routes.architecture_views import project_architecture_graph
from fdai.delivery.read_api.routes.inventory_graph import InventoryGraphViewNotFoundError


def _resource(
    resource_id: str,
    resource_type: str,
    *,
    parent_id: str | None = None,
    tags: dict[str, str] | None = None,
) -> dict[str, object]:
    resource: dict[str, object] = {
        "id": resource_id,
        "type": resource_type,
        "name": resource_id,
        "status": "healthy",
        "props": {"tags": tags or {}},
    }
    if parent_id is not None:
        resource["parent_id"] = parent_id
    return resource


def _graph(requested_view: str | None = None) -> dict[str, object]:
    resources = [
        _resource("sub", "subscription"),
        _resource(
            "rg-fdai",
            "resource-group",
            parent_id="sub",
            tags={"fdai:managed": "true", "fdai:workload": "fdai"},
        ),
        _resource("fdai-api", "container-app", parent_id="rg-fdai"),
        _resource(
            "fdai-runner",
            "compute.vm",
            parent_id="sub",
            tags={"workload": "fdai"},
        ),
        _resource("rg-apps", "resource-group", parent_id="sub"),
        _resource(
            "orders-api",
            "app-service",
            parent_id="rg-apps",
            tags={"service": "Orders"},
        ),
        _resource(
            "orders-db",
            "postgresql",
            parent_id="rg-apps",
            tags={"application": "Orders"},
        ),
        _resource(
            "ambiguous-worker",
            "function-app",
            parent_id="rg-apps",
            tags={"service": "Orders", "application": "Billing"},
        ),
        _resource("untagged-cache", "cache", parent_id="rg-apps"),
    ]
    links = [
        {"source": str(resource["parent_id"]), "target": str(resource["id"]), "type": "contains"}
        for resource in resources
        if "parent_id" in resource
    ]
    return project_architecture_graph(
        resources=resources,
        links=links,
        requested_view=requested_view,
    )


def test_default_view_contains_only_fdai_resources_and_parent_boundaries() -> None:
    graph = _graph()

    assert graph["active_view"] == "fdai-control-plane"
    assert {resource["id"] for resource in graph["resources"]} == {
        "sub",
        "rg-fdai",
        "fdai-api",
        "fdai-runner",
    }
    assert [view["kind"] for view in graph["views"]] == [
        "fdai",
        "service",
        "resource_group",
    ]
    assert all(view["label"].casefold() != "fdai" for view in graph["views"][1:])


def test_service_view_groups_matching_explicit_tags_across_resources() -> None:
    manifest = _graph()["views"]
    service_view = next(view for view in manifest if view["kind"] == "service")

    graph = _graph(str(service_view["id"]))

    assert {resource["id"] for resource in graph["resources"]} == {
        "sub",
        "rg-apps",
        "orders-api",
        "orders-db",
    }
    assert graph["links"] == [
        {"source": "sub", "target": "rg-apps", "type": "contains"},
        {"source": "rg-apps", "target": "orders-api", "type": "contains"},
        {"source": "rg-apps", "target": "orders-db", "type": "contains"},
    ]


def test_missing_or_conflicting_service_tags_fall_back_to_resource_group() -> None:
    graph = _graph("rg-apps")

    assert {resource["id"] for resource in graph["resources"]} == {
        "sub",
        "rg-apps",
        "ambiguous-worker",
        "untagged-cache",
    }
    active = next(view for view in graph["views"] if view["id"] == "rg-apps")
    assert active["classification"] == "resource_group_fallback"


def test_conflicting_resource_tags_do_not_inherit_a_parent_service() -> None:
    resources = [
        _resource("rg", "resource-group", tags={"service": "Orders"}),
        _resource(
            "worker",
            "function-app",
            parent_id="rg",
            tags={"service": "Orders", "application": "Billing"},
        ),
    ]

    graph = project_architecture_graph(
        resources=resources,
        links=({"source": "rg", "target": "worker", "type": "contains"},),
        requested_view="rg",
    )

    assert {resource["id"] for resource in graph["resources"]} == {"rg", "worker"}


def test_service_tag_values_are_case_insensitive() -> None:
    resources = [
        _resource("rg", "resource-group"),
        _resource(
            "api",
            "app-service",
            parent_id="rg",
            tags={"service": "Orders", "application": "orders"},
        ),
    ]

    manifest = project_architecture_graph(
        resources=resources,
        links=({"source": "rg", "target": "api", "type": "contains"},),
        requested_view=None,
    )["views"]

    assert [view["kind"] for view in manifest] == ["fdai", "service"]


def test_unknown_view_fails_instead_of_returning_default() -> None:
    with pytest.raises(InventoryGraphViewNotFoundError, match="missing"):
        _graph("missing")
