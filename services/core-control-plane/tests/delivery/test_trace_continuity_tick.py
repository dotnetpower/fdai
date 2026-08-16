"""Trace-continuity tick publication and retry behavior."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.detection.trace_continuity import (
    TraceSpanObservation,
    TraceTopologyObservation,
)
from fdai.delivery.analyzer_tick import ANALYZER_EVENT_TOPIC
from fdai.delivery.azure.trace_continuity import TraceTopologyTarget
from fdai.delivery.trace_continuity_tick import TraceContinuityTickRunner

_NOW = datetime(2026, 8, 17, 2, 0, tzinfo=UTC)
_HOPS = ("application", "agent", "api-gateway", "model-endpoint")


class _Source:
    def __init__(self, observations: tuple[TraceTopologyObservation, ...]) -> None:
        self._observations = observations
        self.calls: list[tuple[int, str]] = []

    async def collect(
        self,
        targets: tuple[TraceTopologyTarget, ...],
        *,
        window_seconds: int,
        window_bucket: str,
    ) -> tuple[TraceTopologyObservation, ...]:
        del targets
        self.calls.append((window_seconds, window_bucket))
        return self._observations


class _Bus:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.published: list[tuple[str, str, dict[str, object]]] = []

    async def publish(self, topic: str, key: str, payload: dict[str, object]) -> None:
        if self.fail:
            raise RuntimeError("broker unavailable")
        self.published.append((topic, key, payload))


def _target() -> TraceTopologyTarget:
    return TraceTopologyTarget(
        topology_ref="synthetic-agent-request",
        resource_ref="trace-topology/synthetic-agent-request",
        expected_hops=_HOPS,
    )


def _observation(trace_ids: tuple[str, ...]) -> TraceTopologyObservation:
    return TraceTopologyObservation(
        topology_ref="synthetic-agent-request",
        scenario_id="scenario-001",
        resource_ref="trace-topology/synthetic-agent-request",
        window_bucket="source-replaced-by-runner",
        expected_hops=_HOPS,
        spans=tuple(
            TraceSpanObservation(
                trace_id=trace_id,
                span_id=f"span-{sequence}",
                hop=hop,
                sequence=sequence,
                observed_at=_NOW + timedelta(seconds=sequence),
                evidence_ref=f"appinsights:span-{sequence}",
            )
            for sequence, (hop, trace_id) in enumerate(zip(_HOPS, trace_ids, strict=True))
        ),
        completed=True,
    )


@pytest.mark.asyncio
async def test_continuous_run_publishes_nothing() -> None:
    source = _Source((_observation(("trace-a",) * len(_HOPS)),))
    bus = _Bus()
    runner = TraceContinuityTickRunner(
        source=source,
        event_bus=bus,  # type: ignore[arg-type]
        clock=lambda: _NOW,
    )

    report = await runner.run_once((_target(),))

    assert report.continuous == 1
    assert report.findings == 0
    assert report.published == 0
    assert bus.published == []


@pytest.mark.asyncio
async def test_discontinuity_publishes_one_governed_event() -> None:
    source = _Source((_observation(("trace-front", "trace-front", "trace-back", "trace-back")),))
    bus = _Bus()
    runner = TraceContinuityTickRunner(
        source=source,
        event_bus=bus,  # type: ignore[arg-type]
        clock=lambda: _NOW,
    )

    report = await runner.run_once((_target(),))

    assert report.findings == 1
    assert report.published == 1
    topic, key, payload = bus.published[0]
    assert topic == ANALYZER_EVENT_TOPIC
    assert key == "trace-topology/synthetic-agent-request"
    assert payload["event_type"] == "trace-continuity.discontinuity"
    assert payload["correlation_id"] == "scenario-001"
    assert payload["incident_correlation"] == "correlate"


@pytest.mark.asyncio
async def test_retry_reuses_the_same_idempotency_key() -> None:
    source = _Source((_observation(("trace-front", "trace-front", "trace-back", "trace-back")),))
    bus = _Bus()
    runner = TraceContinuityTickRunner(
        source=source,
        event_bus=bus,  # type: ignore[arg-type]
        clock=lambda: _NOW,
    )

    await runner.run_once((_target(),))
    await runner.run_once((_target(),))

    keys = {payload["idempotency_key"] for _, _, payload in bus.published}
    assert len(bus.published) == 2
    assert len(keys) == 1


@pytest.mark.asyncio
async def test_publish_failure_is_reported_for_job_retry() -> None:
    source = _Source((_observation(("trace-front", "trace-front", "trace-back", "trace-back")),))
    runner = TraceContinuityTickRunner(
        source=source,
        event_bus=_Bus(fail=True),  # type: ignore[arg-type]
        clock=lambda: _NOW,
    )

    report = await runner.run_once((_target(),))

    assert report.failed is True
    assert report.published == 0
    assert report.publish_errors[0][1].startswith("RuntimeError:")
