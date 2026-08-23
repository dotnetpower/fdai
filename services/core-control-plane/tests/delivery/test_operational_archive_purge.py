"""Focused archive purge gate and idempotency tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.archive_manifest import (
    ArchiveSourcePartition,
    build_archive_manifest,
    verify_archive_manifest,
)
from fdai.core.ontology_platform.archive_retention import (
    evaluate_restore_sample,
    evaluate_retention_holds,
)
from fdai.delivery.operational_archive_purge import (
    ArchivePurgeReceipt,
    ArchivePurgeStatus,
    OperationalArchivePurgeCoordinator,
)

_START = datetime(2026, 8, 22, tzinfo=UTC)
_PARTITION = "sha256:" + "a" * 64
_ARCHIVE = "sha256:" + "b" * 64
_RELEASE = "sha256:" + "c" * 64
_CREATION = "sha256:" + "d" * 64


class _Receipts:
    def __init__(self) -> None:
        self.items: list[ArchivePurgeReceipt] = []

    async def latest(self, idempotency_key: str) -> ArchivePurgeReceipt | None:
        matches = [item for item in self.items if item.idempotency_key == idempotency_key]
        return matches[-1] if matches else None

    async def append(self, receipt: ArchivePurgeReceipt) -> None:
        self.items.append(receipt)


class _Source:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def purge(self, partition_ids: tuple[str, ...]) -> None:
        assert partition_ids == ("partition-1",)
        self.calls += 1
        if self.fail:
            raise RuntimeError("injected source purge failure")


def _gates():
    manifest = build_archive_manifest(
        (
            ArchiveSourcePartition(
                partition_id="partition-1",
                content_digest=_PARTITION,
                interval_start=_START,
                interval_end=_START + timedelta(hours=1),
                object_count=2,
                relationship_count=1,
                schema_version="topology-history-1.0.0",
                ontology_release_digest=_RELEASE,
                complete=True,
            ),
        ),
        archive_content_digest=_ARCHIVE,
        compression_profile="zstd-1",
        encryption_profile="platform-managed-1",
        destination_class="archive",
        retention_class="operational-history",
        creation_receipt_digest=_CREATION,
        created_at=_START + timedelta(hours=2),
    )
    verification = verify_archive_manifest(
        manifest,
        observed_archive_content_digest=_ARCHIVE,
        observed_source_partition_digests=(_PARTITION,),
        observed_source_schema_versions=("topology-history-1.0.0",),
        observed_ontology_release_digests=(_RELEASE,),
        verified_at=_START + timedelta(hours=3),
    )
    restore = evaluate_restore_sample(
        manifest,
        verification,
        sampled_partition_digests=(_PARTITION,),
        observed_partition_digests=(_PARTITION,),
        restored_object_count=2,
        restored_relationship_count=1,
        failure_code=None,
        sampled_at=_START + timedelta(hours=4),
    )
    retention = evaluate_retention_holds(
        manifest,
        (),
        evaluated_at=_START + timedelta(hours=5),
    )
    return manifest, verification, restore, retention


async def test_purge_failure_preserves_source_and_reports_pressure() -> None:
    receipts = _Receipts()
    source = _Source(fail=True)
    manifest, verification, restore, retention = _gates()
    coordinator = OperationalArchivePurgeCoordinator(receipts=receipts, source=source)

    result = await coordinator.purge(
        manifest,
        verification,
        restore,
        retention,
        idempotency_key="purge-1",
        recorded_at=_START + timedelta(hours=6),
    )

    assert result.status is ArchivePurgeStatus.FAILED
    assert result.source_data_preserved is True
    assert result.storage_pressure is True
    assert [item.status for item in receipts.items] == [
        ArchivePurgeStatus.PENDING,
        ArchivePurgeStatus.FAILED,
    ]


async def test_successful_purge_duplicate_does_not_delete_twice() -> None:
    receipts = _Receipts()
    source = _Source()
    manifest, verification, restore, retention = _gates()
    coordinator = OperationalArchivePurgeCoordinator(receipts=receipts, source=source)

    first = await coordinator.purge(
        manifest,
        verification,
        restore,
        retention,
        idempotency_key="purge-1",
        recorded_at=_START + timedelta(hours=6),
    )
    duplicate = await coordinator.purge(
        manifest,
        verification,
        restore,
        retention,
        idempotency_key="purge-1",
        recorded_at=_START + timedelta(hours=7),
    )

    assert first.status is ArchivePurgeStatus.SUCCEEDED
    assert duplicate.status is ArchivePurgeStatus.DUPLICATE
    assert source.calls == 1


@pytest.mark.parametrize("failed_gate", ["verification", "restore", "hold"])
async def test_each_failed_gate_blocks_source_purge(failed_gate: str) -> None:
    receipts = _Receipts()
    source = _Source()
    manifest, verification, restore, retention = _gates()
    if failed_gate == "verification":
        verification = replace(verification, verified=False)
    elif failed_gate == "restore":
        restore = replace(restore, passed=False)
    else:
        retention = replace(
            retention,
            blocking_hold_ids=("legal-case-1",),
            permitted=False,
        )
    coordinator = OperationalArchivePurgeCoordinator(receipts=receipts, source=source)

    result = await coordinator.purge(
        manifest,
        verification,
        restore,
        retention,
        idempotency_key=f"purge-{failed_gate}",
        recorded_at=_START + timedelta(hours=6),
    )

    assert result.status is ArchivePurgeStatus.BLOCKED
    assert result.source_data_preserved is True
    assert result.storage_pressure is True
    assert source.calls == 0
