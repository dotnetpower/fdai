"""Forecast evaluation and publication lifecycle for Heimdall."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from fdai.agents._framework.bus import PantheonBus
from fdai.core.detection.forecast_closure import ForecastClosureCoordinator
from fdai.core.detection.forecast_episode import ForecastEpisodeStore
from fdai.core.detection.forecast_evaluation import ForecastEpisodeEvaluator
from fdai.shared.contracts.models import ForecastOutcome

_MAX_FORECAST_PUBLICATION_ATTEMPTS = 5


class HeimdallForecastMixin:
    """Run due forecast evaluations and publish their durable outbox records."""

    bus: PantheonBus | None
    _forecast_clock: Callable[[], datetime]
    _forecast_evaluator: ForecastEpisodeEvaluator | None
    _forecast_closer: ForecastClosureCoordinator | None
    _forecast_store: ForecastEpisodeStore | None

    if TYPE_CHECKING:

        def record_behavior(self, key: str, count: int = 1) -> None: ...

    async def _run_forecast_tick(self, payload: dict[str, object]) -> None:
        identity_fields = (
            payload.get("event_id"),
            payload.get("idempotency_key"),
            payload.get("correlation_id"),
        )
        if payload.get("source") != "forecast-evaluation-scheduler" or any(
            not isinstance(value, str) or not value.startswith("forecast-evaluation:")
            for value in identity_fields
        ):
            self.record_behavior("forecast_tick:invalid")
            return
        if (
            self._forecast_evaluator is None
            or self._forecast_closer is None
            or self._forecast_store is None
        ):
            self.record_behavior("forecast_tick:unavailable")
            return
        now = self._forecast_clock()
        if now.tzinfo is None:
            raise ValueError("Heimdall forecast clock MUST be timezone-aware")
        evaluated = await self._forecast_evaluator.evaluate(now=now)
        closed = await self._forecast_closer.close_due(now=now)
        published = await self._publish_forecast_outbox(now=now)
        self.record_behavior("forecast_tick:completed")
        for _ in range(evaluated):
            self.record_behavior("forecast_episode:evaluated")
        for _ in range(closed):
            self.record_behavior("forecast_episode:closed")
        for _ in range(published):
            self.record_behavior("forecast_publication:published")

    async def _publish_forecast_outbox(self, *, now: datetime) -> int:
        if self._forecast_store is None or self.bus is None:
            return 0
        publications = await self._forecast_store.claim_publications(
            now=now,
            limit=100,
            lease_until=now + timedelta(seconds=60),
        )
        published = 0
        for publication in publications:
            try:
                publication_payload = dict(publication.payload)
                if publication.topic == "object.forecast-outcome":
                    publication_payload = ForecastOutcome.model_validate(
                        publication_payload
                    ).model_dump(mode="json")
                elif publication.topic != "object.forecast":
                    raise ValueError("forecast publication topic is unsupported")
                await self.bus.publish("Heimdall", publication.topic, publication_payload)
                await self._forecast_store.complete_publication(
                    publication.publication_id,
                    published_at=now,
                )
                published += 1
            except Exception as exc:
                error = type(exc).__name__
                if (
                    isinstance(exc, (TypeError, ValueError))
                    or publication.attempts >= _MAX_FORECAST_PUBLICATION_ATTEMPTS
                ):
                    await self._forecast_store.dead_letter_publication(
                        publication.publication_id,
                        failed_at=now,
                        error=error,
                    )
                    self.record_behavior("forecast_publication:dead_lettered")
                else:
                    await self._forecast_store.release_publication(
                        publication.publication_id,
                        available_at=now + timedelta(seconds=30),
                        error=error,
                    )
                    self.record_behavior("forecast_publication:retry")
                continue
        return published


__all__ = ["HeimdallForecastMixin"]
