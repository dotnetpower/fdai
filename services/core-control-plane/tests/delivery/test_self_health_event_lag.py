from datetime import UTC, datetime
from decimal import Decimal, localcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fdai.delivery.self_health_event_lag import RuntimeEventLagSource
from fdai.shared.providers.self_health import SelfHealthExporterUnavailableError
from fdai.shared.providers.stage_publisher import (
    ObservationSource,
    StageEvent,
    StageName,
    StagePhase,
)
from fdai.shared.providers.testing import RecordingStagePublisher

NOW = datetime(2026, 10, 20, tzinfo=UTC)


def event(stage, *, key="example", tier="t0", phase=StagePhase.DONE, **changes):
    return StageEvent(
        event_id=key,
        correlation_id=changes.pop("correlation_id", key),
        stage=stage,
        phase=phase,
        source=changes.pop("source", ObservationSource.RUNTIME_OBSERVED),
        detail=changes.pop("detail", {"tier": tier}),
        error="example stage failure" if phase is StagePhase.FAILED else None,
        **changes,
    )


def fixture(*, capacity=4096):
    clock = SimpleNamespace(tick=0)
    source = RuntimeEventLagSource(
        metric="fdai.event.lag_seconds",
        maximum_age_seconds=60,
        capacity=capacity,
        ticks=lambda: clock.tick,
    )
    publisher = RecordingStagePublisher()
    wrapped = source.wrap(publisher)
    return clock, source, publisher, wrapped


@pytest.mark.parametrize("tier", ["t0", "t1", "t2"])
async def test_exact_first_tier_duration_and_original_publication(tier):
    clock, source, publisher, wrapped = fixture()
    ingress = event(StageName.INGEST)
    decision = event(StageName.VERIFY, tier=tier)
    await wrapped.emit(ingress)
    clock.tick = 5_000_000_001
    await wrapped.emit(decision)
    with localcontext() as context:
        context.prec = 1
        sample = await source.observe(now=NOW)
    assert sample.value == Decimal("5.000000001")
    assert sample.observed_at == NOW
    assert sample.source == source.exporter_id
    assert publisher.events == (ingress, decision)


async def test_route_selection_does_not_finish_a_pending_decision():
    clock, source, _, wrapped = fixture()
    await wrapped.emit(event(StageName.INGEST))
    clock.tick = 1_000_000_000
    await wrapped.emit(event(StageName.ROUTE))
    clock.tick = 6_000_000_000
    assert (await source.observe(now=NOW)).value == 6


async def test_fast_sibling_never_hides_a_stalled_event_and_duplicate_keeps_oldest_start():
    clock, source, _, wrapped = fixture()
    await wrapped.emit(event(StageName.INGEST, key="slow"))
    clock.tick = 4_000_000_000
    await wrapped.emit(event(StageName.INGEST, key="slow"))
    await wrapped.emit(event(StageName.INGEST, key="fast"))
    clock.tick = 4_100_000_000
    await wrapped.emit(event(StageName.VERIFY, key="fast"))
    clock.tick = 8_000_000_000
    assert (await source.observe(now=NOW)).value == 8


async def test_duplicate_or_later_tier_cannot_renew_a_completed_sample():
    clock, source, _, wrapped = fixture()
    await wrapped.emit(event(StageName.INGEST))
    clock.tick = 2_000_000_000
    await wrapped.emit(event(StageName.VERIFY))
    clock.tick = 20_000_000_000
    await wrapped.emit(event(StageName.INGEST))
    await wrapped.emit(event(StageName.VERIFY, tier="t2"))
    assert (await source.observe(now=NOW)).value == 2
    clock.tick = 62_000_000_001
    with pytest.raises(SelfHealthExporterUnavailableError) as failure:
        await source.observe(now=NOW)
    assert failure.value.reason == "source_stale"


@pytest.mark.parametrize("source_kind", [ObservationSource.REPLAY, ObservationSource.SYNTHETIC_DEV])
async def test_untrusted_stage_cannot_produce_a_health_sample(source_kind):
    _, source, publisher, wrapped = fixture()
    value = event(StageName.INGEST, source=source_kind)
    await wrapped.emit(value)
    with pytest.raises(SelfHealthExporterUnavailableError) as failure:
        await source.observe(now=NOW)
    assert failure.value.reason == "source_incomplete"
    assert publisher.events == (value,)


