"""Focused startup readiness coordinator tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.core.readiness import (
    AuthorityCeiling,
    EvidenceRequirement,
    ModelStartupEvidence,
    ProbeCriticality,
    ProbeStatus,
    ReadinessDecision,
    StartupPhase,
    StartupProbeResult,
    StartupProbeSpec,
)
from fdai.core.readiness.coordinator import (
    StartupProbeBudget,
    StartupReadinessCoordinator,
)
from fdai.shared.providers.event_bus import PublishReceipt
from fdai.shared.providers.startup_probe import StartupProbeRequest

_NOW = datetime(2026, 7, 23, tzinfo=UTC)


class _Store:
    def __init__(self) -> None:
        self.values: dict[str, dict[str, Any]] = {}
        self.audit_entries: list[dict[str, Any]] = []

    async def append_audit_entry(self, entry: dict[str, Any]) -> None:
        self.audit_entries.append(entry)

    async def read_state(self, key: str) -> dict[str, Any] | None:
        return self.values.get(key)

    async def write_state(self, key: str, value: dict[str, Any]) -> None:
        self.values[key] = value


class _Bus:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, dict[str, Any]]] = []

    async def publish(
        self,
        topic: str,
        key: str,
        payload: dict[str, Any],
    ) -> PublishReceipt:
        self.published.append((topic, key, payload))
        return PublishReceipt(topic=topic, partition=0, offset=0)


class _Validator:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    def validate(self, instance: dict[str, Any]) -> None:
        self.payloads.append(instance)


class _Probe:
    def __init__(
        self,
        probe_id: str,
        *,
        result: StartupProbeResult | None = None,
        failure: Exception | None = None,
        delay: float = 0,
        calls: list[str] | None = None,
    ) -> None:
        self.probe_id = probe_id
        self._result = result
        self._failure = failure
        self._delay = delay
        self._calls = calls
        self.requests: list[StartupProbeRequest] = []

    async def run(self, request: StartupProbeRequest) -> StartupProbeResult:
        self.requests.append(request)
        if self._calls is not None:
            self._calls.append(self.probe_id)
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._failure is not None:
            raise self._failure
        assert self._result is not None
        return self._result


def _spec(
    probe_id: str,
    phase: StartupPhase,
    *,
    criticality: ProbeCriticality = ProbeCriticality.PROCESS_CRITICAL,
    ceiling: AuthorityCeiling = AuthorityCeiling.DISABLED,
    requirement: EvidenceRequirement = EvidenceRequirement.STANDARD,
    cost: float = 0,
) -> StartupProbeSpec:
    return StartupProbeSpec(
        probe_id=probe_id,
        capability=probe_id,
        phase=phase,
        criticality=criticality,
        failure_ceiling=ceiling,
        evidence_requirement=requirement,
        estimated_cost_usd=cost,
    )


def _passed(
    probe_id: str,
    *,
    model_evidence: ModelStartupEvidence | None = None,
) -> StartupProbeResult:
    return StartupProbeResult(
        probe_id=probe_id,
        status=ProbeStatus.PASSED,
        observed_at=_NOW,
        expires_at=_NOW + timedelta(minutes=5),
        latency_ms=5,
        model_evidence=model_evidence,
    )


def _coordinator(
    specs: list[StartupProbeSpec],
    probes: list[_Probe],
    *,
    budget: StartupProbeBudget | None = None,
) -> tuple[StartupReadinessCoordinator, _Store, _Bus, _Validator]:
    store = _Store()
    bus = _Bus()
    validator = _Validator()
    coordinator = StartupReadinessCoordinator(
        specs=specs,
        probes=probes,
        state_store=store,  # type: ignore[arg-type]
        event_bus=bus,  # type: ignore[arg-type]
        event_validator=validator,  # type: ignore[arg-type]
        budget=budget or StartupProbeBudget(),
        clock=lambda: _NOW,
    )
    return coordinator, store, bus, validator


async def test_phases_run_in_order_and_publish_one_validated_transition() -> None:
    calls: list[str] = []
    specs = [
        _spec("static", StartupPhase.STATIC_LOAD),
        _spec("reachability", StartupPhase.REQUIRED_REACHABILITY),
        _spec(
            "optional",
            StartupPhase.CAPABILITY_WARMUP,
            criticality=ProbeCriticality.OPTIONAL,
            ceiling=AuthorityCeiling.DETERMINISTIC_FALLBACK,
        ),
        _spec("smoke", StartupPhase.ACTIVE_SMOKE),
    ]
    probes = [_Probe(spec.probe_id, result=_passed(spec.probe_id), calls=calls) for spec in specs]
    coordinator, store, bus, validator = _coordinator(specs, probes)

    report = await coordinator.evaluate()

    assert report.decision is ReadinessDecision.READY
    assert calls == ["static", "reachability", "optional", "smoke"]
    assert store.values["runtime:startup-readiness:latest"]["decision"] == "ready"
    assert store.audit_entries[0]["kind"] == "startup_readiness.transition"
    assert len(validator.payloads) == 1
    assert len(bus.published) == 1
    assert bus.published[0][0] == "runtime.readiness.transitions"


async def test_timeout_and_crash_are_sanitized_and_block_readiness() -> None:
    specs = [
        _spec("timeout", StartupPhase.REQUIRED_REACHABILITY),
        _spec("crash", StartupPhase.REQUIRED_REACHABILITY),
    ]
    probes = [
        _Probe("timeout", result=_passed("timeout"), delay=0.02),
        _Probe("crash", failure=RuntimeError("secret endpoint text")),
    ]
    coordinator, _, _, _ = _coordinator(
        specs,
        probes,
        budget=StartupProbeBudget(per_probe_timeout_seconds=0.001, retries=0),
    )

    report = await coordinator.evaluate()

    assert report.decision is ReadinessDecision.BLOCKED
    failures = {result.probe_id: result.failure_class for result in report.results}
    assert failures == {
        "crash": "probe_crashed",
        "timeout": "probe_deadline_exceeded",
    }
    assert "secret" not in report.to_json()


async def test_total_cost_budget_is_reserved_across_concurrent_probes() -> None:
    specs = [
        _spec("model-a", StartupPhase.CAPABILITY_WARMUP, cost=0.04),
        _spec("model-b", StartupPhase.CAPABILITY_WARMUP, cost=0.04),
    ]
    probes = [_Probe(spec.probe_id, result=_passed(spec.probe_id)) for spec in specs]
    coordinator, _, _, _ = _coordinator(
        specs,
        probes,
        budget=StartupProbeBudget(total_cost_limit_usd=0.05),
    )

    report = await coordinator.evaluate()

    assert report.decision is ReadinessDecision.BLOCKED
    assert [probe.requests for probe in probes].count([]) == 1
    assert any(result.failure_class == "cost_budget_exhausted" for result in report.results)


async def test_streaming_model_requires_two_ttft_and_token_rate_samples() -> None:
    spec = _spec(
        "model-stream",
        StartupPhase.CAPABILITY_WARMUP,
        requirement=EvidenceRequirement.MODEL_STREAM,
    )
    incomplete = ModelStartupEvidence(
        sample_count=2,
        total_latency_ms=(100, 110),
    )
    probe = _Probe(spec.probe_id, result=_passed(spec.probe_id, model_evidence=incomplete))
    coordinator, _, _, _ = _coordinator([spec], [probe])

    report = await coordinator.evaluate()

    assert report.decision is ReadinessDecision.BLOCKED
    assert report.results[0].failure_class == "capability_unproven"
    assert probe.requests[0].model_sample_count == 2


async def test_unchanged_periodic_refresh_does_not_republish_transition() -> None:
    spec = _spec("audit", StartupPhase.REQUIRED_REACHABILITY)
    probe = _Probe(spec.probe_id, result=_passed(spec.probe_id))
    coordinator, _, bus, _ = _coordinator([spec], [probe])

    await coordinator.evaluate()
    await coordinator.evaluate()

    assert len(bus.published) == 1
