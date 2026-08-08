from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.chaos.contract import ExperimentOutcome, FaultScenario
from fdai.core.chaos.governance import ChaosEligibilityContext, evaluate_chaos_eligibility
from fdai.core.chaos.guard import (
    ChaosStopReason,
    ImpactObservation,
    evaluate_impact_guard,
)
from fdai.core.chaos.harness import FaultInjectionHarness
from fdai.core.chaos.injector import ShadowFaultInjector
from fdai.core.chaos.run_state import ChaosRunSnapshot, ChaosRunState, transition_chaos_run
from fdai.core.impact_analysis import (
    ImpactEnvelopeRecord,
    ObjectiveBound,
    TelemetryRequirements,
)
from fdai.shared.contracts.models import Mode

_NOW = datetime(2026, 7, 31, tzinfo=UTC)


def _eligibility(**overrides: object) -> ChaosEligibilityContext:
    values: dict[str, object] = {
        "catalog_valid": True,
        "scenario_promoted": True,
        "action_types_promoted": True,
        "causal_hypothesis_ref": "causal-1",
        "refutation_query_ref": "query-1",
        "explicit_targets": ("resource-a",),
        "supported_environment": True,
        "owner_ref": "owner-1",
        "maintenance_window_active": True,
        "graph_complete": True,
        "objective_headroom": True,
        "recovery_ready": True,
        "telemetry_ready": True,
        "no_conflicting_work": True,
        "dry_run_receipt": "dry-run-1",
        "locks_acquired": True,
        "idempotency_key": "run-1",
        "kill_switch_clear": True,
        "stop_conditions_ready": True,
        "audit_ready": True,
        "approval_principal": "Var",
        "approver_ids": ("approver-a",),
        "initiator_id": "initiator-a",
    }
    values.update(overrides)
    return ChaosEligibilityContext(**values)  # type: ignore[arg-type]


def test_chaos_enforce_is_human_approved_and_fully_gated() -> None:
    assert evaluate_chaos_eligibility(_eligibility()).eligible
    failed = evaluate_chaos_eligibility(
        _eligibility(
            recovery_ready=False,
            graph_complete=False,
            telemetry_ready=False,
            approval_principal="Loki",
        )
    )
    assert not failed.eligible
    assert set(failed.reasons) >= {
        "graph_incomplete",
        "recovery_not_ready",
        "telemetry_not_ready",
        "var_approval_required",
    }


def test_production_or_stateful_chaos_requires_two_distinct_non_initiators() -> None:
    insufficient = evaluate_chaos_eligibility(_eligibility(production_or_stateful=True))
    assert insufficient.quorum_required == 2
    assert "approval_quorum_not_met" in insufficient.reasons
    self_approved = evaluate_chaos_eligibility(
        _eligibility(
            production_or_stateful=True,
            approver_ids=("initiator-a", "approver-b"),
        )
    )
    assert "self_approval_forbidden" in self_approved.reasons


def test_chaos_state_machine_is_monotonic_and_idempotent() -> None:
    snapshot = ChaosRunSnapshot(
        run_id="run-1",
        state=ChaosRunState.PLANNED,
        revision=0,
        updated_at=_NOW,
        last_idempotency_key="created",
    )
    states = (
        ChaosRunState.IMPACT_CHECKED,
        ChaosRunState.DRY_RUN_VERIFIED,
        ChaosRunState.APPROVED,
        ChaosRunState.INJECTING,
        ChaosRunState.OBSERVING,
        ChaosRunState.VERIFIED,
        ChaosRunState.RECOVERING,
        ChaosRunState.VERIFYING,
        ChaosRunState.RECOVERED,
    )
    for index, state in enumerate(states, start=1):
        snapshot = transition_chaos_run(
            snapshot,
            target=state,
            idempotency_key=f"transition-{index}",
            at=_NOW + timedelta(seconds=index),
        )
    assert snapshot.state is ChaosRunState.RECOVERED
    duplicate = transition_chaos_run(
        snapshot,
        target=ChaosRunState.RECOVERED,
        idempotency_key=snapshot.last_idempotency_key,
        at=snapshot.updated_at,
    )
    assert duplicate is snapshot
    with pytest.raises(ValueError, match="terminal"):
        transition_chaos_run(
            snapshot,
            target=ChaosRunState.FAILED,
            idempotency_key="late",
            at=_NOW + timedelta(seconds=20),
        )


def _envelope() -> ImpactEnvelopeRecord:
    return ImpactEnvelopeRecord(
        envelope_id="impact-1",
        decision_case_id="decision-1",
        graph_revision="graph-1",
        target_set_digest="targets",
        affected_set_digest="affected",
        direct_target_ids=("resource-a",),
        affected_resource_ids=("resource-a", "resource-b"),
        protected_objective_ids=("slo-a",),
        max_affected_resources=2,
        max_dependency_depth=2,
        max_duration_seconds=60,
        objective_bounds=(ObjectiveBound(metric="availability", lower=99.0),),
        required_signals=("pod_restart",),
        forbidden_signals=("security_event",),
        telemetry_requirements=TelemetryRequirements(
            required_sources=("metrics",),
            freshness_seconds=30,
            cadence_seconds=5,
        ),
        uncertainty=0.1,
        expires_at=_NOW + timedelta(hours=1),
    )


