"""Thor rollback and pre-flight simulator bindings selected at Pantheon startup."""

from __future__ import annotations

from dataclasses import dataclass

from fdai.agents import CompositeThorPreflightSimulator, ThorPreflightSimulator
from fdai.agents.vidar import RollbackExecutor
from fdai.runtime.aks_commerce import AcceptanceRuntimeBindings
from fdai.runtime.t2_route_registry import T2RoutePreflightSimulator, T2RouteRegistry


@dataclass(frozen=True, slots=True)
class ThorExecutionBindings:
    """Rollback executors and the composite simulator Thor receives at startup."""

    action_rollback_executors: dict[tuple[str, str], RollbackExecutor]
    rollback_executors: dict[str, RollbackExecutor] | None
    preflight_simulator: CompositeThorPreflightSimulator | None
    acceptance_scale_out_recovery_bound: bool


def build_thor_execution_bindings(
    *,
    thor_mutation_bound: bool,
    t2_route_registry: T2RouteRegistry,
    acceptance_bindings: AcceptanceRuntimeBindings | None,
) -> ThorExecutionBindings:
    """Bind per-ActionType rollback and simulators only for selected mutation paths."""
    action_rollback_executors: dict[tuple[str, str], RollbackExecutor] = {}
    if thor_mutation_bound:
        action_rollback_executors[("ops.switch-t2-proposer-route", "state_forward_only")] = (
            t2_route_registry.rollback
        )
    if acceptance_bindings is not None:
        action_rollback_executors.update(acceptance_bindings.rollback_executors)
    rollback_executors: dict[str, RollbackExecutor] | None = (
        {"state_forward_only": t2_route_registry.rollback}
        if thor_mutation_bound and not acceptance_bindings
        else None
    )
    thor_preflight_simulators: dict[str, ThorPreflightSimulator] = {}
    if thor_mutation_bound:
        thor_preflight_simulators["ops.switch-t2-proposer-route"] = T2RoutePreflightSimulator(
            t2_route_registry
        )
    acceptance_scale_out_recovery_bound = (
        "ops.scale-out",
        "state_forward_only",
    ) in action_rollback_executors
    if acceptance_bindings is not None and acceptance_scale_out_recovery_bound:
        thor_preflight_simulators["ops.scale-out"] = acceptance_bindings.preflight_simulator
    thor_preflight_simulator = (
        CompositeThorPreflightSimulator(thor_preflight_simulators)
        if thor_preflight_simulators
        else None
    )
    return ThorExecutionBindings(
        action_rollback_executors=action_rollback_executors,
        rollback_executors=rollback_executors,
        preflight_simulator=thor_preflight_simulator,
        acceptance_scale_out_recovery_bound=acceptance_scale_out_recovery_bound,
    )


__all__ = ["ThorExecutionBindings", "build_thor_execution_bindings"]
