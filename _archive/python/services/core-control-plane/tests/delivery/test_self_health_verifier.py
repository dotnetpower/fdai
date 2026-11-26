"""Verify actual-call accounting without creating operational outcome evidence."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, Inexact, localcontext

import pytest
from fdai.core.quality_gate.gate import QualityCandidate
from fdai.delivery.self_health_verifier import RuntimeVerifierHealthSource
from fdai.shared.providers.self_health import SelfHealthExporterUnavailableError


@dataclass
class Clock:
    seconds: int = 0

    def now(self) -> datetime:
        return datetime(2026, 10, 19, tzinfo=UTC) + timedelta(seconds=self.seconds)

    def ticks(self) -> int:
        return self.seconds * 1_000_000_000


@dataclass
class Verifier:
    result: bool | None = True
    failure: BaseException | None = None
    calls: int = 0

    def verify(self, candidate: QualityCandidate) -> bool | None:
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        return self.result


def source(clock: Clock) -> RuntimeVerifierHealthSource:
    return RuntimeVerifierHealthSource(
        metric="fdai.verifier.failure_rate", window_seconds=300, clock=clock.now, ticks=clock.ticks
    )


def candidate() -> QualityCandidate:
    return QualityCandidate("example.action", "example/resource", {}, ())


async def unavailable(health: RuntimeVerifierHealthSource, clock: Clock, reason: str) -> None:
    with pytest.raises(SelfHealthExporterUnavailableError) as raised:
        await health.observe(now=clock.now())
    assert raised.value.reason == reason


async def test_missing_unobserved_warmup_and_empty_windows_are_unavailable() -> None:
    clock = Clock()
    health = source(clock)
    await unavailable(health, clock, "source_missing")
    observed = health.bind(Verifier())
    await unavailable(health, clock, "source_incomplete")
    clock.seconds = 300
    await unavailable(health, clock, "source_incomplete")
    assert observed.verify(candidate()) is True
    await unavailable(health, clock, "source_incomplete")


async def test_actual_tri_state_results_have_exact_denominator_and_no_recollection() -> None:
    clock = Clock()
    health = source(clock)
    verifier = Verifier()
    observed = health.bind(verifier)
    for result in (True, False, None):
        clock.seconds += 1
        verifier.result = result
        assert observed.verify(candidate()) is result
    clock.seconds = 300
    sample = await health.observe(now=clock.now())
    assert sample.value > Decimal("0.66")
    assert health.latest_window is not None
    assert health.latest_window.completed == 3
    assert health.latest_window.rejected_or_abstained == 2
    clock.seconds = 301
    repeated = await health.observe(now=clock.now())
    assert repeated == sample
    assert sample.observed_at == datetime(2026, 10, 19, 0, 0, 3, tzinfo=UTC)
    assert verifier.calls == 3


async def test_exception_propagates_and_invalidates_whole_completed_window() -> None:
    clock = Clock()
    health = source(clock)
    verifier = Verifier()
    observed = health.bind(verifier)
    assert observed.verify(candidate()) is True
    verifier.failure = RuntimeError("test verification failure")
    with pytest.raises(RuntimeError, match="test verification failure"):
        observed.verify(candidate())
    clock.seconds = 300
    await unavailable(health, clock, "source_incomplete")
    verifier.failure = None
    assert observed.verify(candidate()) is True
    clock.seconds = 600
    assert (await health.observe(now=clock.now())).value == 0


async def test_idle_gap_restart_close_and_duplicate_binding_cannot_reuse_success() -> None:
    clock = Clock()
    health = source(clock)
    observed = health.bind(Verifier())
    observed.verify(candidate())
    clock.seconds = 300
    await health.observe(now=clock.now())
    clock.seconds = 900
    await unavailable(health, clock, "source_incomplete")
    restarted = source(clock)
    restarted.bind(Verifier())
    await unavailable(restarted, clock, "source_incomplete")
    restarted.bind(Verifier())
    await unavailable(restarted, clock, "source_incomplete")
    health.close()
    await unavailable(health, clock, "source_missing")


async def test_monotonic_regression_is_explicit_and_never_refreshes_old_rate() -> None:
    clock = Clock()
    health = source(clock)
    observed = health.bind(Verifier())
    observed.verify(candidate())
    clock.seconds = 300
    await health.observe(now=clock.now())
    clock.seconds = 299
    await unavailable(health, clock, "source_malformed")


async def test_rate_is_independent_of_callers_decimal_context() -> None:
    clock = Clock()
    health = source(clock)
    verifier = Verifier()
    observed = health.bind(verifier)
    for result in (False, True, True):
        verifier.result = result
        observed.verify(candidate())
    clock.seconds = 300
    with localcontext() as context:
        context.prec = 1
        context.traps[Inexact] = True
        sample = await health.observe(now=clock.now())
    assert Decimal("0.33333333333333333333") < sample.value < Decimal("0.33333333333333333334")


async def test_incomplete_current_window_cannot_reexpose_previous_healthy_rate() -> None:
    clock = Clock()
    health = source(clock)
    verifier = Verifier()
    observed = health.bind(verifier)
    observed.verify(candidate())
    clock.seconds = 300
    assert (await health.observe(now=clock.now())).value == 0
    clock.seconds = 301
    verifier.failure = RuntimeError("unknown result")
    with pytest.raises(RuntimeError, match="unknown result"):
        observed.verify(candidate())
    await unavailable(health, clock, "source_incomplete")


@pytest.mark.parametrize("seconds", [0, 86_401])
def test_invalid_observation_window_is_rejected(seconds: int) -> None:
    with pytest.raises(ValueError, match="observation window"):
        RuntimeVerifierHealthSource(metric="fdai.verifier.failure_rate", window_seconds=seconds)


@pytest.mark.parametrize("clock_fault", ["unreachable", "naive"])
async def test_recording_clock_failure_preserves_verifier_result_and_holds_health(
    monkeypatch, caplog, clock_fault: str
) -> None:
    clock = Clock()
    health = source(clock)
    observed = health.bind(Verifier())

    def failed_clock() -> datetime:
        if clock_fault == "unreachable":
            raise OSError("private clock detail")
        return datetime(2026, 10, 19)

    monkeypatch.setattr(health, "_clock", failed_clock)
    assert observed.verify(candidate()) is True
    await unavailable(health, clock, "source_malformed")
    assert "private clock detail" not in caplog.text


async def test_collection_clock_failure_and_closed_source_are_explicit(monkeypatch) -> None:
    clock = Clock()
    health = source(clock)
    verifier = Verifier()
    observed = health.bind(verifier)

    def failed_ticks() -> int:
        raise OSError("private clock detail")

    monkeypatch.setattr(health, "_ticks", failed_ticks)
    await unavailable(health, clock, "source_unreachable")
    health.close()
    assert observed.verify(candidate()) is True
    assert verifier.calls == 1
    assert health.latest_window is None


async def test_cancelled_verification_propagates_without_an_invented_outcome() -> None:
    clock = Clock()
    health = source(clock)
    observed = health.bind(Verifier(failure=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        observed.verify(candidate())
    clock.seconds = 300
    await unavailable(health, clock, "source_incomplete")


async def test_concurrent_gate_entries_count_calls_not_distinct_operational_episodes() -> None:
    clock = Clock()
    health = source(clock)
    verifier = Verifier(result=None)
    observed = health.bind(verifier)

    async def invoke() -> None:
        await asyncio.sleep(0)
        assert observed.verify(candidate()) is None

    await asyncio.gather(*(invoke() for _ in range(20)))
    clock.seconds = 300
    assert (await health.observe(now=clock.now())).value == 1
    assert health.latest_window is not None
    assert health.latest_window.completed == verifier.calls == 20


@pytest.mark.parametrize(
    ("failed", "total", "above_threshold"), [(0, 1, False), (1, 20, False), (1, 19, True)]
)
async def test_exact_existing_five_percent_policy_boundary(
    failed: int, total: int, above_threshold: bool
) -> None:
    clock = Clock()
    health = source(clock)
    verifier = Verifier()
    observed = health.bind(verifier)
    for index in range(total):
        verifier.result = index >= failed
        observed.verify(candidate())
    clock.seconds = 300
    sample = await health.observe(now=clock.now())
    assert (sample.value > Decimal("0.05")) is above_threshold


@pytest.mark.parametrize(
    ("recording_offset", "fresh", "reason"),
    [(0, True, None), (302, False, "observation_stale"), (-2, False, "observation_from_future")],
)
async def test_production_gate_and_readiness_share_the_actual_verifier_source(
    app_config, recording_offset: int, fresh: bool, reason: str | None
) -> None:
    from unittest.mock import MagicMock

    from fdai.composition import default_container
    from fdai.core.quality_gate.promotion import ActionModeSource
    from fdai.delivery.startup_probe import StaticStartupProbe
    from fdai.runtime.bootstrap_readiness import load_runtime_self_health_catalog
    from fdai.runtime.bootstrap_resources import RuntimeResources
    from fdai.runtime.control_loop_auxiliary import build_t2_quality_gate
    from fdai.runtime.readiness import build_startup_readiness_runtime
    from fdai.shared.providers.local.event_bus import LocalEventBus
    from fdai.shared.providers.local.identity import LocalWorkloadIdentity
    from fdai.shared.providers.testing.state_store import InMemoryStateStore
    from fdai_service_contracts.self_health import (
        OperationalStateSnapshotV1,
        SelfHealthSignalName,
        SelfHealthSignalStatus,
    )

    class Embedding:
        async def embed(self, text: str) -> list[float]:
            return [0.1, 0.2]

    clock = Clock()
    catalog = load_runtime_self_health_catalog()
    policy = catalog.policies[SelfHealthSignalName.VERIFIER_FAILURE_RATE]
    health = RuntimeVerifierHealthSource(
        metric=policy.metric,
        window_seconds=policy.maximum_age_seconds,
        clock=clock.now,
        ticks=clock.ticks,
    )
    container = default_container(app_config)
    modes = MagicMock(spec=ActionModeSource)
    baseline = build_t2_quality_gate(
        container, rules_by_id={}, action_modes=modes, deterministic_evidence_verifiers=None
    )
    instrumented = build_t2_quality_gate(
        container,
        rules_by_id={},
        action_modes=modes,
        deterministic_evidence_verifiers=None,
        verifier_health_source=health,
    )
    before = await baseline.evaluate(candidate())
    clock.seconds = 299
    after = await instrumented.evaluate(candidate())
    assert (before.outcome, before.reasons) == (after.outcome, after.reasons)
    clock.seconds = 300
    store = InMemoryStateStore()
    runtime = build_startup_readiness_runtime(
        state_store=store,
        event_bus=LocalEventBus(),
        transition_event_bus=LocalEventBus(),
        event_validator=container.event_validator,
        identity=LocalWorkloadIdentity(),
        embedding_model=Embedding(),
        policy_compile_probe=StaticStartupProbe(probe_id="policy.compile", evidence_key="compiled"),
        environment={},
        self_health_catalog=catalog,
        verifier_health_source=health,
    )
    assert runtime.self_health_monitor is not None
    await runtime.self_health_monitor.collect_and_persist(
        now=clock.now() + timedelta(seconds=recording_offset)
    )
    persisted = await store.read_state("runtime:operational-state")
    assert persisted is not None
    snapshot = OperationalStateSnapshotV1.model_validate(persisted["snapshot"])
    observed = next(
        item
        for item in snapshot.self_health.signals
        if item.signal is SelfHealthSignalName.VERIFIER_FAILURE_RATE
    )
    assert observed.value == 1
    assert observed.status is SelfHealthSignalStatus.ALERT
    assert observed.observed_at == datetime(2026, 10, 19, 0, 4, 59, tzinfo=UTC)
    assert observed.fresh is fresh
    if reason is not None:
        assert observed.reason == reason
    assert not observed.execution_authority
    await RuntimeResources(verifier_health_source=health).close()
    await unavailable(health, clock, "source_missing")
