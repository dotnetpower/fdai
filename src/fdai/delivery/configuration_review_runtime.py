"""Fresh configuration review runs with durable evidence and blueprint handoff."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fdai.core.detection.configuration_drift_models import (
    ConfigurationDriftReport,
    FrozenConfigurationBaseline,
)
from fdai.core.detection.configuration_review import (
    ConfigurationReviewCampaign,
    ConfigurationReviewCampaignService,
    ConfigurationReviewState,
    propose_weekly_configuration_review,
)
from fdai.core.scheduler.blueprints import (
    AutomationBlueprintCandidate,
    configuration_review_blueprint,
)
from fdai.delivery.configuration_review_store import configuration_review_campaign_id


class ConfigurationReviewBaselineSource(Protocol):
    async def load(self) -> FrozenConfigurationBaseline: ...


class ConfigurationReviewDriftService(Protocol):
    async def run(self) -> ConfigurationDriftReport: ...


class ConfigurationReviewBlueprintSubmitter(Protocol):
    async def submit(
        self,
        candidate: AutomationBlueprintCandidate,
    ) -> AutomationBlueprintCandidate: ...


@dataclass(frozen=True, slots=True)
class ConfigurationReviewRunResult:
    campaign: ConfigurationReviewCampaign
    report: ConfigurationDriftReport
    blueprint: AutomationBlueprintCandidate | None


class ConfigurationReviewRuntime:
    """Run one pinned review and hand ready evidence to blueprint governance."""

    def __init__(
        self,
        *,
        baseline_source: ConfigurationReviewBaselineSource,
        drift_service: ConfigurationReviewDriftService,
        campaigns: ConfigurationReviewCampaignService,
        blueprints: ConfigurationReviewBlueprintSubmitter,
        cron_expression: str = "0 9 * * 1",
        timezone: str = "UTC",
    ) -> None:
        self._baseline_source = baseline_source
        self._drift_service = drift_service
        self._campaigns = campaigns
        self._blueprints = blueprints
        self._cron_expression = cron_expression
        self._timezone = timezone

    async def run(
        self,
        *,
        principal_id: str,
        run_id: str,
        now: datetime,
    ) -> ConfigurationReviewRunResult:
        baseline = await self._baseline_source.load()
        campaign_id = configuration_review_campaign_id(
            scope=baseline.scope,
            version=baseline.version,
        )
        await self._campaigns.ensure(
            ConfigurationReviewCampaign(
                campaign_id=campaign_id,
                baseline_version=baseline.version,
                baseline_sha256=baseline.sha256,
                scope=baseline.scope,
            )
        )
        report = await self._drift_service.run()
        campaign = await self._campaigns.record(campaign_id, report, run_id=run_id)
        blueprint = None
        if campaign.state is ConfigurationReviewState.READY_FOR_WEEKLY:
            blueprint = await self._blueprints.submit(
                configuration_review_blueprint(
                    propose_weekly_configuration_review(
                        campaign,
                        cron_expression=self._cron_expression,
                        timezone=self._timezone,
                    ),
                    proposer=principal_id,
                    now=now,
                )
            )
        return ConfigurationReviewRunResult(
            campaign=campaign,
            report=report,
            blueprint=blueprint,
        )


__all__ = [
    "ConfigurationReviewBlueprintSubmitter",
    "ConfigurationReviewRunResult",
    "ConfigurationReviewRuntime",
]
