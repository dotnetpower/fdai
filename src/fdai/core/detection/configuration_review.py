"""Pure readiness reducer for bounded scheduled configuration reviews."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from croniter import croniter

from fdai.core.detection.configuration_drift_models import (
    ConfigurationDriftReport,
    DriftVerdict,
    KnowledgeGroundingStatus,
)
from fdai.core.detection.configuration_drift_reports import (
    ConfigurationDriftReportStore,
    persist_configuration_drift_report,
)


class ConfigurationReviewState(StrEnum):
    """Lifecycle state for one bounded review campaign."""

    ACTIVE = "active"
    READY_FOR_WEEKLY = "ready-for-weekly"
    PAUSED_FAILED = "paused-failed"


@dataclass(frozen=True, slots=True)
class ConfigurationReviewRun:
    """One immutable evaluated run in a review campaign."""

    run_id: str
    observed_at: datetime
    verdict: DriftVerdict
    verified: bool
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("configuration review run_id MUST be non-empty")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("configuration review observed_at MUST be timezone-aware")


@dataclass(frozen=True, slots=True)
class ConfigurationReviewCampaign:
    """Server-pinned bounded campaign awaiting three verified runs."""

    campaign_id: str
    baseline_version: str
    baseline_sha256: str
    scope: str
    run_limit: int = 3
    required_successes: int = 3
    state: ConfigurationReviewState = ConfigurationReviewState.ACTIVE
    runs: tuple[ConfigurationReviewRun, ...] = ()
    revision: int = 0

    def __post_init__(self) -> None:
        if (
            not self.campaign_id.strip()
            or not self.baseline_version.strip()
            or not self.scope.strip()
        ):
            raise ValueError("configuration review identity fields MUST be non-empty")
        if len(self.baseline_sha256) != 64:
            raise ValueError("configuration review baseline_sha256 MUST be a SHA-256 digest")
        if self.run_limit < 1 or not 1 <= self.required_successes <= self.run_limit:
            raise ValueError("configuration review success target MUST fit inside the run limit")
        if len(self.runs) > self.run_limit:
            raise ValueError("configuration review runs MUST NOT exceed the run limit")
        if self.revision < 0:
            raise ValueError("configuration review revision MUST be non-negative")


@dataclass(frozen=True, slots=True)
class ConfigurationReviewScheduleProposal:
    """Inert weekly schedule proposal; it grants no creation authority."""

    campaign_id: str
    cron_expression: str
    timezone: str
    baseline_version: str
    baseline_sha256: str
    scope: str
    evidence_run_ids: tuple[str, ...]


class ConfigurationReviewCampaignStore(Protocol):
    """Persist revisioned review campaigns behind a CAS boundary."""

    async def get(self, campaign_id: str) -> ConfigurationReviewCampaign | None: ...

    async def create(self, campaign: ConfigurationReviewCampaign) -> bool: ...

    async def replace(
        self,
        campaign: ConfigurationReviewCampaign,
        *,
        expected_revision: int,
    ) -> bool: ...


class ConfigurationReviewConflictError(RuntimeError):
    """Concurrent review updates exhausted the bounded CAS retry."""


class ConfigurationReviewCampaignService:
    """Create and advance durable campaigns with bounded CAS retry."""

    def __init__(
        self,
        store: ConfigurationReviewCampaignStore,
        reports: ConfigurationDriftReportStore,
        *,
        max_attempts: int = 3,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("configuration review max_attempts MUST be positive")
        self._store = store
        self._reports = reports
        self._max_attempts = max_attempts

    async def create(self, campaign: ConfigurationReviewCampaign) -> ConfigurationReviewCampaign:
        if not await self._store.create(campaign):
            existing = await self._store.get(campaign.campaign_id)
            if existing == campaign:
                return campaign
            raise ConfigurationReviewConflictError("configuration review campaign already exists")
        return campaign

    async def record(
        self,
        campaign_id: str,
        report: ConfigurationDriftReport,
        *,
        run_id: str,
    ) -> ConfigurationReviewCampaign:
        for _attempt in range(self._max_attempts):
            current = await self._store.get(campaign_id)
            if current is None:
                raise KeyError(campaign_id)
            next_campaign = record_configuration_review_run(current, report, run_id=run_id)
            if next_campaign is current:
                return current
            await persist_configuration_drift_report(
                self._reports,
                campaign_id=campaign_id,
                run_id=run_id,
                report=report,
            )
            updated = replace(next_campaign, revision=current.revision + 1)
            if await self._store.replace(updated, expected_revision=current.revision):
                return updated
        raise ConfigurationReviewConflictError("configuration review campaign update conflicted")


def record_configuration_review_run(
    campaign: ConfigurationReviewCampaign,
    report: ConfigurationDriftReport,
    *,
    run_id: str,
) -> ConfigurationReviewCampaign:
    """Return the next campaign state after one exact report, idempotently."""

    normalized_run_id = run_id.strip()
    if not normalized_run_id:
        raise ValueError("configuration review run_id MUST be non-empty")
    if any(run.run_id == normalized_run_id for run in campaign.runs):
        return campaign
    if campaign.state is not ConfigurationReviewState.ACTIVE:
        raise ValueError("configuration review campaign is paused")
    if (
        report.baseline_version != campaign.baseline_version
        or report.baseline_sha256 != campaign.baseline_sha256
        or report.scope != campaign.scope
    ):
        raise ValueError("configuration review report does not match the pinned campaign")

    verified = _is_verified(report)
    runs = campaign.runs + (
        ConfigurationReviewRun(
            run_id=normalized_run_id,
            observed_at=report.observed_at,
            verdict=report.verdict,
            verified=verified,
            evidence_refs=report.knowledge_citations,
        ),
    )
    if len(runs) < campaign.run_limit:
        return replace(campaign, runs=runs)
    successes = sum(run.verified for run in runs)
    state = (
        ConfigurationReviewState.READY_FOR_WEEKLY
        if successes >= campaign.required_successes
        else ConfigurationReviewState.PAUSED_FAILED
    )
    return replace(campaign, runs=runs, state=state)


def propose_weekly_configuration_review(
    campaign: ConfigurationReviewCampaign,
    *,
    cron_expression: str,
    timezone: str = "UTC",
) -> ConfigurationReviewScheduleProposal:
    """Create an inert weekly proposal from a ready campaign."""

    if campaign.state is not ConfigurationReviewState.READY_FOR_WEEKLY:
        raise ValueError("configuration review campaign is not ready for weekly promotion")
    if len(cron_expression.split()) != 5 or not croniter.is_valid(cron_expression, strict=True):
        raise ValueError("weekly configuration review requires a strict 5-field cron")
    return ConfigurationReviewScheduleProposal(
        campaign_id=campaign.campaign_id,
        cron_expression=cron_expression,
        timezone=timezone,
        baseline_version=campaign.baseline_version,
        baseline_sha256=campaign.baseline_sha256,
        scope=campaign.scope,
        evidence_run_ids=tuple(run.run_id for run in campaign.runs),
    )


def _is_verified(report: ConfigurationDriftReport) -> bool:
    return (
        report.verdict in (DriftVerdict.PASSED, DriftVerdict.FAILED)
        and report.knowledge_status is KnowledgeGroundingStatus.CITED
        and report.mutation_count == 0
        and report.approval_request_count == 0
        and report.mitigation_execution_count == 0
        and report.unsupported_claim_count == 0
    )


__all__ = [
    "ConfigurationReviewCampaign",
    "ConfigurationReviewCampaignService",
    "ConfigurationReviewCampaignStore",
    "ConfigurationReviewConflictError",
    "ConfigurationReviewRun",
    "ConfigurationReviewScheduleProposal",
    "ConfigurationReviewState",
    "propose_weekly_configuration_review",
    "record_configuration_review_run",
]
