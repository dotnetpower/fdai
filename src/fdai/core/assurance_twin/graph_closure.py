"""Off-path trajectory closure and challenger-only graph learning."""

from __future__ import annotations

import hashlib
import math
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fdai.core.assurance_twin.graph_learning import GraphModelLearningObservation
from fdai.core.assurance_twin.graph_model_registry import (
    GraphRegistryUpdate,
    StateStoreGraphEffectModelRegistry,
)
from fdai.core.assurance_twin.state_trajectory import (
    OperationalStateTrajectory,
    StateSlice,
    TrajectoryKind,
    TrajectoryOutcomeStatus,
)
from fdai.core.assurance_twin.trajectory_ledger import (
    OpenTrajectoryEpisode,
    StateStoreTrajectoryEpisodeLedger,
    TrajectoryClosure,
)
from fdai.shared.providers.metric import MetricPoint, MetricProvider, MetricQuery
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


class MetricGraphTrajectoryOutcomeSource:
    """Observe due trajectories from an independent metric provider."""

    def __init__(
        self,
        *,
        ledger: StateStoreTrajectoryEpisodeLedger,
        metrics: MetricProvider,
        clock: Callable[[], datetime] | None = None,
        telemetry_grace: timedelta = timedelta(minutes=5),
        observation_window: timedelta = timedelta(minutes=1),
        max_episodes: int = 256,
    ) -> None:
        if telemetry_grace < timedelta(0) or observation_window <= timedelta(0):
            raise ValueError("graph trajectory observation windows MUST be valid")
        if not 1 <= max_episodes <= 1000:
            raise ValueError("graph trajectory max_episodes MUST be in [1, 1000]")
        self._ledger = ledger
        self._metrics = metrics
        self._clock = clock or _default_clock
        self._telemetry_grace = telemetry_grace
        self._observation_window = observation_window
        self._max_episodes = max_episodes

    async def outcomes(self) -> AsyncIterator[TrajectoryClosureCommand]:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("graph trajectory observation clock MUST be timezone-aware")
        episodes = await self._ledger.list_open(limit=self._max_episodes)
        for episode in episodes:
            if now < episode.predicted.horizon_end + self._telemetry_grace:
                continue
            observed = await self._observe_episode(episode)
            if observed is not None:
                yield TrajectoryClosureCommand(
                    prediction_digest=episode.predicted.digest,
                    observed=observed,
                    recorded_at=now,
                )

    async def _observe_episode(
        self,
        episode: OpenTrajectoryEpisode,
    ) -> OperationalStateTrajectory | None:
        observed_slices = []
        for predicted_slice in episode.predicted.slices:
            points = [
                point
                async for point in self._metrics.query(
                    MetricQuery(
                        metric_name=predicted_slice.metric,
                        labels={"resource_id": predicted_slice.object_ref},
                        since=predicted_slice.effective_at,
                        until=predicted_slice.effective_at + self._observation_window,
                    )
                )
            ]
            point = _select_observation(
                points,
                effective_at=predicted_slice.effective_at,
                until=predicted_slice.effective_at + self._observation_window,
                metric=predicted_slice.metric,
                resource_ref=predicted_slice.object_ref,
            )
            if point is None:
                return None
            observed_slices.append(
                StateSlice(
                    object_ref=predicted_slice.object_ref,
                    object_type=predicted_slice.object_type,
                    metric=predicted_slice.metric,
                    value=point.value,
                    effective_at=predicted_slice.effective_at,
                    evidence_refs=(_metric_evidence_ref(point),),
                    independent_observer=True,
                )
            )
        predicted = episode.predicted
        return OperationalStateTrajectory(
            kind=TrajectoryKind.OBSERVED,
            ontology_release=predicted.ontology_release,
            graph_revision=predicted.graph_revision,
            inventory_generation=predicted.inventory_generation,
            base_snapshot_id=predicted.base_snapshot_id,
            evidence_cutoff=predicted.evidence_cutoff,
            horizon_end=predicted.horizon_end,
            slices=tuple(observed_slices),
            intervention_refs=predicted.intervention_refs,
            source_watermarks=predicted.source_watermarks,
        )


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


def _select_observation(
    points: list[MetricPoint],
    *,
    effective_at: datetime,
    until: datetime,
    metric: str,
    resource_ref: str,
) -> MetricPoint | None:
    valid = [
        point
        for point in points
        if point.at.tzinfo is not None
        and effective_at <= point.at <= until
        and point.metric_name == metric
        and point.labels.get("resource_id") == resource_ref
        and math.isfinite(point.value)
    ]
    if not valid:
        return None
    return min(valid, key=lambda point: (abs(point.at - effective_at), point.at))


def _metric_evidence_ref(point: MetricPoint) -> str:
    material = "\0".join(
        (
            point.metric_name,
            point.at.astimezone(UTC).isoformat(),
            repr(point.value),
            *(f"{key}={value}" for key, value in sorted(point.labels.items())),
        )
    )
    return f"metric:{hashlib.sha256(material.encode()).hexdigest()}"


__all__ = [
    "GraphClosureReport",
    "GraphDynamicClosureCoordinator",
    "GraphDynamicClosureRunner",
    "GraphTrajectoryOutcomeSource",
    "MetricGraphTrajectoryOutcomeSource",
    "TrajectoryClosureCommand",
]
