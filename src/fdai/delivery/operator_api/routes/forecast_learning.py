"""Read-only operational truth for forecast evaluation and case-history learning."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol


class ForecastLearningHealthReader(Protocol):
    async def health_snapshot(self, *, now: datetime) -> Mapping[str, object]: ...


class ForecastLearningPanel:
    path = "/forecast-learning"
    name = "forecast-learning"

    def __init__(self, reader: ForecastLearningHealthReader) -> None:
        self._reader = reader

    async def render(self, *, params: Mapping[str, str]) -> Mapping[str, object]:
        del params
        snapshot = dict(await self._reader.health_snapshot(now=datetime.now(UTC)))
        return {"source": "postgres", "durable": True, **snapshot}


__all__ = ["ForecastLearningHealthReader", "ForecastLearningPanel"]
