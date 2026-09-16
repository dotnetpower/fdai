"""Principal isolation tests for durable Operator operations replay."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from fdai_operator_service.families.operations.contracts import (
    InventoryImpactContext,
    InventoryImpactEdge,
    InventoryImpactLinkPage,
    InventoryInstanceActivityPage,
    InventoryInstanceNeighborhood,
    InventoryProjectionSourceState,
    InventoryRelationshipCoverage,
    InventoryRelationshipDropClassification,
    InventoryRelationshipEvidence,
    ProjectionNotFoundError,
    ProjectionQuery,
    ReplayQuery,
)
from fdai_operator_service.families.operations.instance_states import (
    InventoryOntologyContext,
)
from fdai_operator_service.family_adapters import PostgresOperationsAdapters
from fdai_operator_service.postgres_family_store import (
    INVENTORY_INVALIDATION_STREAM,
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
    PostgresFamilyStoreUnavailable,
    _instance_relationship_evidence,
    _projection_source_states,
)
from fdai_service_contracts import OperatorRole
from fdai_service_contracts.runtime_call import (
    RUNTIME_CALL_MAPPING_ID,
    RUNTIME_CALL_MAPPING_REVISION,
    RUNTIME_CALL_SOURCE_SCHEMA_DIGEST,
    RUNTIME_CALL_SOURCE_SCHEMA_VERSION,
    RUNTIME_CALL_VERIFICATION_METHOD,
)


async def test_postgres_operations_builds_dynamic_impact_instead_of_reading_static_key(
    monkeypatch: Any,
) -> None:
    operations: list[str] = []

    async def read_projection(
        self: PostgresFamilyStore,
        *,
        family: str,
        operation: str,
    ) -> Mapping[str, object]:
        del self
        assert family == "operations"
        operations.append(operation)
        return {
            "ontology_release_digest": f"sha256:{'a' * 64}",
            "mutation_authority": False,
            "link_types": ["contains"],
        }

    async def read_context(self: PostgresFamilyStore) -> InventoryImpactContext:
        del self
        return InventoryImpactContext(
            snapshot_id="generation-1",
            observed_at=datetime(2026, 8, 19, tzinfo=UTC),
        )

    async def resource_exists(
        self: PostgresFamilyStore,
        *,
        snapshot_id: str,
        resource_id: str,
    ) -> bool:
        del self
        return snapshot_id == "generation-1" and resource_id == "root"

    async def read_ontology_context(
        self: PostgresFamilyStore,
    ) -> InventoryOntologyContext:
        del self
        return InventoryOntologyContext(
            generation="generation-1",
            ontology_release_digest=f"sha256:{'a' * 64}",
            manifest_digest=f"sha256:{'b' * 64}",
        )

    async def read_links(
        self: PostgresFamilyStore,
        *,
        snapshot_id: str,
        source_ids: tuple[str, ...],
        link_types: tuple[str, ...],
        limit: int,
    ) -> InventoryImpactLinkPage:
        del self, snapshot_id, link_types, limit
        edges = (
            (InventoryImpactEdge("root", "child", "contains"),) if source_ids == ("root",) else ()
        )
        return InventoryImpactLinkPage(edges=edges, truncated=False)

    async def resources_exist(
        self: PostgresFamilyStore,
        *,
        snapshot_id: str,
        resource_ids: tuple[str, ...],
    ) -> bool:
        del self
        return snapshot_id == "generation-1" and resource_ids == ("child",)

    monkeypatch.setattr(PostgresFamilyStore, "read_projection", read_projection)
    monkeypatch.setattr(PostgresFamilyStore, "read_inventory_impact_context", read_context)
    monkeypatch.setattr(
        PostgresFamilyStore,
        "read_inventory_ontology_context",
        read_ontology_context,
    )
    monkeypatch.setattr(PostgresFamilyStore, "inventory_resource_exists", resource_exists)
    monkeypatch.setattr(PostgresFamilyStore, "read_inventory_outgoing_links", read_links)
    monkeypatch.setattr(PostgresFamilyStore, "inventory_resources_exist", resources_exist)
    adapter = PostgresOperationsAdapters(
        PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))
    )

    result = await adapter.read(
        ProjectionQuery(
            operation="blast_radius.simulate",
            principal_id="reader",
            path={},
            params={"target": ("root",), "depth": ("1",), "link": ("contains",)},
            limit=100,
            cursor=None,
            roles=frozenset({OperatorRole.READER}),
        )
    )

    assert operations == ["ontology.graph"]
    assert result["affected_count"] == 1
    assert result["mutation_authority"] is False


async def test_postgres_operations_builds_dynamic_instance_projection(
    monkeypatch: Any,
) -> None:
    async def read_projection(
        self: PostgresFamilyStore,
        *,
        family: str,
        operation: str,
    ) -> Mapping[str, object]:
        del self
        assert (family, operation) == ("operations", "ontology.graph")
        return {
            "ontology_release_digest": f"sha256:{'a' * 64}",
            "link_types": ["contains"],
        }

    async def read_context(self: PostgresFamilyStore) -> InventoryImpactContext:
        del self
        return InventoryImpactContext(
            snapshot_id="generation-1",
            observed_at=datetime(2026, 8, 22, tzinfo=UTC),
        )

    async def read_neighborhood(
        self: PostgresFamilyStore,
        **kwargs: object,
    ) -> InventoryInstanceNeighborhood:
        del self
        assert kwargs["root_id"] == "root"
        return InventoryInstanceNeighborhood(resources=(), edges=(), truncated=False)

    async def read_activity(
        self: PostgresFamilyStore,
        **kwargs: object,
    ) -> InventoryInstanceActivityPage:
        del self, kwargs
        return InventoryInstanceActivityPage(activities=(), truncated=False)

    monkeypatch.setattr(PostgresFamilyStore, "read_projection", read_projection)
    monkeypatch.setattr(PostgresFamilyStore, "read_inventory_impact_context", read_context)
    monkeypatch.setattr(
        PostgresFamilyStore,
        "read_inventory_instance_neighborhood",
        read_neighborhood,
    )
    monkeypatch.setattr(
        PostgresFamilyStore,
        "read_inventory_instance_activity",
        read_activity,
    )
    adapter = PostgresOperationsAdapters(
        PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))
    )

    with pytest.raises(ProjectionNotFoundError):
        await adapter.read(
            ProjectionQuery(
                operation="ontology.instance.explore",
                principal_id="reader",
                path={},
                params={"root": ("root",)},
                limit=100,
                cursor=None,
                roles=frozenset({OperatorRole.READER}),
            )
        )


async def test_postgres_inventory_impact_reads_only_active_snapshot_identity_and_links(
    monkeypatch: Any,
) -> None:
    captured: list[tuple[str, Mapping[str, object]]] = []

    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self
        captured.append((statement, parameters))
        if "JOIN inventory_snapshot AS snapshot" in statement:
            return [
                {
                    "id": "generation-1",
                    "completed_at": datetime(2026, 8, 19, tzinfo=UTC),
                    "metadata": {
                        "relationship_drop_reasons": ["missing_target_endpoint"],
                        "relationship_drop_classifications": [
                            {
                                "reason": "missing_target_endpoint",
                                "mapping_id": "azure.example-depends-on-target",
                                "source_property_path": "properties.target.id",
                                "source_provider_type": "microsoft.example/widgets",
                                "target_provider_type": "Microsoft.Example/targets",
                                "unavailable_reason": "target_outside_active_generation",
                                "count": 2,
                            },
                            {
                                "reason": "target_type_mismatch",
                                "mapping_id": "azure.role-assignment-attached-to-scope",
                                "source_property_path": "properties.scope",
                                "source_provider_type": "microsoft.authorization/roleassignments",
                                "target_provider_type": (
                                    "microsoft.storage/storageaccounts/blobservices/containers"
                                ),
                                "unavailable_reason": "authorization_child_scope_unmodeled",
                                "count": 1,
                            },
                        ],
                        "derived_source_states": [
                            {
                                "source": "kubernetes_runtime_inventory",
                                "status": "unavailable",
                                "observed_at": None,
                                "reason": "kubernetes_source_unconfigured",
                            },
                            {
                                "source": "runtime_call_graph",
                                "status": "available",
                                "observed_at": "2026-08-19T00:00:00+00:00",
                                "reason": None,
                            },
                            {
                                "source": "postgres_role_evidence",
                                "status": "unavailable",
                                "observed_at": None,
                                "reason": "database_role_observation_unavailable",
                            },
                            {
                                "source": "azure_static_web_app_environment",
                                "status": "available",
                                "observed_at": "2026-08-19T00:01:00+00:00",
                                "reason": None,
                                "coverage": {"observed": 4, "targets": 4},
                            },
                        ],
                    },
                }
            ]
        if "SELECT 1 AS present" in statement:
            return [{"present": 1}]
        if "SELECT resource_id FROM inventory_snapshot_resource" in statement:
            return [{"resource_id": "child"}]
        return [
            {
                "from_id": "root",
                "link_type": "contains",
                "to_id": "child",
                "props": {"provider_relationship_evidence": _provider_relationship_evidence()},
            },
            {
                "from_id": "root",
                "link_type": "contains",
                "to_id": "extra",
                "props": {},
            },
        ]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    context = await store.read_inventory_impact_context()
    exists = await store.inventory_resource_exists(
        snapshot_id="generation-1",
        resource_id="root",
    )
    targets_exist = await store.inventory_resources_exist(
        snapshot_id="generation-1",
        resource_ids=("child",),
    )
    page = await store.read_inventory_outgoing_links(
        snapshot_id="generation-1",
        source_ids=("root",),
        link_types=("contains",),
        limit=1,
    )

    assert context == InventoryImpactContext(
        snapshot_id="generation-1",
        observed_at=datetime(2026, 8, 19, tzinfo=UTC),
        relationship_drop_reasons=("missing_target_endpoint",),
        relationship_drop_classifications=(
            InventoryRelationshipDropClassification(
                reason="missing_target_endpoint",
                mapping_id="azure.example-depends-on-target",
                source_property_path="properties.target.id",
                source_provider_type="microsoft.example/widgets",
                target_provider_type="Microsoft.Example/targets",
                unavailable_reason="target_outside_active_generation",
                count=2,
            ),
            InventoryRelationshipDropClassification(
                reason="target_type_mismatch",
                mapping_id="azure.role-assignment-attached-to-scope",
                source_property_path="properties.scope",
                source_provider_type="microsoft.authorization/roleassignments",
                target_provider_type=("microsoft.storage/storageaccounts/blobservices/containers"),
                unavailable_reason="authorization_child_scope_unmodeled",
                count=1,
            ),
        ),
        projection_source_states=(
            InventoryProjectionSourceState(
                source="azure_static_web_app_environment",
                status="available",
                observed_at=datetime(2026, 8, 19, 0, 1, tzinfo=UTC),
                reason=None,
            ),
            InventoryProjectionSourceState(
                source="kubernetes_runtime_inventory",
                status="unavailable",
                observed_at=None,
                reason="kubernetes_source_unconfigured",
            ),
            InventoryProjectionSourceState(
                source="postgres_role_evidence",
                status="unavailable",
                observed_at=None,
                reason="database_role_observation_unavailable",
            ),
            InventoryProjectionSourceState(
                source="runtime_call_graph",
                status="available",
                observed_at=datetime(2026, 8, 19, tzinfo=UTC),
                reason=None,
            ),
        ),
    )
    assert exists is True
    assert targets_exist is True
    assert [(edge.source, edge.link_type, edge.target) for edge in page.edges] == [
        ("root", "contains", "child")
    ]
    assert page.edges[0].evidence == InventoryRelationshipEvidence(
        source_identity="azure-resource-graph",
        source_property_path="id.providerParent",
        mapping_id="azure.test-parent",
        evidence_method="deterministic-cross-check",
        freshness_ceiling_seconds=3_600,
    )
    assert page.truncated is True
    assert captured[-1][1] == {
        "snapshot_id": "generation-1",
        "source_ids": ["root"],
        "link_types": ["contains"],
        "probe": 2,
    }


async def test_postgres_inventory_impact_decodes_relationship_coverage(
    monkeypatch: Any,
) -> None:
    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self, parameters
        return [
            {
                "id": "generation-1",
                "completed_at": datetime(2026, 8, 19, tzinfo=UTC),
                "metadata": {
                    "relationship_coverage": {
                        "materialized": 10,
                        "reviewed_unavailable": 2,
                        "unclassified": 0,
                        "total_candidates": 12,
                        "complete": True,
                    },
                },
            }
        ]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    context = await store.read_inventory_impact_context()

    assert context is not None
    assert context.relationship_coverage == InventoryRelationshipCoverage(
        materialized=10,
        reviewed_unavailable=2,
        unclassified=0,
        total_candidates=12,
        complete=True,
    )


async def test_postgres_inventory_impact_treats_a_null_relationship_coverage_as_absent(
    monkeypatch: Any,
) -> None:
    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self, parameters
        return [
            {
                "id": "generation-1",
                "completed_at": datetime(2026, 8, 19, tzinfo=UTC),
                "metadata": {"relationship_coverage": None},
            }
        ]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    context = await store.read_inventory_impact_context()

    assert context is not None
    assert context.relationship_coverage is None


async def test_postgres_inventory_impact_treats_a_missing_relationship_coverage_as_absent(
    monkeypatch: Any,
) -> None:
    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self, parameters
        return [
            {
                "id": "generation-1",
                "completed_at": datetime(2026, 8, 19, tzinfo=UTC),
                "metadata": {},
            }
        ]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    context = await store.read_inventory_impact_context()

    assert context is not None
    assert context.relationship_coverage is None


@pytest.mark.parametrize(
    "coverage",
    [
        {
            "materialized": -1,
            "reviewed_unavailable": 0,
            "unclassified": 0,
            "total_candidates": -1,
            "complete": False,
        },
        {
            "materialized": True,
            "reviewed_unavailable": 0,
            "unclassified": 0,
            "total_candidates": 1,
            "complete": False,
        },
        {
            "materialized": 1,
            "reviewed_unavailable": 0,
            "unclassified": 0,
            "total_candidates": 2,
            "complete": False,
        },
        {
            "materialized": 1,
            "reviewed_unavailable": 0,
            "unclassified": 1,
            "total_candidates": 2,
            "complete": True,
        },
        {
            "materialized": 1,
            "reviewed_unavailable": 0,
            "unclassified": 0,
            "total_candidates": 1,
            "complete": 1,
        },
    ],
)
async def test_postgres_inventory_impact_rejects_malformed_relationship_coverage(
    monkeypatch: Any,
    coverage: dict[str, object],
) -> None:
    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self, parameters
        return [
            {
                "id": "generation-1",
                "completed_at": datetime(2026, 8, 19, tzinfo=UTC),
                "metadata": {"relationship_coverage": coverage},
            }
        ]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    with pytest.raises(PostgresFamilyStoreUnavailable, match="relationship coverage"):
        await store.read_inventory_impact_context()


async def test_postgres_inventory_impact_translates_malformed_edge_rows(
    monkeypatch: Any,
) -> None:
    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self, statement, parameters
        return [
            {
                "from_id": "",
                "link_type": "contains",
                "to_id": "child",
                "props": {},
            }
        ]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    with pytest.raises(PostgresFamilyStoreUnavailable, match="row is malformed"):
        await store.read_inventory_outgoing_links(
            snapshot_id="generation-1",
            source_ids=("root",),
            link_types=("contains",),
            limit=1,
        )


def test_runtime_call_relationship_evidence_decodes_as_observation() -> None:
    metadata = _runtime_call_observation_metadata()
    evidence = _instance_relationship_evidence(
        {"link_observation_metadata": metadata},
        inventory_generation="inventory:generation-one",
    )

    assert evidence is not None
    assert evidence.evidence_kind == "observation"
    assert evidence.source_identity == "telemetry.runtime-calls"
    assert evidence.mapping_id == "runtime-call-endpoint-identity"
    assert evidence.evidence_cutoff == datetime(2026, 8, 24, 4, 59, tzinfo=UTC)


def test_runtime_call_relationship_evidence_rejects_forged_authority() -> None:
    metadata = _runtime_call_observation_metadata()
    _runtime_call_state_fact(metadata)["authority"] = "execution_ledger"

    with pytest.raises(PostgresFamilyStoreUnavailable, match="not verified"):
        _instance_relationship_evidence(
            {"link_observation_metadata": metadata},
            inventory_generation="inventory:generation-one",
        )


def test_runtime_call_relationship_evidence_rejects_another_generation() -> None:
    with pytest.raises(PostgresFamilyStoreUnavailable, match="not verified"):
        _instance_relationship_evidence(
            {"link_observation_metadata": _runtime_call_observation_metadata()},
            inventory_generation="inventory:generation-two",
        )


@pytest.mark.parametrize(
    ("location", "field", "value", "message"),
    [
        (
            "metadata",
            "verification_method",
            "self-attested",
            "method is not trusted",
        ),
        (
            "state_fact",
            "freshness_ceiling_seconds",
            31_536_001,
            "freshness is malformed",
        ),
        (
            "state_fact",
            "completeness",
            True,
            "completeness is malformed",
        ),
        (
            "metadata",
            "verifier_revision",
            "",
            "verifier_revision is malformed",
        ),
        (
            "state_fact",
            "source_revision",
            "",
            "source_revision is malformed",
        ),
        (
            "state_fact",
            "effective_at",
            "2026-08-24T05:00:00Z",
            "timestamps are inconsistent",
        ),
        (
            "metadata",
            "source_schema_digest",
            f"sha256:{'f' * 64}",
            "not verified",
        ),
        (
            "state_fact",
            "evidence_cutoff",
            "2026-08-24T04:59:00+00:00:30",
            "evidence_cutoff is malformed",
        ),
        (
            "state_fact",
            "recorded_at",
            "2026-08-24T04:58:30Z",
            "timestamps are inconsistent",
        ),
    ],
)
def test_runtime_call_relationship_evidence_rejects_untrusted_bounds(
    location: str,
    field: str,
    value: object,
    message: str,
) -> None:
    metadata = _runtime_call_observation_metadata()
    if location == "metadata":
        metadata[field] = value
    else:
        _runtime_call_state_fact(metadata)[field] = value

    with pytest.raises(PostgresFamilyStoreUnavailable, match=message):
        _instance_relationship_evidence(
            {"link_observation_metadata": metadata},
            inventory_generation="inventory:generation-one",
        )


def test_provider_relationship_evidence_rejects_untrusted_method() -> None:
    evidence = _provider_relationship_evidence()
    evidence["evidence_method"] = "self-attested"

    with pytest.raises(PostgresFamilyStoreUnavailable, match="method is not trusted"):
        _instance_relationship_evidence(
            {"provider_relationship_evidence": evidence},
            inventory_generation="inventory:generation-one",
        )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda evidence: evidence.__setitem__("unexpected", True),
            "shape is malformed",
        ),
        (
            lambda evidence: evidence.__setitem__(
                "freshness_ceiling_seconds",
                31_536_001,
            ),
            "freshness is malformed",
        ),
    ],
)
def test_provider_relationship_evidence_rejects_malformed_claims(
    mutate: Any,
    message: str,
) -> None:
    evidence = _provider_relationship_evidence()
    mutate(evidence)

    with pytest.raises(PostgresFamilyStoreUnavailable, match=message):
        _instance_relationship_evidence(
            {"provider_relationship_evidence": evidence},
            inventory_generation="inventory:generation-one",
        )


def test_projection_source_reason_rejects_principal_text() -> None:
    with pytest.raises(PostgresFamilyStoreUnavailable, match="source state is malformed"):
        _projection_source_states(
            [
                {
                    "source": "postgres_role_evidence",
                    "status": "unavailable",
                    "observed_at": None,
                    "reason": "user@example.com",
                }
            ]
        )


def _runtime_call_observation_metadata() -> dict[str, object]:
    return {
        "state_fact": {
            "authority": "telemetry",
            "completeness": 1.0,
            "conflicts": [],
            "effective_at": "2026-08-24T04:58:00Z",
            "evidence_cutoff": "2026-08-24T04:59:00Z",
            "evidence_refs": ["sha256:" + "1" * 64, "telemetry:runtime-call:one"],
            "freshness_ceiling_seconds": 300,
            "lane": "observed",
            "recorded_at": "2026-08-24T05:00:00Z",
            "source_identity": "telemetry.runtime-calls",
            "source_revision": "1.0.0",
            "synthetic": False,
        },
        "verification_method": RUNTIME_CALL_VERIFICATION_METHOD,
        "verified": True,
        "verifier_identity": "inventory.endpoint-verifier",
        "verifier_revision": "1.0.0",
        "verification_receipt_ref": "sha256:" + "2" * 64,
        "inventory_generation": "inventory:generation-one",
        "mapping_id": RUNTIME_CALL_MAPPING_ID,
        "mapping_revision": RUNTIME_CALL_MAPPING_REVISION,
        "source_schema_version": RUNTIME_CALL_SOURCE_SCHEMA_VERSION,
        "source_schema_digest": RUNTIME_CALL_SOURCE_SCHEMA_DIGEST,
    }


def _runtime_call_state_fact(metadata: dict[str, object]) -> dict[str, object]:
    state_fact = metadata["state_fact"]
    assert isinstance(state_fact, dict)
    return state_fact


def _provider_relationship_evidence() -> dict[str, object]:
    return {
        "mapping_id": "azure.test-parent",
        "mapping_revision": "mapping-v1",
        "mapping_receipt_ref": "catalog-receipt:test",
        "source_identity": "azure-resource-graph",
        "source_property_path": "id.providerParent",
        "source_schema_version": "azure-resource-graph@1",
        "source_schema_digest": f"sha256:{'1' * 64}",
        "evidence_method": "deterministic-cross-check",
        "freshness_ceiling_seconds": 3_600,
        "observation_receipt_ref": f"sha256:{'2' * 64}",
    }


async def test_instance_neighborhood_returns_the_selected_induced_subgraph(
    monkeypatch: Any,
) -> None:
    statements: list[str] = []

    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self, parameters
        statements.append(statement)
        if "AND (from_id = %(root_id)s OR to_id = %(root_id)s)" in statement:
            return [
                {"from_id": "group", "link_type": "contains", "to_id": "root"},
                {"from_id": "endpoint", "link_type": "attached_to", "to_id": "root"},
            ]
        if "SELECT resource_id, resource_type, props, last_seen" in statement:
            return [
                {
                    "resource_id": "endpoint",
                    "resource_type": "network.private-endpoint",
                    "props": {},
                    "last_seen": None,
                },
                {
                    "resource_id": "group",
                    "resource_type": "resource-group",
                    "props": {},
                    "last_seen": None,
                },
                {
                    "resource_id": "root",
                    "resource_type": "postgresql-server",
                    "props": {},
                    "last_seen": None,
                },
            ]
        return [
            {
                "from_id": "group",
                "link_type": "contains",
                "to_id": "endpoint",
                "props": {},
            },
            {
                "from_id": "group",
                "link_type": "contains",
                "to_id": "root",
                "props": {},
            },
            {
                "from_id": "endpoint",
                "link_type": "attached_to",
                "to_id": "root",
                "props": {},
            },
        ]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    neighborhood = await store.read_inventory_instance_neighborhood(
        snapshot_id="generation-1",
        root_id="root",
        link_types=("contains", "attached_to"),
        depth=2,
        limit=10,
    )

    assert [(edge.source, edge.link_type, edge.target) for edge in neighborhood.edges] == [
        ("group", "contains", "endpoint"),
        ("group", "contains", "root"),
        ("endpoint", "attached_to", "root"),
    ]
    assert neighborhood.truncated is False
    assert any("from_id = ANY(%(resource_ids)s)" in statement for statement in statements)


async def test_instance_neighborhood_bounds_dense_induced_links(
    monkeypatch: Any,
) -> None:
    captured: list[tuple[str, Mapping[str, object]]] = []
    neighbors = tuple(f"neighbor-{index}" for index in range(14))

    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self
        captured.append((statement, parameters))
        if "NOT (to_id=ANY(%(selected)s))" in statement:
            if parameters["frontier"] != ["root"]:
                return []
            return [
                {
                    "from_id": neighbor,
                    "from_type": "resource-group",
                    "link_type": "contains",
                    "to_id": "root",
                    "to_type": "resource-group",
                    "props": {},
                }
                for neighbor in neighbors
            ]
        if "SELECT resource_id, resource_type, props, last_seen" in statement:
            return [
                {
                    "resource_id": resource_id,
                    "resource_type": "resource-group",
                    "props": {},
                    "last_seen": None,
                }
                for resource_id in ("root", *neighbors)
            ]
        return [
            {
                "from_id": neighbors[index % len(neighbors)],
                "link_type": f"link-{index // len(neighbors)}",
                "to_id": neighbors[(index + 1) % len(neighbors)],
                "props": {},
            }
            for index in range(1601)
        ]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    neighborhood = await store.read_inventory_instance_neighborhood(
        snapshot_id="generation-1",
        root_id="root",
        link_types=tuple(f"link-{index}" for index in range(15)),
        depth=2,
        limit=15,
    )

    assert len(neighborhood.resources) == 15
    assert len(neighborhood.edges) == 1600
    assert neighborhood.truncated is True
    assert neighborhood.truncation_reasons == ("link_limit",)
    induced_statement, induced_parameters = captured[-1]
    assert "ORDER BY CASE WHEN from_id = %(root_id)s OR to_id = %(root_id)s" in induced_statement
    assert induced_parameters["probe"] == 1601


async def test_postgres_instance_directory_and_activity_are_bounded_exact_reads(
    monkeypatch: Any,
) -> None:
    captured: list[tuple[str, Mapping[str, object]]] = []

    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self
        captured.append((statement, parameters))
        if "FROM inventory_snapshot_resource" in statement:
            return [
                {
                    "resource_id": "root",
                    "resource_type": "compute.container-app",
                    "props": {"name": "core"},
                    "last_seen": datetime(2026, 8, 22, tzinfo=UTC),
                },
                {
                    "resource_id": "extra",
                    "resource_type": "compute.container-app",
                    "props": {"name": "extra"},
                    "last_seen": None,
                },
            ]
        return [
            {
                "seq": 2,
                "correlation_id": None,
                "actor": "fdai.system",
                "action_kind": "audit.record",
                "entry": {"payload": {"resource_id": "root", "reason": "no_rule_match"}},
                "created_at": datetime(2026, 8, 22, tzinfo=UTC),
            },
            {
                "seq": 1,
                "correlation_id": None,
                "actor": "fdai.system",
                "action_kind": "audit.record",
                "entry": {"payload": {"resource_id": "root"}},
                "created_at": datetime(2026, 8, 21, tzinfo=UTC),
            },
        ]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    directory = await store.read_inventory_instances(
        snapshot_id="generation-1",
        search="core_%",
        limit=1,
    )
    activity = await store.read_inventory_instance_activity(resource_id="root", limit=1)

    assert len(directory.resources) == 1
    assert directory.truncated is True
    assert activity.activities[0].facts == {"reason": "no_rule_match"}
    assert activity.truncated is True
    assert captured[0][1] == {
        "snapshot_id": "generation-1",
        "pattern": "%core\\_\\%%",
        "probe": 2,
        "unselectable_types": ["authorization.role-assignment"],
    }
    assert "resource_type <> ALL(%(unselectable_types)s)" in captured[0][0]
    assert "entry #>> '{payload,resource_id}' = %(resource_id)s" in captured[1][0]
    assert captured[1][1] == {"resource_id": "root", "probe": 2}


async def test_postgres_operations_selects_role_scoped_exact_declaration(
    monkeypatch: Any,
) -> None:
    operations: list[str] = []

    async def read_projection(
        self: PostgresFamilyStore,
        *,
        family: str,
        operation: str,
    ) -> Mapping[str, object]:
        del self
        assert family == "operations"
        operations.append(operation)
        return {
            "purpose": "operations-review",
            "mutation_authority": False,
            "details": {
                "object-types": {
                    "Decision": {
                        "schema_version": "1.0.0",
                        "declaration_name": "Decision",
                        "mutation_authority": False,
                    }
                }
            },
        }

    monkeypatch.setattr(PostgresFamilyStore, "read_projection", read_projection)
    adapter = PostgresOperationsAdapters(
        PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))
    )
    query = ProjectionQuery(
        operation="ontology.declaration.detail",
        principal_id="principal-a",
        path={"kind": "object-types", "name": "Decision"},
        params={},
        limit=100,
        cursor=None,
        roles=frozenset({OperatorRole.READER, OperatorRole.APPROVER}),
    )

    detail = await adapter.read(query)

    assert detail["declaration_name"] == "Decision"
    assert operations == ["ontology.declaration.detail.approver"]

    with pytest.raises(ProjectionNotFoundError):
        await adapter.read(replace(query, path={"kind": "object-types", "name": "Unknown"}))


async def test_postgres_operations_replay_scopes_sql_to_authenticated_principal(
    monkeypatch: Any,
) -> None:
    captured: list[tuple[str, Mapping[str, object]]] = []

    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self
        captured.append((statement, parameters))
        return [
            {
                "seq": 8,
                "action_kind": "provision.progress",
                "entry": {"principal_id": "principal-a", "status": "running"},
            }
        ]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    adapter = PostgresOperationsAdapters(
        PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))
    )

    batch = await adapter.replay(ReplayQuery("provision", "principal-a", 7, 100))

    assert batch.events[0].sequence == 8
    statement, parameters = captured[0]
    assert "entry ->> 'principal_id' = %(principal_id)s" in statement
    assert parameters == {
        "after_sequence": 7,
        "stream": "provision",
        "principal_id": "principal-a",
        "limit": 100,
    }


async def test_postgres_replay_rejects_empty_principal_before_query(monkeypatch: Any) -> None:
    called = False

    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self, statement, parameters
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    try:
        await store.replay(stream="provision", principal_id="", after_sequence=None, limit=100)
    except ValueError as exc:
        assert "principal_id" in str(exc)
    else:
        raise AssertionError("empty replay principal did not fail closed")
    assert called is False


async def test_postgres_readiness_references_required_projection_schema(monkeypatch: Any) -> None:
    captured: list[str] = []

    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self
        assert parameters == {"expected_role": "fdai_operator"}
        captured.append(statement)
        return [{"ready": True}]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    assert await store.probe_readiness() is True
    statement = captured[0]
    assert "current_user = %(expected_role)s" in statement
    assert "has_table_privilege(current_user, 'state_kv', 'SELECT')" in statement
    assert "has_table_privilege(current_user, 'state_kv', 'INSERT')" in statement
    assert "has_table_privilege(current_user, 'audit_log', 'SELECT')" in statement
    assert "has_table_privilege(current_user, 'inventory_active', 'SELECT')" in statement


def _invalidation_row(
    *,
    sequence: object = 42,
    generation: str = "generation-1",
    observed_at: object = datetime(2026, 9, 6, 1, 0, tzinfo=UTC),
    recorded_at: object = datetime(2026, 9, 6, 1, 0, 5, tzinfo=UTC),
    aligned: bool = True,
) -> dict[str, object]:
    digest = "sha256:" + "a" * 64
    return {
        "marker": {
            "schema_version": "1.0.0",
            "sequence": sequence,
            "generation": generation,
            "manifest_digest": digest,
            "complete": True,
            "execution_authority": False,
            "mutation_authority": False,
        },
        "active_generation": generation if aligned else "generation-2",
        "manifest": {
            "generation": generation,
            "manifest_digest": digest,
            "complete": True,
        },
        "observed_at": observed_at,
        "recorded_at": recorded_at,
    }


def test_projection_source_states_accept_model_serving_metrics() -> None:
    states = _projection_source_states(
        [
            {
                "source": "azure_model_serving_metrics",
                "status": "available",
                "observed_at": "2026-09-16T02:00:00+00:00",
                "reason": None,
                "coverage": {"observed": 3, "targets": 5},
            }
        ]
    )

    assert states[0].source == "azure_model_serving_metrics"
    assert states[0].status == "available"


async def test_inventory_invalidation_initial_connect_establishes_watermark_without_full_replay(
    monkeypatch: Any,
) -> None:
    captured: list[tuple[str, Mapping[str, object]]] = []

    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self
        captured.append((statement, parameters))
        return [_invalidation_row()]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    events = await store.replay(
        stream=INVENTORY_INVALIDATION_STREAM,
        principal_id="reader-oid",
        after_sequence=None,
        limit=1,
    )

    assert len(events) == 1
    event = events[0]
    assert event.sequence == 42
    assert event.event == "inventory.invalidated"
    assert event.data == {
        "schema_version": "1.0.0",
        "watermark": 42,
        "observation_count": 1,
        "observed_at": "2026-09-06T01:00:00+00:00",
        "recorded_at": "2026-09-06T01:00:05+00:00",
        "complete": False,
        "execution_authority": False,
        "mutation_authority": False,
    }
    statement, parameters = captured[0]
    assert "inventory_observation_journal" not in statement
    assert "inventory_active" in statement
    assert parameters == {
        "manifest_key": "inventory-ontology:manifest",
        "marker_key": "inventory-ontology:invalidation",
    }


async def test_inventory_invalidation_initial_connect_without_a_commit_yields_no_event(
    monkeypatch: Any,
) -> None:
    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self, statement, parameters
        return []

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    events = await store.replay(
        stream=INVENTORY_INVALIDATION_STREAM,
        principal_id="reader-oid",
        after_sequence=None,
        limit=500,
    )

    # Pre-projection journal rows are not queried, so no committed marker means
    # there is no browser-visible change.
    assert events == ()


async def test_inventory_invalidation_subsequent_poll_with_no_new_rows_yields_no_event(
    monkeypatch: Any,
) -> None:
    captured: list[tuple[str, Mapping[str, object]]] = []

    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self
        captured.append((statement, parameters))
        return [_invalidation_row(sequence=42)]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    events = await store.replay(
        stream=INVENTORY_INVALIDATION_STREAM,
        principal_id="reader-oid",
        after_sequence=42,
        limit=500,
    )

    assert events == ()
    statement, parameters = captured[0]
    assert "inventory-ontology:invalidation" not in statement
    assert parameters["marker_key"] == "inventory-ontology:invalidation"


async def test_inventory_invalidation_emits_one_committed_projection_event(
    monkeypatch: Any,
) -> None:
    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self, statement, parameters
        return [
            _invalidation_row(
                sequence=45,
                observed_at=datetime(2026, 9, 6, 1, 0, 9, tzinfo=UTC),
                recorded_at=datetime(2026, 9, 6, 1, 0, 10, tzinfo=UTC),
            )
        ]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    events = await store.replay(
        stream=INVENTORY_INVALIDATION_STREAM,
        principal_id="reader-oid",
        after_sequence=42,
        limit=500,
    )

    assert len(events) == 1
    event = events[0]
    assert event.sequence == 45
    assert event.data["watermark"] == 45
    assert event.data["observation_count"] == 1
    assert event.data["observed_at"] == "2026-09-06T01:00:09+00:00"
    assert event.data["recorded_at"] == "2026-09-06T01:00:10+00:00"


async def test_inventory_invalidation_rejects_a_malformed_watermark(monkeypatch: Any) -> None:
    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self, statement, parameters
        return [_invalidation_row(sequence="not-a-number")]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    with pytest.raises(PostgresFamilyStoreUnavailable, match="marker is malformed"):
        await store.replay(
            stream=INVENTORY_INVALIDATION_STREAM,
            principal_id="reader-oid",
            after_sequence=0,
            limit=500,
        )


async def test_inventory_invalidation_rejects_a_missing_observed_at(monkeypatch: Any) -> None:
    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self, statement, parameters
        return [_invalidation_row(observed_at=None)]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    with pytest.raises(PostgresFamilyStoreUnavailable, match="timestamps are malformed"):
        await store.replay(
            stream=INVENTORY_INVALIDATION_STREAM,
            principal_id="reader-oid",
            after_sequence=0,
            limit=500,
        )


async def test_inventory_invalidation_rejects_a_missing_recorded_at(monkeypatch: Any) -> None:
    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self, statement, parameters
        return [_invalidation_row(recorded_at=None)]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    with pytest.raises(PostgresFamilyStoreUnavailable, match="timestamps are malformed"):
        await store.replay(
            stream=INVENTORY_INVALIDATION_STREAM,
            principal_id="reader-oid",
            after_sequence=0,
            limit=500,
        )


async def test_inventory_invalidation_ignores_replay_page_size_for_one_commit(
    monkeypatch: Any,
) -> None:
    """The committed marker is one event regardless of the generic replay page size."""
    captured: list[Mapping[str, object]] = []

    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self, statement
        captured.append(parameters)
        return [_invalidation_row(sequence=47)]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    events = await store.replay(
        stream=INVENTORY_INVALIDATION_STREAM,
        principal_id="reader-oid",
        after_sequence=42,
        limit=5,
    )

    assert len(events) == 1
    assert events[0].data["observation_count"] == 1
    assert captured[0]["marker_key"] == "inventory-ontology:invalidation"


async def test_inventory_invalidation_never_leaks_extra_commit_row_columns(
    monkeypatch: Any,
) -> None:
    """Even if the row carries extra columns, only the sanitized fields survive."""

    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self, statement, parameters
        return [
            {
                **_invalidation_row(sequence=50),
                "subject_ref": "resource-1",
                "provider_ref": "azure:vm:1",
                "properties": {"secret": "value"},
                "source_identity": "principal-a",
            }
        ]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    events = await store.replay(
        stream=INVENTORY_INVALIDATION_STREAM,
        principal_id="reader-oid",
        after_sequence=42,
        limit=500,
    )

    assert len(events) == 1
    assert set(events[0].data) == {
        "schema_version",
        "watermark",
        "observation_count",
        "observed_at",
        "recorded_at",
        "complete",
        "execution_authority",
        "mutation_authority",
    }


async def test_inventory_invalidation_waits_for_active_committed_generation(
    monkeypatch: Any,
) -> None:
    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self, statement, parameters
        return [_invalidation_row(sequence=50, aligned=False)]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    events = await store.replay(
        stream=INVENTORY_INVALIDATION_STREAM,
        principal_id="reader-oid",
        after_sequence=42,
        limit=500,
    )

    assert events == ()


async def test_inventory_invalidation_replay_wraps_into_one_operations_replay_batch(
    monkeypatch: Any,
) -> None:
    """The generic operations adapter coalesces the store's tuple into one ReplayBatch."""

    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self, statement, parameters
        return [_invalidation_row(sequence=9)]

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    adapter = PostgresOperationsAdapters(
        PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))
    )

    batch = await adapter.replay(ReplayQuery(INVENTORY_INVALIDATION_STREAM, "reader-oid", None, 1))

    assert len(batch.events) == 1
    assert batch.events[0].event == "inventory.invalidated"
    assert batch.watermark == 9
