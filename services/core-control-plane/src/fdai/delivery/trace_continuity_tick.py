"""Run configured trace-continuity checks and publish governed findings."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from fdai.core.detection.trace_continuity import (
    TraceContinuityDetector,
    TraceContinuityState,
    TraceTopologyObservation,
)
from fdai.delivery.analyzer_tick import ANALYZER_EVENT_TOPIC, DEFAULT_WINDOW_SECONDS
from fdai.delivery.azure.trace_continuity import TraceTopologyTarget
from fdai.shared.providers.event_bus import EventBus

_LOGGER = logging.getLogger(__name__)


class TraceContinuityObservationSource(Protocol):
    """Collect normalized scenario runs for configured topology targets."""

    async def collect(
        self,
        targets: Sequence[TraceTopologyTarget],
        *,
        window_seconds: int,
        window_bucket: str,
    ) -> tuple[TraceTopologyObservation, ...]: ...


@dataclass(frozen=True, slots=True)
class TraceContinuityTickReport:
    """Bounded outcome of one trace-continuity pass."""

    targets: int
    scenarios: int
    continuous: int
    unknown: int
    findings: int
    published: int
    publish_errors: tuple[tuple[str, str], ...] = ()

    @property
    def failed(self) -> bool:
        """Return true when at least one finding needs publication retry."""
        return bool(self.publish_errors)

    def to_dict(self) -> dict[str, object]:
        return {
            "targets": self.targets,
            "scenarios": self.scenarios,
            "continuous": self.continuous,
            "unknown": self.unknown,
            "findings": self.findings,
            "published": self.published,
            "publish_errors": [list(item) for item in self.publish_errors],
        }


class TraceContinuityTickRunner:
    """Evaluate one bounded telemetry window without starting an action."""

    def __init__(
        self,
        *,
        source: TraceContinuityObservationSource,
        event_bus: EventBus,
        detector: TraceContinuityDetector | None = None,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
        topic: str = ANALYZER_EVENT_TOPIC,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if window_seconds < 1:
            raise ValueError("trace continuity window_seconds MUST be positive")
        if not topic:
            raise ValueError("trace continuity topic MUST be non-empty")
        self._source = source
        self._bus = event_bus
        self._detector = detector or TraceContinuityDetector()
        self._window_seconds = window_seconds
        self._topic = topic
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def run_once(
        self,
        targets: Sequence[TraceTopologyTarget],
    ) -> TraceContinuityTickReport:
        """Collect, evaluate, and publish every discontinuity in one window."""
        if not targets:
            return TraceContinuityTickReport(
                targets=0,
                scenarios=0,
                continuous=0,
                unknown=0,
                findings=0,
                published=0,
            )
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("trace continuity clock MUST return a timezone-aware timestamp")
        window_bucket = str(int(now.timestamp() // self._window_seconds))
        observations = await self._source.collect(
            targets,
            window_seconds=self._window_seconds,
            window_bucket=window_bucket,
        )

        continuous = 0
        unknown = 0
        findings = 0
        published = 0
        publish_errors: list[tuple[str, str]] = []
        for observation in observations:
            result = self._detector.evaluate(observation)
            if result.state is TraceContinuityState.CONTINUOUS:
                continuous += 1
                continue
            if result.state is TraceContinuityState.UNKNOWN:
                unknown += 1
                continue
            findings += 1
            event = self._detector.to_event(result)
            if event is None:
                raise RuntimeError("trace continuity discontinuity did not produce an Event")
            try:
                await self._bus.publish(
                    self._topic,
                    observation.resource_ref,
                    event.model_dump(mode="json"),
                )
            except Exception as exc:  # noqa: BLE001 - retain other scenario findings
                publish_errors.append((event.idempotency_key, f"{type(exc).__name__}:{exc}"))
                _LOGGER.warning(
                    "trace_continuity_publish_failed",
                    extra={
                        "idempotency_key": event.idempotency_key,
                        "correlation_id": event.correlation_id,
                        "error_type": type(exc).__name__,
                    },
                )
                continue
            published += 1

        return TraceContinuityTickReport(
            targets=len(targets),
            scenarios=len(observations),
            continuous=continuous,
            unknown=unknown,
            findings=findings,
            published=published,
            publish_errors=tuple(publish_errors),
        )


__all__ = [
    "TraceContinuityObservationSource",
    "TraceContinuityTickReport",
    "TraceContinuityTickRunner",
]
