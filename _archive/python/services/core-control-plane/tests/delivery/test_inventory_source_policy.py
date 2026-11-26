"""Focused tests for validated inventory source policies."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from fdai.delivery.inventory_source_policy import (
    CollectionSourceKind,
    InventoryCollectionPolicy,
    load_inventory_collection_policy,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]


def _policy_document() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "sources": [
            {
                "source_id": "provider-delta",
                "source_kind": "delta",
                "target_freshness_seconds": 120,
                "max_staleness_seconds": 600,
                "min_poll_interval_seconds": 5,
                "max_poll_interval_seconds": 120,
                "budget_window_seconds": 60,
                "max_requests_per_window": 120,
                "max_bytes_per_window": 16_777_216,
                "global_concurrency_limit": 16,
                "scope_concurrency_limit": 8,
                "resource_type_concurrency_limit": 4,
                "endpoint_concurrency_limit": 2,
                "max_cursor_pages": 100,
                "max_objects": 10_000,
                "max_relationships": 20_000,
                "max_run_seconds": 300,
                "no_progress_timeout_seconds": 60,
                "jitter_ratio": 0.1,
                "backoff_base_seconds": 5,
                "backoff_max_seconds": 300,
                "circuit_failure_threshold": 5,
                "circuit_probe_interval_seconds": 120,
                "priority": {
                    "base": 10,
                    "changed_boost": 20,
                    "stale_boost": 30,
                    "critical_boost": 40,
                    "operator_requested_boost": 50,
                },
            }
        ],
    }


def test_policy_accepts_complete_bounded_source_declaration() -> None:
    policy = InventoryCollectionPolicy.from_mapping(_policy_document())

    source = policy.source("provider-delta")
    assert source.source_kind is CollectionSourceKind.DELTA
    assert source.target_freshness_seconds == 120
    assert source.endpoint_concurrency_limit == 2
    assert source.priority.operator_requested_boost == 50


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("target_freshness_seconds", 601, "target freshness"),
        ("max_poll_interval_seconds", 601, "maximum poll interval"),
        ("endpoint_concurrency_limit", 17, "nested concurrency"),
        ("no_progress_timeout_seconds", 301, "no-progress"),
        ("jitter_ratio", 0.51, "jitter_ratio"),
        ("backoff_base_seconds", 301, "backoff base"),
    ],
)
def test_policy_rejects_unsafe_freshness_budget_and_throttling_bounds(
    field: str,
    value: object,
    match: str,
) -> None:
    document = deepcopy(_policy_document())
    sources = document["sources"]
    assert isinstance(sources, list)
    source = sources[0]
    assert isinstance(source, dict)
    source[field] = value

    with pytest.raises(ValueError, match=match):
        InventoryCollectionPolicy.from_mapping(document)


def test_policy_rejects_unknown_fields_and_duplicate_sources() -> None:
    document = _policy_document()
    sources = document["sources"]
    assert isinstance(sources, list)
    source = sources[0]
    assert isinstance(source, dict)
    source["tenant_override"] = "not-allowed"
    with pytest.raises(ValueError, match="unknown=.*tenant_override"):
        InventoryCollectionPolicy.from_mapping(document)

    duplicate_document = _policy_document()
    duplicate_sources = duplicate_document["sources"]
    assert isinstance(duplicate_sources, list)
    duplicate_sources.append(deepcopy(duplicate_sources[0]))
    with pytest.raises(ValueError, match="source ids MUST be unique"):
        InventoryCollectionPolicy.from_mapping(duplicate_document)


def test_repository_policy_declares_each_collection_mode() -> None:
    policy = load_inventory_collection_policy(
        _REPO_ROOT / "config" / "inventory-collection-policy.json"
    )

    assert {source.source_kind for source in policy.sources} == set(CollectionSourceKind)
    assert policy.source("arg-snapshot").target_freshness_seconds == 21_600
    assert policy.source("activity-log-delta").max_cursor_pages == 100
    for source in policy.sources:
        if source.source_kind is CollectionSourceKind.SNAPSHOT:
            assert source.max_objects <= 50_000
            assert source.max_relationships <= 200_000


@pytest.mark.parametrize(
    ("field", "value"), [("max_objects", 50_001), ("max_relationships", 200_001)]
)
def test_snapshot_policy_cannot_exceed_projection_capacity(field: str, value: int) -> None:
    document = _policy_document()
    sources = document["sources"]
    assert isinstance(sources, list)
    source = sources[0]
    source["source_kind"] = "snapshot"
    source[field] = value
    with pytest.raises(ValueError, match="projection capacity"):
        InventoryCollectionPolicy.from_mapping(document)


async def test_source_composition_applies_registered_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    import httpx
    from fdai.delivery import inventory_sync_cli_support as support
    from fdai.delivery.inventory_change_acceleration import load_resource_type_registry
    from fdai.delivery.inventory_job_config import InventoryJobConfig
    from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity

    config = InventoryJobConfig.from_env(
        {
            "FDAI_INVENTORY_DSN": "postgresql://localhost/example",
            "FDAI_INVENTORY_SCOPES": "sub-example",
        }
    )
    arm_configs = []
    arg_configs = []
    arm_factory = support.AzureArmInventoryFactory
    arg_factory = support.AzureArgQueryFactory

    def capture_arm(**kwargs):
        arm_configs.append(kwargs["config"])
        return arm_factory(**kwargs)

    def capture_arg(**kwargs):
        arg_configs.append(kwargs["config"])
        return arg_factory(**kwargs)

    monkeypatch.setattr(support, "AzureArmInventoryFactory", capture_arm)
    monkeypatch.setattr(support, "AzureArgQueryFactory", capture_arg)
    async with httpx.AsyncClient() as client:
        sources = support.build_sources(
            config=config,
            vocabulary=load_resource_type_registry(),
            resource_types=("resource-group", "compute.vm"),
            identity=StaticWorkloadIdentity(
                audience="https://management.azure.com/.default", token="test-token"
            ),
            http_client=client,
            started_at=datetime.now(UTC),
        )
    assert arg_configs[0].max_pages == config.snapshot_policy("arg").max_cursor_pages
    assert arm_configs[-1].max_records == config.snapshot_policy("arm").max_objects
    assert arm_configs[-1].max_pages == config.snapshot_policy("arm").max_cursor_pages
    assert (
        arm_configs[-1].max_total_response_bytes
        == config.snapshot_policy("arm").max_bytes_per_window
    )
    assert sources[0].inventory._config.max_concurrent_queries == 4
    assert sources[1].inventory._config.max_concurrent_queries == 2


def test_policy_loader_rejects_invalid_or_oversized_documents(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="root MUST be an object"):
        load_inventory_collection_policy(invalid)

    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b" " * 1_048_577)
    with pytest.raises(ValueError, match="1 MiB"):
        load_inventory_collection_policy(oversized)