@pytest.mark.parametrize("failure", ["missing-ingest", "correlation", "terminal", "failed"])
async def test_incomplete_observation_never_falls_back_to_an_older_healthy_sample(failure):
    clock, source, _, wrapped = fixture()
    await wrapped.emit(event(StageName.INGEST))
    clock.tick = 1
    await wrapped.emit(event(StageName.VERIFY))
    if failure == "missing-ingest":
        await wrapped.emit(event(StageName.VERIFY, key="unseen"))
    else:
        await wrapped.emit(event(StageName.INGEST, key="pending"))
        if failure == "correlation":
            await wrapped.emit(event(StageName.VERIFY, key="pending", correlation_id="other"))
        elif failure == "terminal":
            await wrapped.emit(event(StageName.AUDIT, key="pending"))
        else:
            await wrapped.emit(event(StageName.VERIFY, key="pending", phase=StagePhase.FAILED))
    with pytest.raises(SelfHealthExporterUnavailableError) as unavailable:
        await source.observe(now=NOW)
    assert unavailable.value.reason == "source_incomplete"


async def test_synthetic_canary_is_not_a_tier_decision_or_an_unfinished_user_event():
    clock, source, _, wrapped = fixture()
    await wrapped.emit(event(StageName.INGEST, detail={"event_type": "fdai.control.canary"}))
    clock.tick = 100_000_000_000
    await wrapped.emit(event(StageName.ROUTE))
    await wrapped.emit(event(StageName.AUDIT))
    with pytest.raises(SelfHealthExporterUnavailableError) as failure:
        await source.observe(now=NOW)
    assert failure.value.reason == "source_missing"
    await wrapped.emit(event(StageName.INGEST, key="normal"))
    clock.tick += 1
    await wrapped.emit(event(StageName.VERIFY, key="normal"))
    assert (await source.observe(now=NOW)).value == Decimal("0.000000001")


@pytest.mark.parametrize("overflow", ["pending", "completed", "canary"])
async def test_each_bounded_state_overflow_remains_unavailable(overflow):
    clock, source, _, wrapped = fixture(capacity=1)
    for key in ("first", "second"):
        detail = {"event_type": "fdai.control.canary"} if overflow == "canary" else {}
        await wrapped.emit(event(StageName.INGEST, key=key, detail=detail))
        if overflow == "completed":
            clock.tick += 1
            await wrapped.emit(event(StageName.VERIFY, key=key))
    clock.tick += 100_000_000_000
    with pytest.raises(SelfHealthExporterUnavailableError):
        await source.observe(now=NOW)


async def test_clock_regression_does_not_recover_into_a_success_shaped_value():
    clock, source, _, wrapped = fixture()
    await wrapped.emit(event(StageName.INGEST))
    clock.tick = 10
    await wrapped.emit(event(StageName.VERIFY))
    clock.tick = 9
    with pytest.raises(SelfHealthExporterUnavailableError):
        await source.observe(now=NOW)
    clock.tick = 100
    with pytest.raises(SelfHealthExporterUnavailableError):
        await source.observe(now=NOW)


async def test_shutdown_and_multiple_bindings_deny_but_keep_original_publisher_behavior():
    _, source, publisher, wrapped = fixture()
    source.wrap(publisher)
    await wrapped.emit(event(StageName.INGEST))
    with pytest.raises(SelfHealthExporterUnavailableError):
        await source.observe(now=NOW)
    source.close()
    terminal = event(StageName.AUDIT)
    await wrapped.emit(terminal)
    assert publisher.events[-1] == terminal
    with pytest.raises(SelfHealthExporterUnavailableError):
        await source.observe(now=NOW)


async def test_original_publisher_exception_is_not_swallowed():
    _, source, _, _ = fixture()
    source = RuntimeEventLagSource(metric="fdai.event.lag_seconds", maximum_age_seconds=60)
    publisher = AsyncMock()
    publisher.emit.side_effect = OSError("example publisher failure")
    wrapped = source.wrap(publisher)
    with pytest.raises(OSError, match="publisher failure"):
        await wrapped.emit(event(StageName.INGEST))


async def test_unbound_source_empty_observation_and_naive_clock_are_explicit():
    source = RuntimeEventLagSource(metric="fdai.event.lag_seconds", maximum_age_seconds=60)
    with pytest.raises(SelfHealthExporterUnavailableError):
        await source.observe(now=NOW)
    source.wrap(RecordingStagePublisher())
    with pytest.raises(SelfHealthExporterUnavailableError) as failure:
        await source.observe(now=NOW)
    assert failure.value.reason == "source_missing"
    with pytest.raises(ValueError, match="aware timestamp"):
        await source.observe(now=NOW.replace(tzinfo=None))


@pytest.mark.parametrize("age,capacity", [(0, 1), (86401, 1), (60, 0), (60, 100001)])
def test_invalid_bounds_are_not_silently_normalized(age, capacity):
    with pytest.raises(ValueError, match="bounds are invalid"):
        RuntimeEventLagSource(
            metric="fdai.event.lag_seconds", maximum_age_seconds=age, capacity=capacity
        )


