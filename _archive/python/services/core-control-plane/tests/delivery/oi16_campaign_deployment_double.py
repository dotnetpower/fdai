"""In-memory deployment double for the OI-16 synthetic certification campaign.

The campaign only produces honest evidence when its writes go through the deployed
observation journal and lifecycle binder. These doubles therefore model those exact
semantics - content-addressed suppression, monotonic watermarks, day-aligned
partitions, late-arrival corrections, incarnation open and close, and the database
owned purge gate - so a focused test can falsify the campaign without a database.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from fdai.core.ontology_platform.archive_manifest import ArchiveManifest, ArchiveVerificationReceipt
from fdai.core.ontology_platform.archive_retention import (
    ArchiveCoverageReceipt,
    ArchiveRestoreReceipt,
    RetentionHold,
)
from fdai.core.ontology_platform.operational_history_lifecycle import (
    ObservationCheckpoint,
    ObservationCorrectionReceipt,
    ObservationPartition,
    ObservationPartitionKind,
    ObservationPartitionPin,
    ObservationPartitionState,
    ResourceIncarnation,
    build_correction_receipt,
    build_observation_checkpoint,
    build_observation_partition,
    build_resource_incarnation,
)
from fdai.core.ontology_platform.operational_history_pressure import (
    StoragePressureAssessment,
    StoragePressurePolicy,
    assess_storage_pressure,
)
from fdai.delivery.operational_archive_purge import ArchivePurgeReceipt, ArchivePurgeStatus
from fdai.delivery.operational_history_archive import OperationalArchiveArtifact
from fdai.delivery.persistence.postgres_inventory_observation import (
    InventoryObservationAppendResult,
)
from fdai.delivery.persistence.postgres_operational_history_lifecycle_runner import (
    ScopeStorageSample,
)
from fdai.shared.providers.inventory_observation import (
    INVENTORY_OBSERVATION_SCHEMA_VERSION,
    InventoryMutationKind,
    InventoryObservationKind,
    InventoryObservationSubjectKind,
    NormalizedInventoryObservation,
)

POLICY_DIGEST = "sha256:" + "1" * 64
GRAPH_DIGEST = "sha256:" + "2" * 64
RELEASE_DIGEST = "sha256:" + "3" * 64
_JOURNAL_FIELDS = (
    "observation_id",
    "content_digest",
    "idempotency_key",
    "subject_kind",
    "observation_kind",
    "mutation_kind",
    "subject_ref",
    "subject_type",
    "property_mask",
    "properties_complete",
    "links_complete",
    "tombstone_confirmed",
    "provider_ref",
    "scope_ref",
    "operation",
    "operation_status",
    "source_identity",
    "source_event_id",
    "source_revision",
    "from_id",
    "from_type",
    "link_type",
    "to_id",
    "to_type",
)


def journal_record(observation: NormalizedInventoryObservation) -> dict[str, object]:
    """Return the canonical journal row shape the archive and replay paths read."""

    record: dict[str, object] = {"schema_version": INVENTORY_OBSERVATION_SCHEMA_VERSION}
    for field in _JOURNAL_FIELDS:
        value = getattr(observation, field)
        record[field] = list(value) if isinstance(value, tuple) else _plain(value)
    record["properties"] = dict(observation.properties)
    for field in ("effective_at", "observed_at", "evidence_cutoff", "recorded_at"):
        record[field] = getattr(observation, field).astimezone(UTC).isoformat()
    return record


def _plain(value: object) -> object:
    return value.value if isinstance(value, InventoryObservationSubjectKind) else _kind(value)


def _kind(value: object) -> object:
    if isinstance(value, InventoryObservationKind | InventoryMutationKind):
        return value.value
    return value


@dataclass(slots=True)
class _Projection:
    """The persisted ontology projection manifest the checkpoint builder reads."""

    complete: bool = True
    watermark: int = 0
    release: str = RELEASE_DIGEST
    graph: str = GRAPH_DIGEST


class FakeDeployment:
    """One in-memory deployment that models the writers the campaign depends on."""

    def __init__(self, *, purge_permitted: bool = True) -> None:
        self.observations: dict[str, NormalizedInventoryObservation] = {}
        self.keys: dict[tuple[str, str, str], str] = {}
        self.watermarks: dict[str, int] = {}
        self.bindings: dict[str, str] = {}
        self.partitions: dict[str, ObservationPartition] = {}
        self.incarnations: dict[str, ResourceIncarnation] = {}
        self.checkpoints: list[ObservationCheckpoint] = []
        self.corrections: dict[str, ObservationCorrectionReceipt] = {}
        self.manifests: dict[str, ArchiveManifest] = {}
        self.verifications: dict[str, ArchiveVerificationReceipt] = {}
        self.restores: dict[str, ArchiveRestoreReceipt] = {}
        self.holds: dict[str, RetentionHold] = {}
        self.coverages: list[ArchiveCoverageReceipt] = []
        self.recovery_records: dict[tuple[str, str], tuple[Mapping[str, object], ...]] = {}
        self.purge_receipts: list[ArchivePurgeReceipt] = []
        self.artifacts_by_manifest: dict[str, OperationalArchiveArtifact] = {}
        self.blobs: dict[str, bytes] = {}
        self.projection = _Projection()
        self.purge_permitted = purge_permitted
        self.purged: list[str] = []
        self._next = 0

    # ---- journal -----------------------------------------------------------------

    async def append_change_batch(
        self, observations: Sequence[NormalizedInventoryObservation]
    ) -> InventoryObservationAppendResult:
        inserted = 0
        for item in observations:
            key = (item.idempotency_key, item.subject_kind.value, item.subject_ref)
            if key in self.keys:
                continue
            self._next += 1
            self.observations[item.observation_id] = item
            self.keys[key] = item.observation_id
            self.watermarks[item.observation_id] = self._next
            inserted += 1
        for item in sorted(observations, key=lambda value: (_priority(value), value.effective_at)):
            if item.observation_id in self.bindings:
                continue
            self.bindings[item.observation_id] = self._bind(item)
        return InventoryObservationAppendResult(self._next, inserted)

    def _bind(self, observation: NormalizedInventoryObservation) -> str:
        late = any(
            other.subject_ref == observation.subject_ref
            and other.observation_id != observation.observation_id
            and other.effective_at > observation.effective_at
            for other in self.observations.values()
        )
        start = observation.effective_at.astimezone(UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        correction_of = None
        if late:
            covering = [
                item
                for item in self.partitions.values()
                if item.kind is ObservationPartitionKind.BASE
                and item.scope_ref == observation.scope_ref
                and item.interval_start <= observation.effective_at < item.interval_end
            ]
            if not covering:
                raise ValueError("late observation has no affected base partition")
            correction_of = covering[-1].partition_id
        watermark = self.watermarks[observation.observation_id]
        partition = build_observation_partition(
            scope_ref=str(observation.scope_ref),
            interval_start=start,
            interval_end=start + timedelta(days=1),
            first_watermark=watermark,
            last_watermark=watermark,
            kind=(ObservationPartitionKind.CORRECTION if late else ObservationPartitionKind.BASE),
            state=(
                ObservationPartitionState.CORRECTION_PENDING
                if late
                else ObservationPartitionState.OPEN
            ),
            correction_of=correction_of,
            retention_policy_digest=POLICY_DIGEST,
            created_at=observation.recorded_at,
        )
        self.partitions.setdefault(partition.partition_id, partition)
        self._incarnate(observation)
        return partition.partition_id

    def _incarnate(self, observation: NormalizedInventoryObservation) -> None:
        if observation.subject_kind is not InventoryObservationSubjectKind.OBJECT:
            return
        live = [
            item
            for item in self.incarnations.values()
            if item.resource_ref == observation.subject_ref and item.closed_at is None
        ]
        if not live:
            if observation.observation_kind is not InventoryObservationKind.FULL:
                raise ValueError("sparse or tombstone observation has no current incarnation")
            incarnation = build_resource_incarnation(
                resource_ref=observation.subject_ref,
                resource_type=observation.subject_type,
                provider_identity=str(observation.provider_ref),
                lifecycle_boundary_ref=observation.source_revision,
                opened_at=observation.effective_at,
                opening_observation_id=observation.observation_id,
            )
            self.incarnations[incarnation.incarnation_id] = incarnation
            live = [incarnation]
        if (
            observation.mutation_kind is InventoryMutationKind.DELETE
            and observation.tombstone_confirmed
        ):
            current = live[0]
            self.incarnations[current.incarnation_id] = current.close(
                closed_at=observation.effective_at,
                closing_observation_id=observation.observation_id,
            )

    # ---- lifecycle repository ----------------------------------------------------

    async def list_partitions(
        self, *, limit: int, now: datetime, scope_ref: str | None = None
    ) -> tuple[ObservationPartition, ...]:
        selected = [
            item
            for item in self.partitions.values()
            if item.state is not ObservationPartitionState.PURGED
            and (item.state is not ObservationPartitionState.OPEN or item.interval_end <= now)
            and (scope_ref is None or item.scope_ref == scope_ref)
        ]
        selected.sort(key=lambda item: (item.interval_start, item.partition_id))
        return tuple(selected[:limit])

    async def build_checkpoint(
        self, partition: ObservationPartition, *, now: datetime
    ) -> ObservationCheckpoint:
        records = await self.archive_records(partition.partition_id)
        source = _digest(list(records))
        valid = (
            bool(records)
            and self.projection.complete
            and self.projection.watermark >= partition.last_watermark
        )
        return build_observation_checkpoint(
            partition_id=partition.partition_id,
            first_watermark=partition.first_watermark,
            last_watermark=partition.last_watermark,
            scope_ref=partition.scope_ref,
            object_count=sum(1 for item in records if item.get("subject_kind") == "object"),
            relationship_count=0,
            property_count=sum(len(_mapping(item.get("properties"))) for item in records),
            source_digest=source,
            schema_digest=_digest(sorted({str(item["schema_version"]) for item in records})),
            ontology_release_digest=self.projection.release,
            projection_digest=self.projection.graph,
            projection_watermark=max(partition.last_watermark, self.projection.watermark),
            graph_digest=self.projection.graph,
            missing_count=0,
            quarantined_count=0,
            conflicted_count=0,
            tombstoned_count=sum(
                1 for item in records if item.get("observation_kind") == "tombstone"
            ),
            valid=valid,
            created_at=now,
        )

    async def archive_records(self, partition_id: str) -> tuple[Mapping[str, object], ...]:
        return tuple(
            journal_record(self.observations[observation_id])
            for observation_id, bound in sorted(
                self.bindings.items(), key=lambda pair: self.watermarks[pair[0]]
            )
            if bound == partition_id and observation_id in self.observations
        )

    async def restore_recovery_records(
        self,
        *,
        campaign_id: str,
        scope_ref: str,
        partition_id: str,
        records: Sequence[Mapping[str, object]],
        recovered_at: datetime,
    ) -> tuple[Mapping[str, object], ...]:
        del recovered_at
        if not campaign_id.startswith("certify-history-") or not scope_ref.startswith(
            "synthetic/oi16-certification/"
        ):
            raise ValueError("recovery rehearsal is outside the synthetic scope")
        key = (campaign_id, partition_id)
        return self.recovery_records.setdefault(key, tuple(dict(item) for item in records))

    async def transition(
        self,
        partition: ObservationPartition,
        target: ObservationPartitionState,
        *,
        reason: str,
        evidence_refs: tuple[str, ...],
        recorded_at: datetime,
    ) -> None:
        current = self.partitions[partition.partition_id]
        if current.state is not partition.state:
            raise RuntimeError("operational history partition state changed concurrently")
        self.partitions[partition.partition_id] = replace(current, state=target)

    async def latest_checkpoint(self, partition_id: str) -> ObservationCheckpoint | None:
        matches = [item for item in self.checkpoints if item.partition_id == partition_id]
        return matches[-1] if matches else None

    async def latest_manifest(self, partition_id: str) -> ArchiveManifest | None:
        matches = [
            item
            for item in self.manifests.values()
            if any(source.partition_id == partition_id for source in item.source_partitions)
        ]
        return matches[-1] if matches else None

    async def latest_manifest_by_digest(self, manifest_digest: str) -> ArchiveManifest | None:
        return self.manifests.get(manifest_digest)

    async def latest_verification(self, manifest_digest: str) -> ArchiveVerificationReceipt | None:
        matches = [
            item for item in self.verifications.values() if item.manifest_digest == manifest_digest
        ]
        return matches[-1] if matches else None

    async def latest_restore(self, manifest_digest: str) -> ArchiveRestoreReceipt | None:
        matches = [
            item for item in self.restores.values() if item.manifest_digest == manifest_digest
        ]
        return matches[-1] if matches else None

    async def active_holds(
        self, manifest_digest: str, *, now: datetime
    ) -> tuple[RetentionHold, ...]:
        return tuple(
            item
            for item in self.holds.values()
            if item.manifest_digest == manifest_digest
            and item.starts_at <= now
            and (item.ends_at is None or now < item.ends_at)
        )

    async def active_pins(
        self, partition_id: str, *, now: datetime
    ) -> tuple[ObservationPartitionPin, ...]:
        return ()

    async def retention_permitted(self, partition: ObservationPartition, *, now: datetime) -> bool:
        if partition.state is not ObservationPartitionState.PURGE_ELIGIBLE:
            return True
        return self.purge_permitted

    async def assess_pressure(self, policy: StoragePressurePolicy) -> StoragePressureAssessment:
        return assess_storage_pressure(
            policy,
            database_bytes=1024,
            purge_backlog=sum(
                1
                for item in self.partitions.values()
                if item.state is ObservationPartitionState.PURGE_ELIGIBLE
            ),
            projection_lag=0,
            growth_bytes_per_second=0,
        )

    async def measure_scope_storage(self, *, scope_ref: str) -> ScopeStorageSample:
        owned = [item for item in self.partitions.values() if item.scope_ref == scope_ref]
        changes = sum(
            1
            for observation_id, partition_id in self.bindings.items()
            if partition_id in {item.partition_id for item in owned}
            and observation_id in self.observations
        )
        return ScopeStorageSample(
            table_bytes=4096 * len(self.observations),
            index_bytes=1024 * len(self.partitions),
            wal_bytes=8192 * (self._next + 1),
            partition_count=sum(
                1 for item in owned if item.state is not ObservationPartitionState.PURGED
            ),
            purge_backlog=sum(
                1 for item in owned if item.state is ObservationPartitionState.PURGE_ELIGIBLE
            ),
            change_count=changes,
        )

    # ---- operational history store ------------------------------------------------

    async def append_checkpoint(self, checkpoint: ObservationCheckpoint) -> bool:
        if any(item.checkpoint_id == checkpoint.checkpoint_id for item in self.checkpoints):
            return False
        self.checkpoints.append(checkpoint)
        return True

    async def resolve_evidence_partitions(self, evidence_refs: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    self.bindings[item]
                    for item in evidence_refs
                    if item in self.bindings and item in self.observations
                }
            )
        )

    async def list_incarnations(
        self, resource_ref: str, *, limit: int = 16
    ) -> tuple[ResourceIncarnation, ...]:
        matches = [item for item in self.incarnations.values() if item.resource_ref == resource_ref]
        matches.sort(key=lambda item: (item.opened_at, item.incarnation_id))
        return tuple(matches[:limit])

    async def latest_correction(
        self, correction_partition_id: str
    ) -> ObservationCorrectionReceipt | None:
        return self.corrections.get(correction_partition_id)

    async def close_scope_corrections(
        self,
        *,
        scope_ref: str,
        generation: str,
        projection_watermark: int,
        closed_at: datetime,
    ) -> None:
        if not self.projection.graph.startswith("sha256:"):
            raise ValueError("ontology manifest digest is unavailable for correction closure")
        for partition_id, partition in list(self.partitions.items()):
            if (
                partition.kind is not ObservationPartitionKind.CORRECTION
                or partition.state is not ObservationPartitionState.CORRECTION_PENDING
                or partition.scope_ref != scope_ref
                or partition.last_watermark > projection_watermark
            ):
                continue
            receipt = build_correction_receipt(
                correction_partition_id=partition_id,
                affected_checkpoint_ids=(),
                correction_manifest_digest=_digest({"correction": partition_id}),
                replay_receipt_digest=_digest({"generation": generation}),
                resulting_graph_digest=self.projection.graph,
                projection_watermark=projection_watermark,
                closed_at=closed_at,
            )
            self.corrections[partition_id] = receipt
            self.partitions[partition_id] = replace(
                partition, state=ObservationPartitionState.CHECKPOINTED
            )

    async def put_archive_artifact(self, artifact: OperationalArchiveArtifact) -> bool:
        if artifact.manifest_digest in self.artifacts_by_manifest:
            return False
        self.artifacts_by_manifest[artifact.manifest_digest] = artifact
        return True

    async def get_archive_artifact(self, manifest_digest: str) -> OperationalArchiveArtifact | None:
        return self.artifacts_by_manifest.get(manifest_digest)

    async def is_archive_verified(self, manifest_digest: str) -> bool:
        return any(
            item.manifest_digest == manifest_digest and item.verified
            for item in self.verifications.values()
        )

    async def purge(self, partition_ids: tuple[str, ...]) -> None:
        for partition_id in sorted(set(partition_ids)):
            partition = self.partitions[partition_id]
            checkpoint = await self.latest_checkpoint(partition_id)
            synthetic_source_complete = (
                checkpoint is not None
                and partition.scope_ref.startswith("synthetic/oi16-certification/")
                and checkpoint.object_count > 0
                and checkpoint.missing_count == 0
                and checkpoint.quarantined_count == 0
                and checkpoint.conflicted_count == 0
            )
            if (
                partition.state is not ObservationPartitionState.PURGE_ELIGIBLE
                or checkpoint is None
                or (not checkpoint.valid and not synthetic_source_complete)
                or not self.purge_permitted
            ):
                raise RuntimeError("observation partition purge gates are incomplete")
            for observation_id, bound in list(self.bindings.items()):
                if bound == partition_id:
                    self.bindings.pop(observation_id)
                    observation = self.observations.pop(observation_id, None)
                    if observation is not None:
                        self.keys.pop(
                            (
                                observation.idempotency_key,
                                observation.subject_kind.value,
                                observation.subject_ref,
                            ),
                            None,
                        )
            self.partitions[partition_id] = replace(
                partition, state=ObservationPartitionState.PURGED
            )
            self.purged.append(partition_id)

    # ---- archive receipt store -----------------------------------------------------

    async def put_manifest(self, manifest: ArchiveManifest) -> bool:
        if manifest.digest in self.manifests:
            return False
        self.manifests[manifest.digest] = manifest
        return True

    async def append_verification(self, receipt: ArchiveVerificationReceipt) -> bool:
        return _insert(self.verifications, receipt.digest, receipt)

    async def append_restore(self, receipt: ArchiveRestoreReceipt) -> bool:
        return _insert(self.restores, receipt.digest, receipt)

    async def append_hold(self, hold: RetentionHold, *, recorded_at: datetime) -> bool:
        return _insert(self.holds, hold.hold_id, hold)

    async def append_coverage(self, receipt: ArchiveCoverageReceipt) -> bool:
        self.coverages.append(receipt)
        return True

    async def append(self, receipt: ArchivePurgeReceipt) -> None:
        self.purge_receipts.append(receipt)

    async def latest(self, idempotency_key: str) -> ArchivePurgeReceipt | None:
        matches = [item for item in self.purge_receipts if item.idempotency_key == idempotency_key]
        if not matches:
            return None
        succeeded = [item for item in matches if item.status is ArchivePurgeStatus.SUCCEEDED]
        return succeeded[-1] if succeeded else matches[-1]

    # ---- artifact store -------------------------------------------------------------

    async def put(self, storage_ref: str, content: bytes, *, digest: str) -> bool:
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("artifact digest mismatch")
        if storage_ref in self.blobs:
            return False
        self.blobs[storage_ref] = content
        return True

    async def get(self, storage_ref: str) -> bytes | None:
        return self.blobs.get(storage_ref)


def _priority(observation: NormalizedInventoryObservation) -> int:
    if (
        observation.subject_kind is InventoryObservationSubjectKind.OBJECT
        and observation.mutation_kind is InventoryMutationKind.UPSERT
    ):
        return 0
    return 2


def _insert[T](store: dict[str, T], key: str, value: T) -> bool:
    if key in store:
        return False
    store[key] = value
    return True


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = ["GRAPH_DIGEST", "POLICY_DIGEST", "RELEASE_DIGEST", "FakeDeployment", "journal_record"]
