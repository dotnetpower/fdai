"""Cross-lane collection, rollup, archive, restore, and purge tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fdai.core.ontology_platform.archive_manifest import (
    build_archive_manifest,
    verify_archive_manifest,
)
from fdai.core.ontology_platform.archive_retention import (
    evaluate_restore_sample,
    evaluate_retention_holds,
)
from fdai.core.ontology_platform.semantic_rollup import (
    RollupFactKind,
    SemanticRollupPolicy,
    build_semantic_rollup,
)
from fdai.delivery.inventory_convergence import (
    InventoryMutationKind,
    InventoryObservationMode,
    InventoryObservedRevision,
)
from fdai.delivery.inventory_rollup import (
    inventory_revision_to_rollup_observation,
    semantic_rollup_to_archive_partition,
)
from fdai.delivery.operational_archive_purge import (
    ArchivePurgeReceipt,
    ArchivePurgeStatus,
    OperationalArchivePurgeCoordinator,
)

_START = datetime(2026, 8, 22, tzinfo=UTC)
_RELEASE = "sha256:" + "c" * 64
_ARCHIVE = "sha256:" + "d" * 64
_CREATION = "sha256:" + "e" * 64


class _Receipts:
    def __init__(self) -> None:
        self.items: list[ArchivePurgeReceipt] = []

    async def latest(self, idempotency_key: str) -> ArchivePurgeReceipt | None:
        matches = [item for item in self.items if item.idempotency_key == idempotency_key]
        return matches[-1] if matches else None

    async def append(self, receipt: ArchivePurgeReceipt) -> None:
        self.items.append(receipt)


class _Source:
    def __init__(self) -> None:
        self.calls = 0

    async def purge(self, partition_ids: tuple[str, ...]) -> None:
        assert partition_ids == ("rollup-partition-1",)
        self.calls += 1


def _revision(
    index: int,
    *,
    mutation: InventoryMutationKind,
) -> InventoryObservedRevision:
    return InventoryObservedRevision(
        logical_key="link:resource-a|depends_on|resource-b",
        mode=InventoryObservationMode.EVENT,
        mutation=mutation,
        observed_at=_START + timedelta(minutes=index + 1),
        recorded_at=_START + timedelta(minutes=index + 1, seconds=1),
        source_id="provider-events",
        source_revision=f"event-{index}",
        payload_digest="sha256:" + str(index + 1) * 64,
    )


def _pipeline(*, conflict_count: int = 0, complete: bool = True):
    policy = SemanticRollupPolicy(
        semantic_id="relationship.depends_on.change",
        revision="policy-1",
        ontology_release_digest=_RELEASE,
        fact_kind=RollupFactKind.RELATIONSHIP_CHANGE,
        expected_interval_seconds=60,
        statistics=("change_counts",),
    )
    revisions = (
        _revision(0, mutation=InventoryMutationKind.UPSERT),
        _revision(1, mutation=InventoryMutationKind.TOMBSTONE),
    )
    observations = tuple(
        inventory_revision_to_rollup_observation(
            revision,
            policy,
            generation_ref="overlay-generation-1",
            interval_start=_START + timedelta(minutes=index),
            interval_end=_START + timedelta(minutes=index + 1),
            complete=complete,
            conflict_count=conflict_count if index == 1 else 0,
        )
        for index, revision in enumerate(revisions)
    )
    rollup = build_semantic_rollup(
        policy,
        observations,
        window_start=_START,
        window_end=_START + timedelta(minutes=2),
    )
    partition = semantic_rollup_to_archive_partition(
        rollup,
        partition_id="rollup-partition-1",
        schema_version="semantic-rollup-1.0.0",
    )
    manifest = build_archive_manifest(
        (partition,),
        archive_content_digest=_ARCHIVE,
        compression_profile="zstd-1",
        encryption_profile="platform-managed-1",
        destination_class="archive",
        retention_class="operational-history",
        creation_receipt_digest=_CREATION,
        created_at=_START + timedelta(hours=1),
    )
    verification = verify_archive_manifest(
        manifest,
        observed_archive_content_digest=_ARCHIVE,
        observed_source_partition_digests=(rollup.digest,),
        observed_source_schema_versions=("semantic-rollup-1.0.0",),
        observed_ontology_release_digests=(_RELEASE,),
        verified_at=_START + timedelta(hours=2),
    )
    restore = evaluate_restore_sample(
        manifest,
        verification,
        sampled_partition_digests=(rollup.digest,),
        observed_partition_digests=(rollup.digest,),
        restored_object_count=0,
        restored_relationship_count=2,
        failure_code=None,
        sampled_at=_START + timedelta(hours=3),
    )
    retention = evaluate_retention_holds(
        manifest,
        (),
        evaluated_at=_START + timedelta(hours=4),
    )
    return rollup, manifest, verification, restore, retention, observations


async def test_observation_rollup_archive_restore_and_duplicate_purge() -> None:
    rollup, manifest, verification, restore, retention, observations = _pipeline()
    replay_revision = replace(
        _revision(0, mutation=InventoryMutationKind.UPSERT),
        mode=InventoryObservationMode.DELTA,
        source_revision="delta-replay-1",
        recorded_at=_START + timedelta(minutes=1, seconds=2),
    )
    replay_observation = inventory_revision_to_rollup_observation(
        replay_revision,
        SemanticRollupPolicy(
            semantic_id=rollup.semantic_id,
            revision=rollup.policy_revision,
            ontology_release_digest=rollup.ontology_release_digest,
            fact_kind=rollup.fact_kind,
            expected_interval_seconds=60,
            statistics=("change_counts",),
        ),
        generation_ref="snapshot-generation-2",
        interval_start=_START,
        interval_end=_START + timedelta(minutes=1),
        complete=True,
        conflict_count=0,
    )
    snapshot_revision = replace(
        replay_revision,
        mode=InventoryObservationMode.SNAPSHOT,
        source_revision="snapshot-replay-1",
        recorded_at=_START + timedelta(minutes=1, seconds=3),
    )
    snapshot_observation = inventory_revision_to_rollup_observation(
        snapshot_revision,
        replay_policy := SemanticRollupPolicy(
            semantic_id=rollup.semantic_id,
            revision=rollup.policy_revision,
            ontology_release_digest=rollup.ontology_release_digest,
            fact_kind=rollup.fact_kind,
            expected_interval_seconds=60,
            statistics=("change_counts",),
        ),
        generation_ref="snapshot-generation-2",
        interval_start=_START,
        interval_end=_START + timedelta(minutes=1),
        complete=True,
        conflict_count=0,
    )
    reordered = build_semantic_rollup(
        replay_policy,
        (
            observations[1],
            replay_observation,
            snapshot_observation,
            observations[0],
            observations[0],
        ),
        window_start=rollup.window_start,
        window_end=rollup.window_end,
    )
    replayed = build_semantic_rollup(
        replay_policy,
        (
            snapshot_observation,
            observations[0],
            observations[1],
            observations[0],
            replay_observation,
        ),
        window_start=rollup.window_start,
        window_end=rollup.window_end,
    )
    receipts = _Receipts()
    source = _Source()
    coordinator = OperationalArchivePurgeCoordinator(receipts=receipts, source=source)

    first = await coordinator.purge(
        manifest,
        verification,
        restore,
        retention,
        idempotency_key="purge-cross-lane-1",
        recorded_at=_START + timedelta(hours=5),
    )
    duplicate = await coordinator.purge(
        manifest,
        verification,
        restore,
        retention,
        idempotency_key="purge-cross-lane-1",
        recorded_at=_START + timedelta(hours=6),
    )

    assert reordered.statistics_json == rollup.statistics_json
    assert replayed.digest == reordered.digest
    assert reordered.observation_count == 2
    assert reordered.generation_refs == (
        "overlay-generation-1",
        "snapshot-generation-2",
    )
    assert reordered.source_revisions == (
        "provider-events@delta-replay-1",
        "provider-events@event-0",
        "provider-events@event-1",
        "provider-events@snapshot-replay-1",
    )
    assert rollup.ontology_release_digest == _RELEASE
    assert rollup.effective_time_range is not None
    assert rollup.event_time_range == rollup.effective_time_range
    assert rollup.recorded_time_range is not None
    assert first.status is ArchivePurgeStatus.SUCCEEDED
    assert duplicate.status is ArchivePurgeStatus.DUPLICATE
    assert source.calls == 1


async def test_incomplete_or_conflicting_rollup_cannot_be_archived_and_purged() -> None:
    for conflict_count, complete in ((1, True), (0, False)):
        _, manifest, verification, restore, retention, _ = _pipeline(
            conflict_count=conflict_count,
            complete=complete,
        )
        receipts = _Receipts()
        source = _Source()
        result = await OperationalArchivePurgeCoordinator(
            receipts=receipts,
            source=source,
        ).purge(
            manifest,
            verification,
            restore,
            retention,
            idempotency_key=f"purge-blocked-{conflict_count}-{complete}",
            recorded_at=_START + timedelta(hours=5),
        )

        assert manifest.coverage_complete is False
        assert verification.verified is False
        assert restore.passed is False
        assert result.status is ArchivePurgeStatus.BLOCKED
        assert result.source_data_preserved is True
        assert source.calls == 0


def test_tampered_archive_verification_stays_failed() -> None:
    _, manifest, _, _, _, _ = _pipeline()
    tampered = replace(manifest, relationship_count=3)

    result = verify_archive_manifest(
        tampered,
        observed_archive_content_digest=_ARCHIVE,
        observed_source_partition_digests=(manifest.source_partitions[0].content_digest,),
        observed_source_schema_versions=("semantic-rollup-1.0.0",),
        observed_ontology_release_digests=(_RELEASE,),
        verified_at=_START + timedelta(hours=2),
    )

    assert result.verified is False
    assert "manifest_digest_mismatch" in result.reason_codes