def _observation(**overrides: object) -> ImpactObservation:
    values: dict[str, object] = {
        "observed_resources": frozenset({"resource-a"}),
        "signals": frozenset({"pod_restart"}),
        "objective_values": {"availability": 99.9},
        "source_observed_at": {"metrics": _NOW},
        "elapsed_seconds": 10.0,
        "injector_reachable": True,
        "recovery_reachable": True,
    }
    values.update(overrides)
    return ImpactObservation(**values)  # type: ignore[arg-type]


def test_guard_allows_only_observations_inside_envelope() -> None:
    assert (
        evaluate_impact_guard(
            run_id="run-1",
            envelope=_envelope(),
            observation=_observation(),
            now=_NOW,
        )
        is None
    )


def test_guard_observation_requires_explicit_finite_evidence() -> None:
    with pytest.raises(TypeError, match="reachability"):
        _observation(injector_reachable=None)
    with pytest.raises(ValueError, match="objective values"):
        _observation(objective_values={"availability": float("nan")})

    event = evaluate_impact_guard(
        run_id="run-1",
        envelope=_envelope(),
        observation=_observation(source_observed_at={"metrics": _NOW + timedelta(seconds=1)}),
        now=_NOW,
    )
    assert event is not None
    assert event.reason is ChaosStopReason.TELEMETRY_INCOMPLETE


@pytest.mark.parametrize(
    ("observation", "reason"),
    [
        (
            _observation(observed_resources=frozenset({"resource-c"})),
            ChaosStopReason.AFFECTED_SET_EXCEEDED,
        ),
        (_observation(elapsed_seconds=61.0), ChaosStopReason.DURATION_EXCEEDED),
        (
            _observation(signals=frozenset({"security_event"})),
            ChaosStopReason.FORBIDDEN_SIGNAL,
        ),
        (
            _observation(objective_values={"availability": 98.0}),
            ChaosStopReason.OBJECTIVE_BOUND_EXCEEDED,
        ),
        (
            _observation(source_observed_at={}),
            ChaosStopReason.TELEMETRY_INCOMPLETE,
        ),
        (
            _observation(recovery_reachable=False),
            ChaosStopReason.BACKEND_UNREACHABLE,
        ),
    ],
)
def test_guard_emits_typed_stop_for_every_safety_breach(
    observation: ImpactObservation,
    reason: ChaosStopReason,
) -> None:
    event = evaluate_impact_guard(
        run_id="run-1",
        envelope=_envelope(),
        observation=observation,
        now=_NOW,
    )
    assert event is not None
    assert event.reason is reason
    assert event.to_payload()["event_type"] == "chaos.stop-triggered"


async def test_harness_guard_stop_short_circuits_hold_and_rolls_back() -> None:
    injector = ShadowFaultInjector(fault_type="pod_kill")
    sleeps: list[float] = []

    async def sleeper(seconds: float) -> None:
        sleeps.append(seconds)

    async def guard(elapsed: float):  # type: ignore[no-untyped-def]
        if elapsed < 5.0:
            return None
        return evaluate_impact_guard(
            run_id="run-1",
            envelope=_envelope(),
            observation=_observation(signals=frozenset({"security_event"})),
            now=_NOW,
        )

    result = await FaultInjectionHarness(
        injectors=(injector,),
        sleeper=sleeper,
    ).run(
        FaultScenario(
            scenario_id="guard-stop",
            fault_type="pod_kill",
            description="guard stop",
            target_selector="demo",
            expected_signal="pod_restart",
            blast_radius_cap=1,
            duration_seconds=60,
        ),
        approved_targets=("resource-a",),
        mode=Mode.ENFORCE,
        impact_guard=guard,
        guard_interval_seconds=5,
    )
    assert sleeps == [5]
    assert result.stop_reason == ChaosStopReason.FORBIDDEN_SIGNAL.value
    assert result.stopped
    assert injector.stopped == ["resource-a"]


async def test_harness_guard_cannot_extend_fault_hold_deadline() -> None:
    injector = ShadowFaultInjector(fault_type="pod_kill")
    never_returns = asyncio.Event()

    async def guard(_elapsed: float):  # type: ignore[no-untyped-def]
        await never_returns.wait()
        return None

    result = await FaultInjectionHarness(
        injectors=(injector,),
        max_hold_seconds=0.01,
        operation_timeout_seconds=1,
    ).run(
        FaultScenario(
            scenario_id="guard-deadline",
            fault_type="pod_kill",
            description="guard deadline",
            target_selector="demo",
            expected_signal="pod_restart",
            blast_radius_cap=1,
            duration_seconds=1,
        ),
        approved_targets=("resource-a",),
        mode=Mode.ENFORCE,
        impact_guard=guard,
        guard_interval_seconds=1,
    )

    assert result.outcome is ExperimentOutcome.ABORTED
    assert result.error is not None and "TimeoutError" in result.error
    assert injector.stopped == ["resource-a"]
