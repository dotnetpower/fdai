"""StateStore-backed immutable configuration drift report ledger."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime

from fdai.core.detection.configuration_drift_codec import report_from_dict, report_to_dict
from fdai.core.detection.configuration_drift_models import ConfigurationDriftReport
from fdai.shared.providers.state_store import StateStore

_PREFIX = "configuration-drift-report:"


class StateStoreConfigurationDriftReportStore:
    """Persist full reports with atomic create-and-audit semantics."""

    def __init__(
        self,
        store: StateStore,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    ) -> None:
        self._store = store
        self._clock = clock

    async def get(self, campaign_id: str, run_id: str) -> ConfigurationDriftReport | None:
        raw = await self._store.read_state(_key(campaign_id, run_id))
        return None if raw is None else report_from_dict(raw)

    async def create(
        self,
        campaign_id: str,
        run_id: str,
        report: ConfigurationDriftReport,
    ) -> bool:
        at = self._clock()
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("configuration drift report clock MUST be timezone-aware")
        return await self._store.write_state_with_audit_if_absent(
            _key(campaign_id, run_id),
            report_to_dict(report),
            {
                "event_id": f"{campaign_id}:{run_id}",
                "action": "configuration_drift.report_recorded",
                "campaign_id": campaign_id,
                "run_id": run_id,
                "baseline_version": report.baseline_version,
                "baseline_sha256": report.baseline_sha256,
                "scope": report.scope,
                "verdict": report.verdict.value,
                "timestamp": at.isoformat(),
            },
        )


def _key(campaign_id: str, run_id: str) -> str:
    if not campaign_id.strip() or not run_id.strip():
        raise ValueError("configuration drift report identity MUST be non-empty")
    digest = hashlib.sha256(f"{campaign_id}\0{run_id}".encode()).hexdigest()
    return f"{_PREFIX}{digest}"


__all__ = ["StateStoreConfigurationDriftReportStore"]
