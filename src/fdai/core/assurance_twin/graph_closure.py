"""Off-path trajectory closure and challenger-only graph learning."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from fdai.core.assurance_twin.graph_learning import GraphModelLearningObservation
from fdai.core.assurance_twin.graph_model_registry import (
    GraphRegistryUpdate,
    StateStoreGraphEffectModelRegistry,
)
from fdai.core.assurance_twin.state_trajectory import (
    OperationalStateTrajectory,
    TrajectoryOutcomeStatus,
)
from fdai.core.assurance_twin.trajectory_ledger import (
    StateStoreTrajectoryEpisodeLedger,
    TrajectoryClosure,
)
from fdai.shared.providers.state_store import StateStore


def _default_clock() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(frozen=True, slots=True)
class GraphClosureReport:
    prediction_digest: str
    outcome_status: TrajectoryOutcomeStatus
    reason: str
    closed: bool
    duplicate: bool
    observation_count: int
    update_count: int
    updates: tuple[GraphRegistryUpdate, ...]


@dataclass(frozen=True, slots=True)
class TrajectoryClosureCommand:
    prediction_digest: str
    observed: OperationalStateTrajectory
    recorded_at: datetime


class GraphTrajectoryOutcomeSource(Protocol):
    def outcomes(self) -> AsyncIterator[TrajectoryClosureCommand]: ...


class GraphDynamicClosureCoordinator:
    """Close one episode and apply only comparable challenger slices."""

    def __init__(
        self,
        *,
        ledger: StateStoreTrajectoryEpisodeLedger,
        registry: StateStoreGraphEffectModelRegistry,
        audit_store: StateStore,
    ) -> None:
        self._ledger = ledger
        self._registry = registry
        self._audit_store = audit_store

    async def close_and_update(
        self,
        *,
        prediction_digest: str,
        observed: OperationalStateTrajectory,
        recorded_at: datetime,
    ) -> GraphClosureReport:
        closure = await self._ledger.close(
            prediction_digest=prediction_digest,
            observed=observed,
            recorded_at=recorded_at,
        )
        observations = (
            _learning_observations(closure, recorded_at=recorded_at)
            if closure.closed and not closure.duplicate
            else ()
        )
        updates = tuple(
            [await self._registry.update_from_observation(item) for item in observations]
        )
        accepted = sum(item.accepted for item in updates)
        if not closure.duplicate:
            await self._audit_store.append_audit_entry(
                {
                    "actor": "Norns",
                    "producer_principal": "Norns",
                    "action_kind": "dynamic.graph_closure.processed",
                    "mode": "shadow",
                    "prediction_digest": prediction_digest,
                    "observation_digest": observed.digest,
                    "outcome_status": closure.outcome.status.value,
                    "reason": closure.outcome.reason,
                    "observation_count": len(observations),
                    "update_count": accepted,
                    "update_reasons": [item.reason for item in updates],
                    "active_model_mutated": False,
                    "promotion_applied": False,
                    "recorded_at": recorded_at.isoformat(),
                }
            )
        return GraphClosureReport(
            prediction_digest=prediction_digest,
            outcome_status=closure.outcome.status,
            reason=closure.outcome.reason,
            closed=closure.closed,
            duplicate=closure.duplicate,
            observation_count=len(observations),
            update_count=accepted,
            updates=updates,
        )


class GraphDynamicClosureRunner:
    """Drain observed trajectories off-path and audit one bounded run."""

    def __init__(
        self,
        *,
        outcome_source: GraphTrajectoryOutcomeSource,
        coordinator: GraphDynamicClosureCoordinator,
        audit_store: StateStore,
        clock: Callable[[], datetime] | None = None,
        max_outcomes: int = 256,
    ) -> None:
        if not 1 <= max_outcomes <= 4096:
            raise ValueError("graph closure max_outcomes MUST be in [1, 4096]")
        self._outcome_source = outcome_source
        self._coordinator = coordinator
        self._audit_store = audit_store
        self._clock = clock or _default_clock
        self._max_outcomes = max_outcomes

    async def run_once(self) -> tuple[GraphClosureReport, ...]:
        reports: list[GraphClosureReport] = []
        async for command in self._outcome_source.outcomes():
            if len(reports) >= self._max_outcomes:
                break
            reports.append(
                await self._coordinator.close_and_update(
                    prediction_digest=command.prediction_digest,
                    observed=command.observed,
                    recorded_at=command.recorded_at,
                )
            )
        await self._audit_store.append_audit_entry(
            {
                "actor": "Norns",
                "producer_principal": "Norns",
                "action_kind": "dynamic.graph_closure.run",
                "mode": "shadow",
                "outcome_count": len(reports),
                "closed_count": sum(item.closed and not item.duplicate for item in reports),
                "duplicate_count": sum(item.duplicate for item in reports),
                "update_count": sum(item.update_count for item in reports),
                "active_model_mutated": False,
                "promotion_applied": False,
                "recorded_at": self._clock().isoformat(),
            }
        )
        return tuple(reports)


def _learning_observations(
    closure: TrajectoryClosure,
    *,
    recorded_at: datetime,
) -> tuple[GraphModelLearningObservation, ...]:
    if not closure.outcome.challenger_eligible:
        return ()
    observed_by_key = {item.key: item for item in closure.observed.slices}
    observations: list[GraphModelLearningObservation] = []
    for predicted_slice in closure.predicted.slices:
        model_ref = predicted_slice.model_ref
        observed_slice = observed_by_key.get(predicted_slice.key)
        if model_ref not in closure.challenger_model_refs or observed_slice is None:
            continue
        if not observed_slice.independent_observer or not observed_slice.evidence_refs:
            continue
        observations.append(
            GraphModelLearningObservation(
                model_ref=model_ref,
                prediction_digest=closure.outcome.prediction_digest,
                observation_digest=closure.outcome.observation_digest,
                object_ref=predicted_slice.object_ref,
                metric=predicted_slice.metric,
                predicted_value=predicted_slice.value,
                observed_value=observed_slice.value,
                observed_at=observed_slice.effective_at,
                recorded_at=recorded_at,
                evidence_refs=observed_slice.evidence_refs,
                independent_observer=True,
                complete=True,
            )
        )
    return tuple(observations)


__all__ = [
    "GraphClosureReport",
    "GraphDynamicClosureCoordinator",
    "GraphDynamicClosureRunner",
    "GraphTrajectoryOutcomeSource",
    "TrajectoryClosureCommand",
]
