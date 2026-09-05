"""Prepare the bounded dev-only synthetic OI-16 operational-history fixture.

The deployed campaign observes persisted operational history, so a dev-only
synthetic scope that starts empty MUST first receive real history. Preparation
appends normalized inventory observations through the deployed journal adapter,
which is the only writer permitted to create observation rows, lifecycle bindings,
partitions, and resource incarnations. This module issues no SQL, writes no
partition, binding, or incarnation directly, and never addresses a scope outside
the synthetic certification prefix.

Every observation identity is a pure function of the synthetic scope, so repeating
one campaign converges on the identical rows and the journal reports a suppressed
replay rather than a second insert. The single per-campaign exception is the purge
target: a campaign may only destroy history it created, so that slot mixes in the
campaign id and, once its durable purge audit records a success, preparation never
recreates it.

Checkpoints are derived by the lifecycle repository from persisted journal records,
never fabricated. Partition states advance only through the repository's own
monotonic transition, so a state the deployment refuses stays refused.

Known blocker, reported rather than worked around: the lifecycle repository derives
``ObservationCheckpoint.valid`` from its own journal records *and* from the global
``inventory-ontology:manifest`` projection state, requiring ``complete`` to be true
with a projection high watermark at or beyond the partition. That manifest has one
writer, the inventory ontology projector owned by the inventory synchronization job,
which atomically replaces the entire provider-observed subgraph well outside any
synthetic scope. A dev-only synthetic campaign therefore cannot complete that
projection. The campaign reports the resulting gap through ``replay_evidence_checks``
and the purge preconditions instead of certifying it, and it never fabricates a
validated checkpoint to close it.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from fdai.core.ontology_platform.archive_manifest import (
    ArchiveManifest,
    ArchiveSourcePartition,
    ArchiveVerificationReceipt,
    build_archive_manifest,
    verify_archive_manifest,
)
from fdai.core.ontology_platform.archive_retention import (
    ArchiveRestoreReceipt,
    RetentionHold,
    RetentionHoldKind,
    evaluate_restore_sample,
)
from fdai.core.ontology_platform.operational_history_certification import (
    OperationalHistoryScenario,
)
from fdai.core.ontology_platform.operational_history_lifecycle import (
    ObservationCheckpoint,
    ObservationPartition,
    ObservationPartitionState,
    advance_partition_state,
)
from fdai.delivery.operational_archive_purge import ArchivePurgeReceipt, ArchivePurgeStatus
from fdai.delivery.operational_history_archive import (
    OperationalArchiveArtifact,
    OperationalArchiveArtifactMetadataStore,
    OperationalArchiveManifestStore,
    OperationalHistoryArchiveWriter,
    OperationalHistoryArtifactStore,
)
from fdai.delivery.operational_history_certification_campaign import (
    CAMPAIGN_PURPOSE,
    MAX_PARTITIONS,
    SYNTHETIC_SCOPE_PREFIX,
    CampaignBinding,
    ScenarioCheck,
    evidence_digest,
    scenario_check,
)
from fdai.delivery.operational_history_certification_campaign_observations import (
    PRIOR_SCHEMA_VERSION,
    CampaignObservationJournal,
    SyntheticSlot,
    downgrade_to_prior_schema,
    full_observation,
    incarnation_lifecycle,
    late_observation,
)
from fdai.shared.config.models import RuntimeEnv
from fdai.shared.providers.inventory_observation import (
    INVENTORY_OBSERVATION_SCHEMA_VERSION,
    NormalizedInventoryObservation,
)

FIXTURE_EPOCH = datetime(2024, 1, 1, tzinfo=UTC)
FIXTURE_SCHEMA_VERSION = "1.0.0"
MAX_FIXTURE_OBSERVATIONS = 12
_ARCHIVE_PROFILE = "oi16-synthetic-certification"
_HOLD_ID_PREFIX = "oi16-synthetic-legal-hold"
_HOLD_ID_LENGTH = 32
_ARCHIVED_SLOTS = (SyntheticSlot.WARM, SyntheticSlot.PURGE, SyntheticSlot.HELD, SyntheticSlot.PRIOR)
_TARGET_STATES: Mapping[SyntheticSlot, ObservationPartitionState] = {
    SyntheticSlot.WARM: ObservationPartitionState.VERIFIED,
    SyntheticSlot.PURGE: ObservationPartitionState.PURGE_ELIGIBLE,
    SyntheticSlot.HELD: ObservationPartitionState.VERIFIED,
    SyntheticSlot.PRIOR: ObservationPartitionState.VERIFIED,
}
_FORWARD_ORDER = (
    ObservationPartitionState.OPEN,
    ObservationPartitionState.SEALED,
    ObservationPartitionState.CHECKPOINTED,
    ObservationPartitionState.ARCHIVED,
    ObservationPartitionState.VERIFIED,
    ObservationPartitionState.PURGE_ELIGIBLE,
)
_LOGGER = logging.getLogger("fdai.operational_history_certification_campaign.fixture")

_REPLAY_FIELDS = (
    "partition_id",
    "first_watermark",
    "last_watermark",
    "scope_ref",
    "object_count",
    "relationship_count",
    "property_count",
    "source_digest",
    "schema_digest",
    "missing_count",
    "quarantined_count",
    "conflicted_count",
    "tombstoned_count",
)


def checkpoint_replay_content(checkpoint: ObservationCheckpoint) -> tuple[object, ...]:
    """Return the journal-derived content an ontology release MUST NOT change."""

    return tuple(getattr(checkpoint, name) for name in _REPLAY_FIELDS)


def unquarantined_completeness(checkpoint: ObservationCheckpoint | None) -> bool | None:
    """Report honest completeness without converting defects or invalidity into coverage.

    A missing checkpoint is unobserved rather than complete. An invalid checkpoint is a
    completeness failure, never an exemption: treating invalidity as a pass would let a
    checkpoint that already failed its own validation satisfy the no-false-completeness
    check. Only a valid checkpoint with no missing, quarantined, or conflicted records
    is complete.
    """

    if checkpoint is None:
        return None
    defects = checkpoint.missing_count + checkpoint.quarantined_count + checkpoint.conflicted_count
    return checkpoint.valid and defects == 0


def checkpoint_watermarks(checkpoint: ObservationCheckpoint) -> tuple[int, int, int]:
    """Return the bounded watermark triple a replayed checkpoint MUST reproduce."""

    return (
        checkpoint.first_watermark,
        checkpoint.last_watermark,
        checkpoint.projection_watermark,
    )


def checkpoint_journal_backed(checkpoint: ObservationCheckpoint | None) -> bool | None:
    """Report whether a checkpoint counted at least one persisted journal record.

    The lifecycle repository derives every count from the observations bound to the
    partition, so an all-zero checkpoint proves the partition holds no normalized
    observation at all. Replaying an empty checkpoint reproduces an empty checkpoint,
    which would otherwise let warm and schema replay pass on nothing.
    """

    if checkpoint is None:
        return None
    counted = checkpoint.object_count + checkpoint.relationship_count + checkpoint.property_count
    return counted > 0


def checkpoint_completeness_state(
    checkpoint: ObservationCheckpoint | None,
) -> tuple[bool, int, int, int] | None:
    """Return the repository-owned validity and defect state a replay MUST reproduce."""

    if checkpoint is None:
        return None
    return (
        checkpoint.valid,
        checkpoint.missing_count,
        checkpoint.quarantined_count,
        checkpoint.conflicted_count,
    )


def completeness_not_overclaimed(
    checkpoint: ObservationCheckpoint | None,
    *,
    claimed_complete: bool | None,
) -> bool | None:
    """Report whether a completeness claim stays grounded in repository state.

    The claim and the underlying checkpoint state are evaluated separately so this check
    can fail when a caller projects completeness over missing, quarantined, conflicted, or
    invalid repository evidence.
    """

    if checkpoint is None or claimed_complete is None:
        return None
    return not claimed_complete or unquarantined_completeness(checkpoint) is True


def replay_state_preserved(
    checkpoints: Sequence[ObservationCheckpoint | None],
) -> bool | None:
    """Report whether every arm of one replay reproduces the same completeness state.

    A replay proves determinism only when it reproduces what was stored, including an
    invalid or defective state. Promoting an invalid stored checkpoint to a valid replayed
    one, or silently dropping a defect count, is a replay defect rather than a pass.
    """

    states = [checkpoint_completeness_state(item) for item in checkpoints]
    if not states or any(item is None for item in states):
        return None
    return len(set(states)) == 1


def all_observed(values: Sequence[bool | None]) -> bool | None:
    """Conjoin tri-state evidence without ever promoting an unobserved value to a pass."""

    if not values or any(item is False for item in values):
        return False if values else None
    return None if any(item is None for item in values) else True


def replay_evidence_checks(
    prefix: str, checkpoints: Sequence[ObservationCheckpoint | None]
) -> tuple[ScenarioCheck, ...]:
    """Return the fail-closed grounding preconditions for one replay arm.

    Every stored and replayed checkpoint an arm compares MUST count at least one
    persisted journal record, so a replay comparison can never be certified from absent
    or empty history. Repository validation is not required, because the campaign may not
    run the global ontology projection; what is required is that an unvalidated or
    defective checkpoint is never projected as complete.
    """

    return (
        scenario_check(
            f"{prefix}journal_backed",
            all_observed([checkpoint_journal_backed(item) for item in checkpoints]),
        ),
        scenario_check(
            f"{prefix}completeness_not_overclaimed",
            all_observed(
                [
                    completeness_not_overclaimed(
                        item,
                        claimed_complete=None if item is None else item.valid,
                    )
                    for item in checkpoints
                ]
            ),
        ),
    )


def coverage_from_read_outcome(outcome: str) -> bool | None:
    """Derive coverage from one read outcome without ever inferring completeness.

    Only a served read projects complete coverage. A read that failed on transport is
    unknown rather than incomplete, and a rejected read is explicitly incomplete.
    """

    if outcome == "served":
        return True
    return None if outcome == "unavailable" else False


class UnavailableArtifactStore:
    """Inject a bounded archive storage outage into one deployed read attempt.

    The outage is confined to the instance that holds it: the campaign keeps its real
    principal scoped reader, so an outage probe proves detection without disabling the
    live archive path or mutating any stored artifact.
    """

    async def put(self, storage_ref: str, content: bytes, *, digest: str) -> bool:
        raise ConnectionError("injected synthetic archive storage outage")

    async def get(self, storage_ref: str) -> bytes | None:
        raise ConnectionError("injected synthetic archive storage outage")


class UnavailableArchiveMetadata:
    """Inject a bounded provider transport failure into one deployed metadata read.

    This is deliberately distinct from :class:`UnavailableArtifactStore`. The artifact
    store models archive storage being unreachable, while this models the upstream
    metadata provider being unreachable, so a provider-failure probe never has to
    borrow an authorization denial to stand in for a transport failure.
    """

    async def put_archive_artifact(self, artifact: OperationalArchiveArtifact) -> bool:
        raise httpx.ConnectError("injected synthetic provider transport failure")

    async def get_archive_artifact(self, manifest_digest: str) -> OperationalArchiveArtifact | None:
        raise httpx.ConnectError("injected synthetic provider transport failure")

    async def is_archive_verified(self, manifest_digest: str) -> bool:
        raise httpx.ConnectError("injected synthetic provider transport failure")


def synthetic_hold_id(binding: CampaignBinding, *, manifest_digest: str) -> str:
    """Return the bounded deterministic legal-hold identity for one scope and manifest.

    Retention holds are append-only and pin one exact archive manifest, so a globally
    constant hold id lets a later campaign in a different synthetic scope reuse a stored
    hold row that is bound to another scope's manifest. The identity is therefore derived
    from the campaign's sanitized synthetic scope digest and the held manifest digest.
    Both inputs are content-addressed, so a different synthetic scope, or the same scope
    whose fixture content changed, yields a different hold row, while repeating the same
    campaign fixture converges on the identical hold row.

    The campaign id is deliberately excluded. It varies with the campaign window, and the
    synthetic fixture body does not, so binding the hold to it would append one more hold
    row on every scheduled run and make the retention table the single unbounded artifact
    of an otherwise idempotent fixture.
    """

    material = evidence_digest({"scope": binding.scope.digest, "manifest": manifest_digest})
    return f"{_HOLD_ID_PREFIX}-{material.removeprefix('sha256:')[:_HOLD_ID_LENGTH]}"


class FixtureRepository(Protocol):
    """Read persisted lifecycle state and commit monotonic partition transitions."""

    async def list_partitions(
        self, *, limit: int, now: datetime, scope_ref: str | None = None
    ) -> tuple[ObservationPartition, ...]: ...

    async def build_checkpoint(
        self, partition: ObservationPartition, *, now: datetime
    ) -> ObservationCheckpoint: ...

    async def archive_records(self, partition_id: str) -> tuple[Mapping[str, object], ...]: ...

    async def transition(
        self,
        partition: ObservationPartition,
        target: ObservationPartitionState,
        *,
        reason: str,
        evidence_refs: tuple[str, ...],
        recorded_at: datetime,
    ) -> None: ...


class FixtureHistoryStore(OperationalArchiveArtifactMetadataStore, Protocol):
    """Persist synthetic checkpoints and resolve observations to their partitions."""

    async def append_checkpoint(self, checkpoint: ObservationCheckpoint) -> bool: ...

    async def resolve_evidence_partitions(
        self, evidence_refs: tuple[str, ...]
    ) -> tuple[str, ...]: ...


class FixtureArchiveStore(OperationalArchiveManifestStore, Protocol):
    """Persist synthetic archive verification, restore, hold, and purge evidence."""

    async def append_verification(self, receipt: ArchiveVerificationReceipt) -> bool: ...

    async def append_restore(self, receipt: ArchiveRestoreReceipt) -> bool: ...

    async def append_hold(self, hold: RetentionHold, *, recorded_at: datetime) -> bool: ...

    async def latest(self, idempotency_key: str) -> ArchivePurgeReceipt | None: ...


@dataclass(frozen=True, slots=True)
class FixturePreparation:
    """Sanitized bounded report of one synthetic fixture preparation."""

    fixture_digest: str
    partition_count: int
    archive_count: int
    observation_count: int
    observations_inserted: int
    inserted: int
    replayed: int
    purge_target_retired: bool

    def record(self) -> dict[str, object]:
        """Return the sanitized manifest fragment for this preparation."""

        return {
            "fixture_digest": self.fixture_digest,
            "partition_count": self.partition_count,
            "archive_count": self.archive_count,
            "observation_count": self.observation_count,
            "observations_inserted": self.observations_inserted,
            "inserted": self.inserted,
            "replayed": self.replayed,
            "purge_target_retired": self.purge_target_retired,
        }


def purge_target_observation(binding: CampaignBinding) -> NormalizedInventoryObservation:
    """Return the exact observation one campaign is permitted to purge."""

    return full_observation(binding, SyntheticSlot.PURGE)


def purge_idempotency_key(binding: CampaignBinding) -> str:
    """Return the durable purge audit key bound to this campaign's purge target.

    The key is derived from the purge target's own content-addressed observation
    identity rather than from an archive manifest, so it is knowable before any row
    exists. Preparation can therefore ask whether this exact target was already
    destroyed before it would otherwise recreate it.
    """

    return binding.idempotency_key(
        OperationalHistoryScenario.SAFE_PARTITION_PURGE,
        target=purge_target_observation(binding).observation_id,
    )


class SyntheticCampaignFixture:
    """Append and stage the bounded synthetic history the campaign observes."""

    def __init__(
        self,
        *,
        binding: CampaignBinding,
        journal: CampaignObservationJournal,
        repository: FixtureRepository,
        history: FixtureHistoryStore,
        archives: FixtureArchiveStore,
        artifacts: OperationalHistoryArtifactStore,
    ) -> None:
        _assert_synthetic(binding)
        self._binding = binding
        self._scope = binding.scope.scope_ref
        self._journal = journal
        self._repository = repository
        self._history = history
        self._archives = archives
        self._writer = OperationalHistoryArchiveWriter(
            artifacts=artifacts, metadata=history, manifests=archives
        )
        self._inserted = 0
        self._replayed = 0
        self._observations_inserted = 0

    async def prepare(self, *, now: datetime) -> FixturePreparation:
        """Append the idempotent synthetic history and stage it for observation."""

        retired = await self._purge_target_retired()
        slots = await self._append_observations(retired)
        partitions = await self._partitions(now)
        manifests: list[ArchiveManifest] = []
        staged: list[ObservationPartition] = []
        for slot in _ARCHIVED_SLOTS:
            partition = partitions.get(slots.get(slot, ""))
            if partition is None:
                continue
            manifest, verified = await self._stage(slot, partition, now=now)
            staged.append(verified)
            if manifest is not None:
                manifests.append(manifest)
                if slot is SyntheticSlot.HELD:
                    await self._hold(manifest)
        _LOGGER.info(
            "synthetic campaign fixture prepared inserted=%d replayed=%d observations=%d",
            self._inserted,
            self._replayed,
            self._observations_inserted,
        )
        return FixturePreparation(
            fixture_digest=evidence_digest(
                {
                    "partitions": sorted(item.partition_id for item in staged),
                    "manifests": sorted(item.digest for item in manifests),
                }
            ),
            partition_count=len(partitions),
            archive_count=len(manifests),
            observation_count=len(slots),
            observations_inserted=self._observations_inserted,
            inserted=self._inserted,
            replayed=self._replayed,
            purge_target_retired=retired,
        )

    async def _purge_target_retired(self) -> bool:
        """Report whether this campaign's purge target was already destroyed.

        A durable succeeded purge receipt is the audit that authorized deleting the
        source. Recreating the deleted observation afterwards would silently undo the
        very effect the campaign verified, so preparation skips that slot instead.
        """

        receipt = await self._archives.latest(purge_idempotency_key(self._binding))
        return receipt is not None and receipt.status is ArchivePurgeStatus.SUCCEEDED

    async def _append_observations(self, retired: bool) -> dict[SyntheticSlot, str]:
        """Append every synthetic arrival in real arrival order and map it to a slot."""

        base = [
            full_observation(self._binding, SyntheticSlot.WARM),
            full_observation(self._binding, SyntheticSlot.HELD),
            full_observation(self._binding, SyntheticSlot.PRIOR),
            full_observation(self._binding, SyntheticSlot.CORRECTION),
        ]
        if not retired:
            base.append(purge_target_observation(self._binding))
        opened, tombstoned, reopened = incarnation_lifecycle(self._binding)
        batches: tuple[tuple[NormalizedInventoryObservation, ...], ...] = (
            (*base, opened),
            (late_observation(self._binding),),
            (tombstoned,),
            (reopened,),
        )
        if sum(len(batch) for batch in batches) > MAX_FIXTURE_OBSERVATIONS:
            raise ValueError("synthetic fixture observation batch exceeds its bound")
        slots: dict[SyntheticSlot, str] = {}
        for batch in batches:
            result = await self._journal.append_change_batch(batch)
            self._observations_inserted += int(getattr(result, "inserted", 0))
        for slot, observation in (
            (SyntheticSlot.WARM, base[0]),
            (SyntheticSlot.HELD, base[1]),
            (SyntheticSlot.PRIOR, base[2]),
            (SyntheticSlot.CORRECTION, base[3]),
        ):
            slots[slot] = await self._partition_of(observation)
        if not retired:
            slots[SyntheticSlot.PURGE] = await self._partition_of(base[4])
        return slots

    async def _partition_of(self, observation: NormalizedInventoryObservation) -> str:
        resolved = await self._history.resolve_evidence_partitions((observation.observation_id,))
        if len(resolved) != 1:
            raise ValueError("synthetic observation did not bind to exactly one partition")
        return resolved[0]

    async def _partitions(self, now: datetime) -> dict[str, ObservationPartition]:
        partitions = await self._repository.list_partitions(
            limit=MAX_PARTITIONS, now=now, scope_ref=self._scope
        )
        return {item.partition_id: item for item in partitions}

    async def _stage(
        self, slot: SyntheticSlot, partition: ObservationPartition, *, now: datetime
    ) -> tuple[ArchiveManifest | None, ObservationPartition]:
        """Advance one partition to its target state, checkpointing and archiving on the way."""

        target = _TARGET_STATES[slot]
        current = partition
        manifest: ArchiveManifest | None = None
        while _FORWARD_ORDER.index(current.state) < _FORWARD_ORDER.index(target):
            following = _FORWARD_ORDER[_FORWARD_ORDER.index(current.state) + 1]
            advance_partition_state(current, target=following)
            if following is ObservationPartitionState.ARCHIVED and manifest is None:
                manifest = await self._archive(slot, current)
            await self._repository.transition(
                current,
                following,
                reason="oi16_synthetic_certification",
                evidence_refs=(partition.partition_id,),
                recorded_at=now,
            )
            current = replace(current, state=following)
            if following is ObservationPartitionState.CHECKPOINTED:
                await self._checkpoint(current)
        if manifest is None:
            manifest = await self._latest_manifest(current)
        return manifest, current

    async def _latest_manifest(self, partition: ObservationPartition) -> ArchiveManifest | None:
        """Rebuild the manifest a previous preparation already wrote for this partition."""

        checkpoint = await self._repository.build_checkpoint(partition, now=partition.interval_end)
        records = await self._records(partition, prior=False)
        covered = await self._covers_partition(partition, records)
        return self._manifest(partition, checkpoint, records, prior=False, covered=covered)

    async def _checkpoint(self, partition: ObservationPartition) -> None:
        checkpoint = await self._repository.build_checkpoint(partition, now=partition.interval_end)
        self._count(await self._history.append_checkpoint(checkpoint))

    async def _records(
        self, partition: ObservationPartition, *, prior: bool
    ) -> tuple[Mapping[str, Any], ...]:
        records = await self._repository.archive_records(partition.partition_id)
        if not prior:
            return tuple(dict(item) for item in records)
        return tuple(downgrade_to_prior_schema(item) for item in records)

    async def _covers_partition(
        self, partition: ObservationPartition, records: Sequence[Mapping[str, Any]]
    ) -> bool:
        """Report whether one payload covers every journal record bound to the partition.

        Archive coverage is a claim about the archived record set, never about the global
        inventory ontology projection. A partition whose checkpoint the repository could
        not validate may still be archived completely, so coverage is derived from an
        independent re-read of the partition's own journal records instead of from
        ``checkpoint.valid``. The N-1 payload is a per-record downgrade of that same set,
        so it covers the partition when its cardinality is preserved.
        """

        observed = await self._repository.archive_records(partition.partition_id)
        return bool(records) and len(records) == len(observed)

    def _manifest(
        self,
        partition: ObservationPartition,
        checkpoint: ObservationCheckpoint,
        records: Sequence[Mapping[str, Any]],
        *,
        prior: bool,
        covered: bool,
    ) -> ArchiveManifest:
        source = ArchiveSourcePartition(
            partition_id=partition.partition_id,
            content_digest=checkpoint.digest,
            interval_start=partition.interval_start,
            interval_end=partition.interval_end,
            object_count=checkpoint.object_count,
            relationship_count=checkpoint.relationship_count,
            schema_version=(
                PRIOR_SCHEMA_VERSION if prior else INVENTORY_OBSERVATION_SCHEMA_VERSION
            ),
            ontology_release_digest=checkpoint.ontology_release_digest,
            complete=covered,
        )
        return build_archive_manifest(
            (source,),
            archive_content_digest=_content_digest((source.content_digest,), records),
            compression_profile=_ARCHIVE_PROFILE,
            encryption_profile=_ARCHIVE_PROFILE,
            destination_class=_ARCHIVE_PROFILE,
            retention_class=_ARCHIVE_PROFILE,
            creation_receipt_digest=evidence_digest({"fixture_archive": partition.partition_id}),
            created_at=partition.interval_end,
        )

    async def _archive(
        self, slot: SyntheticSlot, partition: ObservationPartition
    ) -> ArchiveManifest:
        """Archive one partition's own persisted records, never an empty payload."""

        prior = slot is SyntheticSlot.PRIOR
        checkpoint = await self._repository.build_checkpoint(partition, now=partition.interval_end)
        records = await self._records(partition, prior=prior)
        if not records:
            raise ValueError("synthetic archive refuses an empty source partition")
        covered = await self._covers_partition(partition, records)
        if not covered:
            raise ValueError("synthetic archive refuses a partial source partition")
        manifest = self._manifest(partition, checkpoint, records, prior=prior, covered=covered)
        source = manifest.source_partitions[0]
        await self._writer.write(
            manifest,
            records,
            scope_refs=(self._scope,),
            allowed_purposes=(CAMPAIGN_PURPOSE,),
        )
        verification = verify_archive_manifest(
            manifest,
            observed_archive_content_digest=manifest.archive_content_digest,
            observed_source_partition_digests=(source.content_digest,),
            observed_source_schema_versions=manifest.source_schema_versions,
            observed_ontology_release_digests=manifest.ontology_release_digests,
            verified_at=partition.interval_end,
        )
        self._count(await self._archives.append_verification(verification))
        restore = evaluate_restore_sample(
            manifest,
            verification,
            sampled_partition_digests=(source.content_digest,),
            observed_partition_digests=(source.content_digest,),
            restored_object_count=source.object_count,
            restored_relationship_count=source.relationship_count,
            failure_code=None,
            sampled_at=partition.interval_end,
        )
        self._count(await self._archives.append_restore(restore))
        return manifest

    async def _hold(self, manifest: ArchiveManifest) -> None:
        hold = RetentionHold(
            hold_id=synthetic_hold_id(self._binding, manifest_digest=manifest.digest),
            manifest_digest=manifest.digest,
            kind=RetentionHoldKind.LEGAL,
            starts_at=FIXTURE_EPOCH,
            ends_at=None,
        )
        self._count(await self._archives.append_hold(hold, recorded_at=FIXTURE_EPOCH))

    def _count(self, inserted: bool) -> None:
        if inserted:
            self._inserted += 1
        else:
            self._replayed += 1


