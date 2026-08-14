"""Deterministically evaluate T1 semantic proposals before bounded T2 escalation."""

from __future__ import annotations

import copy
import logging
from typing import Any, Protocol

from fdai_service_contracts.ontology_query import OntologyQueryPlan, SemanticProblemFrame
from pydantic import ValidationError

from fdai.core.ontology_platform import OntologyQueryPlanVerifier, QueryManifest

from .semantic_planning_models import (
    ClarificationRequirement,
    QueryPlanProposal,
    SemanticFrameProposal,
    SemanticPlanningModel,
)
from .session import Principal

_LOGGER = logging.getLogger(__name__)
_SERVER_BOUND_REQUIREMENTS = frozenset(
    {ClarificationRequirement.PRINCIPAL_SCOPE, ClarificationRequirement.PURPOSE}
)


class FrameBuilder(Protocol):
    def __call__(
        self,
        proposal: SemanticFrameProposal,
        *,
        utterance: str,
        context: tuple[str, ...],
    ) -> SemanticProblemFrame: ...


class PlanBuilder(Protocol):
    def __call__(
        self,
        proposal: QueryPlanProposal,
        *,
        frame: SemanticProblemFrame,
        manifest: QueryManifest,
        principal: Principal,
        purpose: str,
    ) -> OntologyQueryPlan: ...


class ProposalRejectedError(RuntimeError):
    """Report the final rejected proposal stage without retaining model input."""

    def __init__(self, stage: str, failure_type: str) -> None:
        super().__init__(stage)
        self.stage = stage
        self.failure_type = failure_type


class SemanticPlanningCascade:
    """Try T1 first and retry one failed proposal stage with optional T2."""

    def __init__(
        self,
        *,
        model: SemanticPlanningModel,
        escalation_model: SemanticPlanningModel | None,
        verifier: OntologyQueryPlanVerifier,
        frame_builder: FrameBuilder,
        plan_builder: PlanBuilder,
    ) -> None:
        self._model = model
        self._escalation_model = escalation_model
        self._verifier = verifier
        self._frame_builder = frame_builder
        self._plan_builder = plan_builder

    def propose_frame(
        self,
        *,
        utterance: str,
        context: tuple[str, ...],
        descriptors: tuple[dict[str, Any], ...],
        principal: Principal,
        purpose: str,
    ) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
        for tier, model in self._planning_models():
            raw = model.propose_frame(
                utterance=utterance,
                context=context,
                descriptors=copy.deepcopy(descriptors),
                principal_role=principal.role.value,
                purpose=purpose,
            )
            if raw is None:
                if self._should_escalate(tier=tier, stage="frame", reason="unavailable"):
                    continue
                return None
            try:
                proposal = SemanticFrameProposal.model_validate(raw)
                _validate_frame_proposal(proposal)
            except (ValidationError, TypeError, ValueError) as exc:
                if self._should_escalate(tier=tier, stage="frame", reason="invalid"):
                    continue
                raise ProposalRejectedError("frame_validation", type(exc).__name__) from exc
            try:
                frame = self._frame_builder(proposal, utterance=utterance, context=context)
            except (TypeError, ValueError) as exc:
                if self._should_escalate(tier=tier, stage="frame", reason="invalid"):
                    continue
                raise ProposalRejectedError("frame_build", type(exc).__name__) from exc
            return proposal, frame
        return None

    def propose_plan(
        self,
        *,
        frame: SemanticProblemFrame,
        descriptors: tuple[dict[str, Any], ...],
        principal: Principal,
        purpose: str,
        manifest: QueryManifest,
    ) -> OntologyQueryPlan | None:
        for tier, model in self._planning_models():
            raw = model.propose_plan(
                frame=frame,
                descriptors=copy.deepcopy(descriptors),
                principal_role=principal.role.value,
                purpose=purpose,
            )
            if raw is None:
                if self._should_escalate(tier=tier, stage="plan", reason="unavailable"):
                    continue
                return None
            try:
                proposal = QueryPlanProposal.model_validate(raw)
            except (ValidationError, TypeError, ValueError) as exc:
                if self._should_escalate(tier=tier, stage="plan", reason="invalid"):
                    continue
                raise ProposalRejectedError("plan_validation", type(exc).__name__) from exc
            try:
                plan = self._plan_builder(
                    proposal,
                    frame=frame,
                    manifest=manifest,
                    principal=principal,
                    purpose=purpose,
                )
            except (TypeError, ValueError) as exc:
                if self._should_escalate(tier=tier, stage="plan", reason="invalid"):
                    continue
                raise ProposalRejectedError("plan_build", type(exc).__name__) from exc
            try:
                self._verifier.verify(plan, manifest=manifest)
            except ValueError as exc:
                if self._should_escalate(tier=tier, stage="plan", reason="invalid"):
                    continue
                raise ProposalRejectedError("plan_verify", type(exc).__name__) from exc
            return plan
        return None

    def _planning_models(self) -> tuple[tuple[str, SemanticPlanningModel], ...]:
        if self._escalation_model is None:
            return (("t1", self._model),)
        return (("t1", self._model), ("t2", self._escalation_model))

    def _should_escalate(self, *, tier: str, stage: str, reason: str) -> bool:
        if tier != "t1" or self._escalation_model is None:
            return False
        _LOGGER.info(
            "semantic_planning_t2_escalated",
            extra={"stage": stage, "reason": reason},
        )
        return True


def _validate_frame_proposal(proposal: SemanticFrameProposal) -> None:
    if _SERVER_BOUND_REQUIREMENTS.intersection(proposal.clarification_requirements):
        raise ValueError("semantic clarification requests server-bound context")


__all__ = ["ProposalRejectedError", "SemanticPlanningCascade"]
