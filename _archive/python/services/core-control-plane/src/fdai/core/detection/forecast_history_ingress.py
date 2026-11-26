"""Produce bound source histories for one exact request, then collect through the gate.

Production and collection stay separate: a producer only appends derived history and honest
coverage, while the unchanged `StateTransitionForecastHistoryCollector` alone decides whether
four complete, fresh, exactly mapped slices exist. Producers run concurrently, each under its own
budget, so one slow kind cannot starve another. A source read that hangs past the producer's own
source deadline still appends `source_unavailable` coverage inside that budget. A producer that
exceeds its whole budget is cancelled and logged without writing; the collector then refuses
missing coverage or relies only on an earlier checkpoint that is still within its freshness bound.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Mapping
from typing import Any, Protocol

from fdai.core.detection.forecast_history_producer import ForecastHistoryProducer
from fdai.shared.providers.forecast_context import ForecastContextRequest

_LOGGER = logging.getLogger(__name__)


class ForecastHistoryCollector(Protocol):
    async def collect(self, request: ForecastContextRequest) -> Mapping[str, Any]: ...


class ProducingForecastHistoryCollector:
    """Run bound producers concurrently with per-kind budgets before the collector read."""

    def __init__(
        self,
        *,
        collector: ForecastHistoryCollector,
        producers: tuple[ForecastHistoryProducer, ...],
        timeout_seconds: float = 2.0,
    ) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 5
        ):
            raise ValueError("forecast history production timeout MUST be in (0, 5]")
        self._collector = collector
        self._timeout_seconds = timeout_seconds
        self._producers: dict[tuple[str, str], dict[str, ForecastHistoryProducer]] = {}
        for producer in producers:
            identity = (producer.access_scope_digest, producer.target_digest)
            group = self._producers.setdefault(identity, {})
            if producer.kind in group:
                raise ValueError("forecast history producer is duplicated for one target")
            group[producer.kind] = producer

    def bound_kinds(self) -> frozenset[str]:
        """Return source kinds with at least one bound producer; binding proves no coverage."""
        return frozenset(kind for group in self._producers.values() for kind in group)

    async def collect(self, request: ForecastContextRequest) -> Mapping[str, Any]:
        group = self._producers.get((request.access_scope_digest, request.target_digest), {})
        await asyncio.gather(*(self._produce(kind, group[kind], request) for kind in sorted(group)))
        return await self._collector.collect(request)

    async def _produce(
        self, kind: str, producer: ForecastHistoryProducer, request: ForecastContextRequest
    ) -> None:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                await producer.produce(request)
        except TimeoutError:
            _LOGGER.warning("forecast_history_production_deadline_exceeded", extra={"kind": kind})
        except Exception as exc:
            _LOGGER.warning(
                "forecast_history_production_failed",
                extra={"kind": kind, "error_type": type(exc).__name__},
            )


__all__ = ["ForecastHistoryCollector", "ProducingForecastHistoryCollector"]
