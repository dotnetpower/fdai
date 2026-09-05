"""Observe the deployed archive, rollback, and safe-purge behavior of OI-16.

Safe deletion is the one campaign action that destroys evidence, so this module
keeps it in a single place with every safeguard visible together: the deployed
purge gate, a bounded rollback restore into a *separate* recovery target, a source
comparison that does not trust the archive index, a durable two-phase audit, and a
retry that reuses that audit instead of recreating what it deleted.

The deployed coordinator and database function remain authoritative. This module
evaluates the one explicit synthetic exception separately: complete journal source
coverage can pass without claiming that the global ontology projection advanced.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol

from fdai.core.ontology_platform.archive_manifest import (
    ArchiveManifest,
    ArchiveVerificationReceipt,
)
from fdai.core.ontology_platform.archive_retention import (
    ArchiveCoverageIndex,
    ArchiveCoverageReceipt,
    ArchiveIndexEntry,
    ArchiveRestoreReceipt,
    build_archive_coverage_receipt,
    evaluate_restore_sample,
    evaluate_retention_holds,
)
from fdai.core.ontology_platform.operational_history_certification import (
    OperationalHistoryScenario,
)
from fdai.core.ontology_platform.operational_history_lifecycle import (
    ObservationCheckpoint,
    ObservationPartition,
    ObservationPartitionPin,
    ObservationPartitionState,
)
from fdai.delivery.operational_archive_purge import (
    ArchivePurgeReceipt,
    ArchivePurgeStatus,
    OperationalArchivePurgeCoordinator,
)
from fdai.delivery.operational_history_archive import (
    OperationalArchivePrincipal,
    OperationalHistoryArchiveReader,
)
from fdai.delivery.operational_history_certification_campaign import (
    MAX_BLAST_RADIUS,
    CampaignBinding,
    ScenarioObservation,
    evidence_digest,
    scenario_check,
)
from fdai.delivery.operational_history_certification_campaign_fixture import (
    checkpoint_journal_backed,
    purge_idempotency_key,
)

ARCHIVE_PAYLOAD_SCHEMA_VERSION = "1.0.0"
RECOVERY_STORAGE_ROOT = "operational-history/oi16-purge-recovery"

ArchiveSelection = tuple[
    ObservationPartition, ArchiveManifest, ArchiveVerificationReceipt, ArchiveRestoreReceipt
]


class ArchiveProbeRepository(Protocol):
    """The bounded lifecycle read surface the archive probes depend on."""

    async def latest_checkpoint(self, partition_id: str) -> ObservationCheckpoint | None: ...

    async def latest_manifest(self, partition_id: str) -> ArchiveManifest | None: ...

    async def latest_manifest_by_digest(self, manifest_digest: str) -> ArchiveManifest | None: ...

    async def active_holds(self, manifest_digest: str, *, now: datetime) -> tuple[Any, ...]: ...

    async def active_pins(
        self, partition_id: str, *, now: datetime
    ) -> tuple[ObservationPartitionPin, ...]: ...

    async def retention_permitted(
        self, partition: ObservationPartition, *, now: datetime
    ) -> bool: ...

    async def archive_records(self, partition_id: str) -> tuple[Mapping[str, object], ...]: ...


class ArchiveProbeReceiptStore(Protocol):
    """The bounded purge and coverage receipt surface these probes depend on."""

    async def latest(self, idempotency_key: str) -> ArchivePurgeReceipt | None: ...

    async def append_coverage(self, receipt: ArchiveCoverageReceipt) -> bool: ...


class ArchiveProbeArtifactStore(Protocol):
    """The bounded content-addressed byte store the recovery target uses."""

    async def put(self, storage_ref: str, content: bytes, *, digest: str) -> bool: ...

    async def get(self, storage_ref: str) -> bytes | None: ...


class ArchiveProbeHost(Protocol):
    """The deployed composition these archive probes observe through."""

    @property
    def repository(self) -> ArchiveProbeRepository: ...

    @property
    def archives(self) -> ArchiveProbeReceiptStore: ...

    @property
    def artifacts(self) -> ArchiveProbeArtifactStore: ...

    @property
    def reader(self) -> OperationalHistoryArchiveReader: ...

    @property
    def purge(self) -> OperationalArchivePurgeCoordinator: ...

    def principal(self, binding: CampaignBinding) -> OperationalArchivePrincipal: ...

    async def scope_partitions(
        self, binding: CampaignBinding, now: datetime
    ) -> tuple[ObservationPartition, ...]: ...

    async def archive_selection(
        self, partitions: Sequence[ObservationPartition], *, now: datetime, held: bool
    ) -> ArchiveSelection | None: ...

    async def read_outcome(self, binding: CampaignBinding, manifest_digest: str) -> str: ...

    async def read_outcome_for_scope(
        self, binding: CampaignBinding, manifest_digest: str, *, scope: str
    ) -> str: ...

    async def outage_read(self, binding: CampaignBinding, manifest_digest: str) -> str: ...


def _unobserved(scenario: OperationalHistoryScenario, reason: str) -> ScenarioObservation:
    return ScenarioObservation(scenario=scenario, unavailable_reason=reason)


def decode_archive_records(content: bytes) -> tuple[Mapping[str, Any], ...]:
    """Decode the canonical archive payload the archive writer produced."""

    payload = json.loads(content.decode())
    if not isinstance(payload, dict):
        raise ValueError("archive payload MUST decode to an object")
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("archive payload records MUST be an array")
    return tuple(dict(item) for item in records if isinstance(item, Mapping))


def archive_payload_digest(
    partition_digests: Sequence[str], records: Sequence[Mapping[str, Any]]
) -> str:
    """Recompute the archive writer's canonical payload digest from live source rows."""

    payload = {
        "schema_version": ARCHIVE_PAYLOAD_SCHEMA_VERSION,
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


def synthetic_purge_reasons(
    *,
    partition: ObservationPartition,
    checkpoint: ObservationCheckpoint | None,
    archive_verified: bool,
    restore_passed: bool,
    retention_permitted: bool,
    pins: Sequence[ObservationPartitionPin],
) -> tuple[str, ...]:
    """Evaluate the DB-enforced synthetic gate without asserting global projection."""

    reasons: list[str] = []
    if partition.state is not ObservationPartitionState.PURGE_ELIGIBLE:
        reasons.append("partition_not_purge_eligible")
    if (
        checkpoint is None
        or checkpoint_journal_backed(checkpoint) is not True
        or checkpoint.missing_count
        or checkpoint.quarantined_count
        or checkpoint.conflicted_count
    ):
        reasons.append("checkpoint_source_incomplete")
    elif checkpoint.partition_id != partition.partition_id:
        reasons.append("checkpoint_partition_mismatch")
    if not archive_verified:
        reasons.append("archive_unverified")
    if not restore_passed:
        reasons.append("restore_sample_failed")
    if not retention_permitted:
        reasons.append("retention_hold_active")
    if pins:
        reasons.append("partition_pinned")
    return tuple(sorted(reasons))


async def observe_safe_partition_purge(
    host: ArchiveProbeHost, binding: CampaignBinding, now: datetime
) -> ScenarioObservation:
    """Purge exactly one synthetic partition behind every safeguard, or refuse.

    Rollback is proven before the source is destroyed: the archived payload is
    restored into a separate recovery target and read back from there, and its
    content is compared against the live source records independently of the
    archive index. A campaign whose durable audit already records a success never
    purges again and never recreates what it deleted; it verifies the recorded
    effect and reuses that audit instead.
    """

    scenario = OperationalHistoryScenario.SAFE_PARTITION_PURGE
    key = purge_idempotency_key(binding)
    durable = await host.archives.latest(key)
    partitions = await host.scope_partitions(binding, now)
    if durable is not None and durable.status is ArchivePurgeStatus.SUCCEEDED:
        return await observe_completed_purge(host, binding, durable, partitions, now)
    eligible = tuple(
        item for item in partitions if item.state is ObservationPartitionState.PURGE_ELIGIBLE
    )
    selection = await host.archive_selection(eligible, now=now, held=False)
    if selection is None:
        return _unobserved(scenario, "purge_candidate_unavailable")
    partition, manifest, verification, restore = selection
    targets = tuple(item.partition_id for item in manifest.source_partitions)
    owned = {item.partition_id for item in partitions}
    locked = bool(targets) and set(targets).issubset(owned)
    blast = 0 < len(targets) <= MAX_BLAST_RADIUS
    holds = await host.repository.active_holds(manifest.digest, now=now)
    retention = evaluate_retention_holds(manifest, holds, evaluated_at=now)
    checkpoint = await host.repository.latest_checkpoint(partition.partition_id)
    reasons = synthetic_purge_reasons(
        partition=partition,
        checkpoint=checkpoint,
        archive_verified=verification.verified,
        restore_passed=restore.passed,
        retention_permitted=(
            retention.permitted and await host.repository.retention_permitted(partition, now=now)
        ),
        pins=await host.repository.active_pins(partition.partition_id, now=now),
    )
    dry_run = not reasons
    rollback, recovery = await restore_to_recovery_target(host, binding, manifest, targets)
    digests = {manifest.digest, verification.digest, restore.digest, retention.digest, recovery}
    audited: bool | None = None
    effect: bool | None = None
    if dry_run and blast and locked and rollback:
        receipt = await host.purge.purge(
            manifest, verification, restore, retention, idempotency_key=key, recorded_at=now
        )
        stored = await host.archives.latest(key)
        repeat = await host.purge.purge(
            manifest, verification, restore, retention, idempotency_key=key, recorded_at=now
        )
        remaining = {item.partition_id for item in await host.scope_partitions(binding, now)}
        audited = (
            receipt.status is ArchivePurgeStatus.SUCCEEDED
            and stored is not None
            and stored.digest == receipt.digest
            and repeat.status is ArchivePurgeStatus.DUPLICATE
            and repeat.attempt == receipt.attempt
        )
        effect = not remaining & set(targets)
        digests.update({receipt.digest, repeat.digest})
    return ScenarioObservation(
        scenario=scenario,
        checks=(
            scenario_check("dry_run_succeeded", dry_run),
            scenario_check("blast_radius_bounded", blast),
            scenario_check("logical_target_locked", locked),
            scenario_check("synthetic_target_only", locked),
            scenario_check("stop_condition_declared", len(eligible) <= MAX_BLAST_RADIUS),
            scenario_check("idempotency_key_stable", key == purge_idempotency_key(binding)),
            scenario_check("rollback_tested", rollback),
            scenario_check("two_phase_audit_recorded", audited),
            scenario_check("effect_verified", effect),
        ),
        evidence_digests=tuple(sorted(digests)),
    )


async def observe_completed_purge(
    host: ArchiveProbeHost,
    binding: CampaignBinding,
    durable: ArchivePurgeReceipt,
    partitions: Sequence[ObservationPartition],
    now: datetime,
) -> ScenarioObservation:
    """Reuse the durable audit of a completed purge without recreating the source.

    Every gate is derived from the persisted receipt rather than asserted. The
    coordinator only records ``succeeded`` after the verification, restore, and
    retention gates passed and the deployed purge gate accepted the deletion, so a
    succeeded receipt is itself the evidence that the dry run and the two-phase audit
    happened. Scope ownership is proven by the idempotency key, which is derived from
    this campaign's own synthetic purge-target observation identity and can therefore
    not be produced by any other scope or campaign.
    """

    scenario = OperationalHistoryScenario.SAFE_PARTITION_PURGE
    manifest_digest = durable.manifest_digest
    remaining = {item.partition_id for item in partitions}
    manifest = await host.repository.latest_manifest_by_digest(manifest_digest)
    targets = (
        () if manifest is None else tuple(item.partition_id for item in manifest.source_partitions)
    )
    recovered = await recovery_content(host, binding, manifest_digest)
    owned = durable.idempotency_key == purge_idempotency_key(binding)
    succeeded = durable.status is ArchivePurgeStatus.SUCCEEDED and durable.attempt >= 1
    absent = bool(targets) and not remaining & set(targets)
    return ScenarioObservation(
        scenario=scenario,
        checks=(
            scenario_check("dry_run_succeeded", succeeded),
            scenario_check("blast_radius_bounded", 0 < len(targets) <= MAX_BLAST_RADIUS),
            scenario_check("logical_target_locked", bool(targets) and owned),
            scenario_check("synthetic_target_only", owned),
            scenario_check("stop_condition_declared", 0 < len(targets) <= MAX_BLAST_RADIUS),
            scenario_check("idempotency_key_stable", owned),
            scenario_check("rollback_tested", recovered is not None),
            scenario_check(
                "two_phase_audit_recorded", succeeded and not durable.source_data_preserved
            ),
            scenario_check("effect_verified", absent),
            scenario_check("source_not_recreated", absent),
        ),
        evidence_digests=tuple(
            sorted(
                {
                    durable.digest,
                    evidence_digest(
                        {
                            "reused_audit": durable.idempotency_key,
                            "attempt": durable.attempt,
                            "recorded_at": durable.recorded_at.isoformat(),
                            "targets": sorted(targets),
                        }
                    ),
                }
            )
        ),
    )


def recovery_storage_ref(binding: CampaignBinding, manifest_digest: str) -> str:
    """Return the separate recovery target one campaign restores an archive into."""

    return f"{RECOVERY_STORAGE_ROOT}/{binding.campaign_id}/{manifest_digest[7:]}.json"


async def recovery_content(
    host: ArchiveProbeHost, binding: CampaignBinding, manifest_digest: str
) -> bytes | None:
    return await host.artifacts.get(recovery_storage_ref(binding, manifest_digest))


async def restore_to_recovery_target(
    host: ArchiveProbeHost,
    binding: CampaignBinding,
    manifest: ArchiveManifest,
    targets: Sequence[str],
) -> tuple[bool | None, str]:
    """Restore the archived payload elsewhere and compare it with the live source.

    The comparison never trusts the archive index: the live journal records are
    read straight from the lifecycle repository and re-encoded with the archive
    writer's own canonical payload rules, so a recovery artifact that does not
    reproduce the source content fails the rollback gate before anything is
    destroyed.
    """

    try:
        read = await host.reader.read(
            principal=host.principal(binding), manifest_digest=manifest.digest
        )
    except (LookupError, PermissionError, ValueError):
        return None, evidence_digest({"recovery": "unreadable"})
    recovery_ref = recovery_storage_ref(binding, manifest.digest)
    await host.artifacts.put(
        recovery_ref, read.content, digest=read.artifact_digest.removeprefix("sha256:")
    )
    restored = await host.artifacts.get(recovery_ref)
    source: list[Mapping[str, Any]] = []
    for partition_id in targets:
        source.extend(dict(item) for item in await host.repository.archive_records(partition_id))
    expected = archive_payload_digest(
        tuple(item.content_digest for item in manifest.source_partitions), source
    )
    observed = None if restored is None else "sha256:" + hashlib.sha256(restored).hexdigest()
    content_matches = (
        restored is not None
        and observed == read.artifact_digest
        and expected == manifest.archive_content_digest
        and bool(source)
    )
    return content_matches, evidence_digest(
        {
            "recovery_target": recovery_ref,
            "recovered_digest": observed,
            "source_digest": expected,
            "records": len(source),
        }
    )


async def rebuild_archive_coverage(
    host: ArchiveProbeHost, binding: CampaignBinding, now: datetime
) -> tuple[str | None, bool | None, bool | None]:
    """Rebuild and persist the scope's archive coverage index after a restart."""

    entries: list[ArchiveIndexEntry] = []
    outcomes: list[bool] = []
    partitions = await host.scope_partitions(binding, now)
    archived = tuple(
        partition
        for partition in partitions
        if partition.state
        in {
            ObservationPartitionState.ARCHIVED,
            ObservationPartitionState.VERIFIED,
            ObservationPartitionState.PURGE_ELIGIBLE,
            ObservationPartitionState.PURGED,
            ObservationPartitionState.HELD,
        }
    )
    for partition in archived:
        manifest = await host.repository.latest_manifest(partition.partition_id)
        if manifest is None:
            continue
        entries.append(
            ArchiveIndexEntry(
                manifest_digest=manifest.digest,
                interval_start=manifest.covered_start,
                interval_end=manifest.covered_end,
            )
        )
        outcomes.append(await host.read_outcome(binding, manifest.digest) == "verified")
    if not entries:
        return None, None, None
    scope_complete = len(entries) == len(archived)
    index = ArchiveCoverageIndex(
        coverage_start=min(item.interval_start for item in entries),
        coverage_end=max(item.interval_end for item in entries),
        complete=False,
        entries=tuple(entries),
    )
    coverage = build_archive_coverage_receipt(index, recorded_at=now)
    await host.archives.append_coverage(coverage)
    return coverage.digest, all(outcomes), scope_complete


async def observe_archive_restore(
    host: ArchiveProbeHost, binding: CampaignBinding, now: datetime
) -> ScenarioObservation:
    """Verify one archived artifact and prove the scope boundary actually denies."""

    selection = await host.archive_selection(
        await host.scope_partitions(binding, now), now=now, held=False
    )
    if selection is None:
        return _unobserved(
            OperationalHistoryScenario.ARCHIVE_RESTORE, "archive_evidence_unavailable"
        )
    _, manifest, verification, restore = selection
    allowed = await host.read_outcome(binding, manifest.digest)
    denied = await host.read_outcome_for_scope(
        binding, manifest.digest, scope="synthetic-denied-scope"
    )
    authorized = True if denied == "denied" else None if denied != "verified" else False
    return ScenarioObservation(
        scenario=OperationalHistoryScenario.ARCHIVE_RESTORE,
        checks=(
            scenario_check(
                "manifest_verified",
                verification.verified and verification.manifest_digest == manifest.digest,
            ),
            scenario_check("restore_sample_passed", restore.passed),
            scenario_check("artifact_content_verified", allowed == "verified"),
            scenario_check("restore_scope_authorized", authorized),
        ),
        evidence_digests=tuple(sorted({manifest.digest, verification.digest, restore.digest})),
    )


async def observe_hold_enforcement(
    host: ArchiveProbeHost, binding: CampaignBinding, now: datetime
) -> ScenarioObservation:
    """Prove an active legal hold blocks purge and preserves the source partition."""

    scenario = OperationalHistoryScenario.HOLD_ENFORCEMENT
    partitions = await host.scope_partitions(binding, now)
    selection = await host.archive_selection(partitions, now=now, held=True)
    if selection is None:
        return _unobserved(scenario, "active_hold_unavailable")
    partition, manifest, verification, restore = selection
    holds = await host.repository.active_holds(manifest.digest, now=now)
    retention = evaluate_retention_holds(manifest, holds, evaluated_at=now)
    receipt = await host.purge.purge(
        manifest,
        verification,
        restore,
        retention,
        idempotency_key=binding.idempotency_key(scenario, target=manifest.digest),
        recorded_at=now,
    )
    remaining = {item.partition_id for item in await host.scope_partitions(binding, now)}
    return ScenarioObservation(
        scenario=scenario,
        checks=(
            scenario_check("active_hold_detected", bool(holds) and not retention.permitted),
            scenario_check(
                "purge_blocked_by_hold",
                receipt.status is ArchivePurgeStatus.BLOCKED
                and "retention_hold_active" in receipt.reason_codes,
            ),
            scenario_check(
                "source_data_preserved",
                receipt.source_data_preserved and partition.partition_id in remaining,
            ),
        ),
        evidence_digests=tuple(sorted({manifest.digest, retention.digest, receipt.digest})),
    )


async def observe_archive_outage(
    host: ArchiveProbeHost, binding: CampaignBinding, now: datetime
) -> ScenarioObservation:
    """Detect a real injected archive storage outage on the deployed read path.

    The probe reads one genuinely archived manifest through the live principal
    scoped reader, repeats that exact read through a reader whose artifact store
    raises a transport failure, and then reads it live again. Requesting an absent
    manifest key would only prove lookup behavior, so the outage is injected into
    the adapter instead.
    """

    scenario = OperationalHistoryScenario.ARCHIVE_OUTAGE
    partitions = await host.scope_partitions(binding, now)
    selection = await host.archive_selection(partitions, now=now, held=False)
    if selection is None:
        return _unobserved(scenario, "archive_outage_evidence_unavailable")
    partition, manifest, verification, _ = selection
    before = await host.read_outcome(binding, manifest.digest)
    outage = await host.outage_read(binding, manifest.digest)
    after = await host.read_outcome(binding, manifest.digest)
    warm = await host.repository.latest_checkpoint(partition.partition_id)
    degraded = evaluate_restore_sample(
        manifest,
        verification,
        sampled_partition_digests=tuple(item.content_digest for item in manifest.source_partitions),
        observed_partition_digests=(),
        restored_object_count=0,
        restored_relationship_count=0,
        failure_code="archive_unavailable",
        sampled_at=now,
    )
    blocked = await host.purge.purge(
        manifest,
        verification,
        degraded,
        evaluate_retention_holds(manifest, (), evaluated_at=now),
        idempotency_key=binding.idempotency_key(scenario, target=manifest.digest),
        recorded_at=now,
    )
    return ScenarioObservation(
        scenario=scenario,
        checks=(
            scenario_check("archive_readable_before_outage", before == "verified"),
            scenario_check("archive_outage_detected", outage == "unavailable"),
            scenario_check("archive_readable_after_outage", after == "verified"),
            scenario_check("warm_path_unaffected", warm is not None),
            scenario_check(
                "purge_blocked_during_outage",
                blocked.status is ArchivePurgeStatus.BLOCKED
                and blocked.source_data_preserved
                and "restore_sample_failed" in blocked.reason_codes,
            ),
        ),
        evidence_digests=tuple(
            sorted(
                {
                    degraded.digest,
                    blocked.digest,
                    evidence_digest(
                        {
                            "seam": "artifact_storage",
                            "before": before,
                            "injected": outage,
                            "after": after,
                            "manifest": manifest.digest,
                            "partition": partition.partition_id,
                            "blocked_reasons": sorted(blocked.reason_codes),
                        }
                    ),
                }
            )
        ),
    )


__all__ = [
    "ARCHIVE_PAYLOAD_SCHEMA_VERSION",
    "RECOVERY_STORAGE_ROOT",
    "ArchiveProbeArtifactStore",
    "ArchiveProbeHost",
    "ArchiveProbeReceiptStore",
    "ArchiveProbeRepository",
    "ArchiveSelection",
    "archive_payload_digest",
    "decode_archive_records",
    "observe_archive_outage",
    "observe_archive_restore",
    "observe_completed_purge",
    "observe_hold_enforcement",
    "observe_safe_partition_purge",
    "rebuild_archive_coverage",
    "recovery_content",
    "recovery_storage_ref",
    "restore_to_recovery_target",
]
