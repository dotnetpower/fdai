"""SloBurnRunner - scheduled burn-rate evaluation + breach publication.

Covers: a breach publishes one slo.error_budget_burn event to the ingest
topic; a cool SLO publishes nothing; missing telemetry is counted insufficient
and never published; a broker failure is recorded and the run continues; the
topic is configurable. Uses an in-memory recording bus and the deterministic
StaticMetricProvider - no network. Async tests run under asyncio_mode="auto".
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.core.slo import (
    SLO_BURN_EVENT_TOPIC,
    MetricBurnRateSource,
    SloBurnRunner,
    SloRegistry,
)
from fdai.core.slo.models import SLI, SLO, BurnRateAlertDef, SLIKind
from fdai.shared.providers.event_bus import PublishReceipt
from fdai.shared.providers.metric import MetricPoint, NoopMetricProvider, StaticMetricProvider

_NOW = datetime(2026, 7, 9, 12, 0, 0, tzinfo=UTC)


class _RecordingBus:
    """Minimal EventBus that records publishes and can fail on chosen keys."""

    def __init__(self, *, fail_keys: set[str] | None = None) -> None:
        self.published: list[tuple[str, str, Mapping[str, Any]]] = []
        self._fail_keys = fail_keys or set()

    async def publish(self, topic: str, key: str, payload: Mapping[str, Any]) -> PublishReceipt:
        if key in self._fail_keys:
            raise RuntimeError("broker down")
        self.published.append((topic, key, payload))
        return PublishReceipt(topic=topic, partition=0, offset=len(self.published))

    def subscribe(self, topic: str, group_id: str):  # pragma: no cover - unused
        raise NotImplementedError

    async def dead_letter(  # pragma: no cover - unused
        self, topic: str, key: str, payload: Mapping[str, Any], reason: str
    ) -> None:
        raise NotImplementedError


def _slo(slo_id: str, *, good: str, total: str) -> SLO:
    return SLO(
        id=slo_id,
        objective_ratio=0.99,
        window_days=28,
        sli=SLI(kind=SLIKind.AVAILABILITY, good_query=good, total_query=total),
        burn_rate_alerts=(
            BurnRateAlertDef(
                name="fast-burn",
                short_window_minutes=5,
                long_window_minutes=60,
                burn_rate_threshold=1.0,
            ),
        ),
    )


def _point(metric: str, value: float) -> MetricPoint:
    return MetricPoint(metric_name=metric, at=_NOW - timedelta(minutes=1), value=value)


# ---------------------------------------------------------------------------


async def test_breach_publishes_one_event_to_ingest_topic() -> None:
    provider = StaticMetricProvider([_point("g", 980.0), _point("t", 1000.0)])
    registry = SloRegistry(slos=[_slo("api.a", good="g", total="t")])
    bus = _RecordingBus()
    runner = SloBurnRunner(registry=registry, source=MetricBurnRateSource(provider), event_bus=bus)
    report = await runner.run_once(now=_NOW)
    assert report.evaluated == 1
    assert report.breached == 1
    assert report.published == 1
    assert report.insufficient == 0
    assert report.publish_errors == ()
    topic, key, payload = bus.published[0]
    assert topic == SLO_BURN_EVENT_TOPIC
    assert key == "api.a"
    assert payload["event_type"] == "slo.error_budget_burn"


async def test_cool_slo_publishes_nothing() -> None:
    provider = StaticMetricProvider([_point("g", 999.0), _point("t", 1000.0)])
    registry = SloRegistry(slos=[_slo("api.a", good="g", total="t")])
    bus = _RecordingBus()
    runner = SloBurnRunner(registry=registry, source=MetricBurnRateSource(provider), event_bus=bus)
    report = await runner.run_once(now=_NOW)
    assert report.breached == 0
    assert report.published == 0
    assert bus.published == []


async def test_insufficient_data_is_counted_and_not_published() -> None:
    registry = SloRegistry(slos=[_slo("api.a", good="g", total="t")])
    bus = _RecordingBus()
    runner = SloBurnRunner(
        registry=registry, source=MetricBurnRateSource(NoopMetricProvider()), event_bus=bus
    )
    report = await runner.run_once(now=_NOW)
    assert report.insufficient == 1
    assert report.breached == 0
    assert report.published == 0
    assert bus.published == []


async def test_publish_failure_is_recorded_and_run_continues() -> None:
    provider = StaticMetricProvider(
        [
            _point("g1", 980.0),
            _point("t1", 1000.0),
            _point("g2", 980.0),
            _point("t2", 1000.0),
        ]
    )
    registry = SloRegistry(
        slos=[
            _slo("api.a", good="g1", total="t1"),
            _slo("api.b", good="g2", total="t2"),
        ]
    )
    bus = _RecordingBus(fail_keys={"api.a"})
    runner = SloBurnRunner(registry=registry, source=MetricBurnRateSource(provider), event_bus=bus)
    report = await runner.run_once(now=_NOW)
    assert report.evaluated == 2
    assert report.breached == 2
    assert report.published == 1  # api.b succeeded
    assert len(report.publish_errors) == 1
    assert report.publish_errors[0][0] == "api.a"
    assert [k for _, k, _ in bus.published] == ["api.b"]


async def test_topic_is_configurable() -> None:
    provider = StaticMetricProvider([_point("g", 980.0), _point("t", 1000.0)])
    registry = SloRegistry(slos=[_slo("api.a", good="g", total="t")])
    bus = _RecordingBus()
    runner = SloBurnRunner(
        registry=registry,
        source=MetricBurnRateSource(provider),
        event_bus=bus,
        topic="custom.slo.topic",
    )
    await runner.run_once(now=_NOW)
    assert bus.published[0][0] == "custom.slo.topic"


class _FlakySource:
    """Wraps a real source but raises on evaluate for one chosen SLO id."""

    def __init__(self, inner: MetricBurnRateSource, *, fail_slo_id: str) -> None:
        self._inner = inner
        self._fail_slo_id = fail_slo_id

    async def evaluate(self, slo: SLO, *, now: datetime):  # noqa: ANN201
        if slo.id == self._fail_slo_id:
            raise RuntimeError("provider blew up")
        return await self._inner.evaluate(slo, now=now)

    def to_events(self, evaluation, *, slo, mode):  # noqa: ANN001, ANN201
        return self._inner.to_events(evaluation, slo=slo, mode=mode)


async def test_evaluation_failure_is_isolated_and_run_continues() -> None:
    # One SLO's evaluation raises; it MUST NOT silence the other SLO's alert.
    provider = StaticMetricProvider(
        [
            _point("g2", 980.0),
            _point("t2", 1000.0),
        ]
    )
    registry = SloRegistry(
        slos=[
            _slo("api.a", good="g1", total="t1"),  # this one will raise
            _slo("api.b", good="g2", total="t2"),  # this one still fires
        ]
    )
    bus = _RecordingBus()
    source = _FlakySource(MetricBurnRateSource(provider), fail_slo_id="api.a")
    runner = SloBurnRunner(registry=registry, source=source, event_bus=bus)  # type: ignore[arg-type]
    report = await runner.run_once(now=_NOW)
    assert report.evaluated == 2
    assert len(report.evaluation_errors) == 1
    assert report.evaluation_errors[0][0] == "api.a"
    # api.b was evaluated and published despite api.a raising.
    assert report.breached == 1
    assert report.published == 1
    assert [k for _, k, _ in bus.published] == ["api.b"]