async def test_real_control_loop_t1_decision_is_observed_without_changing_stages(tmp_path):
    from fdai.core.tiers.t1_lightweight.testing import (
        DeterministicEmbeddingModel,
        InMemoryPatternLibrary,
    )
    from fdai.core.tiers.t1_lightweight.tier import T1Tier

    from tests.core.test_control_loop_stage_events import _event_dict, _make_loop

    _, source, publisher, wrapped = fixture()
    loop = _make_loop(
        stage_publisher=wrapped,
        t1_engine=T1Tier(
            embedding_model=DeterministicEmbeddingModel(), pattern_library=InMemoryPatternLibrary()
        ),
        tmp_path=tmp_path,
    )
    await loop.process(_event_dict("actual-lag-test"))
    assert any(
        value.stage is StageName.VERIFY and value.detail.get("tier") == "t1"
        for value in publisher.events
    )
    assert (await source.observe(now=NOW)).value == 0
    assert not source._pending


async def test_normal_binding_collects_that_same_source_and_shutdown_retires_it(app_config):
    from fdai.composition import default_container
    from fdai.core.readiness.self_health_runtime import SelfHealthRuntimeMonitor
    from fdai.delivery.self_health_sources import runtime_self_health_registry
    from fdai.runtime.bootstrap_messaging import MessagingRuntime
    from fdai.runtime.bootstrap_readiness import build_runtime_self_health_bindings
    from fdai.runtime.bootstrap_resources import RuntimeResources
    from fdai.shared.providers.local.event_bus import LocalEventBus
    from fdai.shared.providers.testing.state_store import InMemoryStateStore
    from fdai.shared.streaming.stage_publisher import EventBusStagePublisher

    resources = RuntimeResources()
    bus = LocalEventBus()
    publisher = EventBusStagePublisher(bus, topic="example.stages")
    resources.messaging = MessagingRuntime(bus, None, bus, publisher)
    bindings = build_runtime_self_health_bindings(
        default_container(app_config), resources=resources
    )
    assert bindings.event_lag_source is resources.event_lag_source
    assert bindings.stage_publisher is not publisher
    assert bindings.collector_sources["event_lag_source"] is bindings.event_lag_source
    await bindings.stage_publisher.emit(event(StageName.INGEST))
    await bindings.stage_publisher.emit(event(StageName.VERIFY))
    store = InMemoryStateStore()
    registry = runtime_self_health_registry(
        catalog=bindings.catalog,
        store=store,
        readiness=lambda now: False,
        event_lag_source=bindings.event_lag_source,
    )
    monitor = SelfHealthRuntimeMonitor(registry=registry, store=store)
    await monitor.collect_and_persist(now=NOW)
    record = await store.read_state("runtime:operational-state")
    state = next(
        signal
        for signal in record["snapshot"]["self_health"]["signals"]
        if signal["signal"] == "event_lag"
    )
    assert state["exporter_id"] == bindings.event_lag_source.exporter_id
    assert state["status"] == "healthy"
    assert record["snapshot"]["execution_authority"] is False
    await resources.close()
    with pytest.raises(SelfHealthExporterUnavailableError):
        await bindings.event_lag_source.observe(now=NOW)


async def test_no_tier_decision_in_real_abstain_path_is_not_a_false_latency_success(tmp_path):
    from tests.core.test_control_loop_stage_events import _event_dict, _make_loop

    _, source, publisher, wrapped = fixture()
    loop = _make_loop(stage_publisher=wrapped, tmp_path=tmp_path)
    await loop.process(_event_dict("actual-no-decision"))
    assert publisher.events[-1].stage is StageName.AUDIT
    with pytest.raises(SelfHealthExporterUnavailableError) as failure:
        await source.observe(now=NOW)
    assert failure.value.reason == "source_incomplete"


async def test_unrecognized_tier_detail_does_not_abort_or_finish_the_original_pipeline():
    clock, source, publisher, wrapped = fixture()
    await wrapped.emit(event(StageName.INGEST))
    value = event(StageName.VERIFY, detail={"tier": ["injected"]})
    await wrapped.emit(value)
    clock.tick = 6_000_000_000
    assert publisher.events[-1] == value
    assert (await source.observe(now=NOW)).value == 6


async def test_completed_window_keeps_largest_latency_and_retains_no_raw_event_body():
    clock, source, _, wrapped = fixture()
    await wrapped.emit(
        event(
            StageName.INGEST,
            key="synthetic-private-event-identity",
            detail={"text": "synthetic-private-body-not-for-health"},
        )
    )
    assert all(isinstance(key, bytes) and len(key) == 32 for key in source._pending)
    clock.tick = 7_000_000_000
    await wrapped.emit(event(StageName.VERIFY, key="synthetic-private-event-identity"))
    await wrapped.emit(event(StageName.INGEST, key="fast"))
    clock.tick += 1
    await wrapped.emit(event(StageName.VERIFY, key="fast"))
    assert (await source.observe(now=NOW)).value == 7
    retained = repr(vars(source))
    assert "synthetic-private-event-identity" not in retained
    assert "synthetic-private-body-not-for-health" not in retained
