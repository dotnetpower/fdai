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

    if await store.create(campaign_id, run_id, report):
        return report
    existing = await store.get(campaign_id, run_id)
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
