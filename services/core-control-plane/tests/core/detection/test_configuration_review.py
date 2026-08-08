from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fdai.core.detection.configuration_drift import (
    ConfigurationDriftReport,
    ConfigurationReviewCampaign,
    ConfigurationReviewState,
    DriftVerdict,
    KnowledgeGroundingStatus,
    propose_weekly_configuration_review,
    record_configuration_review_run,
)

_NOW = datetime(2026, 8, 4, tzinfo=UTC)
_DIGEST = "a" * 64


def _campaign() -> ConfigurationReviewCampaign:
    return ConfigurationReviewCampaign(
        campaign_id="review-example",
        baseline_version="v1",
        baseline_sha256=_DIGEST,
        scope="example-scope",
    )


def _report(verdict: DriftVerdict = DriftVerdict.PASSED) -> ConfigurationDriftReport:
    return ConfigurationDriftReport(
        baseline_version="v1",
        baseline_sha256=_DIGEST,
        scope="example-scope",
        observed_at=_NOW,
        verdict=verdict,
        findings=(),
        knowledge_status=KnowledgeGroundingStatus.CITED,
        knowledge_citations=("knowledge:baseline.docx#v1#digest#0",),
    )


def test_three_verified_runs_create_only_a_weekly_proposal() -> None:
    campaign = _campaign()
    for run_number in range(1, 4):
        campaign = record_configuration_review_run(
            campaign,
            _report(),
            run_id=f"run-{run_number}",
        )

    proposal = propose_weekly_configuration_review(
        campaign,
        cron_expression="0 9 * * 1",
    )

    assert campaign.state is ConfigurationReviewState.READY_FOR_WEEKLY
    assert proposal.evidence_run_ids == ("run-1", "run-2", "run-3")
    assert proposal.scope == "example-scope"


def test_blocked_run_pauses_campaign_without_promotion() -> None:
    campaign = _campaign()
    campaign = record_configuration_review_run(campaign, _report(), run_id="run-1")
    campaign = record_configuration_review_run(
        campaign,
        _report(DriftVerdict.BLOCKED),
        run_id="run-2",
    )
    campaign = record_configuration_review_run(campaign, _report(), run_id="run-3")

    assert campaign.state is ConfigurationReviewState.PAUSED_FAILED
    with pytest.raises(ValueError, match="not ready"):
        propose_weekly_configuration_review(campaign, cron_expression="0 9 * * 1")


def test_duplicate_run_is_idempotent() -> None:
    first = record_configuration_review_run(_campaign(), _report(), run_id="run-1")

    assert record_configuration_review_run(first, _report(), run_id="run-1") is first


def test_mismatched_or_unsafe_report_cannot_satisfy_readiness() -> None:
    with pytest.raises(ValueError, match="pinned campaign"):
        record_configuration_review_run(
            _campaign(),
            replace(_report(), scope="another-scope"),
            run_id="run-1",
        )

    campaign = _campaign()
    unsafe = replace(_report(), mutation_count=1)
    campaign = record_configuration_review_run(campaign, unsafe, run_id="run-1")
    campaign = record_configuration_review_run(campaign, _report(), run_id="run-2")
    campaign = record_configuration_review_run(campaign, _report(), run_id="run-3")
    assert campaign.state is ConfigurationReviewState.PAUSED_FAILED
