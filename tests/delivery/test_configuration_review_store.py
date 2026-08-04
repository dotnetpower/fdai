from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from fdai.core.detection.configuration_drift import (
    ConfigurationDriftReport,
    ConfigurationDriftReportConflictError,
    ConfigurationReviewCampaign,
    ConfigurationReviewCampaignService,
    DriftVerdict,
    KnowledgeGroundingStatus,
    persist_configuration_drift_report,
)
from fdai.delivery.configuration_drift_report_store import (
    StateStoreConfigurationDriftReportStore,
)
from fdai.delivery.configuration_review_store import (
    StateStoreConfigurationReviewCampaignStore,
    configuration_review_campaign_id,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 8, 4, tzinfo=UTC)


def _report(digest: str) -> ConfigurationDriftReport:
    return ConfigurationDriftReport(
        baseline_version="v1",
        baseline_sha256=digest,
        scope="example-scope",
        observed_at=_NOW,
        verdict=DriftVerdict.PASSED,
        findings=(),
        knowledge_status=KnowledgeGroundingStatus.CITED,
        knowledge_citations=("knowledge:baseline#0",),
    )


async def test_state_store_campaign_survives_round_trip_and_advances_revision() -> None:
    state_store = InMemoryStateStore()
    store = StateStoreConfigurationReviewCampaignStore(state_store)
    reports = StateStoreConfigurationDriftReportStore(state_store, clock=lambda: _NOW)
    digest = "a" * 64
    campaign_id = configuration_review_campaign_id(scope="example-scope", version="v1")
    service = ConfigurationReviewCampaignService(store, reports)
    campaign = ConfigurationReviewCampaign(
        campaign_id=campaign_id,
        baseline_version="v1",
        baseline_sha256=digest,
        scope="example-scope",
    )

    await service.create(campaign)
    advanced = await service.record(campaign_id, _report(digest), run_id="run-1")
    restored = await store.get(campaign_id)

    assert advanced.revision == 1
    assert restored == advanced
    assert restored is not None
    assert restored.runs[0].run_id == "run-1"
    assert await reports.get(campaign_id, "run-1") == _report(digest)
    assert await state_store.verify_chain()


async def test_campaign_create_and_duplicate_run_are_idempotent() -> None:
    state_store = InMemoryStateStore()
    store = StateStoreConfigurationReviewCampaignStore(state_store)
    reports = StateStoreConfigurationDriftReportStore(state_store, clock=lambda: _NOW)
    digest = "a" * 64
    campaign_id = configuration_review_campaign_id(scope="example-scope", version="v1")
    service = ConfigurationReviewCampaignService(store, reports)
    campaign = ConfigurationReviewCampaign(
        campaign_id=campaign_id,
        baseline_version="v1",
        baseline_sha256=digest,
        scope="example-scope",
    )

    assert await service.create(campaign) is campaign
    assert await service.create(campaign) == campaign
    first = await service.record(campaign_id, _report(digest), run_id="run-1")
    duplicate = await service.record(campaign_id, _report(digest), run_id="run-1")

    assert duplicate == first
    assert duplicate.revision == 1

    with pytest.raises(ConfigurationDriftReportConflictError, match="different evidence"):
        await service.record(
            campaign_id,
            replace(_report(digest), verdict=DriftVerdict.FAILED),
            run_id="run-1",
        )


async def test_report_identity_rejects_different_replay_evidence() -> None:
    state_store = InMemoryStateStore()
    reports = StateStoreConfigurationDriftReportStore(state_store, clock=lambda: _NOW)
    campaign_id = configuration_review_campaign_id(scope="example-scope", version="v1")
    first = _report("a" * 64)

    assert (
        await persist_configuration_drift_report(
            reports,
            campaign_id=campaign_id,
            run_id="run-1",
            report=first,
        )
        == first
    )
    assert (
        await persist_configuration_drift_report(
            reports,
            campaign_id=campaign_id,
            run_id="run-1",
            report=first,
        )
        == first
    )
    with pytest.raises(ConfigurationDriftReportConflictError, match="different evidence"):
        await persist_configuration_drift_report(
            reports,
            campaign_id=campaign_id,
            run_id="run-1",
            report=replace(first, verdict=DriftVerdict.FAILED),
        )
    assert await reports.get(campaign_id, "run-1") == first
    assert len(tuple(state_store.audit_entries)) == 1
    assert await state_store.verify_chain()


async def test_failed_campaign_resumes_without_deleting_prior_attempt() -> None:
    state_store = InMemoryStateStore()
    store = StateStoreConfigurationReviewCampaignStore(state_store, clock=lambda: _NOW)
    reports = StateStoreConfigurationDriftReportStore(state_store, clock=lambda: _NOW)
    digest = "a" * 64
    campaign_id = configuration_review_campaign_id(scope="example-scope", version="v1")
    service = ConfigurationReviewCampaignService(store, reports)
    await service.create(
        ConfigurationReviewCampaign(
            campaign_id=campaign_id,
            baseline_version="v1",
            baseline_sha256=digest,
            scope="example-scope",
        )
    )
    await service.record(campaign_id, _report(digest), run_id="attempt-1-run-1")
    await service.record(
        campaign_id,
        replace(_report(digest), verdict=DriftVerdict.BLOCKED),
        run_id="attempt-1-run-2",
    )
    failed = await service.record(campaign_id, _report(digest), run_id="attempt-1-run-3")

    resumed = await service.resume(campaign_id)
    restored = await store.get(campaign_id)

    assert failed.state.value == "paused-failed"
    assert resumed.state.value == "active"
    assert resumed.runs == ()
    assert resumed.failed_attempts == (failed.runs,)
    assert restored == resumed
    assert resumed.revision == 4
    assert await state_store.verify_chain()
