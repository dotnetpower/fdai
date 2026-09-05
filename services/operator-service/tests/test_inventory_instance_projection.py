"""Focused contract tests for bounded ontology Resource instance exploration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fdai_operator_service.context_selection import ContextSelectionRegistry
from fdai_operator_service.families.operations.contracts import (
    InventoryImpactContext,
    InventoryInstanceActivity,
    InventoryInstanceActivityPage,
    InventoryInstanceEdge,
    InventoryInstanceNeighborhood,
    InventoryInstanceResource,
    InventoryInstanceResourcePage,
    InventoryProjectionSourceState,
    InventoryRelationshipCoverage,
    InventoryRelationshipDropClassification,
    InventoryRelationshipEvidence,
    ProjectionQuery,
)
from fdai_operator_service.families.operations.instance_explorer import (
    _relationship_evidence_projection,
    _resource_capacity,
    _resource_status,
    project_inventory_instance,
    project_inventory_instances,
)
from fdai_operator_service.families.operations.recorded_state import (
    RecordedStateObservation,
    recorded_resource_states,
)
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
)
from fdai_operator_service.redaction import redact_projection
from fdai_service_contracts import OperatorRole
from fdai_service_contracts.ontology_query import content_digest


class _Reader:
    async def read_inventory_impact_context(self) -> InventoryImpactContext:
        return InventoryImpactContext(
            snapshot_id="generation-1",
            observed_at=datetime(2026, 8, 22, 1, 0, tzinfo=UTC),
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
            ),
            projection_source_states=(
                InventoryProjectionSourceState(
                    source="kubernetes_runtime_inventory",
                    status="unavailable",
                    observed_at=None,
                    reason="kubernetes_source_unconfigured",
                ),
                InventoryProjectionSourceState(
                    source="runtime_call_graph",
                    status="available",
                    observed_at=datetime(2026, 8, 22, 0, 57, tzinfo=UTC),
                    reason=None,
                ),
                InventoryProjectionSourceState(
                    source="postgres_role_evidence",
                    status="unavailable",
                    observed_at=None,
                    reason="database_role_observation_unavailable",
                ),
            ),
        )

    async def read_inventory_instance_neighborhood(
        self,
        *,
        snapshot_id: str,
        root_id: str,
        link_types: tuple[str, ...],
        depth: int,
        limit: int,
    ) -> InventoryInstanceNeighborhood:
        assert (snapshot_id, root_id, link_types, depth, limit) == (
            "generation-1",
            "container-app-1",
            ("contains", "attached_to", "depends_on"),
            6,
            25,
        )
        return InventoryInstanceNeighborhood(
            resources=(
                InventoryInstanceResource(
                    resource_id="container-app-1",
                    resource_type="compute.container-app",
                    properties={
                        "name": "core",
                        "location": "koreacentral",
                        "resourceGroup": "resource-group-one",
                        "properties": {"provisioningState": "Succeeded", "secret": "hidden"},
                        "tags": {"owner": "hidden"},
                    },
                    last_seen=datetime(2026, 8, 22, 0, 59, tzinfo=UTC),
                ),
                InventoryInstanceResource(
                    resource_id="environment-1",
                    resource_type="compute.container-app-environment",
                    properties={"name": "environment"},
                    last_seen=None,
                ),
            ),
            edges=(
                InventoryInstanceEdge(
                    "container-app-1",
                    "environment-1",
                    "depends_on",
                    InventoryRelationshipEvidence(
                        source_identity="azure-resource-graph",
                        source_property_path="properties.managedEnvironmentId",
                        mapping_id="azure.container-app-depends-on-managed-environment",
                        evidence_method="deterministic-cross-check",
                        freshness_ceiling_seconds=21600,
                    ),
                ),
                InventoryInstanceEdge(
                    "environment-1",
                    "container-app-1",
                    "contains",
                ),
            ),
            truncated=False,
        )

    async def read_inventory_instance_activity(
        self,
        *,
        resource_id: str,
        limit: int,
    ) -> InventoryInstanceActivityPage:
        assert (resource_id, limit) == ("container-app-1", 10)
        return InventoryInstanceActivityPage(
            activities=(
                InventoryInstanceActivity(
                    sequence=42,
                    action_kind="audit.record",
                    actor="fdai.system",
                    recorded_at=datetime(2026, 8, 22, 0, 58, tzinfo=UTC),
                    correlation_id=None,
                    facts={"reason": "no_rule_match", "secret": "hidden"},
                ),
            ),
            truncated=False,
        )

    async def read_inventory_instances(
        self,
        *,
        snapshot_id: str,
        search: str | None,
        limit: int,
    ) -> InventoryInstanceResourcePage:
        assert (snapshot_id, search, limit) == ("generation-1", "core", 25)
        return InventoryInstanceResourcePage(
            resources=(
                InventoryInstanceResource(
                    resource_id="container-app-1",
                    resource_type="compute.container-app",
                    properties={"name": "core", "tags": {"secret": "hidden"}},
                    last_seen=None,
                ),
            ),
            truncated=False,
        )


async def test_instance_directory_uses_the_active_detail_generation() -> None:
    selection_registry = ContextSelectionRegistry()
    result = await project_inventory_instances(
        query=ProjectionQuery(
            operation="ontology.instance.list",
            principal_id="reader",
            path={},
            params={"search": ("core",)},
            limit=25,
            cursor=None,
            roles=frozenset({OperatorRole.READER}),
        ),
        reader=_Reader(),
        ontology_projection={
            "ontology_release_digest": f"sha256:{'a' * 64}",
            "link_types": ["contains"],
        },
        selection_registry=selection_registry,
    )

    assert result["source_generation"] == "generation-1"
    assert result["search"] == "core"
    assert result["complete"] is True
    assert result["principal_id"] == "reader"
    assert result["principal_scope_digest"] == content_digest(
        {"principal_id": "reader", "role": "reader", "purpose": "operations-review"}
    )
    assert isinstance(result["selection_digest"], str)
    capability = result["context_capability"]
    assert isinstance(capability, dict)
    token = capability.get("selection_token")
    assert isinstance(token, str)
    resolved = selection_registry.resolve(
        token,
        principal_id="reader",
        role="reader",
        purpose="operations-review",
    )
    assert resolved is not None
    assert redact_projection(result)["context_capability"] == capability
    resources = result["resources"]
    assert isinstance(resources, list)
    assert resources == [
        {
            "id": "container-app-1",
            "object_type": "Resource",
            "resource_type": "compute.container-app",
            "name": "core",
            "location": None,
            "resource_group": None,
            "subscription_id": None,
            "status": None,
            "states": recorded_resource_states(
                {},
                resource_type="compute.container-app",
            ),
            "last_seen": None,
            "selected": False,
        }
    ]


async def test_empty_instance_directory_omits_context_selection_identity() -> None:
    class _EmptyReader(_Reader):
        async def read_inventory_instances(
            self,
            *,
            snapshot_id: str,
            search: str | None,
            limit: int,
        ) -> InventoryInstanceResourcePage:
            assert (snapshot_id, search, limit) == ("generation-1", "missing", 25)
            return InventoryInstanceResourcePage(resources=(), truncated=False)

    result = await project_inventory_instances(
        query=ProjectionQuery(
            operation="ontology.instance.list",
            principal_id="reader",
            path={},
            params={"search": ("missing",)},
            limit=25,
            cursor=None,
            roles=frozenset({OperatorRole.READER}),
        ),
        reader=_EmptyReader(),
        ontology_projection={
            "ontology_release_digest": f"sha256:{'a' * 64}",
            "link_types": ["contains"],
        },
        selection_registry=ContextSelectionRegistry(),
    )

    assert result["resources"] == []
    assert result["complete"] is True
    assert "context_capability" not in result
    assert "selection_digest" not in result


async def test_instance_selection_token_excludes_hidden_role_assignments() -> None:
    class _CompleteReader(_Reader):
        async def read_inventory_impact_context(self) -> InventoryImpactContext:
            context = await super().read_inventory_impact_context()
            return replace(
                context,
                relationship_drop_reasons=(),
                relationship_drop_classifications=(),
            )

        async def read_inventory_instance_neighborhood(
            self,
            **kwargs: object,
        ) -> InventoryInstanceNeighborhood:
            neighborhood = await super().read_inventory_instance_neighborhood(**kwargs)  # type: ignore[arg-type]
            return replace(
                neighborhood,
                resources=(
                    *neighborhood.resources,
                    InventoryInstanceResource(
                        resource_id="role-assignment-1",
                        resource_type="authorization.role-assignment",
                        properties={"name": "hidden-role"},
                        last_seen=None,
                    ),
                ),
            )

    registry = ContextSelectionRegistry()
    result = await project_inventory_instance(
        query=ProjectionQuery(
            operation="ontology.instance.explore",
            principal_id="reader",
            path={},
            params={"root": ("container-app-1",), "activity_limit": ("10",)},
            limit=25,
            cursor=None,
            roles=frozenset({OperatorRole.READER}),
        ),
        reader=_CompleteReader(),
        ontology_projection={
            "ontology_release_digest": f"sha256:{'a' * 64}",
            "link_types": ["contains", "attached_to", "depends_on"],
        },
        selection_registry=registry,
        now=lambda: datetime(2026, 8, 22, 2, 0, tzinfo=UTC),
    )

    token = result["context_capability"]["selection_token"]  # type: ignore[index]
    selection = registry.resolve(
        token,  # type: ignore[arg-type]
        principal_id="reader",
        role="reader",
        purpose="operations-review",
    )
    assert selection is not None
    assert selection["resource_ids"] == ["container-app-1", "environment-1"]
    assert "role-assignment-1" not in selection["resource_ids"]


async def test_instance_projection_combines_snapshot_neighborhood_and_activity() -> None:
    result = await project_inventory_instance(
        query=ProjectionQuery(
            operation="ontology.instance.explore",
            principal_id="reader",
            path={},
            params={"root": ("container-app-1",), "activity_limit": ("10",)},
            limit=25,
            cursor=None,
            roles=frozenset({OperatorRole.READER}),
        ),
        reader=_Reader(),
        ontology_projection={
            "ontology_release_digest": f"sha256:{'a' * 64}",
            "link_types": [
                "caused_by",
                "contains",
                "attached_to",
                "depends_on",
                "governed_by",
            ],
        },
        now=lambda: datetime(2026, 8, 22, 2, 0, tzinfo=UTC),
    )

    assert result["source_generation"] == "generation-1"
    assert result["complete"] is False
    assert result["execution_authority"] is False
    assert result["mutation_authority"] is False
    assert result["resources"] == [
        {
            "id": "container-app-1",
            "object_type": "Resource",
            "resource_type": "compute.container-app",
            "name": "core",
            "location": "koreacentral",
            "resource_group": "resource-group-one",
            "subscription_id": None,
            "status": "Succeeded",
            "states": recorded_resource_states(
                {"properties": {"provisioningState": "Succeeded"}},
                resource_type="compute.container-app",
                observation=RecordedStateObservation(
                    generation="generation-1",
                    observed_at=datetime(2026, 8, 22, 0, 59, tzinfo=UTC),
                    recorded_at=datetime(2026, 8, 22, 1, 0, tzinfo=UTC),
                ),
                now=datetime(2026, 8, 22, 2, 0, tzinfo=UTC),
            ),
            "last_seen": "2026-08-22T00:59:00+00:00",
            "selected": True,
        },
        {
            "id": "environment-1",
            "object_type": "Resource",
            "resource_type": "compute.container-app-environment",
            "name": "environment",
            "location": None,
            "resource_group": None,
            "subscription_id": None,
            "status": None,
            "states": recorded_resource_states(
                {},
                resource_type="compute.container-app-environment",
            ),
            "last_seen": None,
            "selected": False,
        },
    ]
    assert result["schema_version"] == "1.4.0"
    assert result["relationship_coverage"] is None
    assert result["relationship_drop_classifications"] == [
        {
            "reason": "missing_target_endpoint",
            "mapping_id": "azure.example-depends-on-target",
            "source_property_path": "properties.target.id",
            "source_provider_type": "microsoft.example/widgets",
            "target_provider_type": "Microsoft.Example/targets",
            "unavailable_reason": "target_outside_active_generation",
            "count": 2,
        }
    ]
    assert result["depth"] == 6
    assert result["links"] == [
        {
            "source": "container-app-1",
            "target": "environment-1",
            "link_type": "depends_on",
            "evidence": {
                "status": "available",
                "evidence_kind": "configuration",
                "verification_status": "configuration_observed",
                "source": "azure-resource-graph",
                "source_property_path": "properties.managedEnvironmentId",
                "mapping_id": "azure.container-app-depends-on-managed-environment",
                "evidence_method": "deterministic-cross-check",
                "cutoff": "2026-08-22T01:00:00+00:00",
                "freshness_ceiling_seconds": 21600,
                "complete": True,
                "reason": None,
            },
        },
        {
            "source": "environment-1",
            "target": "container-app-1",
            "link_type": "contains",
            "evidence": {
                "status": "unavailable",
                "evidence_kind": None,
                "verification_status": "unavailable",
                "source": None,
                "source_property_path": None,
                "mapping_id": None,
                "evidence_method": None,
                "cutoff": None,
                "freshness_ceiling_seconds": None,
                "complete": False,
                "reason": "provider_relationship_evidence_unavailable",
            },
        },
    ]
    assert result["timeline"] == {
        "items": [
            {
                "sequence": 42,
                "action_kind": "audit.record",
                "actor": "fdai.system",
                "recorded_at": "2026-08-22T00:58:00+00:00",
                "correlation_id": None,
                "facts": {"reason": "no_rule_match"},
                "evidence_ref": "audit:42",
            }
        ],
        "complete": True,
        "truncation_reason": None,
    }
    sources = result["sources"]
    assert isinstance(sources, list)
    assert sources[-5] == {
        "source": "runtime_call_graph",
        "status": "available",
        "observed_at": "2026-08-22T00:57:00+00:00",
        "reason": None,
    }
    assert sources[-4:] == [
        {
            "source": "kubernetes_runtime_inventory",
            "status": "unavailable",
            "observed_at": None,
            "reason": "kubernetes_source_unconfigured",
        },
        {
            "source": "postgres_role_evidence",
            "status": "unavailable",
            "observed_at": None,
            "reason": "database_role_observation_unavailable",
        },
        {
            "source": "azure_resource_health",
            "status": "unavailable",
            "observed_at": None,
            "reason": "projection_not_bound",
        },
        {
            "source": "azure_activity_log",
            "status": "unavailable",
            "observed_at": None,
            "reason": "projection_not_bound",
        },
    ]


class _FullCoverageReader(_Reader):
    """Extend ``_Reader`` with every derived source state and a coverage count."""

    async def read_inventory_impact_context(self) -> InventoryImpactContext:
        base = await super().read_inventory_impact_context()
        return replace(
            base,
            projection_source_states=(
                *base.projection_source_states,
                InventoryProjectionSourceState(
                    source="azure_resource_health",
                    status="available",
                    observed_at=datetime(2026, 8, 22, 0, 55, tzinfo=UTC),
                    reason=None,
                ),
                InventoryProjectionSourceState(
                    source="azure_activity_log",
                    status="unavailable",
                    observed_at=None,
                    reason="activity_log_query_unavailable",
                ),
            ),
            relationship_coverage=InventoryRelationshipCoverage(
                materialized=4,
                reviewed_unavailable=1,
                unclassified=0,
                total_candidates=5,
                complete=False,
            ),
        )

    async def read_inventory_instance_neighborhood(
        self,
        *,
        snapshot_id: str,
        root_id: str,
        link_types: tuple[str, ...],
        depth: int,
        limit: int,
    ) -> InventoryInstanceNeighborhood:
        neighborhood = await super().read_inventory_instance_neighborhood(
            snapshot_id=snapshot_id,
            root_id=root_id,
            link_types=link_types,
            depth=depth,
            limit=limit,
        )
        return replace(neighborhood, truncated=True)

    async def read_inventory_instance_activity(
        self,
        *,
        resource_id: str,
        limit: int,
    ) -> InventoryInstanceActivityPage:
        activity = await super().read_inventory_instance_activity(
            resource_id=resource_id,
            limit=limit,
        )
        return replace(activity, truncated=True)


async def test_instance_projection_reports_full_source_coverage_and_truncation_reasons() -> None:
    result = await project_inventory_instance(
        query=ProjectionQuery(
            operation="ontology.instance.explore",
            principal_id="reader",
            path={},
            params={"root": ("container-app-1",), "activity_limit": ("10",)},
            limit=25,
            cursor=None,
            roles=frozenset({OperatorRole.READER}),
        ),
        reader=_FullCoverageReader(),
        ontology_projection={
            "ontology_release_digest": f"sha256:{'a' * 64}",
            "link_types": [
                "caused_by",
                "contains",
                "attached_to",
                "depends_on",
                "governed_by",
            ],
        },
        now=lambda: datetime(2026, 8, 22, 2, 0, tzinfo=UTC),
    )

    assert result["relationship_coverage"] == {
        "materialized": 4,
        "reviewed_unavailable": 1,
        "unclassified": 0,
        "total_candidates": 5,
        "complete": False,
    }
    assert result["truncation_reasons"] == ["resource_limit", "activity_limit"]
    assert result["complete"] is False
    sources = result["sources"]
    assert isinstance(sources, list)
    assert sources[-2:] == [
        {
            "source": "azure_resource_health",
            "status": "available",
            "observed_at": "2026-08-22T00:55:00+00:00",
            "reason": None,
        },
        {
            "source": "azure_activity_log",
            "status": "unavailable",
            "observed_at": None,
            "reason": "activity_log_query_unavailable",
        },
    ]


async def test_instance_projection_marks_expired_relationship_evidence_stale() -> None:
    result = await project_inventory_instance(
        query=ProjectionQuery(
            operation="ontology.instance.explore",
            principal_id="reader",
            path={},
            params={"root": ("container-app-1",), "activity_limit": ("10",)},
            limit=25,
            cursor=None,
            roles=frozenset({OperatorRole.READER}),
        ),
        reader=_Reader(),
        ontology_projection={
            "ontology_release_digest": f"sha256:{'a' * 64}",
            "link_types": ["contains", "attached_to", "depends_on"],
        },
        now=lambda: datetime(2026, 8, 22, 8, 0, 1, tzinfo=UTC),
    )

    links = result["links"]
    assert isinstance(links, list)
    evidence = links[0]["evidence"]
    assert evidence["status"] == "stale"
    assert evidence["verification_status"] == "configuration_observed"
    assert evidence["complete"] is False
    assert evidence["reason"] == "relationship_evidence_stale"


def test_relationship_evidence_freshness_boundaries_and_verification_level() -> None:
    cutoff = datetime(2026, 8, 22, 1, 0, tzinfo=UTC)
    evidence = InventoryRelationshipEvidence(
        source_identity="runtime-telemetry",
        source_property_path="caller_resource_ids,target_resource_ids",
        mapping_id="runtime-call-endpoint-identity",
        evidence_method="deterministic-cross-check",
        freshness_ceiling_seconds=300,
        evidence_kind="observation",
        evidence_cutoff=cutoff,
    )

    current = _relationship_evidence_projection(
        evidence,
        cutoff=cutoff,
        evaluated_at=datetime(2026, 8, 22, 1, 5, tzinfo=UTC),
    )
    assert current["status"] == "available"
    assert current["verification_status"] == "independently_verified"
    assert current["complete"] is True

    future = _relationship_evidence_projection(
        evidence,
        cutoff=cutoff,
        evaluated_at=datetime(2026, 8, 22, 0, 59, 59, tzinfo=UTC),
    )
    assert future["status"] == "stale"
    assert future["complete"] is False
    assert future["reason"] == "relationship_evidence_future_cutoff"


def test_observed_kubernetes_state_is_reported_instead_of_absent_status() -> None:
    assert _resource_status({"phase": "Running", "ready_status": "True"}) == "Running"
    assert _resource_status({"ready_status": "True"}) == "Ready"
    assert _resource_status({"ready_status": "False"}) == "NotReady"
    assert _resource_status({"ready_status": "Unknown"}) == "Ready unknown"
    assert _resource_status({"provisioningState": "Succeeded"}) == "Succeeded"
    assert _resource_status({"name": "kube-system"}) is None


def test_scalable_resource_capacity_uses_only_allowlisted_fields() -> None:
    assert (
        _resource_capacity(
            "kubernetes-node-pool",
            {"properties": {"count": 2}},
        )
        == 2
    )
    assert _resource_capacity("compute.vm-scale-set", {"sku": {"capacity": 3}}) == 3
    assert (
        _resource_capacity(
            "kubernetes-node-pool",
            {"properties": {"count": -1}},
        )
        is None
    )
    assert _resource_capacity("compute.vm", {"sku": {"capacity": 3}}) is None


async def test_a_realtime_event_refreshes_a_resource_without_erasing_its_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_id = "scope/resource-group/rg/providers/microsoft.example/widgets/one"
    statements: list[str] = []

    async def fetch_all(
        self: PostgresFamilyStore,
        statement: str,
        parameters: Mapping[str, object],
    ) -> list[dict[str, object]]:
        del self, parameters
        statements.append(statement)
        if "WHERE resource_id=%(root_id)s" in statement:
            return [
                {
                    "resource_id": root_id,
                    "resource_type": "microsoft.example/widgets",
                    "props": {"name": "one"},
                    "last_seen": datetime(2026, 8, 22, 1, 0, tzinfo=UTC),
                }
            ]
        return []

    monkeypatch.setattr(PostgresFamilyStore, "_fetch_all", fetch_all)
    store = PostgresFamilyStore(PostgresFamilyStoreConfig("postgresql://example.invalid/fdai"))

    await store.read_inventory_instance_neighborhood(
        snapshot_id="generation-1",
        root_id=root_id,
        link_types=("contains",),
        depth=1,
        limit=10,
    )

    assert statements, "the neighborhood read MUST issue at least one statement"
    resource_query = statements[0]
    # Replacing the snapshot row with the event row dropped name, location, and resource group.
    assert "snapshot.props || overlay.props" in resource_query
    assert "LEFT JOIN inventory_realtime_resource overlay" in resource_query
    assert (
        "AND NOT EXISTS (SELECT 1 FROM inventory_realtime_resource overlay "
        "WHERE overlay.resource_id=inventory_snapshot_resource.resource_id)"
    ) not in resource_query
    # Merging must not resurrect what a realtime delete removed.
    assert "removed.change_kind='delete'" in resource_query

    link_queries = [statement for statement in statements if "effective_links" in statement]
    assert link_queries, "the neighborhood read MUST read relationships"
    for link_query in link_queries:
        # Replacing the snapshot link with the event link dropped its relationship evidence.
        assert "snapshot.props || overlay.props" in link_query
        assert "LEFT JOIN inventory_realtime_link overlay" in link_query
        assert "NOT EXISTS (SELECT 1 FROM inventory_realtime_link overlay" not in link_query
        assert "removed.change_kind='delete'" in link_query
