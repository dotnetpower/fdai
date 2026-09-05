"""Deployment-owned operational history retention policy tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, create_autospec

import pytest
from fdai.core.ontology_platform.operational_history_retention import (
    RetentionDeletionMethod,
    build_retention_policy,
)
from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.delivery.operational_history_policy import (
    RETENTION_POLICY_PATH_ENV,
    ConfiguredInventoryObservationJournal,
    load_operational_history_retention_policies,
)
from fdai.delivery.persistence.postgres_inventory_observation import (
    InventorySnapshotObservationAppendResult,
    PostgresInventoryObservationJournal,
)
from fdai.delivery.persistence.postgres_operational_history import (
    PostgresOperationalHistoryStore,
)


def test_missing_deployment_policy_keeps_safe_retain_default() -> None:
    assert load_operational_history_retention_policies({}) == ()


def test_deployment_policy_file_is_typed_and_content_addressed(tmp_path) -> None:
    path = tmp_path / "retention.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "policies": [
                    {
                        "policy_id": "full-v1",
                        "fact_family": "full_observation",
                        "purpose": "bounded-exact-replay",
                        "hot_retention_seconds": 3600,
                        "warm_retention_seconds": 86400,
                        "archive_class": "operational-history",
                        "deletion_method": "partition_purge",
                        "review_at": "2026-10-05T00:00:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    (policy,) = load_operational_history_retention_policies({RETENTION_POLICY_PATH_ENV: str(path)})

    assert policy.fact_family == "full_observation"
    assert policy.digest.startswith("sha256:")


def test_malformed_deployment_policy_fails_closed(tmp_path) -> None:
    path = tmp_path / "retention.json"
    path.write_text('{"schema_version":"1.0.0","policies":"bad"}', encoding="utf-8")

    with pytest.raises(ValueError, match="MUST be an array"):
        load_operational_history_retention_policies({RETENTION_POLICY_PATH_ENV: str(path)})


@pytest.mark.asyncio
async def test_configured_journal_persists_policy_before_snapshot() -> None:
    recorded_at = datetime(2026, 9, 5, tzinfo=UTC)
    policy = build_retention_policy(
        policy_id="full-v1",
        fact_family="full_observation",
        purpose="bounded-exact-replay",
        hot_retention_seconds=3600,
        warm_retention_seconds=86400,
        archive_class="operational-history",
        deletion_method=RetentionDeletionMethod.PARTITION_PURGE,
        review_at=recorded_at,
    )
    result = InventorySnapshotObservationAppendResult(
        journal_high_watermark=7,
        projection_high_watermark=5,
    )
    journal = create_autospec(PostgresInventoryObservationJournal, instance=True)
    journal.append_promoted_snapshot = AsyncMock(return_value=result)
    history = create_autospec(PostgresOperationalHistoryStore, instance=True)
    history.put_retention_policy = AsyncMock()
    configured = ConfiguredInventoryObservationJournal(
        journal=journal,
        policies=(policy,),
        history=history,
    )
    observation = PromotedInventoryObservation(
        generation="inventory-generation",
        resources=(),
        links=(),
        complete=True,
        recorded_at=recorded_at,
    )

    assert await configured.append_promoted_snapshot(observation) == result
    history.put_retention_policy.assert_awaited_once_with(policy, recorded_at=recorded_at)
    journal.append_promoted_snapshot.assert_awaited_once_with(observation)


@pytest.mark.asyncio
async def test_configured_journal_rejects_snapshot_without_recorded_time() -> None:
    journal = create_autospec(PostgresInventoryObservationJournal, instance=True)
    history = create_autospec(PostgresOperationalHistoryStore, instance=True)
    configured = ConfiguredInventoryObservationJournal(
        journal=journal,
        policies=(),
        history=history,
    )

    with pytest.raises(ValueError, match="recorded_at MUST be supplied"):
        await configured.append_promoted_snapshot(
            PromotedInventoryObservation(
                generation="inventory-generation",
                resources=(),
                links=(),
                complete=True,
            )
        )

    journal.append_promoted_snapshot.assert_not_awaited()


@pytest.mark.asyncio
async def test_configured_journal_forwards_projection_watermark() -> None:
    journal = create_autospec(PostgresInventoryObservationJournal, instance=True)
    journal.mark_ontology_projected = AsyncMock()
    history = create_autospec(PostgresOperationalHistoryStore, instance=True)
    configured = ConfiguredInventoryObservationJournal(
        journal=journal,
        policies=(),
        history=history,
    )

    await configured.mark_ontology_projected(generation="inventory-generation", watermark=7)

    journal.mark_ontology_projected.assert_awaited_once_with(
        generation="inventory-generation",
        watermark=7,
    )
