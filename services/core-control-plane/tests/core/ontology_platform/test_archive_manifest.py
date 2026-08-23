"""Focused archive manifest safety tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fdai.core.ontology_platform.archive_manifest import (
    ArchiveSourcePartition,
    build_archive_manifest,
    verify_archive_manifest,
)
from fdai.core.ontology_platform.archive_retention import (
    ArchiveCoverageIndex,
    ArchiveHistoryStatus,
    ArchiveIndexEntry,
    RetentionHold,
    RetentionHoldKind,
    build_archive_coverage_receipt,
    evaluate_restore_sample,
    evaluate_retention_holds,
    locate_archive_history,
)

_START = datetime(2026, 8, 22, tzinfo=UTC)
_PARTITION_DIGEST = "sha256:" + "a" * 64
_ARCHIVE_DIGEST = "sha256:" + "b" * 64
_RELEASE_DIGEST = "sha256:" + "c" * 64
_RECEIPT_DIGEST = "sha256:" + "d" * 64


def _manifest():
    partition = ArchiveSourcePartition(
        partition_id="partition-1",
        content_digest=_PARTITION_DIGEST,
        interval_start=_START,
        interval_end=_START + timedelta(hours=1),
        object_count=2,
        relationship_count=1,
        schema_version="topology-history-1.0.0",
        ontology_release_digest=_RELEASE_DIGEST,
        complete=True,
    )
    return build_archive_manifest(
        (partition,),
        archive_content_digest=_ARCHIVE_DIGEST,
        compression_profile="zstd-1",
        encryption_profile="platform-managed-1",
        destination_class="archive",
        retention_class="operational-history",
        creation_receipt_digest=_RECEIPT_DIGEST,
        created_at=_START + timedelta(hours=2),
    )


def test_manifest_tamper_fails_content_address_verification() -> None:
    manifest = _manifest()
    tampered = replace(manifest, object_count=manifest.object_count + 1)

    result = verify_archive_manifest(
        tampered,
        observed_archive_content_digest=_ARCHIVE_DIGEST,
        observed_source_partition_digests=(_PARTITION_DIGEST,),
        observed_source_schema_versions=("topology-history-1.0.0",),
        observed_ontology_release_digests=(_RELEASE_DIGEST,),
        verified_at=_START + timedelta(hours=3),
    )

    assert result.verified is False
    assert result.reason_codes == ("manifest_digest_mismatch",)


def _verified(manifest):
    return verify_archive_manifest(
        manifest,
        observed_archive_content_digest=_ARCHIVE_DIGEST,
        observed_source_partition_digests=(_PARTITION_DIGEST,),
        observed_source_schema_versions=("topology-history-1.0.0",),
        observed_ontology_release_digests=(_RELEASE_DIGEST,),
        verified_at=_START + timedelta(hours=3),
    )


def test_incomplete_coverage_and_restore_failure_block_receipts() -> None:
    manifest = _manifest()
    incomplete = replace(manifest, coverage_complete=False)
    verification = _verified(incomplete)
    restore = evaluate_restore_sample(
        manifest,
        _verified(manifest),
        sampled_partition_digests=(_PARTITION_DIGEST,),
        observed_partition_digests=(),
        restored_object_count=0,
        restored_relationship_count=0,
        failure_code="restore_io_failed",
        sampled_at=_START + timedelta(hours=4),
    )

    assert verification.verified is False
    assert set(verification.reason_codes) == {
        "manifest_digest_mismatch",
        "incomplete_coverage",
    }
    assert restore.passed is False
    assert "restore_failed" in restore.reason_codes


def test_legal_hold_blocks_purge_and_history_distinguishes_absence() -> None:
    manifest = _manifest()
    hold = RetentionHold(
        hold_id="legal-case-1",
        manifest_digest=manifest.digest,
        kind=RetentionHoldKind.LEGAL,
        starts_at=_START,
        ends_at=None,
    )
    retention = evaluate_retention_holds(
        manifest,
        (hold,),
        evaluated_at=_START + timedelta(hours=5),
    )
    index = ArchiveCoverageIndex(
        coverage_start=_START,
        coverage_end=_START + timedelta(hours=3),
        complete=True,
        entries=(
            ArchiveIndexEntry(
                manifest_digest=manifest.digest,
                interval_start=_START,
                interval_end=_START + timedelta(hours=1),
            ),
        ),
    )

    assert retention.permitted is False
    assert retention.blocking_hold_ids == ("legal-case-1",)
    assert (
        locate_archive_history(
            index,
            interval_start=_START,
            interval_end=_START + timedelta(minutes=30),
        )
        is ArchiveHistoryStatus.ARCHIVED
    )
    assert (
        locate_archive_history(
            index,
            interval_start=_START + timedelta(hours=2),
            interval_end=_START + timedelta(hours=3),
        )
        is ArchiveHistoryStatus.ABSENT
    )
    coverage_receipt = build_archive_coverage_receipt(
        index,
        recorded_at=_START + timedelta(hours=6),
    )
    assert coverage_receipt.digest.startswith("sha256:")
