"""Thor rollback and pre-flight simulator bindings selected at Pantheon startup."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any

from fdai.agents import CompositeThorPreflightSimulator, ThorPreflightSimulator
from fdai.agents.vidar import RollbackExecutor
from fdai.core.ontology_platform.typed_selection_contracts import READ_PROMOTION_ACTION
from fdai.delivery.persistence.state_store_typed_selection_read import StateStoreTypedSelectionRead
from fdai.runtime.aks_commerce import AcceptanceRuntimeBindings
from fdai.runtime.t2_route_registry import T2RoutePreflightSimulator, T2RouteRegistry
from fdai.runtime.typed_selection_read_lifecycle import (
    FinalizedTypedReadApproval,
    TypedReadLifecycle,
)
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmissionProvider
from fdai.shared.providers.state_store import StateStore


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


def build_typed_read_execution_bindings(
    *,
    thor_mutation_bound: bool,
    t2_route_registry: T2RouteRegistry,
    acceptance_bindings: AcceptanceRuntimeBindings | None,
    store: StateStore,
    admission: DecisionEvidenceAdmissionProvider | None,
    can_approve: Callable[[str, str], bool] | None,
) -> tuple[
    TypedReadLifecycle,
    ThorExecutionBindings,
    Callable[[dict[str, Any]], Awaitable[bool]],
]:
    """Compose the typed read lane without replacing any existing action bindings."""
    bindings = build_thor_execution_bindings(
        thor_mutation_bound=thor_mutation_bound,
        t2_route_registry=t2_route_registry,
        acceptance_bindings=acceptance_bindings,
    )
    registry = StateStoreTypedSelectionRead(
        store, admission=admission, approvals=FinalizedTypedReadApproval(store)
    )
    lifecycle = TypedReadLifecycle(registry, can_approve=can_approve)
    simulators = dict(
        bindings.preflight_simulator.simulators_by_action_type
        if bindings.preflight_simulator is not None
        else {}
    )
    simulators[READ_PROMOTION_ACTION] = lifecycle
    fallback = (
        acceptance_bindings.execute
        if acceptance_bindings is not None and bindings.acceptance_scale_out_recovery_bound
        else t2_route_registry.execute
        if thor_mutation_bound
        else None
    )

    async def execute(context: dict[str, Any]) -> bool:
        run = context.get("run")
        if getattr(run, "action_type", None) == READ_PROMOTION_ACTION:
            return await lifecycle.execute(context)
        return await fallback(context) if fallback is not None else False

    return (
        lifecycle,
        replace(
            bindings,
            action_rollback_executors={
                **bindings.action_rollback_executors,
                (READ_PROMOTION_ACTION, "scripted"): lifecycle.rollback,
            },
            preflight_simulator=CompositeThorPreflightSimulator(simulators),
        ),
        execute,
    )


__all__ = [
    "ThorExecutionBindings",
    "build_thor_execution_bindings",
    "build_typed_read_execution_bindings",
]
