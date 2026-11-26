from __future__ import annotations

from datetime import UTC, datetime

from fdai.agents import (
    ActionRun,
    CompositeThorPreflightSimulator,
    PreflightSimulationResult,
)
from fdai.agents.thor import ActionRunState
from fdai.runtime.t2_route_registry import T2RoutePreflightSimulator, T2RouteRegistry
from fdai.shared.contracts.models import Autonomy
from fdai.shared.providers.testing.state_store import InMemoryStateStore


def _run(**params: object) -> ActionRun:
    return ActionRun(
        correlation_id=str(params.pop("correlation_id", "corr-route")),
        action_type=str(params.pop("action_type", "ops.switch-t2-proposer-route")),
        resource_id=str(params.pop("resource_id", "control-plane:t2-proposer")),
        state=ActionRunState.APPROVED,
        verdict="hil",
        params={
            "target_resource_ref": "control-plane:t2-proposer",
            "prior_route_ref": "primary",
            "target_route_ref": "secondary",
            "reason_code": "proposer_failed",
            **params,
        },
        resolved_autonomy_ceiling=Autonomy.ENFORCE_HIL,
    )


async def test_t2_route_preflight_passes_without_writing_state() -> None:
    store = InMemoryStateStore()
    simulator = T2RoutePreflightSimulator(
        T2RouteRegistry(store=store, clock=lambda: datetime(2026, 10, 1, tzinfo=UTC))
    )

    result = await simulator.simulate(_run())

    assert result.outcome == "passed"
    assert result.reason == "passed"
    assert await store.read_state("t2-recovery:route:proposer") is None
    assert store.audit_entries == ()


async def test_t2_route_preflight_mismatch_fails_without_writing_state() -> None:
    store = InMemoryStateStore()
    simulator = T2RoutePreflightSimulator(
        T2RouteRegistry(store=store, clock=lambda: datetime(2026, 10, 1, tzinfo=UTC))
    )

    result = await simulator.simulate(_run(prior_route_ref="secondary"))

    assert result.outcome == "failed"
    assert result.reason == "prior_route_mismatch"
    assert await store.read_state("t2-recovery:route:proposer") is None
    assert store.audit_entries == ()


class _PassingSimulator:
    async def simulate(self, run: ActionRun) -> PreflightSimulationResult:
        return PreflightSimulationResult(
            outcome="passed",
            simulator_id="test",
            simulator_version="1",
            reason=run.action_type,
        )


async def test_composite_preflight_routes_and_fails_closed_on_unbound_action_type() -> None:
    simulator = CompositeThorPreflightSimulator(
        {"ops.switch-t2-proposer-route": _PassingSimulator()}
    )

    passed = await simulator.simulate(_run())
    failed = await simulator.simulate(_run(action_type="ops.unknown"))

    assert passed.outcome == "passed"
    assert passed.reason == "ops.switch-t2-proposer-route"
    assert failed.outcome == "failed"
    assert failed.reason == "no_simulator_for_action_type"
