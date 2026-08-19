"""Focused dynamic inventory impact projection tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai_operator_service.families.operations.contracts import (
    InventoryImpactContext,
    InventoryImpactEdge,
    InventoryImpactLinkPage,
    ProjectionNotFoundError,
    ProjectionQuery,
)
from fdai_operator_service.families.operations.inventory_impact import (
    project_inventory_impact,
)

DIGEST = f"sha256:{'a' * 64}"


class _Reader:
    def __init__(self, *, exists: bool = True) -> None:
        self.exists = exists
        self.edges = (
            InventoryImpactEdge("root", "service", "contains"),
            InventoryImpactEdge("service", "database", "depends_on"),
            InventoryImpactEdge("database", "replica", "depends_on"),
        )

    async def read_inventory_impact_context(self) -> InventoryImpactContext:
        return InventoryImpactContext(
            snapshot_id="generation-1",
            observed_at=datetime(2026, 8, 19, tzinfo=UTC),
        )

    async def inventory_resource_exists(self, *, snapshot_id: str, resource_id: str) -> bool:
        assert snapshot_id == "generation-1"
        assert resource_id == "root"
        return self.exists

    async def read_inventory_outgoing_links(
        self,
        *,
        snapshot_id: str,
        source_ids: tuple[str, ...],
        link_types: tuple[str, ...],
        limit: int,
    ) -> InventoryImpactLinkPage:
        assert snapshot_id == "generation-1"
        matches = tuple(
            edge
            for edge in self.edges
            if edge.source in source_ids and edge.link_type in link_types
        )
        return InventoryImpactLinkPage(edges=matches[:limit], truncated=len(matches) > limit)


def _query(**params: tuple[str, ...]) -> ProjectionQuery:
    return ProjectionQuery(
        operation="blast_radius.simulate",
        principal_id="reader",
        path={},
        params=params,
        limit=100,
        cursor=None,
    )


def _ontology() -> dict[str, object]:
    return {
        "ontology_release_digest": DIGEST,
        "mutation_authority": False,
        "link_types": ["contains", "depends_on", "attached_to"],
    }


async def test_inventory_impact_preserves_direction_cutoff_and_depth_truncation() -> None:
    result = await project_inventory_impact(
        query=_query(target=("root",), depth=("2",), link=("depends_on", "contains")),
        reader=_Reader(),
        ontology_projection=_ontology(),
    )

    assert result["ontology_release_digest"] == DIGEST
    assert result["source_generation"] == "generation-1"
    assert result["reached"] == [
        {"resource_id": "root", "depth": 0, "via_link_type": None},
        {"resource_id": "service", "depth": 1, "via_link_type": "contains"},
        {"resource_id": "database", "depth": 2, "via_link_type": "depends_on"},
    ]
    assert result["edges"] == [
        {
            "source": "root",
            "target": "service",
            "link_type": "contains",
            "depth": 1,
            "verification_status": "unverified",
        },
        {
            "source": "service",
            "target": "database",
            "link_type": "depends_on",
            "depth": 2,
            "verification_status": "unverified",
        },
    ]
    assert result["complete"] is False
    assert result["truncated_at_depth"] is True
    assert result["truncation_reasons"] == ["depth_limit"]
    assert result["mutation_authority"] is False
    assert result["execution_authority"] is False


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"depth": ("2",), "link": ("contains",)}, "target MUST be supplied"),
        ({"target": ("root",), "depth": ("6",), "link": ("contains",)}, "depth MUST be"),
        ({"target": ("root",), "depth": ("2",), "links": ("none",)}, "MUST NOT be empty"),
        ({"target": ("root",), "depth": ("2",), "link": ("unknown",)}, "not declared"),
    ],
)
async def test_inventory_impact_rejects_unbounded_or_untyped_queries(
    params: dict[str, tuple[str, ...]],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        await project_inventory_impact(
            query=_query(**params),
            reader=_Reader(),
            ontology_projection=_ontology(),
        )


async def test_inventory_impact_rejects_an_unknown_exact_target() -> None:
    with pytest.raises(ProjectionNotFoundError):
        await project_inventory_impact(
            query=_query(target=("root",), depth=("1",), link=("contains",)),
            reader=_Reader(exists=False),
            ontology_projection=_ontology(),
        )
