"""Runtime startup readiness composition and recovery tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.core.readiness import (
    AuthorityCeiling,
    ProbeStatus,
    ReadinessDecision,
    StartupProbeResult,
    StartupReadinessReport,
)
from fdai.delivery.startup_probe import StaticStartupProbe
from fdai.runtime.readiness import (
    RuntimeReadinessState,
    StartupReadinessRuntime,
    build_startup_readiness_runtime,
)
from fdai.shared.providers.event_bus import PublishReceipt
from fdai.shared.providers.local.event_bus import LocalEventBus
from fdai.shared.providers.local.identity import LocalWorkloadIdentity
from fdai.shared.providers.testing.state_store import InMemoryStateStore


class _RecordingBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, dict[str, Any]]] = []

    async def publish(self, topic: str, key: str, payload: dict[str, Any]) -> PublishReceipt:
        self.published.append((topic, key, payload))
        return PublishReceipt(topic=topic, partition=0, offset=0)


class _Validator:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def validate(self, instance: dict[str, Any]) -> None:
        self.payloads.append(instance)


class _Embedding:
    async def embed(self, text: str) -> list[float]:
        return [0.1, 0.2]


def _policy_probe() -> StaticStartupProbe:
    return StaticStartupProbe(probe_id="policy.compile", evidence_key="compiled")


class _CrossCheck:
    def __init__(self) -> None:
        self.calls = 0

    async def propose(self, candidate: Any) -> tuple[str, dict[str, int]]:
        self.calls += 1
        return "startup-readiness-probe", {"sample": self.calls}


class _CrossCheckPool:
    def __init__(self, candidates: tuple[_CrossCheck, ...]) -> None:
        self._candidates = candidates

    def startup_candidates(self) -> tuple[_CrossCheck, ...]:
        return self._candidates

    async def propose(self, candidate: Any) -> tuple[str, dict[str, int]]:
        return await self._candidates[0].propose(candidate)


async def test_standard_runtime_inventory_reaches_ready_and_persists_report() -> None:
    store = InMemoryStateStore()
    validator = _Validator()
    runtime = build_startup_readiness_runtime(
        state_store=store,
        event_bus=LocalEventBus(),
        transition_event_bus=LocalEventBus(),
        event_validator=validator,  # type: ignore[arg-type]
        identity=LocalWorkloadIdentity(),
        embedding_model=_Embedding(),
        policy_compile_probe=_policy_probe(),
        environment={"FDAI_STARTUP_KAFKA_SETTLE_SECONDS": "0"},
    )

    report = await runtime.evaluate()

    assert report.decision is ReadinessDecision.READY
    assert len(report.results) == 11
    assert runtime.state.is_ready()
    persisted = await store.read_state("runtime:startup-readiness:latest")
    assert persisted is not None
    assert persisted["decision"] == "ready"
    assert len(validator.payloads) == 1
    assert any(
        entry.get("entry", {}).get("kind") == "startup_readiness.transition"
        for entry in store.audit_entries
    )


async def test_readiness_transitions_publish_on_the_transition_bus_not_the_probe_bus() -> None:
    transition_bus = _RecordingBus()
    runtime = build_startup_readiness_runtime(
        state_store=InMemoryStateStore(),
        event_bus=LocalEventBus(),
        transition_event_bus=transition_bus,  # type: ignore[arg-type]
        event_validator=_Validator(),  # type: ignore[arg-type]
        identity=LocalWorkloadIdentity(),
        embedding_model=_Embedding(),
        policy_compile_probe=_policy_probe(),
        environment={"FDAI_STARTUP_KAFKA_SETTLE_SECONDS": "0"},
    )

    await runtime.evaluate()

    assert [topic for topic, _key, _payload in transition_bus.published] == [
        "runtime.readiness.transitions"
    ]


async def test_runtime_probes_every_candidate_inside_cross_check_pool() -> None:
    candidates = (_CrossCheck(), _CrossCheck())
    runtime = build_startup_readiness_runtime(
        state_store=InMemoryStateStore(),
        event_bus=LocalEventBus(),
        transition_event_bus=LocalEventBus(),
        event_validator=_Validator(),  # type: ignore[arg-type]
        identity=LocalWorkloadIdentity(),
        embedding_model=_Embedding(),
        policy_compile_probe=_policy_probe(),
        cross_check_models=(_CrossCheckPool(candidates),),
        environment={"FDAI_STARTUP_KAFKA_SETTLE_SECONDS": "0"},
    )

    report = await runtime.evaluate()

    assert report.decision is ReadinessDecision.READY
    assert [candidate.calls for candidate in candidates] == [2, 2]
    assert len(report.results) == 13


async def test_audit_chain_timeout_degrades_and_disables_autonomous_action() -> None:
    class _SlowAuditStore(InMemoryStateStore):
        async def verify_chain(self) -> bool:
            await asyncio.Event().wait()
            return True

    runtime = build_startup_readiness_runtime(
        state_store=_SlowAuditStore(),
        event_bus=LocalEventBus(),
        transition_event_bus=LocalEventBus(),
        event_validator=_Validator(),  # type: ignore[arg-type]
        identity=LocalWorkloadIdentity(),
        embedding_model=_Embedding(),
        policy_compile_probe=_policy_probe(),
        environment={
            "FDAI_STARTUP_KAFKA_SETTLE_SECONDS": "0",
            "FDAI_STARTUP_PROBE_TIMEOUT_SECONDS": "0.001",
            "FDAI_STARTUP_PHASE_TIMEOUT_SECONDS": "0.01",
            "FDAI_STARTUP_PROBE_RETRIES": "0",
        },
    )

    report = await runtime.evaluate()

    assert report.decision is ReadinessDecision.DEGRADED
    assert runtime.state.is_ready()
    assert report.authority_ceilings["autonomous-action"] is AuthorityCeiling.SHADOW
    audit_result = next(result for result in report.results if result.probe_id == "audit.chain")
    assert audit_result.failure_class == "probe_deadline_exceeded"


def test_expired_evidence_closes_runtime_readiness() -> None:
    now = datetime(2026, 7, 23, tzinfo=UTC)
    result = StartupProbeResult(
        probe_id="audit",
        status=ProbeStatus.PASSED,
        observed_at=now - timedelta(minutes=2),
        expires_at=now + timedelta(seconds=1),
        latency_ms=1,
    )
    state = RuntimeReadinessState(
        report=StartupReadinessReport(
            generated_at=now,
            decision=ReadinessDecision.READY,
            results=(result,),
            authority_ceilings={"audit": AuthorityCeiling.DEPLOYMENT},
        )
    )

    assert state.is_ready(now=now)
    assert not state.is_ready(now=now + timedelta(seconds=1))


async def test_waiting_processing_gate_opens_after_recovery() -> None:
    now = datetime.now(UTC)
    blocked = StartupReadinessReport(
        generated_at=now,
        decision=ReadinessDecision.BLOCKED,
        results=(),
        missing_probe_ids=("postgres",),
    )
    ready = StartupReadinessReport(
        generated_at=now,
        decision=ReadinessDecision.READY,
        results=(
            StartupProbeResult(
                probe_id="postgres",
                status=ProbeStatus.PASSED,
                observed_at=now,
                expires_at=now + timedelta(minutes=5),
                latency_ms=1,
            ),
        ),
    )
    state = RuntimeReadinessState()
    state.update(blocked)
    stop = asyncio.Event()
    waiting = asyncio.create_task(state.wait_until_ready(stop))
    await asyncio.sleep(0)

    state.update(ready)

    assert await waiting is True


async def test_refresh_survives_transient_evaluation_failure_and_recovers(
    caplog: pytest.LogCaptureFixture,
) -> None:
    stop = asyncio.Event()
    first_attempt_finished = asyncio.Event()
    allow_recovery = asyncio.Event()
    now = datetime.now(UTC)

    class _Coordinator:
        def __init__(self) -> None:
            self.calls = 0

        async def evaluate(self) -> StartupReadinessReport:
            self.calls += 1
            if self.calls == 1:
                first_attempt_finished.set()
                raise ConnectionError("state store unavailable")
            await allow_recovery.wait()
            stop.set()
            return StartupReadinessReport(
                generated_at=now,
                decision=ReadinessDecision.READY,
                results=(
                    StartupProbeResult(
                        probe_id="postgres",
                        status=ProbeStatus.PASSED,
                        observed_at=now,
                        expires_at=now + timedelta(minutes=5),
                        latency_ms=1,
                    ),
                ),
            )

    coordinator = _Coordinator()
    runtime = StartupReadinessRuntime(
        coordinator=coordinator,  # type: ignore[arg-type]
        state=RuntimeReadinessState(),
        refresh_interval_seconds=0.001,
    )
    caplog.set_level("WARNING", logger="fdai.startup")

    refresh = asyncio.create_task(runtime.refresh_until_stopped(stop))
    await first_attempt_finished.wait()
    while "startup_readiness_refresh_failed" not in caplog.messages:
        await asyncio.sleep(0)

    assert runtime.state.refresh_failed is True
    assert runtime.state._blocked_event.is_set()
    assert not runtime.state.is_ready(now=now)

    allow_recovery.set()
    await asyncio.wait_for(refresh, timeout=0.5)

    assert coordinator.calls == 2
    assert runtime.state.refresh_failed is False
    assert runtime.state.is_ready(now=now)
    assert "startup_readiness_refresh_failed" in caplog.messages
    failure_record = next(
        record for record in caplog.records if record.message == "startup_readiness_refresh_failed"
    )
    assert failure_record.error_type == "ConnectionError"  # type: ignore[attr-defined]
    assert "state store unavailable" not in caplog.text


async def test_refresh_propagates_programming_error_after_closing_readiness() -> None:
    class _Coordinator:
        async def evaluate(self) -> StartupReadinessReport:
            raise AttributeError("broken coordinator")

    runtime = StartupReadinessRuntime(
        coordinator=_Coordinator(),  # type: ignore[arg-type]
        state=RuntimeReadinessState(),
        refresh_interval_seconds=0.001,
    )

    with pytest.raises(AttributeError, match="broken coordinator"):
        await runtime.refresh_until_stopped(asyncio.Event())

    assert runtime.state.refresh_failed is True
    assert runtime.state._blocked_event.is_set()


async def test_refresh_closes_running_operation_at_evidence_expiry() -> None:
    now = datetime.now(UTC)
    cancelled = asyncio.Event()
    evaluation_started = asyncio.Event()
    stop = asyncio.Event()

    class _Coordinator:
        async def evaluate(self) -> StartupReadinessReport:
            evaluation_started.set()
            await stop.wait()
            return StartupReadinessReport(
                generated_at=now,
                decision=ReadinessDecision.BLOCKED,
                results=(),
            )

    runtime = StartupReadinessRuntime(
        coordinator=_Coordinator(),  # type: ignore[arg-type]
        state=RuntimeReadinessState(
            report=StartupReadinessReport(
                generated_at=now,
                decision=ReadinessDecision.READY,
                results=(
                    StartupProbeResult(
                        probe_id="postgres",
                        status=ProbeStatus.PASSED,
                        observed_at=now,
                        expires_at=now + timedelta(milliseconds=20),
                        latency_ms=1,
                    ),
                ),
            )
        ),
        refresh_interval_seconds=60,
    )

    async def operation() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    guarded = asyncio.create_task(runtime.run_when_ready(stop, operation))
    refresh = asyncio.create_task(runtime.refresh_until_stopped(stop))

    await asyncio.wait_for(evaluation_started.wait(), timeout=0.5)
    await asyncio.wait_for(cancelled.wait(), timeout=0.5)
    assert runtime.state._blocked_event.is_set()
    assert not runtime.state.is_ready()

    stop.set()
    await asyncio.gather(guarded, refresh)


async def test_guarded_operation_is_not_created_before_readiness() -> None:
    store = InMemoryStateStore()
    runtime = build_startup_readiness_runtime(
        state_store=store,
        event_bus=LocalEventBus(),
        transition_event_bus=LocalEventBus(),
        event_validator=_Validator(),  # type: ignore[arg-type]
        identity=LocalWorkloadIdentity(),
        embedding_model=_Embedding(),
        policy_compile_probe=_policy_probe(),
        environment={"FDAI_STARTUP_KAFKA_SETTLE_SECONDS": "0"},
    )
    started = False
    stop = asyncio.Event()

    async def operation() -> None:
        nonlocal started
        started = True

    guarded = asyncio.create_task(runtime.run_when_ready(stop, operation))
    await asyncio.sleep(0)
    assert started is False

    await runtime.evaluate()
    await guarded

    assert started is True


async def test_guarded_operation_is_cancelled_on_blocker_and_restarts() -> None:
    now = datetime.now(UTC)
    state = RuntimeReadinessState()
    store = InMemoryStateStore()
    runtime = build_startup_readiness_runtime(
        state_store=store,
        event_bus=LocalEventBus(),
        transition_event_bus=LocalEventBus(),
        event_validator=_Validator(),  # type: ignore[arg-type]
        identity=LocalWorkloadIdentity(),
        embedding_model=_Embedding(),
        policy_compile_probe=_policy_probe(),
        environment={"FDAI_STARTUP_KAFKA_SETTLE_SECONDS": "0"},
    )
    object.__setattr__(runtime, "state", state)
    stop = asyncio.Event()
    starts = 0

    async def operation() -> None:
        nonlocal starts
        starts += 1
        await asyncio.Event().wait()

    ready_result = StartupProbeResult(
        probe_id="postgres",
        status=ProbeStatus.PASSED,
        observed_at=now,
        expires_at=now + timedelta(minutes=5),
        latency_ms=1,
    )
    state.update(
        StartupReadinessReport(
            generated_at=now,
            decision=ReadinessDecision.READY,
            results=(ready_result,),
        )
    )
    guarded = asyncio.create_task(runtime.run_when_ready(stop, operation))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert starts == 1

    state.update(
        StartupReadinessReport(
            generated_at=now,
            decision=ReadinessDecision.BLOCKED,
            results=(),
            missing_probe_ids=("postgres",),
        )
    )
    await asyncio.sleep(0)
    state.update(
        StartupReadinessReport(
            generated_at=now,
            decision=ReadinessDecision.READY,
            results=(ready_result,),
        )
    )
    for _ in range(5):
        await asyncio.sleep(0)
        if starts == 2:
            break
    stop.set()
    await guarded

    assert starts == 2


async def test_guarded_operation_is_drained_when_the_supervisor_is_cancelled() -> None:
    now = datetime.now(UTC)
    state = RuntimeReadinessState()
    runtime = build_startup_readiness_runtime(
        state_store=InMemoryStateStore(),
        event_bus=LocalEventBus(),
        transition_event_bus=LocalEventBus(),
        event_validator=_Validator(),  # type: ignore[arg-type]
        identity=LocalWorkloadIdentity(),
        embedding_model=_Embedding(),
        policy_compile_probe=_policy_probe(),
        environment={"FDAI_STARTUP_KAFKA_SETTLE_SECONDS": "0"},
    )
    object.__setattr__(runtime, "state", state)
    stop = asyncio.Event()
    running = asyncio.Event()
    cleaned = asyncio.Event()

    async def operation() -> None:
        running.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    state.update(
        StartupReadinessReport(
            generated_at=now,
            decision=ReadinessDecision.READY,
            results=(
                StartupProbeResult(
                    probe_id="postgres",
                    status=ProbeStatus.PASSED,
                    observed_at=now,
                    expires_at=now + timedelta(minutes=5),
                    latency_ms=1,
                ),
            ),
        )
    )
    guarded = asyncio.create_task(runtime.run_when_ready(stop, operation))
    await running.wait()

    guarded.cancel()
    with pytest.raises(asyncio.CancelledError):
        await guarded

    assert cleaned.is_set()
