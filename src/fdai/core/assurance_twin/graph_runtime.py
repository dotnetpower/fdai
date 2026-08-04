"""Runtime coordination for graph-wide Dynamic shadow simulation."""

from __future__ import annotations

from dataclasses import dataclass
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
from fdai.core.assurance_twin.state_trajectory import OperationalStateTrajectory
from fdai.core.tiers.t1_lightweight import LearnedAction
from fdai.shared.contracts.models import Event


@dataclass(frozen=True, slots=True)
class GraphDynamicSimulationRequest:
    baseline: OperationalStateTrajectory
    topology: tuple[GraphTopologyEdge, ...]
    interventions: tuple[GraphIntervention, ...]
    interaction_terms: tuple[EffectInteractionTerm, ...] = ()
    divergence_threshold: float = 0.0
    max_slices: int = 4096


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
    ) -> None:
        self._request_provider = request_provider
        self._model_reader = model_reader
        self._causal_evidence_verifier = causal_evidence_verifier

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
            divergence_threshold=request.divergence_threshold,
            max_slices=request.max_slices,
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
