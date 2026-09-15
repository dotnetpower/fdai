"""Focused dynamic inventory impact projection tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai_operator_service.families.operations.contracts import (
    InventoryImpactContext,
    InventoryImpactEdge,
    InventoryImpactLinkPage,
    InventoryRelationshipCoverage,
    InventoryRelationshipEvidence,
    ProjectionNotFoundError,
    ProjectionQuery,
    ProjectionUnavailableError,
)
from fdai_operator_service.families.operations.instance_states import (
    InventoryOntologyContext,
)
from fdai_operator_service.families.operations.inventory_impact import (
    project_inventory_impact,
)
from fdai_operator_service.families.operations.relationship_evidence import (
    project_relationship_evidence,
)

DIGEST = f"sha256:{'a' * 64}"
CUTOFF = datetime(2026, 8, 19, tzinfo=UTC)


def _evidence(
    *,
    kind: str = "configuration",
    cutoff: datetime | None = None,
) -> InventoryRelationshipEvidence:
    return InventoryRelationshipEvidence(
        source_identity=("runtime-telemetry" if kind == "observation" else "azure-resource-graph"),
        source_property_path="properties.parent",
        mapping_id="test.relationship",
        evidence_method="deterministic-cross-check",
        freshness_ceiling_seconds=3_600,
        evidence_kind=kind,
        evidence_cutoff=cutoff,
    )


def test_observed_relationship_evidence_requires_an_exact_cutoff() -> None:
    with pytest.raises(ValueError, match="exact cutoff"):
        _evidence(kind="observation")


class _Reader:
    def __init__(
        self,
        *,
        exists: bool = True,
        ontology_generation: str = "generation-1",
        ontology_release: str = DIGEST,
        missing_resource_ids: frozenset[str] = frozenset(),
    ) -> None:
        self.exists = exists
        self.ontology_generation = ontology_generation
        self.ontology_release = ontology_release
        self.missing_resource_ids = missing_resource_ids
        self.relationship_coverage = InventoryRelationshipCoverage(
            materialized=3,
            reviewed_unavailable=0,
            unclassified=0,
            total_candidates=3,
            complete=True,
        )
        self.edges = (
            InventoryImpactEdge("root", "service", "contains", _evidence()),
            InventoryImpactEdge(
                "service",
                "database",
                "depends_on",
                _evidence(kind="observation", cutoff=CUTOFF),
            ),
            InventoryImpactEdge("database", "replica", "depends_on", _evidence()),
        )

    async def read_inventory_impact_context(self) -> InventoryImpactContext:
        return InventoryImpactContext(
            snapshot_id="generation-1",
            observed_at=CUTOFF,
            relationship_coverage=self.relationship_coverage,
        )

    async def inventory_resource_exists(self, *, snapshot_id: str, resource_id: str) -> bool:
        assert snapshot_id == "generation-1"
        assert resource_id == "root"
        return self.exists

    async def read_inventory_ontology_context(self) -> InventoryOntologyContext:
        return InventoryOntologyContext(
            generation=self.ontology_generation,
            ontology_release_digest=self.ontology_release,
            manifest_digest=f"sha256:{'b' * 64}",
        )

    async def inventory_resources_exist(
        self,
        *,
        snapshot_id: str,
        resource_ids: tuple[str, ...],
    ) -> bool:
        assert snapshot_id == "generation-1"
        return not self.missing_resource_ids.intersection(resource_ids)

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
        now=lambda: CUTOFF,
    )

    assert result["schema_version"] == "1.1.0"
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
            "verification_status": "verified",
            "evidence": {
                "status": "available",
                "evidence_kind": "configuration",
                "verification_status": "configuration_observed",
                "source": "azure-resource-graph",
                "source_property_path": "properties.parent",
                "mapping_id": "test.relationship",
                "evidence_method": "deterministic-cross-check",
                "cutoff": CUTOFF.isoformat(),
                "freshness_ceiling_seconds": 3_600,
                "complete": True,
                "reason": None,
            },
        },
        {
            "source": "service",
            "target": "database",
            "link_type": "depends_on",
            "depth": 2,
            "verification_status": "verified",
            "evidence": {
                "status": "available",
                "evidence_kind": "observation",
                "verification_status": "independently_verified",
                "source": "runtime-telemetry",
                "source_property_path": "properties.parent",
                "mapping_id": "test.relationship",
                "evidence_method": "deterministic-cross-check",
                "cutoff": CUTOFF.isoformat(),
                "freshness_ceiling_seconds": 3_600,
                "complete": True,
                "reason": None,
            },
        },
    ]
    assert result["complete"] is False
    assert result["relationship_evidence_complete"] is True
    assert result["relationship_source_coverage"] == {
        "materialized": 3,
        "reviewed_unavailable": 0,
        "unclassified": 0,
        "total_candidates": 3,
        "complete": True,
    }
    projected_edges = result["edges"]
    assert isinstance(projected_edges, list)
    first_edge = projected_edges[0]
    assert isinstance(first_edge, dict)
    assert first_edge["evidence"] == project_relationship_evidence(
        _evidence(),
        cutoff=CUTOFF,
        evaluated_at=CUTOFF,
        source_complete=True,
    )
    assert result["truncated_at_depth"] is True
    assert result["truncation_reasons"] == ["depth_limit"]
    assert result["mutation_authority"] is False
    assert result["execution_authority"] is False


async def test_inventory_impact_depth_probe_fails_closed_after_a_leading_cycle() -> None:
    reader = _Reader()
    reader.edges = (
        InventoryImpactEdge("root", "service-a", "contains"),
        InventoryImpactEdge("root", "service-b", "contains"),
        InventoryImpactEdge("service-a", "root", "depends_on"),
        InventoryImpactEdge("service-b", "database", "depends_on"),
    )

    result = await project_inventory_impact(
        query=_query(target=("root",), depth=("1",), link=("contains", "depends_on")),
        reader=reader,
        ontology_projection=_ontology(),
        now=lambda: CUTOFF,
    )

    assert result["complete"] is False
    assert result["truncated_at_depth"] is True
    assert result["truncation_reasons"] == ["depth_limit"]


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
            now=lambda: CUTOFF,
        )


async def test_inventory_impact_keeps_missing_and_stale_evidence_unverified() -> None:
    reader = _Reader()
    reader.edges = (
        InventoryImpactEdge("root", "missing", "contains"),
        InventoryImpactEdge(
            "root",
            "stale",
            "contains",
            _evidence(cutoff=CUTOFF),
        ),
    )

    result = await project_inventory_impact(
        query=_query(target=("root",), depth=("1",), link=("contains",)),
        reader=reader,
        ontology_projection=_ontology(),
        now=lambda: datetime(2026, 8, 19, 2, tzinfo=UTC),
    )

    edges = result["edges"]
    assert isinstance(edges, list)
    assert [edge["verification_status"] for edge in edges] == [
        "unverified",
        "unverified",
    ]
    assert [edge["evidence"]["status"] for edge in edges] == [
        "unavailable",
        "stale",
    ]
    assert result["relationship_evidence_complete"] is False


async def test_inventory_impact_rejects_a_naive_evaluation_time() -> None:
    with pytest.raises(ValueError, match="evaluation time MUST be timezone-aware"):
        await project_inventory_impact(
            query=_query(target=("root",), depth=("1",), link=("contains",)),
            reader=_Reader(),
            ontology_projection=_ontology(),
            now=lambda: datetime(2026, 8, 19),
        )


@pytest.mark.parametrize(
    "reader",
    [
        _Reader(ontology_generation="generation-2"),
        _Reader(ontology_release=f"sha256:{'c' * 64}"),
    ],
)
async def test_inventory_impact_rejects_a_cross_generation_or_release_projection(
    reader: _Reader,
) -> None:
    with pytest.raises(ProjectionUnavailableError, match="not aligned"):
        await project_inventory_impact(
            query=_query(target=("root",), depth=("1",), link=("contains",)),
            reader=reader,
            ontology_projection=_ontology(),
            now=lambda: CUTOFF,
        )


@pytest.mark.parametrize(
    "edges",
    [
        (
            InventoryImpactEdge("root", "child", "contains", _evidence()),
            InventoryImpactEdge("root", "child", "contains", _evidence()),
        ),
        (InventoryImpactEdge("outside", "child", "contains", _evidence()),),
        (InventoryImpactEdge("root", "child", "depends_on", _evidence()),),
    ],
)
async def test_inventory_impact_rejects_out_of_scope_or_duplicate_reader_edges(
    edges: tuple[InventoryImpactEdge, ...],
) -> None:
    class _UntrustedReader(_Reader):
        async def read_inventory_outgoing_links(
            self,
            *,
            snapshot_id: str,
            source_ids: tuple[str, ...],
            link_types: tuple[str, ...],
            limit: int,
        ) -> InventoryImpactLinkPage:
            del snapshot_id, source_ids, link_types
            return InventoryImpactLinkPage(
                edges=edges[:limit],
                truncated=len(edges) > limit,
            )

    with pytest.raises(ProjectionUnavailableError, match="reader returned"):
        await project_inventory_impact(
            query=_query(target=("root",), depth=("1",), link=("contains",)),
            reader=_UntrustedReader(),
            ontology_projection=_ontology(),
            now=lambda: CUTOFF,
        )


async def test_inventory_impact_rejects_source_coverage_that_undercounts_edges() -> None:
    reader = _Reader()
    reader.relationship_coverage = InventoryRelationshipCoverage(
        materialized=0,
        reviewed_unavailable=0,
        unclassified=0,
        total_candidates=0,
        complete=True,
    )

    with pytest.raises(ProjectionUnavailableError, match="undercounts"):
        await project_inventory_impact(
            query=_query(target=("root",), depth=("1",), link=("contains",)),
            reader=reader,
            ontology_projection=_ontology(),
            now=lambda: CUTOFF,
        )


async def test_inventory_impact_rejects_an_edge_target_absent_from_the_snapshot() -> None:
    with pytest.raises(ProjectionUnavailableError, match="absent from the active snapshot"):
        await project_inventory_impact(
            query=_query(target=("root",), depth=("1",), link=("contains",)),
            reader=_Reader(missing_resource_ids=frozenset({"service"})),
            ontology_projection=_ontology(),
            now=lambda: CUTOFF,
        )


async def test_inventory_impact_does_not_verify_configuration_from_incomplete_source() -> None:
    reader = _Reader()
    reader.relationship_coverage = InventoryRelationshipCoverage(
        materialized=3,
        reviewed_unavailable=0,
        unclassified=1,
        total_candidates=4,
        complete=False,
    )

    result = await project_inventory_impact(
        query=_query(target=("root",), depth=("1",), link=("contains",)),
        reader=reader,
        ontology_projection=_ontology(),
        now=lambda: CUTOFF,
    )

    edges = result["edges"]
    assert isinstance(edges, list)
    assert edges[0]["verification_status"] == "unverified"
    assert edges[0]["evidence"]["reason"] == "relationship_source_incomplete"
    assert edges[0]["evidence"]["source"] == "azure-resource-graph"
    assert edges[0]["evidence"]["mapping_id"] == "test.relationship"
    assert result["relationship_evidence_complete"] is False


async def test_inventory_impact_preserves_evidence_when_source_coverage_is_unavailable() -> None:
    reader = _Reader()
    reader.relationship_coverage = None

    result = await project_inventory_impact(
        query=_query(target=("root",), depth=("1",), link=("contains",)),
        reader=reader,
        ontology_projection=_ontology(),
        now=lambda: CUTOFF,
    )

    edges = result["edges"]
    assert isinstance(edges, list)
    assert edges[0]["verification_status"] == "unverified"
    assert edges[0]["evidence"] == {
        "status": "unavailable",
        "evidence_kind": "configuration",
        "verification_status": "configuration_observed",
        "source": "azure-resource-graph",
        "source_property_path": "properties.parent",
        "mapping_id": "test.relationship",
        "evidence_method": "deterministic-cross-check",
        "cutoff": CUTOFF.isoformat(),
        "freshness_ceiling_seconds": 3_600,
        "complete": False,
        "reason": "relationship_source_coverage_unavailable",
    }
    assert result["relationship_evidence_complete"] is False
    assert result["relationship_source_coverage"] is None
