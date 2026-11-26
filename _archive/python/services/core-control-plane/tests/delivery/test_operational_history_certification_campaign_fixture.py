"""Focused tests for the journal-backed OI-16 synthetic fixture and probes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from fdai.core.ontology_platform.operational_history_certification import (
    OperationalHistoryScenario,
    OperationalHistoryScenarioStatus,
)
from fdai.core.ontology_platform.operational_history_lifecycle import (
    ObservationPartitionKind,
    ObservationPartitionState,
)
from fdai.core.ontology_platform.operational_history_pressure import StoragePressurePolicy
from fdai.delivery.operational_archive_purge import ArchivePurgeStatus
from fdai.delivery.operational_history_certification_campaign import (
    CAMPAIGN_PURPOSE,
    CampaignBinding,
    SyntheticScope,
    evaluate_scenario,
)
from fdai.delivery.operational_history_certification_campaign_archive_probes import (
    RECOVERY_STORAGE_ROOT,
    recovery_storage_ref,
)
from fdai.delivery.operational_history_certification_campaign_fixture import (
    SyntheticCampaignFixture,
    purge_idempotency_key,
    purge_target_observation,
    synthetic_hold_id,
    unquarantined_completeness,
)
from fdai.delivery.operational_history_certification_campaign_observations import (
    PRIOR_SCHEMA_VERSION,
    SyntheticSlot,
    cross_release_stable_body,
    downgrade_to_prior_schema,
    full_observation,
    incarnation_lifecycle,
    late_observation,
    slot_idempotency_key,
    synthetic_resource_ref,
)
from fdai.delivery.operational_history_certification_campaign_probes import (
    DeployedOperationalHistoryCampaignProbes,
)
from fdai.shared.providers.inventory_observation import (
    INVENTORY_OBSERVATION_SCHEMA_VERSION,
    replay_inventory_observation_schema,
)

from tests.delivery.oi16_campaign_deployment_double import FakeDeployment, journal_record

SCOPE_REF = "synthetic/oi16-certification/campaign-a"
SOURCE = "0123456789abcdef0123456789abcdef01234567"
RELEASE = "sha256:" + "c" * 64
NOW = datetime(2026, 5, 1, 12, tzinfo=UTC)
POLICY = StoragePressurePolicy(
    warning_bytes=10 * 1024**3,
    critical_bytes=20 * 1024**3,
    hard_bytes=30 * 1024**3,
    max_purge_backlog=256,
    max_projection_lag=1000,
)


def _binding(scope_ref: str = SCOPE_REF, *, campaign_id: str | None = None) -> CampaignBinding:
    return CampaignBinding(
        scope=SyntheticScope(environment="dev", scope_ref=scope_ref),
        source_revision=SOURCE,
        ontology_release_digest=RELEASE,
        window_start=NOW - timedelta(hours=1),
        window_end=NOW,
        campaign_id_override=campaign_id,
    )


def _fixture(deployment: FakeDeployment, binding: CampaignBinding) -> SyntheticCampaignFixture:
    store = cast(Any, deployment)
    return SyntheticCampaignFixture(
        binding=binding,
        journal=store,
        repository=store,
        history=store,
        archives=store,
        artifacts=store,
    )


def _probes(
    deployment: FakeDeployment, *, prior_baseline: Any = None
) -> DeployedOperationalHistoryCampaignProbes:
    store = cast(Any, deployment)
    return DeployedOperationalHistoryCampaignProbes(
        repository=store,
        history=store,
        archives=store,
        artifacts=store,
        policy=POLICY,
        journal=store,
        prior_baseline=prior_baseline,
    )


async def _prepared(
    *, purge_permitted: bool = True, projected: bool = True
) -> tuple[FakeDeployment, CampaignBinding]:
    deployment = FakeDeployment(purge_permitted=purge_permitted)
    binding = _binding()
    if projected:
        deployment.projection.watermark = 1_000_000
    await _fixture(deployment, binding).prepare(now=NOW)
    return deployment, binding


async def test_fixture_writes_only_through_the_journal_and_is_non_vacuous() -> None:
    deployment, binding = await _prepared()
    assert deployment.observations, "fixture MUST persist normalized observations"
    partitions = await deployment.list_partitions(limit=64, now=NOW, scope_ref=SCOPE_REF)
    assert len(partitions) >= 6
    assert all(item.scope_ref == SCOPE_REF for item in partitions)
    warm = await deployment.resolve_evidence_partitions(
        (full_observation(binding, SyntheticSlot.WARM).observation_id,)
    )
    records = await deployment.archive_records(warm[0])
    assert records, "warm partition MUST hold at least one persisted journal record"
    checkpoint = await deployment.latest_checkpoint(warm[0])
    assert checkpoint is not None
    assert checkpoint.object_count > 0 and checkpoint.property_count > 0


async def test_fixture_repeat_inserts_no_observation_and_stays_stable() -> None:
    deployment, binding = await _prepared()
    partitions = dict(deployment.partitions)
    second = await _fixture(deployment, binding).prepare(now=NOW)
    assert second.observations_inserted == 0
    assert second.inserted == 0
    assert deployment.partitions == partitions
    assert second.observation_count >= 5


async def test_fixture_reports_invalid_checkpoints_honestly() -> None:
    """Warm replay may certify an invalid checkpoint, but MUST NOT promote it."""

    deployment, binding = await _prepared(projected=False)
    assert not [item for item in deployment.checkpoints if item.valid]
    observation = await _probes(deployment).observe(
        OperationalHistoryScenario.WARM_REPLAY, binding, now=NOW
    )
    assert observation is not None
    result = evaluate_scenario(OperationalHistoryScenario.WARM_REPLAY, observation)
    assert result.status is OperationalHistoryScenarioStatus.PASSED, result.reason_codes
    codes = {item.code: item.satisfied for item in observation.checks}
    assert codes["checkpoint_journal_backed"] is True
    assert codes["replay_state_preserved"] is True
    assert codes["checkpoint_completeness_not_overclaimed"] is True
    stored = [item for item in deployment.checkpoints if not item.valid]
    assert stored, "the unprojected fixture MUST keep its checkpoints invalid"
    assert all(unquarantined_completeness(item) is False for item in stored)
    assert deployment.manifests
    assert all(item.coverage_complete for item in deployment.manifests.values()), (
        "archive coverage describes the archived record set, not the ontology projection"
    )


async def test_warm_replay_passes_only_on_real_journal_backed_history() -> None:
    deployment, binding = await _prepared()
    observation = await _probes(deployment).observe(
        OperationalHistoryScenario.WARM_REPLAY, binding, now=NOW
    )
    assert observation is not None
    result = evaluate_scenario(OperationalHistoryScenario.WARM_REPLAY, observation)
    assert result.status is OperationalHistoryScenarioStatus.PASSED, result.reason_codes


async def test_duplicate_delivery_proves_zero_insert_and_zero_state_delta() -> None:
    deployment, binding = await _prepared()
    before = len(deployment.observations)
    observation = await _probes(deployment).observe(
        OperationalHistoryScenario.DUPLICATE_DELIVERY, binding, now=NOW
    )
    assert observation is not None
    result = evaluate_scenario(OperationalHistoryScenario.DUPLICATE_DELIVERY, observation)
    assert result.status is OperationalHistoryScenarioStatus.PASSED, result.reason_codes
    assert len(deployment.observations) == before
    codes = {item.code: item.satisfied for item in observation.checks}
    assert codes["journal_watermark_unchanged"] is True


async def test_duplicate_delivery_fails_when_the_journal_reinserts() -> None:
    deployment, binding = await _prepared()
    deployment.keys.clear()
    observation = await _probes(deployment).observe(
        OperationalHistoryScenario.DUPLICATE_DELIVERY, binding, now=NOW
    )
    assert observation is not None
    result = evaluate_scenario(OperationalHistoryScenario.DUPLICATE_DELIVERY, observation)
    assert result.status is OperationalHistoryScenarioStatus.FAILED
    assert "duplicate_suppressed" in result.reason_codes


async def test_late_observation_binds_a_real_correction_and_closes_it_in_scope() -> None:
    deployment, binding = await _prepared()
    late = late_observation(binding)
    bound = await deployment.resolve_evidence_partitions((late.observation_id,))
    assert len(bound) == 1
    correction = deployment.partitions[bound[0]]
    assert correction.kind is ObservationPartitionKind.CORRECTION
    assert correction.correction_of in deployment.partitions
    observation = await _probes(deployment).observe(
        OperationalHistoryScenario.LATE_OBSERVATION, binding, now=NOW
    )
    assert observation is not None
    result = evaluate_scenario(OperationalHistoryScenario.LATE_OBSERVATION, observation)
    assert result.status is OperationalHistoryScenarioStatus.PASSED, result.reason_codes
    assert deployment.corrections[correction.partition_id].complete
    assert (
        deployment.partitions[correction.partition_id].state
        is ObservationPartitionState.CHECKPOINTED
    )


async def test_late_observation_is_unavailable_without_a_persisted_projection() -> None:
    deployment, binding = await _prepared()
    deployment.projection.graph = ""
    observation = await _probes(deployment).observe(
        OperationalHistoryScenario.LATE_OBSERVATION, binding, now=NOW
    )
    assert observation is not None
    assert observation.unavailable_reason == "correction_closure_unavailable"


async def test_delete_recreate_verifies_persisted_incarnation_boundaries() -> None:
    deployment, binding = await _prepared()
    opened, tombstoned, reopened = incarnation_lifecycle(binding)
    incarnations = await deployment.list_incarnations(
        synthetic_resource_ref(binding, SyntheticSlot.INCARNATION)
    )
    assert len(incarnations) == 2
    assert incarnations[0].closed_at == tombstoned.effective_at
    assert incarnations[0].opening_observation_id == opened.observation_id
    assert incarnations[1].closed_at is None
    assert incarnations[1].opening_observation_id == reopened.observation_id
    observation = await _probes(deployment).observe(
        OperationalHistoryScenario.DELETE_RECREATE, binding, now=NOW
    )
    assert observation is not None
    result = evaluate_scenario(OperationalHistoryScenario.DELETE_RECREATE, observation)
    assert result.status is OperationalHistoryScenarioStatus.PASSED, result.reason_codes


async def test_schema_replay_uses_the_archived_prior_record() -> None:
    deployment, binding = await _prepared()
    observation = await _probes(deployment).observe(
        OperationalHistoryScenario.SCHEMA_REPLAY, binding, now=NOW
    )
    assert observation is not None
    result = evaluate_scenario(OperationalHistoryScenario.SCHEMA_REPLAY, observation)
    assert result.status is OperationalHistoryScenarioStatus.PASSED, result.reason_codes


async def test_schema_replay_is_unavailable_without_an_archived_prior_record() -> None:
    deployment, binding = await _prepared()
    for digest, manifest in list(deployment.manifests.items()):
        if PRIOR_SCHEMA_VERSION in manifest.source_schema_versions:
            deployment.manifests.pop(digest)
            deployment.artifacts_by_manifest.pop(digest, None)
    observation = await _probes(deployment).observe(
        OperationalHistoryScenario.SCHEMA_REPLAY, binding, now=NOW
    )
    assert observation is not None
    assert observation.unavailable_reason == "schema_record_unavailable"


def test_prior_schema_downgrade_is_replayable_and_content_stable() -> None:
    record = journal_record(full_observation(_binding(), SyntheticSlot.PRIOR))
    downgraded = downgrade_to_prior_schema(record)
    assert downgraded["schema_version"] == PRIOR_SCHEMA_VERSION
    assert "property_mask" not in downgraded
    with pytest.raises(ValueError, match="current-release record"):
        downgrade_to_prior_schema(downgraded)
    replay = replay_inventory_observation_schema(downgraded)
    assert replay.target_schema_version == INVENTORY_OBSERVATION_SCHEMA_VERSION
    assert cross_release_stable_body(replay.transformed_record) == cross_release_stable_body(record)


async def test_bounded_storage_measures_real_growth_across_an_idempotent_replay() -> None:
    deployment, binding = await _prepared()
    probes = _probes(deployment)
    await probes.sample_storage(binding, now=NOW)
    await _fixture(deployment, binding).prepare(now=NOW)
    await probes.sample_storage(binding, now=NOW + timedelta(seconds=30))
    observation = await probes.observe(OperationalHistoryScenario.BOUNDED_STORAGE, binding, now=NOW)
    assert observation is not None
    result = evaluate_scenario(OperationalHistoryScenario.BOUNDED_STORAGE, observation)
    assert result.status is OperationalHistoryScenarioStatus.PASSED, result.reason_codes
    codes = {item.code: item.satisfied for item in observation.checks}
    assert codes["recorded_change_count_present"] is True
    assert codes["replay_change_count_unchanged"] is True


async def test_bounded_storage_fails_when_a_replay_adds_records() -> None:
    deployment, binding = await _prepared()
    probes = _probes(deployment)
    await probes.sample_storage(binding, now=NOW)
    await deployment.append_change_batch((full_observation(binding, SyntheticSlot.WARM, index=42),))
    await probes.sample_storage(binding, now=NOW + timedelta(seconds=30))
    observation = await probes.observe(OperationalHistoryScenario.BOUNDED_STORAGE, binding, now=NOW)
    assert observation is not None
    result = evaluate_scenario(OperationalHistoryScenario.BOUNDED_STORAGE, observation)
    assert result.status is OperationalHistoryScenarioStatus.FAILED
    assert "replay_change_count_unchanged" in result.reason_codes


async def test_exact_scope_query_survives_many_foreign_partitions() -> None:
    deployment, binding = await _prepared()
    foreign = _binding("synthetic/oi16-certification/other")
    for index in range(70):
        await deployment.append_change_batch(
            (full_observation(foreign, SyntheticSlot.WARM, index=index),)
        )
    owned = await deployment.list_partitions(limit=64, now=NOW, scope_ref=SCOPE_REF)
    assert owned and all(item.scope_ref == SCOPE_REF for item in owned)
    observation = await _probes(deployment).observe(
        OperationalHistoryScenario.WARM_REPLAY, binding, now=NOW
    )
    assert observation is not None
    assert observation.unavailable_reason is None


async def test_safe_purge_restores_to_a_separate_recovery_target_before_deleting() -> None:
    deployment, binding = await _prepared()
    observation = await _probes(deployment).observe(
        OperationalHistoryScenario.SAFE_PARTITION_PURGE, binding, now=NOW
    )
    assert observation is not None
    result = evaluate_scenario(OperationalHistoryScenario.SAFE_PARTITION_PURGE, observation)
    assert result.status is OperationalHistoryScenarioStatus.PASSED, result.reason_codes
    recovery = [key for key in deployment.blobs if key.startswith(RECOVERY_STORAGE_ROOT)]
    assert len(recovery) == 1
    assert deployment.purged, "an authorized purge MUST reach the deployed purge gate"
    statuses = [item.status for item in deployment.purge_receipts]
    assert ArchivePurgeStatus.SUCCEEDED in statuses
    codes = {item.code: item.satisfied for item in observation.checks}
    assert codes["two_phase_audit_recorded"] is True
    assert codes["rollback_tested"] is True


async def test_safe_purge_does_not_claim_global_projection_for_synthetic_source() -> None:
    deployment, binding = await _prepared(projected=False)
    observation = await _probes(deployment).observe(
        OperationalHistoryScenario.SAFE_PARTITION_PURGE, binding, now=NOW
    )

    assert observation is not None
    result = evaluate_scenario(OperationalHistoryScenario.SAFE_PARTITION_PURGE, observation)
    assert result.status is OperationalHistoryScenarioStatus.PASSED, result.reason_codes
    assert not [item for item in deployment.checkpoints if item.valid]
    assert deployment.purged


async def test_safe_purge_refuses_when_the_deployment_forbids_deletion() -> None:
    deployment, binding = await _prepared(purge_permitted=False)
    observation = await _probes(deployment).observe(
        OperationalHistoryScenario.SAFE_PARTITION_PURGE, binding, now=NOW
    )
    assert observation is not None
    result = evaluate_scenario(OperationalHistoryScenario.SAFE_PARTITION_PURGE, observation)
    assert result.status is OperationalHistoryScenarioStatus.FAILED
    assert "dry_run_succeeded" in result.reason_codes
    assert not deployment.purged


async def test_retry_after_purge_reuses_the_audit_and_never_recreates_the_source() -> None:
    deployment, binding = await _prepared()
    await _probes(deployment).observe(
        OperationalHistoryScenario.SAFE_PARTITION_PURGE, binding, now=NOW
    )
    purged = set(deployment.purged)
    target = purge_target_observation(binding)
    prepared = await _fixture(deployment, binding).prepare(now=NOW)
    assert prepared.purge_target_retired is True
    assert target.observation_id not in deployment.observations
    retry = await _probes(deployment).observe(
        OperationalHistoryScenario.SAFE_PARTITION_PURGE, binding, now=NOW
    )
    assert retry is not None
    result = evaluate_scenario(OperationalHistoryScenario.SAFE_PARTITION_PURGE, retry)
    assert result.status is OperationalHistoryScenarioStatus.PASSED, result.reason_codes
    codes = {item.code: item.satisfied for item in retry.checks}
    assert codes["source_not_recreated"] is True
    assert set(deployment.purged) == purged
    durable = await deployment.latest(purge_idempotency_key(binding))
    assert durable is not None and durable.status is ArchivePurgeStatus.SUCCEEDED


async def test_hold_enforcement_blocks_purge_and_preserves_source() -> None:
    deployment, binding = await _prepared()
    observation = await _probes(deployment).observe(
        OperationalHistoryScenario.HOLD_ENFORCEMENT, binding, now=NOW
    )
    assert observation is not None
    result = evaluate_scenario(OperationalHistoryScenario.HOLD_ENFORCEMENT, observation)
    assert result.status is OperationalHistoryScenarioStatus.PASSED, result.reason_codes


async def test_injected_failures_carry_content_bound_receipts() -> None:
    deployment, binding = await _prepared()
    probes = _probes(deployment)
    provider = await probes.observe(OperationalHistoryScenario.PROVIDER_FAILURE, binding, now=NOW)
    outage = await probes.observe(OperationalHistoryScenario.ARCHIVE_OUTAGE, binding, now=NOW)
    assert provider is not None and outage is not None
    assert len(provider.evidence_digests) >= 2
    assert len(outage.evidence_digests) >= 3
    provider_codes = {item.code: item.satisfied for item in provider.checks}
    assert provider_codes["provider_failure_detected"] is True
    outage_codes = {item.code: item.satisfied for item in outage.checks}
    assert outage_codes["archive_outage_detected"] is True
    assert outage_codes["purge_blocked_during_outage"] is True


async def test_database_recovery_rebuilds_archive_coverage() -> None:
    deployment, binding = await _prepared()
    baseline = await _probes(deployment).baseline(binding, now=NOW)
    assert baseline is not None
    observation = await _probes(deployment, prior_baseline=baseline).observe(
        OperationalHistoryScenario.DATABASE_RECOVERY, binding, now=NOW
    )
    assert observation is not None
    result = evaluate_scenario(OperationalHistoryScenario.DATABASE_RECOVERY, observation)
    assert result.status is OperationalHistoryScenarioStatus.PASSED, result.reason_codes
    assert deployment.coverages, "recovery MUST persist a rebuilt archive coverage receipt"
    assert deployment.coverages[-1].index.complete is False
    codes = {item.code: item.satisfied for item in observation.checks}
    assert codes["archive_artifact_content_restored"] is True
    assert codes["database_records_restored"] is True
    assert deployment.recovery_records


async def test_database_recovery_refuses_incomplete_scope_archive_coverage() -> None:
    deployment, binding = await _prepared()
    baseline = await _probes(deployment).baseline(binding, now=NOW)
    assert baseline is not None
    deployment.manifests.pop(next(iter(deployment.manifests)))

    observation = await _probes(deployment, prior_baseline=baseline).observe(
        OperationalHistoryScenario.DATABASE_RECOVERY, binding, now=NOW
    )

    assert observation is not None
    result = evaluate_scenario(OperationalHistoryScenario.DATABASE_RECOVERY, observation)
    assert result.status is OperationalHistoryScenarioStatus.FAILED
    assert "archive_coverage_rebuilt" in result.reason_codes
    assert deployment.coverages[-1].index.complete is False


async def test_archive_artifacts_stay_scope_and_purpose_bound() -> None:
    deployment, _ = await _prepared()
    assert deployment.artifacts_by_manifest
    for artifact in deployment.artifacts_by_manifest.values():
        assert artifact.scope_refs == (SCOPE_REF,)
        assert artifact.allowed_purposes == (CAMPAIGN_PURPOSE,)


def test_purge_identity_is_campaign_scoped_and_hold_identity_is_scope_scoped() -> None:
    first = _binding(campaign_id="certify-history-" + "a" * 48)
    second = _binding(campaign_id="certify-history-" + "b" * 48)
    assert purge_idempotency_key(first) != purge_idempotency_key(second)
    assert (
        purge_target_observation(first).observation_id
        != purge_target_observation(second).observation_id
    )
    assert slot_idempotency_key(first, SyntheticSlot.WARM) == slot_idempotency_key(
        second, SyntheticSlot.WARM
    )
    manifest = "sha256:" + "d" * 64
    assert synthetic_hold_id(first, manifest_digest=manifest) == synthetic_hold_id(
        second, manifest_digest=manifest
    )
    other = _binding("synthetic/oi16-certification/other")
    assert synthetic_hold_id(other, manifest_digest=manifest) != synthetic_hold_id(
        first, manifest_digest=manifest
    )


def test_recovery_target_is_separate_from_the_archive_object() -> None:
    manifest = "sha256:" + "e" * 64
    reference = recovery_storage_ref(_binding(), manifest)
    assert reference.startswith(RECOVERY_STORAGE_ROOT)
    assert reference != f"operational-history/{manifest[7:]}.json"


async def test_fixture_refuses_a_non_dev_or_non_synthetic_scope() -> None:
    deployment = FakeDeployment()
    binding = _binding()
    object.__setattr__(binding.scope, "environment", "prod")
    with pytest.raises(PermissionError, match="dev runtime environment"):
        _fixture(deployment, binding)
    other = _binding()
    object.__setattr__(other.scope, "scope_ref", "production/live")
    with pytest.raises(PermissionError, match="non-synthetic scope"):
        _fixture(deployment, other)
