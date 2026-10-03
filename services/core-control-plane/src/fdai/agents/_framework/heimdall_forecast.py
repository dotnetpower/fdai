"""Forecast evaluation and publication lifecycle for Heimdall."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from fdai.agents._framework.bus import PantheonBus
from fdai.core.detection.forecast_closure import ForecastClosureCoordinator
from fdai.core.detection.forecast_episode import (
    ForecastEpisodeStore,
    ForecastPublicationOutboxItem,
    forecast_publication_id,
)
from fdai.core.detection.forecast_evaluation import ForecastEpisodeEvaluator
from fdai.shared.contracts.models import ForecastOutcome

_MAX_FORECAST_PUBLICATION_ATTEMPTS = 5
_FORECAST_PROVIDER_TIMEOUT_SECONDS = 5.0


class HeimdallForecastMixin:
    """Run due forecast evaluations and publish their durable outbox records."""

    bus: PantheonBus | None
    _forecast_clock: Callable[[], datetime]
    _forecast_evaluator: ForecastEpisodeEvaluator | None
    _forecast_closer: ForecastClosureCoordinator | None
    _forecast_store: ForecastEpisodeStore | None
    _forecast_history_ingress: Callable[[Mapping[str, Any]], Awaitable[str]] | None = None

    if TYPE_CHECKING:

        def record_behavior(self, key: str, count: int = 1) -> None: ...

    def bind_forecast_history_ingress(
        self,
        handler: Callable[[Mapping[str, Any]], Awaitable[str]],
    ) -> None:
        """Bind verified source-history retention; never infer completeness from empty input."""
        if self._forecast_history_ingress is not None:
            raise RuntimeError("forecast history ingress is already bound")
        self._forecast_history_ingress = handler

    async def _forecast_context_message(self, payload: dict[str, Any]) -> bool:
        if payload.get("event_type") == "test_context.command.v1":
            self.record_behavior("test_context:governance_command_ignored")
            return True
        if payload.get("event_type") != "forecast.context_history.v1":
            return False
        if self._forecast_history_ingress is None:
            raise RuntimeError("forecast history ingress is unavailable")
        async with asyncio.timeout(5):
            await self._forecast_history_ingress(payload)
        self.record_behavior("forecast_history:retained")
        return True

    async def publish_forecast_outcome(self, outcome: ForecastOutcome) -> bool:
        """Publish one schema-validated terminal forecast result."""

        if not isinstance(outcome, ForecastOutcome):
            raise TypeError("Heimdall forecast outcome MUST be a ForecastOutcome")
        self.record_behavior(f"forecast_outcome:{outcome.label.value}")
        if self.bus is None:
            return False
        if self._forecast_store is not None:
            episode_id = outcome.prediction_id or outcome.outcome_id
            publication = ForecastPublicationOutboxItem(
                publication_id=forecast_publication_id(
                    episode_id=episode_id,
                    topic="object.forecast-outcome",
                ),
                episode_id=episode_id,
                topic="object.forecast-outcome",
                payload=outcome.model_dump(mode="json"),
                attempts=0,
            )
            await self._forecast_store.enqueue_publication(
                publication,
                available_at=outcome.closed_at,
            )
            published = await self._publish_forecast_outbox(now=self._forecast_clock())
            return published > 0
        self.record_behavior("forecast_publication:outbox_unavailable")
        await self.bus.publish(
            "Heimdall",
            "object.forecast-outcome",
            outcome.model_dump(mode="json"),
        )
        return True

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
        evaluated = 0
        closed = 0
        evaluation_timed_out = False
        closure_timed_out = False
        try:
            async with asyncio.timeout(_FORECAST_PROVIDER_TIMEOUT_SECONDS):
                evaluated = await self._forecast_evaluator.evaluate(now=now)
                errors = getattr(self._forecast_evaluator, "absolute_percentage_errors", None)
                recorder = getattr(self, "record_forecast_absolute_percentage_error", None)
                if callable(recorder) and isinstance(errors, tuple | list):
                    for error in errors:
                        if isinstance(error, int | float) and not isinstance(error, bool):
                            recorder(float(error))
        except TimeoutError:
            evaluation_timed_out = True
            self.record_behavior("forecast_episode:evaluation_timeout")
        try:
            async with asyncio.timeout(_FORECAST_PROVIDER_TIMEOUT_SECONDS):
                closed = await self._forecast_closer.close_due(now=now)
        except TimeoutError:
            closure_timed_out = True
            self.record_behavior("forecast_episode:closure_timeout")
        published = await self._publish_forecast_outbox(now=now)
        if evaluation_timed_out or closure_timed_out:
            self.record_behavior("forecast_tick:incomplete")
        elif evaluated or closed or published:
            self.record_behavior("forecast_tick:completed")
        else:
            self.record_behavior("forecast_tick:noop")
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
                complete_task = asyncio.create_task(
                    self._forecast_store.complete_publication(
                        publication.publication_id,
                        published_at=now,
                    )
                )
                try:
                    await asyncio.shield(complete_task)
                except asyncio.CancelledError:
                    await complete_task
                    self.record_behavior("forecast_publication:completion_cancelled")
                    raise
                published += 1
            except asyncio.CancelledError:
                raise
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
