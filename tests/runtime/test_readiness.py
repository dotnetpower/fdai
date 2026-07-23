"""Runtime startup readiness composition and recovery tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.core.readiness import (
    AuthorityCeiling,
    ProbeStatus,
    ReadinessDecision,
    StartupProbeResult,
    StartupReadinessReport,
)
from fdai.delivery.startup_probe import StaticStartupProbe
from fdai.runtime.readiness import RuntimeReadinessState, build_startup_readiness_runtime
from fdai.shared.providers.local.event_bus import LocalEventBus
from fdai.shared.providers.local.identity import LocalWorkloadIdentity
from fdai.shared.providers.testing.state_store import InMemoryStateStore


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
        event_validator=validator,  # type: ignore[arg-type]
        identity=LocalWorkloadIdentity(),
        embedding_model=_Embedding(),
        policy_compile_probe=_policy_probe(),
        environment={"FDAI_STARTUP_KAFKA_SETTLE_SECONDS": "0"},
    )

    report = await runtime.evaluate()

    assert report.decision is ReadinessDecision.READY
    assert len(report.results) == 10
    assert runtime.state.is_ready()
    persisted = await store.read_state("runtime:startup-readiness:latest")
    assert persisted is not None
    assert persisted["decision"] == "ready"
    assert len(validator.payloads) == 1
    assert any(
        entry.get("entry", {}).get("kind") == "startup_readiness.transition"
        for entry in store.audit_entries
    )


async def test_runtime_probes_every_candidate_inside_cross_check_pool() -> None:
    candidates = (_CrossCheck(), _CrossCheck())
    runtime = build_startup_readiness_runtime(
        state_store=InMemoryStateStore(),
        event_bus=LocalEventBus(),
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
    assert len(report.results) == 12


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


async def test_guarded_operation_is_not_created_before_readiness() -> None:
    store = InMemoryStateStore()
    runtime = build_startup_readiness_runtime(
        state_store=store,
        event_bus=LocalEventBus(),
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
