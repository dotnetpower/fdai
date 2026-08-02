"""Focused tests for bounded in-memory inventory graph traversal."""

from fdai.delivery.operator_api.routes.inventory_graph_bounds import (
    project_bounded_inventory_neighborhood,
)


def test_bounded_neighborhood_expands_frontier_fairly() -> None:
    resources = [
        {"id": resource_id, "type": "test"}
        for resource_id in (
            "fair-root",
            "fair-a",
            "fair-z",
            *(f"fair-a-child-{index:03d}" for index in range(65)),
            "fair-z-child",
        )
    ]
    links = [
        {"source": "fair-root", "target": "fair-a", "type": "contains"},
        {"source": "fair-root", "target": "fair-z", "type": "contains"},
        *(
            {
                "source": "fair-a",
                "target": f"fair-a-child-{index:03d}",
                "type": "contains",
            }
            for index in range(65)
        ),
        {"source": "fair-z", "target": "fair-z-child", "type": "contains"},
    ]

    graph = project_bounded_inventory_neighborhood(
        resources=resources,
        links=links,
        root="fair-root",
        depth=2,
        link_types=("contains",),
        limit=5,
    )

    assert [resource["id"] for resource in graph["resources"]] == [
        "fair-root",
        "fair-a",
        "fair-z",
        "fair-a-child-000",
        "fair-z-child",
    ]
    assert graph["truncated"] is True
    assert graph["truncation_reasons"] == ["resource_limit"]


def test_bounded_neighborhood_caps_internal_links() -> None:
    resource_ids = tuple(f"dense-{index}" for index in range(10))
    resources = [{"id": resource_id, "type": "test"} for resource_id in resource_ids]
    links = [
        {"source": source, "target": target, "type": "depends_on"}
        for source in resource_ids
        for target in resource_ids
        if source != target
    ]

    graph = project_bounded_inventory_neighborhood(
        resources=resources,
        links=links,
        root="dense-0",
        depth=1,
        link_types=("depends_on",),
        limit=10,
    )

    assert len(graph["resources"]) == 10
    assert len(graph["links"]) == 80
    assert graph["truncated"] is True
    assert graph["truncation_reasons"] == ["internal_edge_limit"]
