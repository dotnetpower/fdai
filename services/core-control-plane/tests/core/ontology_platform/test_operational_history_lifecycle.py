"""OI-14 and OI-15 operational history lifecycle contracts."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.operational_history_lifecycle import (
    ObservationPartitionKind,
    ObservationPartitionState,
    ObservationPinKind,
    active_partition_pins,
    advance_partition_state,
    build_correction_receipt,
    build_observation_checkpoint,
    build_observation_partition,
    build_partition_pin,
    build_resource_incarnation,
    partition_purge_reasons,
)
from fdai.core.ontology_platform.operational_history_pressure import (
    StoragePressureLevel,
    StoragePressurePolicy,
    assess_storage_pressure,
)
from fdai.core.ontology_platform.operational_history_retention import (
    RetentionDeletionMethod,
    build_retention_policy,
    load_retention_policy_registry,
)

NOW = datetime(2026, 9, 5, tzinfo=UTC)
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64
DIGEST_D = "sha256:" + "d" * 64


def _policy():
    return build_retention_policy(
        policy_id="inventory-full-v1",
        fact_family="full_observation",
        purpose="bounded-exact-replay",
        hot_retention_seconds=3600,
        warm_retention_seconds=86400,
        archive_class="operational-history",
        deletion_method=RetentionDeletionMethod.PARTITION_PURGE,
        review_at=NOW + timedelta(days=30),
    )


def _partition(*, kind: ObservationPartitionKind = ObservationPartitionKind.BASE):
    return build_observation_partition(
        scope_ref="scope-example",
        interval_start=NOW,
        interval_end=NOW + timedelta(hours=1),
        first_watermark=1,
        last_watermark=10,
        kind=kind,
        state=(
            ObservationPartitionState.CORRECTION_PENDING
            if kind is ObservationPartitionKind.CORRECTION
            else ObservationPartitionState.OPEN
        ),
        correction_of=DIGEST_A if kind is ObservationPartitionKind.CORRECTION else None,
        retention_policy_digest=_policy().digest,
        created_at=NOW + timedelta(hours=1),
    )


def _checkpoint(
    partition_id: str,
    *,
    valid: bool = True,
    projection_watermark: int = 10,
):
    return build_observation_checkpoint(
        partition_id=partition_id,
        first_watermark=1,
        last_watermark=10,
        scope_ref="scope-example",
        object_count=3,
        relationship_count=2,
        property_count=8,
        source_digest=DIGEST_A,
        schema_digest=DIGEST_B,
        ontology_release_digest=DIGEST_C,
        projection_digest=DIGEST_D,
        projection_watermark=projection_watermark,
        graph_digest=DIGEST_A,
        missing_count=0,
        quarantined_count=0,
        conflicted_count=0,
        tombstoned_count=1,
        valid=valid,
        created_at=NOW + timedelta(hours=2),
    )


def test_resource_incarnation_is_stable_until_explicit_close_and_recreate() -> None:
    first = build_resource_incarnation(
        resource_ref="resource-1",
        resource_type="compute.vm",
        provider_identity="/providers/example/resource-1",
        lifecycle_boundary_ref="generation-1",
        opened_at=NOW,
        opening_observation_id=DIGEST_A,
    )
    replay = build_resource_incarnation(
        resource_ref="resource-1",
        resource_type="compute.vm",
        provider_identity="/providers/example/resource-1",
        lifecycle_boundary_ref="generation-1",
        opened_at=NOW,
        opening_observation_id=DIGEST_A,
    )
    closed = first.close(
        closed_at=NOW + timedelta(hours=1),
        closing_observation_id=DIGEST_B,
    )
    recreated = build_resource_incarnation(
        resource_ref="resource-1",
        resource_type="compute.vm",
        provider_identity="/providers/example/resource-1",
        lifecycle_boundary_ref="generation-2",
        opened_at=NOW + timedelta(hours=2),
        opening_observation_id=DIGEST_C,
    )

    assert first.incarnation_id == replay.incarnation_id == closed.incarnation_id
    assert recreated.incarnation_id != first.incarnation_id
    assert closed.closed_at is not None


def test_partition_lifecycle_cannot_skip_verification_or_move_backward() -> None:
    partition = _partition()
    for state in (
        ObservationPartitionState.SEALED,
        ObservationPartitionState.CHECKPOINTED,
        ObservationPartitionState.ARCHIVED,
        ObservationPartitionState.VERIFIED,
        ObservationPartitionState.PURGE_ELIGIBLE,
        ObservationPartitionState.PURGED,
    ):
        partition = advance_partition_state(partition, target=state)
    assert partition.state is ObservationPartitionState.PURGED

    with pytest.raises(ValueError, match="skip or move backward"):
        advance_partition_state(_partition(), target=ObservationPartitionState.ARCHIVED)


def test_checkpoint_requires_projection_to_cover_the_whole_partition() -> None:
    with pytest.raises(ValueError, match="projection watermark trails"):
        _checkpoint(_partition().partition_id, projection_watermark=9)


def test_late_correction_stays_blocked_until_replay_receipt_closes_it() -> None:
    correction = _partition(kind=ObservationPartitionKind.CORRECTION)
    assert correction.state is ObservationPartitionState.CORRECTION_PENDING
    receipt = build_correction_receipt(
        correction_partition_id=correction.partition_id,
        affected_checkpoint_ids=(DIGEST_A,),
        correction_manifest_digest=DIGEST_B,
        replay_receipt_digest=DIGEST_C,
        resulting_graph_digest=DIGEST_D,
        projection_watermark=10,
        closed_at=NOW + timedelta(hours=3),
    )
    closed = advance_partition_state(
        correction,
        target=ObservationPartitionState.CHECKPOINTED,
    )

    assert receipt.complete is True
    assert closed.state is ObservationPartitionState.CHECKPOINTED


def test_active_case_and_legal_hold_pins_block_purge_until_release() -> None:
    partition = replace(_partition(), state=ObservationPartitionState.PURGE_ELIGIBLE)
    placed = build_partition_pin(
        partition_id=partition.partition_id,
        kind=ObservationPinKind.INCIDENT,
        case_ref="incident-example",
        placed_at=NOW,
        released_at=None,
        expires_at=NOW + timedelta(days=1),
        evidence_refs=("evidence:incident",),
    )
    released = build_partition_pin(
        partition_id=partition.partition_id,
        kind=ObservationPinKind.INCIDENT,
        case_ref="incident-example",
        placed_at=NOW,
        released_at=NOW + timedelta(hours=1),
        expires_at=NOW + timedelta(days=1),
        evidence_refs=("evidence:incident",),
    )

    assert active_partition_pins((placed,), at=NOW + timedelta(minutes=1)) == (placed.pin_id,)
    assert active_partition_pins((placed, released), at=NOW + timedelta(hours=2)) == ()
    assert partition_purge_reasons(
        partition=partition,
        checkpoint=_checkpoint(partition.partition_id),
        archive_verified=True,
        restore_passed=True,
        retention_permitted=True,
        pins=(placed,),
        evaluated_at=NOW + timedelta(minutes=1),
    ) == ("partition_pin_active",)

    with pytest.raises(ValueError, match="cannot expire"):
        build_partition_pin(
            partition_id=partition.partition_id,
            kind=ObservationPinKind.LEGAL_HOLD,
            case_ref="legal-example",
            placed_at=NOW,
            released_at=None,
            expires_at=NOW + timedelta(days=1),
            evidence_refs=("evidence:legal",),
        )


def test_retention_registry_is_deployment_owned_unique_and_content_addressed() -> None:
    registry = load_retention_policy_registry(
        (
            {
                "policy_id": "inventory-full-v1",
                "fact_family": "full_observation",
                "purpose": "bounded-exact-replay",
                "hot_retention_seconds": 3600,
                "warm_retention_seconds": 86400,
                "archive_class": "operational-history",
                "deletion_method": "partition_purge",
                "review_at": "2026-10-05T00:00:00+00:00",
            },
        )
    )

    assert registry["full_observation"].digest == _policy().digest


@pytest.mark.parametrize(
    ("database_bytes", "backlog", "lag", "expected"),
    [
        (10, 0, 0, StoragePressureLevel.NORMAL),
        (100, 0, 0, StoragePressureLevel.WARNING),
        (200, 0, 0, StoragePressureLevel.CRITICAL),
        (300, 0, 0, StoragePressureLevel.HARD),
        (10, 11, 0, StoragePressureLevel.HARD),
        (10, 0, 11, StoragePressureLevel.HARD),
    ],
)
def test_storage_pressure_degrades_monotonically_without_deleting_evidence(
    database_bytes: int,
    backlog: int,
    lag: int,
    expected: StoragePressureLevel,
) -> None:
    assessment = assess_storage_pressure(
        StoragePressurePolicy(
            warning_bytes=100,
            critical_bytes=200,
            hard_bytes=300,
            max_purge_backlog=10,
            max_projection_lag=10,
        ),
        database_bytes=database_bytes,
        purge_backlog=backlog,
        projection_lag=lag,
        growth_bytes_per_second=1,
    )

    assert assessment.level is expected
    assert assessment.hold_completeness_dependent_work is (expected is StoragePressureLevel.HARD)
