"""Observe deployed dev-only synthetic OI-16 behavior through existing adapters.

This module owns the deployment wiring for
:mod:`fdai.delivery.operational_history_certification_campaign`. It never re-implements
lifecycle, archive, retention, or purge logic; it composes the existing PostgreSQL and
principal-scoped Azure Blob adapters and reduces what they report to bounded
scenario observations. Every probe fails closed to ``unavailable``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime
from typing import Any, cast

import httpx
import psycopg

from fdai.core.ontology_platform.archive_manifest import (
    ArchiveManifest,
    ArchiveVerificationReceipt,
)
from fdai.core.ontology_platform.archive_retention import (
    ArchiveRestoreReceipt,
)
from fdai.core.ontology_platform.operational_history_certification import (
    OperationalHistoryScenario,
    build_operational_history_recovery_receipt,
)
from fdai.core.ontology_platform.operational_history_lifecycle import (
    ObservationCheckpoint,
    ObservationPartition,
    ObservationPartitionState,
)
from fdai.core.ontology_platform.operational_history_pressure import (
    StoragePressureLevel,
    StoragePressurePolicy,
)
from fdai.delivery.azure.operational_history_archive import (
    AzureBlobOperationalHistoryArtifactStore,
)
from fdai.delivery.operational_archive_purge import (
    OperationalArchivePurgeCoordinator,
)
from fdai.delivery.operational_history_archive import (
    OperationalArchivePrincipal,
    OperationalHistoryArchiveReader,
)
from fdai.delivery.operational_history_certification_campaign import (
    CAMPAIGN_PURPOSE,
    DIGEST_PATTERN,
    MAX_PARTITIONS,
    CampaignBinding,
    RecoveryBaseline,
    ScenarioObservation,
    evidence_digest,
    scenario_check,
)
from fdai.delivery.operational_history_certification_campaign_archive_probes import (
    ArchiveSelection,
    decode_archive_records,
    observe_archive_outage,
    observe_archive_restore,
    observe_hold_enforcement,
    observe_safe_partition_purge,
    rebuild_archive_coverage,
)
from fdai.delivery.operational_history_certification_campaign_fixture import (
    UnavailableArchiveMetadata,
    UnavailableArtifactStore,
    checkpoint_watermarks,
    completeness_not_overclaimed,
    coverage_from_read_outcome,
    replay_evidence_checks,
    replay_state_preserved,
)
from fdai.delivery.operational_history_certification_campaign_lifecycle_probes import (
    observe_delete_recreate,
    observe_duplicate_delivery,
    observe_late_observation,
    observe_schema_replay,
)
from fdai.delivery.operational_history_certification_campaign_observations import (
    PRIOR_SCHEMA_VERSION,
    CampaignObservationJournal,
)
from fdai.delivery.persistence.postgres_operational_archive import (
    PostgresOperationalArchiveStore,
)
from fdai.delivery.persistence.postgres_operational_history import (
    PostgresOperationalHistoryStore,
)
from fdai.delivery.persistence.postgres_operational_history_lifecycle_runner import (
    PostgresOperationalHistoryLifecycleRepository,
)

_LOGGER = logging.getLogger("fdai.operational_history_certification_campaign_probes")
# Concrete database, HTTP, and socket transport faults only. Broad OSError and
# RuntimeError also carry configuration and programming defects, and reporting
# those as unavailable evidence would hide a broken job behind a missing result.
_PROBE_ERRORS = (psycopg.Error, httpx.HTTPError, ConnectionError, TimeoutError)
MAX_REPLAY_WAL_BYTES = 64 * 1024 * 1024
RECOVERY_STORAGE_ROOT = "operational-history/oi16-purge-recovery"
HARD_PRESSURE = StoragePressureLevel.HARD


_WARM_STATES = (
    ObservationPartitionState.CHECKPOINTED,
    ObservationPartitionState.ARCHIVED,
    ObservationPartitionState.VERIFIED,
    ObservationPartitionState.PURGE_ELIGIBLE,
)
_ArchiveSet = tuple[
    ObservationPartition, ArchiveManifest, ArchiveVerificationReceipt, ArchiveRestoreReceipt
]


def _unobserved(scenario: OperationalHistoryScenario, reason: str) -> ScenarioObservation:
    return ScenarioObservation(scenario=scenario, unavailable_reason=reason)


class DeployedOperationalHistoryCampaignProbes:
    """Observe deployed synthetic behavior through the existing adapters only."""

    def __init__(
        self,
        *,
        repository: PostgresOperationalHistoryLifecycleRepository,
        history: PostgresOperationalHistoryStore,
        archives: PostgresOperationalArchiveStore,
        artifacts: AzureBlobOperationalHistoryArtifactStore,
        policy: StoragePressurePolicy,
        journal: CampaignObservationJournal | None = None,
        prior_baseline: RecoveryBaseline | None = None,
        restart_receipt_digest: str | None = None,
    ) -> None:
        self._repository = repository
        self._journal = journal
        self._history = history
        self._archives = archives
        self._policy = policy
        self._prior = prior_baseline
        self._restart = restart_receipt_digest
        self._artifacts = artifacts
        self._storage_samples: list[dict[str, int]] = []
        self._storage_taken_at: list[datetime] = []
        self._reader = OperationalHistoryArchiveReader(artifacts=artifacts, metadata=history)
        self._outage_reader = OperationalHistoryArchiveReader(
            artifacts=UnavailableArtifactStore(), metadata=history
        )
        self._provider_reader = OperationalHistoryArchiveReader(
            artifacts=artifacts, metadata=UnavailableArchiveMetadata()
        )
        self._purge = OperationalArchivePurgeCoordinator(receipts=archives, source=history)

    @property
    def repository(self) -> PostgresOperationalHistoryLifecycleRepository:
        """Expose the deployed lifecycle repository to the archive-safety probes."""

        return self._repository

    @property
    def archives(self) -> PostgresOperationalArchiveStore:
        """Expose the deployed archive receipt store to the archive-safety probes."""

        return self._archives

    @property
    def artifacts(self) -> AzureBlobOperationalHistoryArtifactStore:
        """Expose the principal-scoped artifact store used by the recovery target."""

        return self._artifacts

    @property
    def reader(self) -> OperationalHistoryArchiveReader:
        """Expose the live principal-scoped archive reader."""

        return self._reader

    @property
    def purge(self) -> OperationalArchivePurgeCoordinator:
        """Expose the deployed purge coordinator that owns every purge gate."""

        return self._purge

    async def scope_partitions(
        self, binding: CampaignBinding, now: datetime
    ) -> tuple[ObservationPartition, ...]:
        """Return this campaign's own partitions for a collaborating probe module."""

        return await self._partitions(binding, now)

    async def archive_selection(
        self, partitions: Sequence[ObservationPartition], *, now: datetime, held: bool
    ) -> ArchiveSelection | None:
        """Return one fully evidenced archive set for a collaborating probe module."""

        return await self._archive_set(partitions, now=now, held=held)

    async def read_outcome(self, binding: CampaignBinding, manifest_digest: str) -> str:
        """Return the bounded live archive read outcome for one manifest."""

        return await self._read_outcome(binding, manifest_digest)

    async def read_outcome_for_scope(
        self, binding: CampaignBinding, manifest_digest: str, *, scope: str
    ) -> str:
        """Return the bounded archive read outcome an alternate scope would observe."""

        return await self._read_outcome(binding, manifest_digest, scope=scope)

    async def observe(
        self,
        scenario: OperationalHistoryScenario,
        binding: CampaignBinding,
        *,
        now: datetime,
    ) -> ScenarioObservation | None:
        """Dispatch one scenario probe and degrade only on a transport fault.

        A database, HTTP, or socket fault is an environment condition and grades
        the scenario unavailable. Every other exception, including a
        configuration or programming ``RuntimeError``, propagates so the job
        fails instead of publishing a scenario as merely unobserved.
        """

        name = f"_observe_{scenario.value}"
        if not hasattr(self, name):
            return None
        handler = cast(
            Callable[[CampaignBinding, datetime], Awaitable[ScenarioObservation]],
            getattr(self, name),
        )
        try:
            return await handler(binding, now)
        except _PROBE_ERRORS:
            _LOGGER.warning("deployed probe failed", extra={"scenario": scenario.value})
            return _unobserved(scenario, "probe_error_unavailable")

    async def baseline(self, binding: CampaignBinding, *, now: datetime) -> RecoveryBaseline | None:
        """Capture independent warm-state watermarks for the restart phases."""

        partitions = await self._partitions(binding, now)
        if not partitions:
            return None
        journal = max(item.last_watermark for item in partitions)
        projection = 0
        index: list[str] = []
        for partition in partitions:
            checkpoint = await self._repository.latest_checkpoint(partition.partition_id)
            if checkpoint is not None:
                projection = max(projection, checkpoint.projection_watermark)
            manifest = await self._repository.latest_manifest(partition.partition_id)
            if manifest is not None:
                index.append(manifest.digest)
        return RecoveryBaseline(
            journal_watermark=journal,
            projection_watermark=projection,
            archive_index_digest=evidence_digest({"index": sorted(set(index))}),
            partition_count=len(partitions),
        )

    async def _partitions(
        self, binding: CampaignBinding, now: datetime
    ) -> tuple[ObservationPartition, ...]:
        """Read this campaign's own partitions with an exact-scope database query.

        Filtering after a bounded ``LIMIT`` would let unrelated partitions crowd the
        synthetic scope out of the result, which the campaign would then read as
        missing evidence rather than as a query bound.
        """

        partitions = await self._repository.list_partitions(
            limit=MAX_PARTITIONS, now=now, scope_ref=binding.scope.scope_ref
        )
        return tuple(item for item in partitions if binding.scope.owns(item.scope_ref))

    async def _archive_set(
        self, partitions: Sequence[ObservationPartition], *, now: datetime, held: bool
    ) -> _ArchiveSet | None:
        for partition in partitions:
            manifest = await self._repository.latest_manifest(partition.partition_id)
            if manifest is None:
                continue
            holds = await self._repository.active_holds(manifest.digest, now=now)
            if bool(holds) is not held:
                continue
            verification = await self._repository.latest_verification(manifest.digest)
            restore = await self._repository.latest_restore(manifest.digest)
            if verification is None or restore is None:
                continue
            return partition, manifest, verification, restore
        return None

    async def _read_outcome(
        self,
        binding: CampaignBinding,
        manifest_digest: str,
        *,
        purpose: str = CAMPAIGN_PURPOSE,
        scope: str | None = None,
    ) -> str:
        """Return the bounded archive read outcome without leaking any scope text."""

        principal = OperationalArchivePrincipal(
            principal_id=binding.campaign_id,
            purpose=purpose,
            scope_refs=(scope or binding.scope.scope_ref,),
        )
        try:
            read = await self._reader.read(principal=principal, manifest_digest=manifest_digest)
        except PermissionError:
            return "denied"
        except LookupError:
            return "missing"
        except ValueError:
            return "corrupt"
        return "verified" if read.artifact_digest.startswith("sha256:") else "corrupt"

    async def sample_storage(self, binding: CampaignBinding, *, now: datetime) -> None:
        """Measure the synthetic scope's real physical footprint once.

        The campaign takes one sample around each idempotent fixture application so
        bounded storage is a measured difference of table bytes, index bytes,
        write-ahead log bytes, purge backlog, and recorded change count, rather than
        an assertion made from a single pressure snapshot.
        """

        measured = await self._repository.measure_scope_storage(scope_ref=binding.scope.scope_ref)
        assessment = await self._repository.assess_pressure(self._policy)
        sample = dict(measured.record())
        sample["pressure_hard"] = int(assessment.level is HARD_PRESSURE)
        sample["hold_dependent"] = int(assessment.hold_completeness_dependent_work)
        self._storage_samples.append(sample)
        self._storage_taken_at.append(now)

    async def _observe_bounded_storage(
        self, binding: CampaignBinding, now: datetime
    ) -> ScenarioObservation:
        """Bound measured storage growth across one idempotent replay of the fixture.

        An idempotent replay MUST add no table bytes, no index bytes, no partition, and
        no recorded change. It does write a bounded amount of write-ahead log, because
        a suppressed insert is still a transaction, so the log is bounded rather than
        required to be unchanged. The observed change count and its rate over the
        sampling interval are published so the bound is legible instead of implied.
        """

        scenario = OperationalHistoryScenario.BOUNDED_STORAGE
        if len(self._storage_samples) < 2:
            return _unobserved(scenario, "bounded_storage_samples_unavailable")
        first, last = self._storage_samples[0], self._storage_samples[-1]
        elapsed = max(0.0, (self._storage_taken_at[-1] - self._storage_taken_at[0]).total_seconds())
        changes = last["change_count"] - first["change_count"]
        partitions = len(await self._partitions(binding, now))
        summary = {
            "table_delta": last["table_bytes"] - first["table_bytes"],
            "index_delta": last["index_bytes"] - first["index_bytes"],
            "wal_delta": last["wal_bytes"] - first["wal_bytes"],
            "partition_delta": last["partition_count"] - first["partition_count"],
            "change_delta": changes,
            "change_count": last["change_count"],
            "change_rate_millis": int(1000 * changes / elapsed) if elapsed > 0 else 0,
            "purge_backlog": last["purge_backlog"],
        }
        return ScenarioObservation(
            scenario=scenario,
            checks=(
                scenario_check(
                    "storage_growth_bounded",
                    summary["table_delta"] <= 0 and summary["index_delta"] <= 0,
                ),
                scenario_check(
                    "replay_change_count_unchanged",
                    summary["change_delta"] == 0 and summary["partition_delta"] == 0,
                ),
                scenario_check(
                    "write_ahead_log_bounded", 0 <= summary["wal_delta"] <= MAX_REPLAY_WAL_BYTES
                ),
                scenario_check("storage_pressure_bounded", not last["pressure_hard"]),
                scenario_check(
                    "purge_backlog_bounded",
                    last["purge_backlog"] <= self._policy.max_purge_backlog,
                ),
                scenario_check("projection_lag_bounded", not last["hold_dependent"]),
                scenario_check(
                    "recorded_change_count_present", last["change_count"] > 0 and partitions > 0
                ),
                scenario_check("partition_count_bounded", 0 < partitions <= MAX_PARTITIONS),
            ),
            evidence_digests=tuple(
                sorted({evidence_digest(first), evidence_digest(last), evidence_digest(summary)})
            ),
        )

    async def _observe_warm_replay(
        self, binding: CampaignBinding, now: datetime
    ) -> ScenarioObservation:
        for partition in await self._partitions(binding, now):
            if partition.state not in _WARM_STATES:
                continue
            stored = await self._repository.latest_checkpoint(partition.partition_id)
            if stored is None:
                continue
            replay = await self._repository.build_checkpoint(partition, now=stored.created_at)
            return ScenarioObservation(
                scenario=OperationalHistoryScenario.WARM_REPLAY,
                checks=(
                    scenario_check("checkpoint_present", True),
                    *replay_evidence_checks("checkpoint_", (stored, replay)),
                    scenario_check(
                        "replay_state_preserved", replay_state_preserved((stored, replay))
                    ),
                    scenario_check("replay_digest_matches", replay.digest == stored.digest),
                    scenario_check(
                        "replay_watermarks_match",
                        checkpoint_watermarks(replay) == checkpoint_watermarks(stored),
                    ),
                    scenario_check(
                        "replay_graph_digest_matches", replay.graph_digest == stored.graph_digest
                    ),
                ),
                evidence_digests=tuple(sorted({stored.digest, replay.digest})),
            )
        return _unobserved(OperationalHistoryScenario.WARM_REPLAY, "warm_checkpoint_unavailable")

    async def _observe_archive_restore(
        self, binding: CampaignBinding, now: datetime
    ) -> ScenarioObservation:
        """Delegate archive restore evidence to the archive-safety module."""

        return await observe_archive_restore(self, binding, now)

    async def _observe_safe_partition_purge(
        self, binding: CampaignBinding, now: datetime
    ) -> ScenarioObservation:
        """Delegate the destructive scenario to the single archive-safety module."""

        return await observe_safe_partition_purge(self, binding, now)

    async def _observe_schema_replay(
        self, binding: CampaignBinding, now: datetime
    ) -> ScenarioObservation:
        """Replay one persisted current record and one archived N-1 record."""

        partitions = await self._partitions(binding, now)
        archived = await self._prior_archive_records(binding, partitions)
        observation = await observe_schema_replay(
            binding=binding,
            records=self._repository,
            partitions=partitions,
            archived=archived,
        )
        if observation.unavailable_reason is not None:
            return observation
        observed: list[ObservationCheckpoint | None] = [
            await self._repository.latest_checkpoint(item.partition_id) for item in partitions
        ]
        checkpoints: list[ObservationCheckpoint | None] = [
            item for item in observed if item is not None
        ] or [None]
        return ScenarioObservation(
            scenario=observation.scenario,
            checks=(*observation.checks, *replay_evidence_checks("schema_", checkpoints)),
            evidence_digests=observation.evidence_digests,
        )

    async def _prior_archive_records(
        self, binding: CampaignBinding, partitions: Sequence[ObservationPartition]
    ) -> tuple[Mapping[str, Any], ...]:
        """Read the archived N-1 payload back through the principal-scoped reader."""

        for partition in partitions:
            manifest = await self._repository.latest_manifest(partition.partition_id)
            if manifest is None or PRIOR_SCHEMA_VERSION not in manifest.source_schema_versions:
                continue
            try:
                read = await self._reader.read(
                    principal=self._principal(binding), manifest_digest=manifest.digest
                )
            except (LookupError, PermissionError, ValueError):
                continue
            return decode_archive_records(read.content)
        return ()

    async def _observe_database_recovery(
        self, binding: CampaignBinding, now: datetime
    ) -> ScenarioObservation:
        """Restore synthetic records, rebuild archive coverage, and compare watermarks.

        Comparing two restart baselines alone would only prove that the database came
        back. Recovery additionally rebuilds the scope's archive coverage index from
        the persisted manifests, restores each indexed artifact through the deployed
        reader so its content is verified rather than assumed, writes those records
        into the append-only database recovery target, and persists the rebuilt
        coverage receipt as durable evidence.
        """

        scenario = OperationalHistoryScenario.DATABASE_RECOVERY
        after = await self.baseline(binding, now=now)
        if self._prior is None or after is None:
            return _unobserved(scenario, "recovery_baseline_unavailable")
        before = self._prior
        receipt = build_operational_history_recovery_receipt(
            source_revision=binding.source_revision,
            before_journal_watermark=before.journal_watermark,
            after_journal_watermark=after.journal_watermark,
            before_projection_watermark=before.projection_watermark,
            after_projection_watermark=after.projection_watermark,
            before_archive_index_digest=before.archive_index_digest,
            after_archive_index_digest=after.archive_index_digest,
            recovered_at=now,
        )
        selection = await self._archive_set(
            await self._partitions(binding, now), now=now, held=False
        )
        if selection is None:
            return _unobserved(scenario, "database_restore_source_unavailable")
        partition, manifest, _, _ = selection
        try:
            archive_read = await self._reader.read(
                principal=self._principal(binding), manifest_digest=manifest.digest
            )
        except (LookupError, PermissionError, ValueError):
            return _unobserved(scenario, "database_restore_archive_unavailable")
        source_records = decode_archive_records(archive_read.content)
        restored_records = await self._repository.restore_recovery_records(
            campaign_id=binding.campaign_id,
            scope_ref=binding.scope.scope_ref,
            partition_id=partition.partition_id,
            records=source_records,
            recovered_at=now,
        )
        source_record_digest = evidence_digest(
            {"records": sorted(source_records, key=lambda item: str(item["observation_id"]))}
        )
        restored_record_digest = evidence_digest(
            {"records": sorted(restored_records, key=lambda item: str(item["observation_id"]))}
        )
        database_restored = (
            bool(source_records)
            and len(restored_records) == len(source_records)
            and restored_record_digest == source_record_digest
        )
        coverage, restored, scope_complete = await rebuild_archive_coverage(self, binding, now)
        digests = {receipt.digest, source_record_digest, restored_record_digest}
        if coverage is not None:
            digests.add(coverage)
        return ScenarioObservation(
            scenario=scenario,
            checks=(
                scenario_check("recovery_receipt_complete", receipt.complete),
                scenario_check("database_records_restored", database_restored),
                scenario_check(
                    "journal_watermark_restored",
                    before.journal_watermark == after.journal_watermark,
                ),
                scenario_check(
                    "projection_watermark_restored",
                    before.projection_watermark == after.projection_watermark,
                ),
                scenario_check(
                    "archive_index_digest_restored",
                    before.archive_index_digest == after.archive_index_digest,
                ),
                scenario_check("archive_coverage_rebuilt", scope_complete),
                scenario_check("archive_artifact_content_restored", restored),
            ),
            evidence_digests=tuple(sorted(digests)),
        )

    async def _observe_database_restart(
        self, binding: CampaignBinding, now: datetime
    ) -> ScenarioObservation:
        scenario = OperationalHistoryScenario.DATABASE_RESTART
        if self._restart is None or DIGEST_PATTERN.fullmatch(self._restart) is None:
            return _unobserved(scenario, "restart_receipt_unavailable")
        after = await self.baseline(binding, now=now)
        if self._prior is None or after is None:
            return _unobserved(scenario, "restart_baseline_unavailable")
        warm = await self._observe_warm_replay(binding, now)
        intact = (
            None
            if warm.unavailable_reason is not None
            or any(item.satisfied is None for item in warm.checks)
            else all(item.satisfied is True for item in warm.checks)
        )
        retained = (
            after.partition_count >= self._prior.partition_count
            and after.journal_watermark >= self._prior.journal_watermark
        )
        return ScenarioObservation(
            scenario=scenario,
            checks=(
                scenario_check("restart_receipt_present", True),
                scenario_check("warm_state_intact_after_restart", intact),
                scenario_check("no_evidence_loss_after_restart", retained),
            ),
            evidence_digests=tuple(sorted({self._restart, after.archive_index_digest})),
        )

    async def _observe_hold_enforcement(
        self, binding: CampaignBinding, now: datetime
    ) -> ScenarioObservation:
        """Delegate retention-hold enforcement to the archive-safety module."""

        return await observe_hold_enforcement(self, binding, now)

    async def _observe_duplicate_delivery(
        self, binding: CampaignBinding, now: datetime
    ) -> ScenarioObservation:
        """Redeliver one exact normalized observation through the real journal."""

        if self._journal is None:
            return _unobserved(
                OperationalHistoryScenario.DUPLICATE_DELIVERY, "journal_adapter_unavailable"
            )
        return await observe_duplicate_delivery(
            binding=binding,
            journal=self._journal,
            history=self._history,
            partitions=await self._partitions(binding, now),
        )

    async def _observe_late_observation(
        self, binding: CampaignBinding, now: datetime
    ) -> ScenarioObservation:
        """Observe the real correction binding and close it inside this scope only."""

        return await observe_late_observation(
            binding=binding,
            now=now,
            history=self._history,
            partitions=await self._partitions(binding, now),
        )

    async def _observe_delete_recreate(
        self, binding: CampaignBinding, now: datetime
    ) -> ScenarioObservation:
        """Verify the persisted closed and open incarnations the lifecycle produced."""

        return await observe_delete_recreate(binding=binding, history=self._history)

    async def _observe_provider_failure(
        self, binding: CampaignBinding, now: datetime
    ) -> ScenarioObservation:
        """Detect a real injected provider transport failure on the deployed read path.

        The failure is injected into the upstream metadata provider, which is a
        different composition seam from the archive storage outage probe. An
        authorization denial is a policy decision rather than a provider failure, so
        it is never relabeled as one here. The failed read derives no coverage, which
        proves the campaign cannot project completeness out of an unavailable provider.
        """

        scenario = OperationalHistoryScenario.PROVIDER_FAILURE
        partitions = await self._partitions(binding, now)
        selection = await self._archive_set(partitions, now=now, held=False)
        if selection is None:
            return _unobserved(scenario, "provider_evidence_unavailable")
        partition, manifest, _, _ = selection
        before = await self._read_outcome(binding, manifest.digest)
        failed = await self._provider_read(binding, manifest.digest)
        after = await self._read_outcome(binding, manifest.digest)
        checkpoint = await self._repository.latest_checkpoint(partition.partition_id)
        return ScenarioObservation(
            scenario=scenario,
            checks=(
                scenario_check("provider_failure_detected", failed == "unavailable"),
                scenario_check("failure_isolated", before == "verified" and after == "verified"),
                scenario_check(
                    "partial_evidence_marked_incomplete",
                    coverage_from_read_outcome(failed) is not True,
                ),
                scenario_check(
                    "no_false_completeness",
                    completeness_not_overclaimed(
                        checkpoint,
                        claimed_complete=None if checkpoint is None else checkpoint.valid,
                    ),
                ),
            ),
            evidence_digests=tuple(
                sorted(
                    {
                        manifest.digest,
                        evidence_digest(
                            {
                                "seam": "metadata_provider",
                                "before": before,
                                "injected": failed,
                                "after": after,
                                "manifest": manifest.digest,
                                "partition": partition.partition_id,
                                "coverage": coverage_from_read_outcome(failed),
                            }
                        ),
                    }
                )
            ),
        )

    async def _observe_archive_outage(
        self, binding: CampaignBinding, now: datetime
    ) -> ScenarioObservation:
        """Delegate the injected storage outage to the archive-safety module."""

        return await observe_archive_outage(self, binding, now)

    def principal(self, binding: CampaignBinding) -> OperationalArchivePrincipal:
        """Return the campaign principal a collaborating probe module reuses."""

        return self._principal(binding)

    def _principal(self, binding: CampaignBinding) -> OperationalArchivePrincipal:
        """Return the campaign principal every injected read reuses unchanged."""

        return OperationalArchivePrincipal(
            principal_id=binding.campaign_id,
            purpose=CAMPAIGN_PURPOSE,
            scope_refs=(binding.scope.scope_ref,),
        )

    async def _provider_read(self, binding: CampaignBinding, manifest_digest: str) -> str:
        """Return the outcome of one read whose metadata provider is forced unavailable."""

        try:
            await self._provider_reader.read(
                principal=self._principal(binding), manifest_digest=manifest_digest
            )
        except httpx.HTTPError:
            return "unavailable"
        except (LookupError, PermissionError, ValueError):
            return "rejected"
        return "served"

    async def outage_read(self, binding: CampaignBinding, manifest_digest: str) -> str:
        """Return the outcome of one read whose artifact storage is forced unavailable."""

        return await self._outage_read(binding, manifest_digest)

    async def _outage_read(self, binding: CampaignBinding, manifest_digest: str) -> str:
        """Return the outcome of one read whose artifact storage is forced unavailable."""

        try:
            await self._outage_reader.read(
                principal=self._principal(binding), manifest_digest=manifest_digest
            )
        except ConnectionError:
            return "unavailable"
        except (LookupError, PermissionError, ValueError):
            return "rejected"
        return "served"


def _decode_records(content: bytes) -> tuple[Mapping[str, Any], ...]:
    """Decode the canonical archive payload written by the archive writer."""

    payload = json.loads(content.decode())
    if not isinstance(payload, dict):
        raise ValueError("archive payload MUST decode to an object")
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("archive payload records MUST be an array")
    return tuple(dict(item) for item in records if isinstance(item, Mapping))


def _archive_payload_digest(
    partition_digests: Sequence[str], records: Sequence[Mapping[str, Any]]
) -> str:
    """Recompute the archive writer's canonical payload digest from live source rows."""

    payload = {
        "schema_version": "1.0.0",
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
    "MAX_REPLAY_WAL_BYTES",
    "RECOVERY_STORAGE_ROOT",
    "DeployedOperationalHistoryCampaignProbes",
]
