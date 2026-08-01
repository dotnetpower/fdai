"""Runtime service for active/challenger Dynamic branch simulation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Protocol

from fdai.core.tiers.t1_lightweight import LearnedAction
from fdai.shared.contracts.models import Event

from .effect_model import (
    DynamicSimulationResult,
    EffectModel,
    EffectModelStatus,
    SimulationBranch,
    SimulationSnapshot,
    simulate_effect_branches,
)

_MAX_RUNTIME_BRANCHES = 32


@dataclass(frozen=True, slots=True)
class DynamicSimulationRequest:
    snapshot: SimulationSnapshot
    branches: tuple[SimulationBranch, ...]
    objective: Literal["minimize", "maximize"] = "minimize"
    divergence_threshold: float = 0.0

    def __post_init__(self) -> None:
        if not 1 <= len(self.branches) <= _MAX_RUNTIME_BRANCHES:
            raise ValueError("Dynamic runtime branches MUST be bounded and non-empty")
        if not math.isfinite(self.divergence_threshold) or self.divergence_threshold < 0.0:
            raise ValueError("Dynamic divergence threshold MUST be finite and non-negative")


class DynamicSimulationRequestProvider(Protocol):
    """Build one bounded simulation request from current observed state."""

    async def build(
        self,
        *,
        event: Event,
        action: LearnedAction,
    ) -> DynamicSimulationRequest | None: ...


class EffectModelReader(Protocol):
    async def get(
        self,
        *,
        status: EffectModelStatus,
        action_type_id: str,
        metric: str,
    ) -> EffectModel | None: ...


class EffectModelCausalEvidenceVerifier(Protocol):
    def verify(self, model: EffectModel) -> bool: ...


@dataclass(frozen=True, slots=True)
class DynamicRuntimeResult:
    simulation: DynamicSimulationResult | None
    reason: str


class DynamicRuntimeCoordinator:
    """Load immutable models and simulate branches without selecting execution."""

    def __init__(
        self,
        *,
        request_provider: DynamicSimulationRequestProvider,
        model_reader: EffectModelReader,
        causal_evidence_verifier: EffectModelCausalEvidenceVerifier,
    ) -> None:
        self._request_provider = request_provider
        self._model_reader = model_reader
        self._causal_evidence_verifier = causal_evidence_verifier

    async def simulate(
        self,
        *,
        event: Event,
        action: LearnedAction,
    ) -> DynamicRuntimeResult:
        request = await self._request_provider.build(event=event, action=action)
        if request is None:
            return DynamicRuntimeResult(None, "simulation_request_unavailable")
        action_types = tuple(sorted({branch.action_type_id for branch in request.branches}))
        active_models: dict[str, EffectModel] = {}
        challenger_models: dict[str, EffectModel] = {}
        for action_type_id in action_types:
            active = await self._model_reader.get(
                status=EffectModelStatus.ACTIVE,
                action_type_id=action_type_id,
                metric=request.snapshot.metric,
            )
            challenger = await self._model_reader.get(
                status=EffectModelStatus.CHALLENGER,
                action_type_id=action_type_id,
                metric=request.snapshot.metric,
            )
            if active is not None:
                if active.learned_through > request.snapshot.observed_at:
                    raise ValueError("Dynamic active model crosses the snapshot cutoff")
                if not self._causal_evidence_verifier.verify(active):
                    raise ValueError("Dynamic active model causal evidence is unverified")
                active_models[action_type_id] = active
            if challenger is not None:
                if challenger.learned_through > request.snapshot.observed_at:
                    raise ValueError("Dynamic challenger model crosses the snapshot cutoff")
                if not self._causal_evidence_verifier.verify(challenger):
                    raise ValueError("Dynamic challenger model causal evidence is unverified")
                challenger_models[action_type_id] = challenger
        simulation = simulate_effect_branches(
            snapshot=request.snapshot,
            branches=request.branches,
            active_models=active_models,
            challenger_models=challenger_models,
            objective=request.objective,
            divergence_threshold=request.divergence_threshold,
        )
        return DynamicRuntimeResult(simulation, "simulation_completed")


__all__ = [
    "DynamicRuntimeCoordinator",
    "DynamicRuntimeResult",
    "DynamicSimulationRequest",
    "DynamicSimulationRequestProvider",
    "EffectModelReader",
    "EffectModelCausalEvidenceVerifier",
]
