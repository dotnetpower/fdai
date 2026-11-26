from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.delivery.forecast_evidence_query_cli import query_forecast_evidence

_NOW = datetime(2026, 9, 10, 10, 0, tzinfo=UTC)


class _Reader:
    def __init__(self) -> None:
        self.observed_at: datetime | None = None

    async def health_snapshot(self, *, now: datetime) -> dict[str, object]:
        self.observed_at = now
        return {
            "episodes": {"total": 0, "closed": 0},
            "operational_metrics": {
                "precision": None,
                "recall": None,
                "missed_breach_rate": None,
                "interval_coverage": None,
                "mean_lead_time_seconds": None,
                "abstention_rate": None,
                "scorable_episode_count": 0,
            },
        }


@pytest.mark.asyncio
async def test_query_preserves_explicit_unknown_denominators() -> None:
    reader = _Reader()

    result = await query_forecast_evidence(reader=reader, observed_at=_NOW)

    assert result["observed_at"] == "2026-09-10T10:00:00+00:00"
    assert result["snapshot"] == {
        "episodes": {"total": 0, "closed": 0},
        "operational_metrics": {
            "precision": None,
            "recall": None,
            "missed_breach_rate": None,
            "interval_coverage": None,
            "mean_lead_time_seconds": None,
            "abstention_rate": None,
            "scorable_episode_count": 0,
        },
    }
    assert reader.observed_at == _NOW


@pytest.mark.asyncio
async def test_query_rejects_naive_observation_time_before_reading() -> None:
    reader = _Reader()

    with pytest.raises(ValueError, match="timezone-aware"):
        await query_forecast_evidence(
            reader=reader,
            observed_at=_NOW.replace(tzinfo=None),
        )

    assert reader.observed_at is None
