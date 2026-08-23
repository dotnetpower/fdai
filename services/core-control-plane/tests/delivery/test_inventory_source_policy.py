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


def test_policy_loader_rejects_invalid_or_oversized_documents(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="root MUST be an object"):
        load_inventory_collection_policy(invalid)

    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b" " * 1_048_577)
    with pytest.raises(ValueError, match="1 MiB"):
        load_inventory_collection_policy(oversized)
