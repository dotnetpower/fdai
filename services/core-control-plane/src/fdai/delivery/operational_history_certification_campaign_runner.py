"""Compose the deployed adapters that one OI-16 campaign phase runs against.

This module is the campaign composition root. It owns nothing the pure core or the
probe adapter already owns: it resolves the binding, opens the existing PostgreSQL and
principal-scoped Azure Blob adapters, applies the bounded dev-only synthetic fixture
twice so bounded storage is measured rather than inferred, runs one phase, and merges
it with the persisted before-restart evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

import httpx

from fdai.delivery.azure.operational_history_archive import (
    AzureBlobOperationalHistoryArtifactStore,
    AzureBlobOperationalHistoryConfig,
)
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.delivery.operational_history_certification_campaign import (
    CampaignBinding,
    CampaignPhase,
    OperationalHistoryCertificationCampaign,
    RecoveryBaseline,
    assert_sanitized,
    baseline_from_manifest,
    binding_from_env,
    merge_campaign_phases,
    policy_from_env,
    read_manifest,
)
from fdai.delivery.operational_history_certification_campaign_cli import CampaignRunOptions
from fdai.delivery.operational_history_certification_campaign_fixture import (
    SyntheticCampaignFixture,
)
from fdai.delivery.operational_history_certification_campaign_phase_store import (
    CampaignPhaseStore,
)
from fdai.delivery.operational_history_certification_campaign_probes import (
    DeployedOperationalHistoryCampaignProbes,
)
from fdai.delivery.persistence.postgres_inventory_observation import (
    PostgresInventoryObservationJournal,
)
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStoreConfig,
)
from fdai.delivery.persistence.postgres_operational_archive import (
    PostgresOperationalArchiveStore,
    PostgresOperationalArchiveStoreConfig,
)
from fdai.delivery.persistence.postgres_operational_history import (
    PostgresOperationalHistoryConfig,
    PostgresOperationalHistoryStore,
)
from fdai.delivery.persistence.postgres_operational_history_lifecycle_runner import (
    PostgresOperationalHistoryLifecycleRepository,
)


async def run_phase(options: CampaignRunOptions, environ: Mapping[str, str]) -> dict[str, object]:
    """Run one campaign phase against the deployed synthetic scope."""

    now = datetime.now(UTC)
    binding = binding_from_env(
        environ,
        source_revision=options.source_revision,
        ontology_release_digest=options.ontology_release_digest,
        window_seconds=options.window_seconds,
        now=now,
        campaign_id=options.campaign_id,
    )
    dsn = environ.get("FDAI_DATABASE_URL", "").strip()
    container_url = environ.get("FDAI_OPERATIONAL_HISTORY_CONTAINER_URL", "").strip()
    if not dsn or not container_url:
        raise ValueError("campaign requires a database URL and an archive container URL")
    if options.phase is not CampaignPhase.SINGLE_PASS and options.campaign_id is None:
        raise ValueError("restart-split campaign phases MUST pin an explicit campaign id")
    history = PostgresOperationalHistoryStore(config=PostgresOperationalHistoryConfig(dsn=dsn))
    archives = PostgresOperationalArchiveStore(
        config=PostgresOperationalArchiveStoreConfig(dsn=dsn)
    )
    async with httpx.AsyncClient() as http_client:
        artifacts = AzureBlobOperationalHistoryArtifactStore(
            config=AzureBlobOperationalHistoryConfig(container_url=container_url),
            identity=ManagedIdentityWorkloadIdentity.from_env(
                http_client=http_client, client_id_env="FDAI_MI_CLIENT_ID"
            ),
            http_client=http_client,
        )
        phases = CampaignPhaseStore(artifacts=artifacts, metadata=history, scope=binding.scope)
        prior = await _prior_phase(phases, options, binding.campaign_id)
        repository = PostgresOperationalHistoryLifecycleRepository(dsn=dsn)
        journal = PostgresInventoryObservationJournal(
            config=PostgresInventorySnapshotStoreConfig(dsn=dsn),
            allow_oi16_synthetic=True,
        )
        probes = DeployedOperationalHistoryCampaignProbes(
            repository=repository,
            history=history,
            archives=archives,
            artifacts=artifacts,
            policy=policy_from_env(environ),
            journal=journal,
            prior_baseline=baseline_from_manifest(prior),
            restart_receipt_digest=options.restart_receipt_digest,
        )
        fixture = None
        if options.phase is not CampaignPhase.POST_RESTART and options.prepare_fixture:
            await _fixture(binding, journal, repository, history, archives, artifacts).prepare(
                now=now
            )
            await probes.sample_storage(binding, now=now)
            fixture = await _fixture(
                binding, journal, repository, history, archives, artifacts
            ).prepare(now=now)
            await probes.sample_storage(binding, now=now)
        else:
            await probes.sample_storage(binding, now=now)
            await probes.sample_storage(binding, now=now)
        campaign = OperationalHistoryCertificationCampaign(
            probes=probes, binding=binding, phase=options.phase
        )
        manifest = await campaign.run(now=now)
        if fixture is not None:
            manifest["synthetic_fixture"] = fixture.record()
            assert_sanitized(manifest)
        if options.phase is CampaignPhase.PRE_RESTART:
            baseline = await probes.baseline(binding, now=now)
            if baseline is not None:
                manifest["recovery_baseline"] = _baseline_record(baseline)
                assert_sanitized(manifest)
        merged = manifest if prior is None else merge_campaign_phases(prior, manifest)
        if options.phase is CampaignPhase.PRE_RESTART:
            await phases.put(
                merged, campaign_id=binding.campaign_id, phase=CampaignPhase.PRE_RESTART, now=now
            )
    return merged


def _fixture(
    binding: CampaignBinding,
    journal: PostgresInventoryObservationJournal,
    repository: PostgresOperationalHistoryLifecycleRepository,
    history: PostgresOperationalHistoryStore,
    archives: PostgresOperationalArchiveStore,
    artifacts: AzureBlobOperationalHistoryArtifactStore,
) -> SyntheticCampaignFixture:
    """Build one fresh fixture applier so each application reports its own counts."""

    return SyntheticCampaignFixture(
        binding=binding,
        journal=journal,
        repository=repository,
        history=history,
        archives=archives,
        artifacts=artifacts,
    )


async def _prior_phase(
    phases: CampaignPhaseStore, options: CampaignRunOptions, campaign_id: str
) -> dict[str, object] | None:
    """Load the persisted before-restart phase evidence for an after-restart run."""

    if options.prior_phase is not None:
        return read_manifest(options.prior_phase)
    if options.phase is not CampaignPhase.POST_RESTART:
        return None
    prior = await phases.get(campaign_id=campaign_id, phase=CampaignPhase.PRE_RESTART)
    if prior is None:
        raise LookupError("after-restart phase found no persisted before-restart evidence")
    return prior


def _baseline_record(baseline: RecoveryBaseline) -> dict[str, object]:
    return {
        "journal_watermark": baseline.journal_watermark,
        "projection_watermark": baseline.projection_watermark,
        "archive_index_digest": baseline.archive_index_digest,
        "partition_count": baseline.partition_count,
    }


__all__ = ["run_phase"]
