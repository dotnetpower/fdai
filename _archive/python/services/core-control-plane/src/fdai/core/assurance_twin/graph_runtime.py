"""Runtime coordination for graph-wide Dynamic shadow simulation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from fdai.core.assurance_twin.effect_model import EffectModelStatus
from fdai.core.assurance_twin.graph_effect import (
    EffectInteractionTerm,
    GraphDynamicSimulationResult,
    GraphEffectModel,
    GraphIntervention,
    GraphTopologyEdge,
    simulate_graph_effects,
)
from fdai.core.assurance_twin.state_trajectory import DynamicInvariant, OperationalStateTrajectory
from fdai.core.assurance_twin.trajectory_ledger import StateStoreTrajectoryEpisodeLedger
from fdai.core.tiers.t1_lightweight import LearnedAction
from fdai.shared.contracts.models import Event


@dataclass(frozen=True, slots=True)
class GraphDynamicSimulationRequest:
    baseline: OperationalStateTrajectory
    topology: tuple[GraphTopologyEdge, ...]
    interventions: tuple[GraphIntervention, ...]
    invariants: tuple[DynamicInvariant, ...]
    interaction_terms: tuple[EffectInteractionTerm, ...] = ()
    divergence_threshold: float = 0.0
    max_slices: int = 4096

    def __post_init__(self) -> None:
        if (
            not self.invariants
            or len(self.invariants) > 256
            or len({item.invariant_id for item in self.invariants}) != len(self.invariants)
        ):
            raise ValueError("graph simulation invariants MUST be non-empty, unique, and bounded")


class GraphDynamicSimulationRequestProvider(Protocol):
    async def build(
        self,
        *,
        event: Event,
        action: LearnedAction,
    ) -> GraphDynamicSimulationRequest | None: ...


class GraphEffectModelReader(Protocol):
    async def list_models(
        self,
        *,
        status: EffectModelStatus,
        trigger_refs: tuple[str, ...],
    ) -> tuple[GraphEffectModel, ...]: ...


class GraphEffectModelCausalEvidenceVerifier(Protocol):
    def verify(self, model: GraphEffectModel) -> bool: ...


@dataclass(frozen=True, slots=True)
class GraphDynamicRuntimeResult:
    simulation: GraphDynamicSimulationResult | None
    reason: str


class GraphDynamicRuntimeCoordinator:
    """Load verified model sets and produce read-only graph trajectories."""

    def __init__(
        self,
        *,
        request_provider: GraphDynamicSimulationRequestProvider,
        model_reader: GraphEffectModelReader,
        causal_evidence_verifier: GraphEffectModelCausalEvidenceVerifier,
        trajectory_ledger: StateStoreTrajectoryEpisodeLedger | None = None,
    ) -> None:
        self._request_provider = request_provider
        self._model_reader = model_reader
        self._causal_evidence_verifier = causal_evidence_verifier
        self._trajectory_ledger = trajectory_ledger

    async def simulate(
        self,
        *,
        event: Event,
        action: LearnedAction,
    ) -> GraphDynamicRuntimeResult:
        request = await self._request_provider.build(event=event, action=action)
        if request is None:
            return GraphDynamicRuntimeResult(None, "graph_simulation_request_unavailable")
        trigger_refs = tuple(sorted({item.trigger_ref for item in request.interventions}))
        active_models = await self._model_reader.list_models(
            status=EffectModelStatus.ACTIVE,
            trigger_refs=trigger_refs,
        )
        challenger_models = await self._model_reader.list_models(
            status=EffectModelStatus.CHALLENGER,
            trigger_refs=trigger_refs,
        )
        for model in (*active_models, *challenger_models):
            if not self._causal_evidence_verifier.verify(model):
                raise ValueError("graph Dynamic model causal evidence is unverified")
        simulation = simulate_graph_effects(
            baseline=request.baseline,
            topology=request.topology,
            interventions=request.interventions,
            active_models=active_models,
            challenger_models=challenger_models,
            interaction_terms=request.interaction_terms,
            invariants=request.invariants,
            divergence_threshold=request.divergence_threshold,
            max_slices=request.max_slices,
        )
        if (
            self._trajectory_ledger is not None
            and challenger_models
            and simulation.challenger_trajectory is not None
        ):
            await self._trajectory_ledger.record_prediction(
                simulation.challenger_trajectory,
                challenger_model_refs=tuple(sorted(model.ref for model in challenger_models)),
                recorded_by="Forseti",
                recorded_at=datetime.now(tz=UTC),
            )
        return GraphDynamicRuntimeResult(simulation, "graph_simulation_completed")


__all__ = [
    "GraphDynamicRuntimeCoordinator",
    "GraphDynamicRuntimeResult",
    "GraphDynamicSimulationRequest",
    "GraphDynamicSimulationRequestProvider",
    "GraphEffectModelCausalEvidenceVerifier",
    "GraphEffectModelReader",
]
