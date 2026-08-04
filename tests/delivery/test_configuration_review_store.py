from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.detection.configuration_drift import (
    ConfigurationDriftReport,
    ConfigurationReviewCampaign,
    ConfigurationReviewCampaignService,
    DriftVerdict,
    KnowledgeGroundingStatus,
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
    digest = "a" * 64
    campaign_id = configuration_review_campaign_id(scope="example-scope", version="v1")
    service = ConfigurationReviewCampaignService(store)
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
    assert await state_store.verify_chain()


async def test_campaign_create_and_duplicate_run_are_idempotent() -> None:
    store = StateStoreConfigurationReviewCampaignStore(InMemoryStateStore())
    digest = "a" * 64
    campaign_id = configuration_review_campaign_id(scope="example-scope", version="v1")
    service = ConfigurationReviewCampaignService(store)
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
