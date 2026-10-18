"""Activation-fenced publication runtime for qualified optimization plans."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from fdai.core.decision_case import ObjectiveEffect
from fdai.core.operational_context import SourceFreshness
from fdai.shared.providers.cost_governance import (
    CostOptimizationCandidatePublisher,
    CostPackageActivationReader,
)

from fdai_cost_governance.optimization import CoupledResourceOptimizationPlan
from fdai_cost_governance.pantheon_composition import (
    OptimizationReinjectionResult,
    compose_njord_optimization_candidate,
)


class OptimizationPublicationState(StrEnum):
    PUBLISHED = "published"
    HELD = "held"


@dataclass(frozen=True, slots=True)
class OptimizationPublicationResult:
    state: OptimizationPublicationState
    reason: str
    candidate: dict[str, object] | None = None


class CostOptimizationRuntime:
    """Publish only through canonical ingress under one exact activation revision."""

    def __init__(
        self,
        *,
        package_id: str,
        activation_reader: CostPackageActivationReader,
        publisher: CostOptimizationCandidatePublisher,
    ) -> None:
        if not package_id.strip() or package_id != package_id.strip():
            raise ValueError("optimization runtime package_id MUST be exact")
        self._package_id = package_id
        self._activation_reader = activation_reader
        self._publisher = publisher

    async def publish_plan(
        self,
        plan: CoupledResourceOptimizationPlan,
        *,
        correlation_id: str,
        observed_at: datetime,
        cost_objective_id: str,
        effects: tuple[ObjectiveEffect, ...],
        evidence_refs: tuple[str, ...],
        source_freshness: tuple[SourceFreshness, ...],
    ) -> OptimizationPublicationResult:
        candidate = compose_njord_optimization_candidate(
            plan,
            correlation_id=correlation_id,
            observed_at=observed_at,
            cost_objective_id=cost_objective_id,
            effects=effects,
            evidence_refs=evidence_refs,
            source_freshness=source_freshness,
        )
        return await self._publish(candidate)

    async def publish_reinjection(
        self,
        reinjection: OptimizationReinjectionResult,
    ) -> OptimizationPublicationResult:
        if reinjection.candidate is None:
            return OptimizationPublicationResult(
                state=OptimizationPublicationState.HELD,
                reason=reinjection.reason,
            )
        return await self._publish(reinjection.candidate)

    async def _publish(self, candidate: dict[str, object]) -> OptimizationPublicationResult:
        activation = await self._activation_reader.read_cost_activation(self._package_id)
        if (
            activation is None
            or activation.package_id != self._package_id
            or not activation.available
            or not activation.enabled
        ):
            return OptimizationPublicationResult(
                state=OptimizationPublicationState.HELD,
                reason="package_activation_unavailable",
            )
        await self._publisher.publish_cost_optimization_candidate(
            candidate,
            activation_revision=activation.revision,
        )
        return OptimizationPublicationResult(
            state=OptimizationPublicationState.PUBLISHED,
            reason="candidate_entered_typed_ingress",
            candidate=candidate,
        )


__all__ = [
    "CostOptimizationRuntime",
    "OptimizationPublicationResult",
    "OptimizationPublicationState",
]
