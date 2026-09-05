from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts/deployment/local/refresh-authoritative-inventory.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("refresh_authoritative_inventory", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_refresh_binds_projection_to_loaded_ontology_release() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "ontology_release_digest=ontology.build_release().digest" in source
    assert "resource_type_mappings=resource_type_mapping_digests(resource_types)" in source
    assert "promotion_enricher=UnavailableKubernetesInventoryEnricher()" in source
    assert "relationship_mapping_catalog=load_provider_relationship_mapping_catalog(" in source
    assert "scope_coverage=query_factory.build_scope_coverage_fn()" in source
    assert "unmapped_resources=query_factory.build_unmapped_resource_query_fn()" in source


def test_operator_projection_is_bounded_and_filters_unsupported_links() -> None:
    module = _module()
    payload = module._operator_inventory_payload(
        snapshot_id="example-snapshot",
        snapshot_at=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
        now=datetime(2026, 8, 10, 12, 1, tzinfo=UTC),
        source="example-inventory",
        observation_kind=module.InventoryObservationKind.OBSERVED,
        freshness_budget_seconds=86400,
        resource_rows=[
            {
                "resource_id": "scope/resource-group/example",
                "resource_type": "resource-group",
                "props": {"name": "example"},
            },
            {
                "resource_id": "scope/resource-group/example/vnet/one",
                "resource_type": "network.vnet",
                "props": {"name": "one", "status": "Ready"},
            },
            {
                "resource_id": "scope/resource-group/example/vnet/two",
                "resource_type": "network.vnet",
                "props": {"name": "two", "status": "Ready"},
            },
        ],
        link_rows=[
            {
                "from_id": "scope/resource-group/example",
                "link_type": "contains",
                "to_id": "scope/resource-group/example/vnet/one",
            },
            {
                "from_id": "scope/resource-group/example/vnet/one",
                "link_type": "peered_with",
                "to_id": "scope/resource-group/example/vnet/two",
            },
            {
                "from_id": "scope/resource-group/example/vnet/two",
                "link_type": "peered_with",
                "to_id": "scope/resource-group/example/vnet/missing",
            },
        ],
    )

    assert payload["source"] == "example-inventory"
    assert payload["snapshot_id"] == "example-snapshot"
    assert payload["observation_kind"] == "observed"
    assert payload["cache"]["age_seconds"] == 60
    assert payload["cursor"] == "example-snapshot"
    assert payload["truncated"] is False
    assert payload["links"] == [
        {
            "source": "scope/resource-group/example",
            "target": "scope/resource-group/example/vnet/one",
            "type": "contains",
        },
        {
            "source": "scope/resource-group/example/vnet/one",
            "target": "scope/resource-group/example/vnet/two",
            "type": "peered_with",
        },
    ]
    resources = payload["resources"]
    assert isinstance(resources, list)
    assert resources[1]["parent_id"] == "scope/resource-group/example"
    assert resources[1]["status"] == "Ready"
    assert payload["included_link_types"] == [
        "contains",
        "attached_to",
        "depends_on",
        "peered_with",
    ]


def test_operator_projection_does_not_claim_expired_or_expected_inventory_is_fresh() -> None:
    module = _module()
    for kind, age in [
        (module.InventoryObservationKind.OBSERVED, 2),
        (module.InventoryObservationKind.EXPECTED, 0),
    ]:
        payload = module._operator_inventory_payload(
            snapshot_id="example-snapshot",
            snapshot_at=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
            now=datetime(2026, 8, 10 + age, 12, 0, tzinfo=UTC),
            source="example-inventory",
            observation_kind=kind,
            freshness_budget_seconds=86400,
            resource_rows=[],
            link_rows=[],
        )
        assert payload["freshness"] == "stale"
        assert payload["cache"]["status"] == "stale"
        assert payload["observation_kind"] == kind.value


def test_operator_projection_preserves_unreconciled_changes_and_newer_failures() -> None:
    module = _module()
    payload = module._operator_inventory_payload(
        snapshot_id="example-snapshot",
        snapshot_at=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
        now=datetime(2026, 8, 10, 12, 1, tzinfo=UTC),
        source="example-inventory",
        observation_kind=module.InventoryObservationKind.OBSERVED,
        freshness_budget_seconds=86400,
        resource_rows=[],
        link_rows=[],
        pending_changes=3,
        newer_failure=True,
    )
    assert payload["freshness"] == "unknown"
    assert payload["cache"]["status"] == "stale"
    assert payload["realtime"]["pending_changes"] == 3
    assert payload["coverage_gaps"] == ["newer_inventory_failure"]


def test_operator_projection_carries_promoted_snapshot_provenance() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "SELECT s.id, s.completed_at, s.source, s.observation_kind" in source
    assert 'snapshot_id=str(snapshot["id"])' in source
    assert 'observation_kind=InventoryObservationKind(snapshot["observation_kind"])' in source
