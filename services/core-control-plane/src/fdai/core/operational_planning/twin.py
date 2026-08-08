"""Assurance Twin effect-model adapter for operational planning."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime

from fdai.core.assurance_twin.effect_model import (
    EffectModel,
    EffectModelStatus,
    SimulationBranch,
    SimulationSnapshot,
    simulate_effect_branches,
)
from fdai.core.assurance_twin.runtime import EffectModelCausalEvidenceVerifier, EffectModelReader
from fdai.core.decision_case import ObjectiveEffect
from fdai.core.operational_context import OperationalContextSnapshot

from .models import SimulationReceipt, SimulationStatus


class AssuranceTwinPlanningSimulator:
    """Apply active and challenger effect models without selecting execution."""

    def __init__(
        self,
        *,
        model_reader: EffectModelReader,
        causal_evidence_verifier: EffectModelCausalEvidenceVerifier,
        divergence_threshold: float = 0.0,
        clock: Callable[[], datetime],
    ) -> None:
        if divergence_threshold < 0.0:
            raise ValueError("planning twin divergence threshold MUST be non-negative")
        self._model_reader = model_reader
        self._causal_evidence_verifier = causal_evidence_verifier
        self._divergence_threshold = divergence_threshold
        self._clock = clock

    async def simulate(
        self,
        *,
        context: OperationalContextSnapshot,
        candidate_id: str,
        action_type: str | None,
        effects: tuple[ObjectiveEffect, ...],
        observed_at: datetime,
    ) -> SimulationReceipt:
        started_at = self._clock()
        if action_type is None:
            return self._unscorable(
                context=context,
                candidate_id=candidate_id,
                started_at=started_at,
                reason="action_type_missing",
            )
        predicted: list[ObjectiveEffect] = []
        evidence_refs: list[str] = []
        requires_review = False
        for effect in sorted(effects, key=lambda item: (item.objective_id, item.metric)):
            active = await self._model_reader.get(
                status=EffectModelStatus.ACTIVE,
                action_type_id=action_type,
                metric=effect.metric,
            )
            challenger = await self._model_reader.get(
                status=EffectModelStatus.CHALLENGER,
                action_type_id=action_type,
                metric=effect.metric,
            )
            if active is None or not self._verified(active, observed_at=observed_at):
                return self._unscorable(
                    context=context,
                    candidate_id=candidate_id,
                    started_at=started_at,
                    reason=f"active_model_unavailable:{effect.metric}",
                )
            if challenger is not None and not self._verified(challenger, observed_at=observed_at):
                return self._unscorable(
                    context=context,
                    candidate_id=candidate_id,
                    started_at=started_at,
                    reason=f"challenger_model_unverified:{effect.metric}",
                )
            midpoint = (effect.expected_min + effect.expected_max) / 2.0
            radius = (effect.expected_max - effect.expected_min) / 2.0
            snapshot = SimulationSnapshot(
                snapshot_id=context.snapshot_id,
                target_digest=hashlib.sha256(context.target_resource_id.encode()).hexdigest(),
                metric=effect.metric,
                observed_at=observed_at,
            )
            result = simulate_effect_branches(
                snapshot=snapshot,
                branches=(SimulationBranch(candidate_id, action_type, midpoint, radius),),
                active_models={action_type: active},
                challenger_models={action_type: challenger} if challenger is not None else {},
                objective="maximize",
                divergence_threshold=self._divergence_threshold,
            )
            branch = result.predictions[0]
            if branch.active_min is None or branch.active_max is None:
                return self._unscorable(
                    context=context,
                    candidate_id=candidate_id,
                    started_at=started_at,
                    reason=f"prediction_unavailable:{effect.metric}",
                )
            requires_review = requires_review or branch.requires_review
            evidence_refs.append(branch.active_model_ref or "")
            if branch.challenger_model_ref is not None:
                evidence_refs.append(branch.challenger_model_ref)
            predicted.append(
                ObjectiveEffect(
                    objective_id=effect.objective_id,
                    utility=effect.utility,
                    confidence=effect.confidence,
                    metric=effect.metric,
                    expected_min=branch.active_min,
                    expected_max=branch.active_max,
                    observation_window_seconds=effect.observation_window_seconds,
                )
            )
        finalized_evidence = tuple(sorted({ref for ref in evidence_refs if ref}))
        identity = hashlib.sha256(
            f"{context.snapshot_id}:{candidate_id}:{action_type}:{finalized_evidence}".encode()
        ).hexdigest()
        return SimulationReceipt(
            receipt_id=f"simulation:{identity}",
            candidate_id=candidate_id,
            snapshot_id=context.snapshot_id,
            logic_invocation_id=f"logic-invocation:{identity}",
            status=SimulationStatus.SUCCEEDED,
            started_at=started_at,
            completed_at=self._clock(),
            evidence_refs=finalized_evidence,
            predicted_effects=tuple(predicted),
            requires_review=requires_review,
            reason="model_divergence" if requires_review else "simulation_completed",
        )

    def _verified(self, model: EffectModel, *, observed_at: datetime) -> bool:
        return model.learned_through <= observed_at and self._causal_evidence_verifier.verify(model)

    def _unscorable(
        self,
        *,
        context: OperationalContextSnapshot,
        candidate_id: str,
        started_at: datetime,
        reason: str,
    ) -> SimulationReceipt:
        identity = hashlib.sha256(
            f"{context.snapshot_id}:{candidate_id}:{reason}".encode()
        ).hexdigest()
        return SimulationReceipt(
            receipt_id=f"simulation:{identity}",
            candidate_id=candidate_id,
            snapshot_id=context.snapshot_id,
            logic_invocation_id=f"logic-invocation:{identity}",
            status=SimulationStatus.UNSCORABLE,
            started_at=started_at,
            completed_at=self._clock(),
            evidence_refs=(f"context:{context.snapshot_id}",),
            requires_review=True,
            reason=reason,
        )


__all__ = ["AssuranceTwinPlanningSimulator"]
