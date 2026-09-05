"""Focused operational-history lifecycle Job runner tests."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fdai.core.ontology_platform.archive_manifest import (
    ArchiveSourcePartition,
    build_archive_manifest,
    verify_archive_manifest,
)
from fdai.core.ontology_platform.archive_retention import (
    RetentionHold,
    RetentionHoldKind,
    evaluate_restore_sample,
)
from fdai.core.ontology_platform.operational_history_lifecycle import (
    ObservationPartitionKind,
    ObservationPartitionState,
    build_observation_checkpoint,
    build_observation_partition,
)
from fdai.core.ontology_platform.operational_history_pressure import (
    StoragePressureAssessment,
    StoragePressureLevel,
)
from fdai.delivery.azure.operational_history_archive import (
    AzureBlobOperationalHistoryArtifactStore,
)
from fdai.delivery.operational_history_lifecycle_runner import (
    OperationalHistoryLifecycleMode,
    OperationalHistoryLifecycleRepository,
    OperationalHistoryLifecycleRunner,
    OperationalHistoryLifecycleRunnerConfig,
)
from fdai.delivery.persistence.postgres_operational_archive import (
    PostgresOperationalArchiveStore,
)
from fdai.delivery.persistence.postgres_operational_history import (
    PostgresOperationalHistoryStore,
)

NOW = datetime(2026, 9, 5, tzinfo=UTC)
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64
DIGEST_D = "sha256:" + "d" * 64


def _partition(state: ObservationPartitionState):
    return build_observation_partition(
        scope_ref="scope-example",
        interval_start=NOW - timedelta(hours=2),
        interval_end=NOW - timedelta(hours=1),
        first_watermark=1,
        last_watermark=2,
        kind=ObservationPartitionKind.BASE,
        state=state,
        correction_of=None,
        retention_policy_digest=DIGEST_A,
        created_at=NOW - timedelta(hours=1),
    )


def _archive_gates(partition_id: str):
    manifest = build_archive_manifest(
        (
            ArchiveSourcePartition(
                partition_id=partition_id,
                content_digest=DIGEST_A,
                interval_start=NOW - timedelta(hours=2),
                interval_end=NOW - timedelta(hours=1),
                object_count=1,
                relationship_count=0,
                schema_version="inventory-observation-1.0.0",
                ontology_release_digest=DIGEST_B,
                complete=True,
            ),
        ),
        archive_content_digest=DIGEST_C,
        compression_profile="none",
        encryption_profile="platform-managed",
        destination_class="private-blob",
        retention_class="operational-history",
        creation_receipt_digest=DIGEST_D,
        created_at=NOW - timedelta(minutes=30),
    )
    verification = verify_archive_manifest(
        manifest,
        observed_archive_content_digest=DIGEST_C,
        observed_source_partition_digests=(DIGEST_A,),
        observed_source_schema_versions=("inventory-observation-1.0.0",),
        observed_ontology_release_digests=(DIGEST_B,),
        verified_at=NOW - timedelta(minutes=20),
    )
    restore = evaluate_restore_sample(
        manifest,
        verification,
        sampled_partition_digests=(DIGEST_A,),
        observed_partition_digests=(DIGEST_A,),
        restored_object_count=1,
        restored_relationship_count=0,
        failure_code=None,
        sampled_at=NOW - timedelta(minutes=10),
    )
    return manifest, verification, restore


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
        created_at=NOW - timedelta(minutes=45),
    )


def _repository(
    partition,
    *,
    checkpoint=None,
    manifest=None,
    verification=None,
    restore=None,
    holds=(),
):
    return SimpleNamespace(
        assess_pressure=AsyncMock(
            return_value=StoragePressureAssessment(
                level=StoragePressureLevel.NORMAL,
                archive_priority=False,
                reduce_nonessential_collection=False,
                apply_source_admission_budget=False,
                hold_completeness_dependent_work=False,
                projected_exhaustion_seconds=None,
            )
        ),
        list_partitions=AsyncMock(return_value=(partition,)),
        latest_checkpoint=AsyncMock(return_value=checkpoint),
        latest_manifest=AsyncMock(return_value=manifest),
        latest_verification=AsyncMock(return_value=verification),
        latest_restore=AsyncMock(return_value=restore),
        active_pins=AsyncMock(return_value=()),
        retention_permitted=AsyncMock(return_value=True),
        active_holds=AsyncMock(return_value=holds),
        build_checkpoint=AsyncMock(),
        archive_records=AsyncMock(return_value=()),
        transition=AsyncMock(),
    )


def _runner(mode, repository):
    authority = None if mode is OperationalHistoryLifecycleMode.SHADOW else DIGEST_D
    history = SimpleNamespace(
        write_storage_pressure=AsyncMock(),
        append_checkpoint=AsyncMock(),
        put_archive_artifact=AsyncMock(),
        get_archive_artifact=AsyncMock(),
        purge=AsyncMock(),
    )
    archives = SimpleNamespace(
        put_manifest=AsyncMock(),
        append_verification=AsyncMock(),
        append_restore=AsyncMock(),
        latest=AsyncMock(return_value=None),
        append=AsyncMock(),
    )
    artifacts = SimpleNamespace(put=AsyncMock(), get=AsyncMock())
    runner = OperationalHistoryLifecycleRunner(
        config=OperationalHistoryLifecycleRunnerConfig(
            dsn="postgresql://example.invalid/fdai",
            container_url="https://example.invalid/operational-history",
            mode=mode,
            authority_receipt_digest=authority,
        ),
        repository=cast(OperationalHistoryLifecycleRepository, repository),
        history=cast(PostgresOperationalHistoryStore, history),
        archives=cast(PostgresOperationalArchiveStore, archives),
        artifacts=cast(AzureBlobOperationalHistoryArtifactStore, artifacts),
    )
    return runner, history, archives, artifacts


@pytest.mark.parametrize(
    "mode",
    [OperationalHistoryLifecycleMode.ENFORCE, OperationalHistoryLifecycleMode.CERTIFY],
)
def test_non_shadow_modes_require_external_authority_receipt(mode) -> None:
    with pytest.raises(ValueError, match="authority receipt"):
        OperationalHistoryLifecycleRunnerConfig(
            dsn="postgresql://example.invalid/fdai",
            container_url="https://example.invalid/operational-history",
            mode=mode,
        )


async def test_shadow_plans_without_database_or_blob_mutation() -> None:
    partition = _partition(ObservationPartitionState.OPEN)
    repository = _repository(partition)
    runner, history, archives, artifacts = _runner(
        OperationalHistoryLifecycleMode.SHADOW, repository
    )

    result = await runner.run_once(now=NOW)

    assert result.planned == (f"{partition.partition_id}:seal",)
    assert result.applied == ()
    assert result.execution_authority is False
    history.write_storage_pressure.assert_not_awaited()
    history.purge.assert_not_awaited()
    archives.append.assert_not_awaited()
    artifacts.put.assert_not_awaited()
    repository.transition.assert_not_awaited()


async def test_enforce_mode_never_executes_purge() -> None:
    partition = _partition(ObservationPartitionState.PURGE_ELIGIBLE)
    manifest, verification, restore = _archive_gates(partition.partition_id)
    repository = _repository(
        partition,
        manifest=manifest,
        verification=verification,
        restore=restore,
    )
    runner, history, archives, _ = _runner(OperationalHistoryLifecycleMode.ENFORCE, repository)

    result = await runner.run_once(now=NOW)

    assert result.blocked == (f"{partition.partition_id}:purge:certify_mode_required",)
    history.purge.assert_not_awaited()
    archives.append.assert_not_awaited()


async def test_enforce_composes_archive_writer_and_durable_stores() -> None:
    partition = _partition(ObservationPartitionState.CHECKPOINTED)
    repository = _repository(
        partition,
        checkpoint=_checkpoint(partition.partition_id),
    )
    repository.archive_records.return_value = (
        {
            "observation_id": DIGEST_B,
            "subject_kind": "object",
            "properties": {"status": "running"},
        },
    )
    runner, history, archives, artifacts = _runner(
        OperationalHistoryLifecycleMode.ENFORCE, repository
    )
    artifacts.put.return_value = True
    history.put_archive_artifact.return_value = True
    archives.put_manifest.return_value = True

    result = await runner.run_once(now=NOW)

    assert result.applied == (f"{partition.partition_id}:archive",)
    artifacts.put.assert_awaited_once()
    archives.put_manifest.assert_awaited_once()
    history.put_archive_artifact.assert_awaited_once()
    repository.transition.assert_awaited_once()


async def test_certify_uses_database_gated_purger() -> None:
    partition = _partition(ObservationPartitionState.PURGE_ELIGIBLE)
    manifest, verification, restore = _archive_gates(partition.partition_id)
    repository = _repository(
        partition,
        manifest=manifest,
        verification=verification,
        restore=restore,
    )
    runner, history, archives, _ = _runner(OperationalHistoryLifecycleMode.CERTIFY, repository)

    result = await runner.run_once(now=NOW)

    assert result.applied == (f"{partition.partition_id}:purge",)
    history.purge.assert_awaited_once_with((partition.partition_id,))
    assert archives.append.await_count == 2


async def test_retention_hold_blocks_certified_purge_and_preserves_source() -> None:
    partition = _partition(ObservationPartitionState.PURGE_ELIGIBLE)
    manifest, verification, restore = _archive_gates(partition.partition_id)
    hold = RetentionHold(
        hold_id="legal-case-example",
        manifest_digest=manifest.digest,
        kind=RetentionHoldKind.LEGAL,
        starts_at=NOW - timedelta(days=1),
        ends_at=None,
    )
    repository = _repository(
        partition,
        manifest=manifest,
        verification=verification,
        restore=restore,
        holds=(hold,),
    )
    runner, history, archives, _ = _runner(OperationalHistoryLifecycleMode.CERTIFY, repository)

    result = await runner.run_once(now=NOW)

    assert result.blocked == (f"{partition.partition_id}:purge",)
    history.purge.assert_not_awaited()
    assert archives.append.await_count == 1
    receipt = archives.append.await_args.args[0]
    assert receipt.source_data_preserved is True


async def test_failed_archive_verification_preserves_partition_state() -> None:
    partition = _partition(ObservationPartitionState.ARCHIVED)
    manifest, _, _ = _archive_gates(partition.partition_id)
    repository = _repository(partition, manifest=manifest)
    runner, history, archives, artifacts = _runner(
        OperationalHistoryLifecycleMode.ENFORCE, repository
    )
    history.get_archive_artifact.return_value = SimpleNamespace(storage_ref="archive.json")
    artifacts.get.return_value = b'{"tampered":true}\n'

    result = await runner.run_once(now=NOW)

    assert result.blocked == (f"{partition.partition_id}:verify",)
    repository.transition.assert_not_awaited()
    receipt = archives.append_verification.await_args.args[0]
    assert receipt.verified is False


async def test_failed_restore_sample_preserves_partition_state() -> None:
    partition = _partition(ObservationPartitionState.VERIFIED)
    content = (
        json.dumps(
            {
                "schema_version": "1.0.0",
                "source_partition_digests": [DIGEST_A],
                "records": [],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )
    archive_digest = "sha256:" + hashlib.sha256(content).hexdigest()
    manifest = build_archive_manifest(
        (
            ArchiveSourcePartition(
                partition_id=partition.partition_id,
                content_digest=DIGEST_A,
                interval_start=partition.interval_start,
                interval_end=partition.interval_end,
                object_count=1,
                relationship_count=0,
                schema_version="inventory-observation-1.0.0",
                ontology_release_digest=DIGEST_B,
                complete=True,
            ),
        ),
        archive_content_digest=archive_digest,
        compression_profile="none",
        encryption_profile="platform-managed",
        destination_class="private-blob",
        retention_class="operational-history",
        creation_receipt_digest=DIGEST_D,
        created_at=NOW - timedelta(minutes=30),
    )
    verification = verify_archive_manifest(
        manifest,
        observed_archive_content_digest=archive_digest,
        observed_source_partition_digests=(DIGEST_A,),
        observed_source_schema_versions=("inventory-observation-1.0.0",),
        observed_ontology_release_digests=(DIGEST_B,),
        verified_at=NOW - timedelta(minutes=20),
    )
    repository = _repository(
        partition,
        manifest=manifest,
        verification=verification,
    )
    runner, history, archives, artifacts = _runner(
        OperationalHistoryLifecycleMode.ENFORCE, repository
    )
    history.get_archive_artifact.return_value = SimpleNamespace(
        storage_ref="operational-history/archive.json",
        allowed_purposes=("operational-history-lifecycle",),
        scope_refs=(partition.scope_ref,),
        byte_count=len(content),
        artifact_digest=archive_digest,
    )
    history.is_archive_verified = AsyncMock(return_value=True)
    artifacts.get.return_value = content

    result = await runner.run_once(now=NOW)

    assert result.blocked == (f"{partition.partition_id}:restore_sample",)
    repository.transition.assert_not_awaited()
    receipt = archives.append_restore.await_args.args[0]
    assert receipt.passed is False
