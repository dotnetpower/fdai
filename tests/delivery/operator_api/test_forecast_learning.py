from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from fdai.delivery.operator_api.routes.forecast_learning import ForecastLearningPanel


class _Reader:
    async def health_snapshot(self, *, now: datetime) -> Mapping[str, object]:
        if now.tzinfo is None:
            raise AssertionError("panel clock must be timezone-aware")
        return {
            "episodes": {"total": 10, "closed": 9, "open": 1, "overdue": 1},
            "outcomes": [{"label": "false_negative", "miss_origin": "pipeline", "count": 1}],
            "publication": {"pending": 1, "oldest_pending_at": "2026-07-23T15:00:00Z"},
            "retention": {"overdue": 2, "pending": 1},
        }


async def test_panel_exposes_closure_and_pipeline_debt() -> None:
    payload = await ForecastLearningPanel(_Reader()).render(params={})
    episodes = payload["episodes"]
    outcomes = payload["outcomes"]
    publication = payload["publication"]
    retention = payload["retention"]
    assert isinstance(episodes, dict) and episodes["overdue"] == 1
    assert isinstance(outcomes, list) and outcomes[0]["miss_origin"] == "pipeline"
    assert isinstance(publication, dict) and publication["pending"] == 1
    assert isinstance(retention, dict) and retention["overdue"] == 2
