"""Scheduled operational-history lifecycle planning tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fdai.core.ontology_platform.operational_history_lifecycle import (
    ObservationPartitionKind,
    ObservationPartitionState,
    build_observation_checkpoint,
    build_observation_partition,
)
from fdai.core.ontology_platform.operational_history_pressure import (
    StoragePressurePolicy,
    assess_storage_pressure,
)
from fdai.core.ontology_platform.operational_history_retention import (
    RetentionDeletionMethod,
    build_retention_policy,
)
from fdai.delivery.operational_history_lifecycle import (
    OperationalHistoryLifecycleAction,
    OperationalHistoryLifecycleEvidence,
    operational_history_lifecycle_schedule,
    plan_operational_history_lifecycle,
)

NOW = datetime(2026, 9, 5, tzinfo=UTC)
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64
DIGEST_D = "sha256:" + "d" * 64


def _partition(state: ObservationPartitionState):
    policy = build_retention_policy(
        policy_id="full-v1",
        fact_family="full_observation",
        purpose="bounded-history",
        hot_retention_seconds=3600,
        warm_retention_seconds=86400,
        archive_class="operational-history",
        deletion_method=RetentionDeletionMethod.PARTITION_PURGE,
        review_at=NOW + timedelta(days=30),
    )
    return build_observation_partition(
        scope_ref="scope-example",
        interval_start=NOW,
        interval_end=NOW + timedelta(hours=1),
        first_watermark=1,
        last_watermark=2,
        kind=ObservationPartitionKind.BASE,
        state=state,
        correction_of=None,
        retention_policy_digest=policy.digest,
        created_at=NOW + timedelta(hours=1),
    )


def _checkpoint(partition_id: str):
    return build_observation_checkpoint(
        partition_id=partition_id,
        first_watermark=1,
        last_watermark=2,
        scope_ref="scope-example",
        object_count=1,
        relationship_count=0,
        property_count=1,
        source_digest=DIGEST_A,
        schema_digest=DIGEST_B,
        ontology_release_digest=DIGEST_C,
        projection_digest=DIGEST_D,
        projection_watermark=2,
        graph_digest=DIGEST_A,
        missing_count=0,
        quarantined_count=0,
        conflicted_count=0,
        tombstoned_count=0,
        valid=True,
        created_at=NOW + timedelta(hours=2),
    )


def _pressure(*, hard: bool = False):
    return assess_storage_pressure(
        StoragePressurePolicy(
            warning_bytes=100,
            critical_bytes=200,
            hard_bytes=300,
            max_purge_backlog=10,
            max_projection_lag=10,
        ),
        database_bytes=300 if hard else 10,
        purge_backlog=0,
        projection_lag=0,
        growth_bytes_per_second=1,
    )


def test_scheduler_definition_is_shadow_only_and_authority_free() -> None:
    task = operational_history_lifecycle_schedule()

    assert task.task_id == "operational-history-lifecycle"
    assert task.event_payload["mode"] == "shadow"
    assert task.event_payload["execution_authority"] is False


def test_lifecycle_planner_requires_every_archive_gate_in_order() -> None:
    partition = _partition(ObservationPartitionState.SEALED)
    evidence = OperationalHistoryLifecycleEvidence(
        checkpoint=None,
        archive_written=False,
        archive_verified=False,
        restore_passed=False,
        retention_permitted=True,
        correction_closed=True,
    )

    checkpoint = plan_operational_history_lifecycle(
        partition,
        evidence,
        _pressure(),
        now=NOW,
    )
    archive = plan_operational_history_lifecycle(
        replace(partition, state=ObservationPartitionState.CHECKPOINTED),
        replace(evidence, checkpoint=_checkpoint(partition.partition_id)),
        _pressure(),
        now=NOW,
    )
    verify = plan_operational_history_lifecycle(
        replace(partition, state=ObservationPartitionState.ARCHIVED),
        replace(evidence, checkpoint=_checkpoint(partition.partition_id), archive_written=True),
        _pressure(),
        now=NOW,
    )
    restore = plan_operational_history_lifecycle(
        replace(partition, state=ObservationPartitionState.VERIFIED),
        replace(
            evidence,
            checkpoint=_checkpoint(partition.partition_id),
            archive_written=True,
            archive_verified=True,
        ),
        _pressure(),
        now=NOW,
    )

    assert checkpoint.action is OperationalHistoryLifecycleAction.CHECKPOINT
    assert checkpoint.reason_codes == ("checkpoint_required",)
    assert archive.action is OperationalHistoryLifecycleAction.ARCHIVE
    assert verify.action is OperationalHistoryLifecycleAction.VERIFY
    assert restore.action is OperationalHistoryLifecycleAction.RESTORE_SAMPLE


def test_hard_storage_pressure_prioritizes_safe_purge_without_skipping_gates() -> None:
    partition = _partition(ObservationPartitionState.PURGE_ELIGIBLE)
    decision = plan_operational_history_lifecycle(
        partition,
        OperationalHistoryLifecycleEvidence(
            checkpoint=_checkpoint(partition.partition_id),
            archive_written=True,
            archive_verified=True,
            restore_passed=True,
            retention_permitted=True,
            correction_closed=True,
        ),
        _pressure(hard=True),
        now=NOW,
    )

    assert decision.action is OperationalHistoryLifecycleAction.PURGE
    assert decision.reason_codes == ("storage_pressure_hard",)
    assert decision.execution_authority is False
