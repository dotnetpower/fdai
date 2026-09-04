from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.delivery.persistence.postgres_wara_scope import (
    PostgresWaraScopeSourceConfig,
    WaraScopeUnavailableError,
    _resolve_resources,
    _validate_snapshot,
    _validate_workload,
)

AT = datetime(2026, 9, 5, tzinfo=UTC)
ONTOLOGY_RELEASE = f"sha256:{'a' * 64}"
PROVIDER_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000001/"
    "resourceGroups/rg-example/providers/Microsoft.ContainerRegistry/registries/example"
)


def test_scope_config_enforces_freshness_and_resource_ceilings() -> None:
    with pytest.raises(ValueError):
        PostgresWaraScopeSourceConfig(dsn="", maximum_resources=1)
    with pytest.raises(ValueError):
        PostgresWaraScopeSourceConfig(dsn="postgresql://localhost/fdai", maximum_resources=1001)
    with pytest.raises(ValueError):
        PostgresWaraScopeSourceConfig(
            dsn="postgresql://localhost/fdai",
            freshness_budget_seconds=604801,
        )


def test_snapshot_requires_current_observed_generation() -> None:
    snapshot_id, completed_at = _validate_snapshot(
        {
            "id": "generation-1",
            "status": "active",
            "observation_kind": "observed",
            "completed_at": AT - timedelta(minutes=5),
        },
        now=AT,
        freshness_budget_seconds=600,
    )

    assert snapshot_id == "generation-1"
    assert completed_at == AT - timedelta(minutes=5)

    with pytest.raises(WaraScopeUnavailableError, match="freshness"):
        _validate_snapshot(
            {
                "id": "generation-1",
                "status": "active",
                "observation_kind": "observed",
                "completed_at": AT - timedelta(minutes=11),
            },
            now=AT,
            freshness_budget_seconds=600,
        )
    with pytest.raises(WaraScopeUnavailableError, match="not an observed"):
        _validate_snapshot(
            {
                "id": "generation-1",
                "status": "active",
                "observation_kind": "expected",
                "completed_at": AT,
            },
            now=AT,
            freshness_budget_seconds=600,
        )
    with pytest.raises(WaraScopeUnavailableError, match="not active"):
        _validate_snapshot(
            {
                "id": "generation-1",
                "status": "failed",
                "observation_kind": "observed",
                "completed_at": AT,
            },
            now=AT,
            freshness_budget_seconds=600,
        )


def test_workload_requires_current_effective_time_and_release() -> None:
    release = _validate_workload(
        {
            "object_type": "Workload",
            "catalog_digest": ONTOLOGY_RELEASE,
            "properties": {
                "effective_from": (AT - timedelta(days=1)).isoformat(),
                "effective_to": (AT + timedelta(days=1)).isoformat(),
            },
        },
        now=AT,
    )

    assert release == ONTOLOGY_RELEASE

    with pytest.raises(WaraScopeUnavailableError, match="not currently effective"):
        _validate_workload(
            {
                "object_type": "Workload",
                "catalog_digest": ONTOLOGY_RELEASE,
                "properties": {
                    "effective_from": (AT - timedelta(days=2)).isoformat(),
                    "effective_to": AT.isoformat(),
                },
            },
            now=AT,
        )


def test_resources_require_complete_matching_ontology_and_provider_identity() -> None:
    resources = _resolve_resources(
        [
            {
                "neutral_resource_id": "resource:example",
                "link_catalog_digest": ONTOLOGY_RELEASE,
                "object_type": "Resource",
                "catalog_digest": ONTOLOGY_RELEASE,
                "resource_type": "container-registry",
                "provider_ref": PROVIDER_ID,
            }
        ],
        ontology_release=ONTOLOGY_RELEASE,
        maximum_resources=10,
    )

    assert resources[0].provider_resource_id == PROVIDER_ID
    assert resources[0].provider_resource_type == "Microsoft.ContainerRegistry/registries"

    with pytest.raises(WaraScopeUnavailableError, match="coverage is incomplete"):
        _resolve_resources(
            [
                {
                    "neutral_resource_id": "resource:example",
                    "link_catalog_digest": ONTOLOGY_RELEASE,
                    "object_type": "Resource",
                    "catalog_digest": ONTOLOGY_RELEASE,
                    "resource_type": "container-registry",
                    "provider_ref": None,
                }
            ],
            ontology_release=ONTOLOGY_RELEASE,
            maximum_resources=10,
        )


def test_resources_reject_case_insensitive_duplicate_provider_ids() -> None:
    base = {
        "link_catalog_digest": ONTOLOGY_RELEASE,
        "object_type": "Resource",
        "catalog_digest": ONTOLOGY_RELEASE,
        "resource_type": "container-registry",
    }
    with pytest.raises(WaraScopeUnavailableError, match="duplicate Azure"):
        _resolve_resources(
            [
                {
                    **base,
                    "neutral_resource_id": "resource:a",
                    "provider_ref": PROVIDER_ID,
                },
                {
                    **base,
                    "neutral_resource_id": "resource:b",
                    "provider_ref": PROVIDER_ID.upper(),
                },
            ],
            ontology_release=ONTOLOGY_RELEASE,
            maximum_resources=10,
        )
