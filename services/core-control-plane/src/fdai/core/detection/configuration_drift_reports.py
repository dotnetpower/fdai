"""Immutable report persistence contract for configuration drift replay."""

from __future__ import annotations

from typing import Protocol

from fdai.core.detection.configuration_drift_models import ConfigurationDriftReport


class ConfigurationDriftReportStore(Protocol):
    """Store one immutable full report for each campaign run."""

    async def get(self, campaign_id: str, run_id: str) -> ConfigurationDriftReport | None: ...

    async def create(
        self,
        campaign_id: str,
        run_id: str,
        report: ConfigurationDriftReport,
    ) -> bool: ...


class ConfigurationDriftReportConflictError(RuntimeError):
    """A report identity was reused with different evidence."""


async def persist_configuration_drift_report(
    store: ConfigurationDriftReportStore,
    *,
    campaign_id: str,
    run_id: str,
    report: ConfigurationDriftReport,
) -> ConfigurationDriftReport:
    """Create one report idempotently and reject payload substitution."""

    if not isinstance(campaign_id, str) or not campaign_id.strip():
        raise ValueError("campaign_id MUST be non-empty")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id MUST be non-empty")
    normalized_campaign = campaign_id.strip()
    normalized_run = run_id.strip()
    if await store.create(normalized_campaign, normalized_run, report):
        return report
    existing = await store.get(normalized_campaign, normalized_run)
    if existing == report:
        return existing
    raise ConfigurationDriftReportConflictError(
        "configuration drift report identity already has different evidence"
    )


__all__ = [
    "ConfigurationDriftReportConflictError",
    "ConfigurationDriftReportStore",
    "persist_configuration_drift_report",
]
