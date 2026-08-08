"""Scheduled burn-rate evaluation runner - publishes breach events to the bus.

Design contract: ``docs/roadmap/fork-and-sequencing/scope-expansion.md`` sections 3.2 (telemetry
ingestion seam) and 3.3 (workload SLO / error budget).

Not a polling daemon. :meth:`SloBurnRunner.run_once` is a single idempotent
pass that an out-of-band trigger (a Container Apps Job / Kubernetes ``CronJob``,
per ``app-shape.instructions.md``) invokes on a schedule - keeping the control
plane event-driven and scale-to-zero rather than running an always-on loop.

Each pass evaluates every registered SLO through the
:class:`~fdai.core.slo.metric_source.MetricBurnRateSource`, normalizes each
fired multi-window burn-rate alert into an ``slo.error_budget_burn`` Event, and
publishes it to the event-ingest topic so the standard
trust-router / risk-gate / executor path governs the response. The runner never
auto-remediates.

Fail-closed on two axes:

- **Missing telemetry** - an SLO whose evaluation reports ``insufficient_data``
  is skipped (counted, logged), never published as a false all-clear.
- **Broker error** - a failed publish is recorded on the report and the run
  continues to the next SLO, so one bad topic partition cannot silence every
  other SLO's alert.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from fdai.shared.contracts.models import Mode
from fdai.shared.providers.event_bus import EventBus

from .metric_source import MetricBurnRateSource
from .registry import SloRegistry

SLO_BURN_EVENT_TOPIC: Final[str] = "aw.slo.events"
"""Event-ingest topic burn-rate breaches re-enter on (``aw.<domain>.events``
convention, mirroring ``aw.change.events``)."""

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SloBurnRunReport:
    """Summary of one :meth:`SloBurnRunner.run_once` pass."""

    evaluated: int
    breached: int
    published: int
    insufficient: int
    publish_errors: tuple[tuple[str, str], ...] = ()
    """``(slo_id, short_error)`` pairs for each publish that failed."""
    evaluation_errors: tuple[tuple[str, str], ...] = ()
    """``(slo_id, short_error)`` pairs for each SLO whose evaluation raised;
    the pass isolates the failure and continues to the next SLO."""


def _default_clock() -> datetime:
    return datetime.now(tz=UTC)


class SloBurnRunner:
    """Evaluate every registered SLO once and publish breach events."""

    __slots__ = ("_clock", "_event_bus", "_mode", "_registry", "_source", "_topic")

    def __init__(
        self,
        *,
        registry: SloRegistry,
        source: MetricBurnRateSource,
        event_bus: EventBus,
        topic: str = SLO_BURN_EVENT_TOPIC,
        mode: Mode = Mode.SHADOW,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._registry = registry
        self._source = source
        self._event_bus = event_bus
        self._topic = topic
        self._mode = mode
        self._clock = clock or _default_clock

    async def run_once(self, *, now: datetime | None = None) -> SloBurnRunReport:
        """Execute one burn-rate evaluation + publish cycle over all SLOs."""
        at = now if now is not None else self._clock()
        evaluated = 0
        breached = 0
        published = 0
        insufficient = 0
        publish_errors: list[tuple[str, str]] = []
        evaluation_errors: list[tuple[str, str]] = []

        for slo in self._registry.all():
            evaluated += 1
            # Isolate a per-SLO evaluation failure the same way the publish
            # path is isolated below: a raising provider, a missing-window
            # KeyError, or any other fault on one SLO MUST NOT silence every
            # other SLO's alert for the whole pass. Record it and continue.
            # (``except Exception`` deliberately lets ``CancelledError`` - a
            # BaseException - propagate so a cancelled run still aborts.)
            try:
                evaluation = await self._source.evaluate(slo, now=at)
            except Exception as exc:  # noqa: BLE001 - fail-close: record and continue
                evaluation_errors.append((slo.id, f"{type(exc).__name__}:{exc}"))
                _LOGGER.warning(
                    "slo_burn_evaluation_failed",
                    extra={"slo_id": slo.id, "error": type(exc).__name__},
                )
                continue
            if evaluation.insufficient_data:
                insufficient += 1
                _LOGGER.info("slo_burn_insufficient_data", extra={"slo_id": slo.id})
                continue
            if not evaluation.breached:
                continue
            breached += 1
            for event in self._source.to_events(evaluation, slo=slo, mode=self._mode):
                key = event.resource_ref or slo.id
                try:
                    await self._event_bus.publish(self._topic, key, event.model_dump(mode="json"))
                    published += 1
                except Exception as exc:  # noqa: BLE001 - fail-close: record and continue
                    publish_errors.append((slo.id, f"{type(exc).__name__}:{exc}"))
                    _LOGGER.warning(
                        "slo_burn_publish_failed",
                        extra={"slo_id": slo.id, "error": type(exc).__name__},
                    )

        return SloBurnRunReport(
            evaluated=evaluated,
            breached=breached,
            published=published,
            insufficient=insufficient,
            publish_errors=tuple(publish_errors),
            evaluation_errors=tuple(evaluation_errors),
        )


__all__ = ["SLO_BURN_EVENT_TOPIC", "SloBurnRunReport", "SloBurnRunner"]