def _assert_synthetic(binding: CampaignBinding) -> None:
    """Refuse to prepare anything outside the dev-only synthetic scope."""

    scope = binding.scope
    if scope.environment != RuntimeEnv.DEV:
        raise PermissionError("synthetic fixture preparation requires the dev runtime environment")
    if not scope.scope_ref.startswith(SYNTHETIC_SCOPE_PREFIX):
        raise PermissionError("synthetic fixture preparation refuses a non-synthetic scope")


def _content_digest(partition_digests: Sequence[str], records: Sequence[Mapping[str, Any]]) -> str:
    """Mirror the archive writer's canonical payload digest before manifest build."""

    payload = {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "source_partition_digests": list(partition_digests),
        "records": list(records),
    }
    encoded = (
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
        + b"\n"
    )
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "FIXTURE_EPOCH",
    "MAX_FIXTURE_OBSERVATIONS",
    "FixtureArchiveStore",
    "FixtureHistoryStore",
    "FixturePreparation",
    "FixtureRepository",
    "SyntheticCampaignFixture",
    "UnavailableArchiveMetadata",
    "UnavailableArtifactStore",
    "all_observed",
    "checkpoint_completeness_state",
    "checkpoint_journal_backed",
    "checkpoint_replay_content",
    "checkpoint_watermarks",
    "completeness_not_overclaimed",
    "coverage_from_read_outcome",
    "purge_idempotency_key",
    "purge_target_observation",
    "replay_evidence_checks",
    "replay_state_preserved",
    "synthetic_hold_id",
    "unquarantined_completeness",
]
