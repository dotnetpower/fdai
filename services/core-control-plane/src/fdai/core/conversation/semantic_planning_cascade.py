"""Deterministically evaluate T1 semantic proposals before bounded T2 escalation."""

from __future__ import annotations

import copy
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from fdai_service_contracts.ontology_query import (
    OntologyQueryPlan,
    SemanticOperation,
    SemanticProblemFrame,
)
from pydantic import ValidationError

from fdai.core.ontology_platform import OntologyQueryPlanVerifier, QueryManifest
from fdai.rule_catalog.schema.inventory_query_language import InventoryQueryLanguageRegistry

from .semantic_activity_planning import normalize_activity_proposal
from .semantic_current_state_planning import normalize_current_state_proposal
from .semantic_ingress_planning import normalize_ingress_proposal
from .semantic_investigation import (
    VerifiedInvestigationIntent,
    normalize_investigation_competitors,
    normalize_investigation_relationships,
    normalize_investigation_symptom,
    normalize_investigation_target,
    verify_investigation_intent,
)
from .semantic_planning_alignment import verify_frame_plan_alignment
from .semantic_planning_cascade_judgment import (
    _judgment_link_subjects,
    _judgment_non_resource_target_clarification,
    _judgment_object_subjects,
    _non_resource_proposal_subjects,
)
from .semantic_planning_cascade_validation import (
    _safe_frame_rejection_reason,
    _validate_frame_proposal,
)
from .semantic_planning_frame import (
    build_semantic_frame,
    canonicalize_semantic_judgment_frame_proposal,
)
from .semantic_planning_frame_normalization import (
    normalize_bound_latency_recovery,
    normalize_missing_mysql_pressure_investigation,
    normalize_missing_resource_slowness_investigation,
    normalize_missing_vm_cpu_investigation,
    normalize_network_application_latency_investigation,
)
from .semantic_planning_models import (
    BoundInvestigationContinuation,
    ClarificationRequirement,
    QueryPlanProposal,
    SemanticFrameProposal,
    SemanticOutputShape,
    SemanticPlanningEscalationModel,
    SemanticPlanningModel,
)
from .semantic_resource_metric_planning import normalize_exact_resource_metric_proposal
from .semantic_resource_state_planning import normalize_resource_state_proposal
from .semantic_service_health_planning import normalize_service_health_event_types
from .semantic_target_candidate_planning import (
    build_non_resource_target_clarification,
    build_resource_target_candidates_fallback,
    build_stated_resource_filter_frame,
    normalize_resource_list_temporal_scope,
    resolve_stated_resource_identity,
    resource_target_candidates_apply_to_proposal,
)
from .session import Principal

_LOGGER = logging.getLogger(__name__)


class FrameBuilder(Protocol):
    def __call__(
        self,
        proposal: SemanticFrameProposal,
        *,
        utterance: str,
        context: tuple[str, ...],
        investigation_intent: VerifiedInvestigationIntent | None,
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
        evaluation_time: datetime,
    ) -> OntologyQueryPlan: ...


class ProposalRejectedError(RuntimeError):
    """Report the final rejected proposal stage without retaining model input."""

    def __init__(self, stage: str, failure_type: str) -> None:
        super().__init__(stage)
        self.stage = stage
        self.failure_type = failure_type


class SemanticPlanningEscalationTrigger(StrEnum):
    """Typed T1 outcomes that an escalation policy may admit to T2."""

    FRAME_UNAVAILABLE = "frame_unavailable"
    FRAME_CLARIFICATION = "frame_clarification"
    FRAME_SCHEMA_INVALID = "frame_schema_invalid"
    FRAME_BUILD_REJECTED = "frame_build_rejected"
    PLAN_UNAVAILABLE = "plan_unavailable"
    PLAN_SCHEMA_INVALID = "plan_schema_invalid"
    PLAN_BUILD_REJECTED = "plan_build_rejected"
    PLAN_VERIFICATION_REJECTED = "plan_verification_rejected"


@dataclass(frozen=True, slots=True)
class SemanticPlanningEscalationPolicy:
    """Allow only explicitly listed T1 outcomes to spend T2 capacity."""

    allowed_triggers: frozenset[SemanticPlanningEscalationTrigger]

    def allows(self, trigger: SemanticPlanningEscalationTrigger) -> bool:
        """Return whether one typed T1 outcome may retry the same stage with T2."""

        return trigger in self.allowed_triggers


BOUNDED_T2_ESCALATION_POLICY = SemanticPlanningEscalationPolicy(
    allowed_triggers=frozenset(
        {
            SemanticPlanningEscalationTrigger.FRAME_UNAVAILABLE,
            SemanticPlanningEscalationTrigger.PLAN_UNAVAILABLE,
        }
    )
)
AGGRESSIVE_T2_ESCALATION_POLICY = SemanticPlanningEscalationPolicy(
    allowed_triggers=frozenset(SemanticPlanningEscalationTrigger)
)
NO_T2_ESCALATION_POLICY = SemanticPlanningEscalationPolicy(allowed_triggers=frozenset())
_T2_ELIGIBLE_CLARIFICATIONS = frozenset(
    {
        ClarificationRequirement.MEASURE,
        ClarificationRequirement.RESOURCE_IDENTITY,
        ClarificationRequirement.SUBJECT,
    }
)
_NON_ESCALATABLE_FRAME_REASONS = frozenset({"semantic clarification requests server-bound context"})


class SemanticPlanningCascade:
    """Try T1 first and apply an explicit policy to any optional T2 retry."""

    def __init__(
        self,
        *,
        model: SemanticPlanningModel,
        escalation_model: SemanticPlanningModel | None,
        verifier: OntologyQueryPlanVerifier,
        frame_builder: FrameBuilder,
        plan_builder: PlanBuilder,
        inventory_query_language: InventoryQueryLanguageRegistry | None = None,
        escalation_policy: SemanticPlanningEscalationPolicy = BOUNDED_T2_ESCALATION_POLICY,
    ) -> None:
        self._model = model
        self._escalation_model = escalation_model
        self._escalation_policy = escalation_policy
        self._verifier = verifier
        self._frame_builder = frame_builder
        self._plan_builder = plan_builder
        self._inventory_query_language = inventory_query_language

    def propose_frame(
        self,
        *,
        utterance: str,
        context: tuple[str, ...],
        descriptors: tuple[dict[str, Any], ...],
        metric_concepts: tuple[str, ...],
        principal: Principal,
        purpose: str,
        semantic_judgment: Mapping[str, Any] | None = None,
        bound_investigation_continuation: BoundInvestigationContinuation | None = None,
        escalation_policy: SemanticPlanningEscalationPolicy | None = None,
    ) -> (
        tuple[
            SemanticFrameProposal,
            SemanticProblemFrame,
            VerifiedInvestigationIntent | None,
        ]
        | None
    ):
        recovery_context: dict[str, str] | None = None
        t1_clarification: (
            tuple[
                SemanticFrameProposal,
                SemanticProblemFrame,
                VerifiedInvestigationIntent | None,
            ]
            | None
        ) = None
        stated_filter = build_stated_resource_filter_frame(
            semantic_judgment=semantic_judgment,
            utterance=utterance,
            context=context,
            descriptors=descriptors,
        )
        if stated_filter is not None:
            _LOGGER.info(
                "semantic_planning_candidate_recovered",
                extra={"stage": "judgment", "recovery": "stated_resource_filter"},
            )
            return (*stated_filter, None)
        if (
            semantic_judgment is not None
            and semantic_judgment.get("primary_intent") == "query.resource_current_state"
            and "cause" not in semantic_judgment.get("requested_facets", ())
            and semantic_judgment.get("action_posture") == "advise_only"
            and semantic_judgment.get("execution_authority") is False
        ):
            current_state = _current_state_clarification_fallback(
                semantic_judgment=semantic_judgment,
                utterance=utterance,
                context=context,
                descriptors=descriptors,
                confidence=float(semantic_judgment.get("confidence", 0.0)),
            )
            if current_state is not None:
                _LOGGER.info(
                    "semantic_planning_candidate_recovered",
                    extra={"stage": "judgment", "recovery": "current_state"},
                )
                return (*current_state, None)
        if (
            semantic_judgment is not None
            and semantic_judgment.get("action_posture") == "advise_only"
            and "cause" in semantic_judgment.get("requested_facets", ())
        ):
            candidate = build_resource_target_candidates_fallback(
                utterance=utterance,
                context=context,
                descriptors=descriptors,
                confidence=float(semantic_judgment.get("confidence", 0.0)),
                inventory_query_language=self._inventory_query_language,
                temporal_scope=_judgment_candidate_temporal_scope(semantic_judgment),
            )
            if candidate is not None:
                _LOGGER.info(
                    "semantic_planning_candidate_recovered",
                    extra={
                        "stage": "judgment",
                        "recovery": "resource_target_candidates",
                    },
                )
                return (*candidate, None)
        for tier, model in self._planning_models():
            raw = _propose_frame(
                model,
                utterance=utterance,
                context=context,
                descriptors=copy.deepcopy(descriptors),
                metric_concepts=metric_concepts,
                principal_role=principal.role.value,
                purpose=purpose,
                semantic_judgment=copy.deepcopy(semantic_judgment),
                recovery_context=recovery_context if tier == "t2" else None,
            )
            if raw is None:
                if tier == "t1":
                    clarification = _judgment_non_resource_target_clarification(
                        None,
                        semantic_judgment=semantic_judgment,
                        utterance=utterance,
                        context=context,
                        descriptors=descriptors,
                        inventory_query_language=self._inventory_query_language,
                    )
                    if clarification is not None:
                        _LOGGER.info(
                            "semantic_planning_candidate_recovered",
                            extra={
                                "stage": "frame_unavailable",
                                "recovery": "non_resource_target_clarification",
                            },
                        )
                        return (*clarification, None)
                    current_state_clarification = _current_state_clarification_fallback(
                        semantic_judgment=semantic_judgment,
                        utterance=utterance,
                        context=context,
                        descriptors=descriptors,
                        confidence=0.0,
                    )
                    if current_state_clarification is not None:
                        return (*current_state_clarification, None)
                    fallback = build_resource_target_candidates_fallback(
                        utterance=utterance,
                        context=context,
                        descriptors=descriptors,
                        confidence=0.0,
                        inventory_query_language=self._inventory_query_language,
                        temporal_scope=_judgment_candidate_temporal_scope(semantic_judgment),
                    )
                    if fallback is not None:
                        _LOGGER.info(
                            "semantic_planning_candidate_recovered",
                            extra={
                                "stage": "frame_unavailable",
                                "recovery": "resource_target_candidates",
                            },
                        )
                        return (*fallback, None)
                if _read_only_escalation_allowed(
                    semantic_judgment,
                    proposal=None,
                ) and self._should_escalate(
                    tier=tier,
                    trigger=SemanticPlanningEscalationTrigger.FRAME_UNAVAILABLE,
                    escalation_policy=escalation_policy,
                ):
                    recovery_context = _recovery_context(
                        "frame",
                        SemanticPlanningEscalationTrigger.FRAME_UNAVAILABLE,
                    )
                    continue
                if tier == "t2" and t1_clarification is not None:
                    return t1_clarification
                return None
            proposal: SemanticFrameProposal | None = None
            try:
                proposal = SemanticFrameProposal.model_validate(raw)
                proposal = normalize_activity_proposal(
                    proposal,
                    utterance=utterance,
                    descriptors=descriptors,
                    inventory_query_language=self._inventory_query_language,
                )
                proposal = normalize_ingress_proposal(proposal, descriptors=descriptors)
                proposal = normalize_current_state_proposal(
                    proposal,
                    utterance=utterance,
                    descriptors=descriptors,
                )
                proposal = normalize_exact_resource_metric_proposal(
                    proposal,
                    utterance=utterance,
                    descriptors=descriptors,
                )
                proposal = normalize_resource_state_proposal(
                    proposal,
                    utterance=utterance,
                    descriptors=descriptors,
                    inventory_query_language=self._inventory_query_language,
                )
                service_health = normalize_service_health_event_types(
                    proposal,
                    utterance=utterance,
                    context=context,
                    inventory_query_language=self._inventory_query_language,
                )
                if service_health is not None:
                    proposal, _service_health_frame = service_health
                proposal = normalize_resource_list_temporal_scope(
                    proposal,
                    utterance=utterance,
                    inventory_query_language=self._inventory_query_language,
                )
                proposal = resolve_stated_resource_identity(
                    proposal,
                    utterance=utterance,
                    descriptors=descriptors,
                )
                proposal = canonicalize_semantic_judgment_frame_proposal(
                    proposal,
                    judgment=semantic_judgment,
                )
                proposal = normalize_bound_latency_recovery(
                    proposal,
                    continuation=bound_investigation_continuation,
                    semantic_judgment=semantic_judgment,
                )
                target_candidate = (
                    _candidate_frame_fallback(
                        tier=tier,
                        proposal=proposal,
                        semantic_judgment=semantic_judgment,
                        utterance=utterance,
                        context=context,
                        descriptors=descriptors,
                        inventory_query_language=self._inventory_query_language,
                    )
                    if proposal.output_shape is SemanticOutputShape.CAUSAL_EVIDENCE
                    else None
                )
                if target_candidate is not None:
                    return (*target_candidate, None)
                proposal = normalize_missing_vm_cpu_investigation(
                    proposal,
                    utterance=utterance,
                    descriptors=descriptors,
                    metric_concepts=metric_concepts,
                    inventory_query_language=self._inventory_query_language,
                )
                proposal = normalize_missing_mysql_pressure_investigation(
                    proposal,
                    utterance=utterance,
                    descriptors=descriptors,
                    metric_concepts=metric_concepts,
                    inventory_query_language=self._inventory_query_language,
                )
                proposal = normalize_network_application_latency_investigation(
                    proposal,
                    utterance=utterance,
                    descriptors=descriptors,
                    metric_concepts=metric_concepts,
                    inventory_query_language=self._inventory_query_language,
                )
                proposal = normalize_missing_resource_slowness_investigation(
                    proposal,
                    utterance=utterance,
                    descriptors=descriptors,
                    metric_concepts=metric_concepts,
                    inventory_query_language=self._inventory_query_language,
                    semantic_judgment=semantic_judgment,
                )
                if proposal.investigation is not None:
                    investigation = normalize_investigation_symptom(
                        proposal.investigation,
                        utterance=utterance,
                        metric_concepts=metric_concepts,
                        inventory_query_language=self._inventory_query_language,
                    )
                    investigation = normalize_investigation_competitors(investigation)
                    investigation = normalize_investigation_target(
                        investigation,
                        subject_constraints=proposal.subject_constraints,
                        utterance=utterance,
                        descriptors=descriptors,
                    )
                    investigation = normalize_investigation_relationships(
                        investigation,
                        descriptors=descriptors,
                    )
                    proposal = proposal.model_copy(
                        update={
                            "measure_concepts": tuple(
                                measure.concept_id for measure in investigation.symptom_measures
                            ),
                            "investigation": investigation,
                        }
                    )
                _validate_frame_proposal(proposal, utterance=utterance, descriptors=descriptors)
                investigation_intent = (
                    verify_investigation_intent(
                        proposal.investigation,
                        utterance=utterance,
                        descriptors=descriptors,
                        metric_concepts=metric_concepts,
                    )
                    if proposal.investigation is not None
                    else None
                )
            except (ValidationError, TypeError, ValueError) as exc:
                fallback = _candidate_frame_fallback(
                    tier=tier,
                    proposal=proposal,
                    semantic_judgment=semantic_judgment,
                    utterance=utterance,
                    context=context,
                    descriptors=descriptors,
                    inventory_query_language=self._inventory_query_language,
                )
                if fallback is not None:
                    return (*fallback, None)
                if _read_only_escalation_allowed(
                    semantic_judgment,
                    proposal=proposal,
                ) and self._should_escalate(
                    tier=tier,
                    trigger=SemanticPlanningEscalationTrigger.FRAME_SCHEMA_INVALID,
                    escalation_policy=escalation_policy,
                    validation_reason=_safe_frame_rejection_reason(exc),
                ):
                    recovery_context = _recovery_context(
                        "frame",
                        SemanticPlanningEscalationTrigger.FRAME_SCHEMA_INVALID,
                        _safe_frame_rejection_reason(exc),
                    )
                    continue
                if tier == "t2" and t1_clarification is not None:
                    return t1_clarification
                raise ProposalRejectedError("frame_validation", type(exc).__name__) from exc
            try:
                frame = self._frame_builder(
                    proposal,
                    utterance=utterance,
                    context=context,
                    investigation_intent=investigation_intent,
                )
            except (TypeError, ValueError) as exc:
                fallback = _candidate_frame_fallback(
                    tier=tier,
                    proposal=proposal,
                    semantic_judgment=semantic_judgment,
                    utterance=utterance,
                    context=context,
                    descriptors=descriptors,
                    inventory_query_language=self._inventory_query_language,
                )
                if fallback is not None:
                    return (*fallback, None)
                if _read_only_escalation_allowed(
                    semantic_judgment,
                    proposal=proposal,
                ) and self._should_escalate(
                    tier=tier,
                    trigger=SemanticPlanningEscalationTrigger.FRAME_BUILD_REJECTED,
                    escalation_policy=escalation_policy,
                ):
                    recovery_context = _recovery_context(
                        "frame",
                        SemanticPlanningEscalationTrigger.FRAME_BUILD_REJECTED,
                    )
                    continue
                if tier == "t2" and t1_clarification is not None:
                    return t1_clarification
                raise ProposalRejectedError("frame_build", type(exc).__name__) from exc
            clarification = _judgment_non_resource_target_clarification(
                proposal,
                semantic_judgment=semantic_judgment,
                utterance=utterance,
                context=context,
                descriptors=descriptors,
                inventory_query_language=self._inventory_query_language,
            )
            if clarification is None:
                clarification = build_non_resource_target_clarification(
                    proposal,
                    utterance=utterance,
                    context=context,
                    descriptors=descriptors,
                    inventory_query_language=self._inventory_query_language,
                )
            if clarification is not None:
                if tier == "t2" and t1_clarification is not None:
                    return t1_clarification
                _LOGGER.info(
                    "semantic_planning_candidate_recovered",
                    extra={"stage": "frame", "recovery": "non_resource_target_clarification"},
                )
                return (*clarification, None)
            if (
                tier == "t1"
                and proposal.operation is not SemanticOperation.ACTION_DRAFT
                and proposal.clarification_requirements
                and set(proposal.clarification_requirements) <= _T2_ELIGIBLE_CLARIFICATIONS
                and self._should_escalate(
                    tier=tier,
                    trigger=SemanticPlanningEscalationTrigger.FRAME_CLARIFICATION,
                    escalation_policy=escalation_policy,
                )
            ):
                t1_clarification = (proposal, frame, investigation_intent)
                recovery_context = _recovery_context(
                    "frame",
                    SemanticPlanningEscalationTrigger.FRAME_CLARIFICATION,
                    ",".join(item.value for item in proposal.clarification_requirements),
                )
                continue
            if (
                tier == "t2"
                and t1_clarification is not None
                and proposal.clarification_requirements
            ):
                return t1_clarification
            return proposal, frame, investigation_intent
        return t1_clarification

    def propose_plan(
        self,
        *,
        frame: SemanticProblemFrame,
        descriptors: tuple[dict[str, Any], ...],
        metric_concepts: tuple[str, ...],
        principal: Principal,
        purpose: str,
        manifest: QueryManifest,
        evaluation_time: datetime,
        escalation_policy: SemanticPlanningEscalationPolicy | None = None,
    ) -> OntologyQueryPlan | None:
        recovery_context: dict[str, str] | None = None
        for tier, model in self._planning_models():
            raw = _propose_plan(
                model,
                frame=frame,
                descriptors=copy.deepcopy(descriptors),
                metric_concepts=metric_concepts,
                principal_role=principal.role.value,
                purpose=purpose,
                evaluation_time=evaluation_time,
                recovery_context=recovery_context if tier == "t2" else None,
            )
            if raw is None:
                if self._should_escalate(
                    tier=tier,
                    trigger=SemanticPlanningEscalationTrigger.PLAN_UNAVAILABLE,
                    escalation_policy=escalation_policy,
                ):
                    recovery_context = _recovery_context(
                        "plan",
                        SemanticPlanningEscalationTrigger.PLAN_UNAVAILABLE,
                    )
                    continue
                return None
            try:
                proposal = QueryPlanProposal.model_validate(raw)
            except (ValidationError, TypeError, ValueError) as exc:
                if self._should_escalate(
                    tier=tier,
                    trigger=SemanticPlanningEscalationTrigger.PLAN_SCHEMA_INVALID,
                    escalation_policy=escalation_policy,
                ):
                    recovery_context = _recovery_context(
                        "plan",
                        SemanticPlanningEscalationTrigger.PLAN_SCHEMA_INVALID,
                    )
                    continue
                raise ProposalRejectedError("plan_validation", type(exc).__name__) from exc
            try:
                plan = self._plan_builder(
                    proposal,
                    frame=frame,
                    manifest=manifest,
                    principal=principal,
                    purpose=purpose,
                    evaluation_time=evaluation_time,
                )
            except (TypeError, ValueError) as exc:
                if self._should_escalate(
                    tier=tier,
                    trigger=SemanticPlanningEscalationTrigger.PLAN_BUILD_REJECTED,
                    escalation_policy=escalation_policy,
                ):
                    recovery_context = _recovery_context(
                        "plan",
                        SemanticPlanningEscalationTrigger.PLAN_BUILD_REJECTED,
                    )
                    continue
                raise ProposalRejectedError("plan_build", type(exc).__name__) from exc
            try:
                self._verifier.verify(plan, manifest=manifest)
                verify_frame_plan_alignment(frame, plan, descriptors=manifest.descriptors)
            except ValueError as exc:
                if self._should_escalate(
                    tier=tier,
                    trigger=SemanticPlanningEscalationTrigger.PLAN_VERIFICATION_REJECTED,
                    escalation_policy=escalation_policy,
                ):
                    recovery_context = _recovery_context(
                        "plan",
                        SemanticPlanningEscalationTrigger.PLAN_VERIFICATION_REJECTED,
                    )
                    continue
                raise ProposalRejectedError("plan_verify", type(exc).__name__) from exc
            return plan
        return None

    def _planning_models(self) -> tuple[tuple[str, SemanticPlanningModel], ...]:
        if self._escalation_model is None:
            return (("t1", self._model),)
        return (("t1", self._model), ("t2", self._escalation_model))

    def _should_escalate(
        self,
        *,
        tier: str,
        trigger: SemanticPlanningEscalationTrigger,
        escalation_policy: SemanticPlanningEscalationPolicy | None,
        validation_reason: str | None = None,
    ) -> bool:
        if tier != "t1" or self._escalation_model is None:
            return False
        policy = escalation_policy or self._escalation_policy
        if (
            trigger is SemanticPlanningEscalationTrigger.FRAME_SCHEMA_INVALID
            and validation_reason in _NON_ESCALATABLE_FRAME_REASONS
        ):
            _LOGGER.info(
                "semantic_planning_t2_withheld",
                extra={"trigger": trigger.value, "validation_reason": validation_reason},
            )
            return False
        if not policy.allows(trigger):
            _LOGGER.info(
                "semantic_planning_t2_withheld",
                extra={"trigger": trigger.value, "validation_reason": validation_reason},
            )
            return False
        _LOGGER.info(
            "semantic_planning_t2_escalated",
            extra={"trigger": trigger.value, "validation_reason": validation_reason},
        )
        return True


def _propose_frame(
    model: SemanticPlanningModel,
    *,
    recovery_context: Mapping[str, str] | None,
    **kwargs: Any,
) -> Mapping[str, Any] | None:
    if recovery_context is not None and isinstance(model, SemanticPlanningEscalationModel):
        return model.propose_escalated_frame(
            **kwargs,
            recovery_context=recovery_context,
        )
    return model.propose_frame(**kwargs)


def _propose_plan(
    model: SemanticPlanningModel,
    *,
    recovery_context: Mapping[str, str] | None,
    **kwargs: Any,
) -> Mapping[str, Any] | None:
    if recovery_context is not None and isinstance(model, SemanticPlanningEscalationModel):
        return model.propose_escalated_plan(
            **kwargs,
            recovery_context=recovery_context,
        )
    return model.propose_plan(**kwargs)


def _recovery_context(
    stage: str,
    trigger: SemanticPlanningEscalationTrigger,
    reason: str | None = None,
) -> dict[str, str]:
    context = {"stage": stage, "trigger": trigger.value}
    if reason:
        context["reason"] = reason[:256]
    return context


def _read_only_escalation_allowed(
    semantic_judgment: Mapping[str, Any] | None,
    *,
    proposal: SemanticFrameProposal | None,
) -> bool:
    if proposal is not None and proposal.operation is SemanticOperation.ACTION_DRAFT:
        return False
    return semantic_judgment is None or semantic_judgment.get("action_posture") != "draft_only"


def _candidate_frame_fallback(
    *,
    tier: str,
    proposal: SemanticFrameProposal | None,
    semantic_judgment: Mapping[str, Any] | None,
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
    inventory_query_language: InventoryQueryLanguageRegistry | None,
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    if tier != "t1" or (
        proposal is not None and proposal.operation is SemanticOperation.ACTION_DRAFT
    ):
        return None
    judgment_clarification = _judgment_non_resource_target_clarification(
        proposal,
        semantic_judgment=semantic_judgment,
        utterance=utterance,
        context=context,
        descriptors=descriptors,
        inventory_query_language=inventory_query_language,
    )
    if judgment_clarification is not None:
        _LOGGER.info(
            "semantic_planning_candidate_recovered",
            extra={"stage": "frame", "recovery": "non_resource_target_clarification"},
        )
        return judgment_clarification
    current_state_clarification = _current_state_clarification_fallback(
        semantic_judgment=semantic_judgment,
        utterance=utterance,
        context=context,
        descriptors=descriptors,
        confidence=proposal.confidence if proposal is not None else 0.0,
    )
    if current_state_clarification is not None:
        _LOGGER.info(
            "semantic_planning_candidate_recovered",
            extra={"stage": "frame", "recovery": "current_state_clarification"},
        )
        return current_state_clarification
    if proposal is not None:
        _LOGGER.info(
            "semantic_planning_candidate_recovery_unavailable",
            extra={
                "operation": proposal.operation.value,
                "output_shape": proposal.output_shape.value,
                "proposal_object_subjects": ",".join(
                    _non_resource_proposal_subjects(proposal, descriptors=descriptors)
                ),
            },
        )
    if proposal is None:
        return None
    clarification = build_non_resource_target_clarification(
        proposal,
        utterance=utterance,
        context=context,
        descriptors=descriptors,
        inventory_query_language=inventory_query_language,
    )
    if clarification is not None:
        _LOGGER.info(
            "semantic_planning_candidate_recovered",
            extra={"stage": "frame", "recovery": "non_resource_target_clarification"},
        )
        return clarification
    if proposal.output_shape is SemanticOutputShape.RESOURCE_TARGET_CANDIDATES:
        return None
    if not resource_target_candidates_apply_to_proposal(
        proposal,
        utterance=utterance,
        descriptors=descriptors,
        inventory_query_language=inventory_query_language,
    ):
        return None
    fallback = build_resource_target_candidates_fallback(
        utterance=utterance,
        context=context,
        descriptors=descriptors,
        confidence=proposal.confidence,
        inventory_query_language=inventory_query_language,
        temporal_scope=(
            proposal.temporal_scope or _judgment_candidate_temporal_scope(semantic_judgment)
        ),
    )
    if fallback is not None:
        _LOGGER.info(
            "semantic_planning_candidate_recovered",
            extra={"stage": "frame", "recovery": "resource_target_candidates"},
        )
    return fallback


def _judgment_candidate_temporal_scope(
    semantic_judgment: Mapping[str, Any] | None,
) -> dict[str, str] | None:
    if semantic_judgment is None:
        return None
    return (
        {"kind": "current"}
        if semantic_judgment.get("primary_intent") == "query.resource_current_state"
        else None
    )


def _current_state_clarification_fallback(
    *,
    semantic_judgment: Mapping[str, Any] | None,
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
    confidence: float,
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    requested_facets = (
        semantic_judgment.get("requested_facets", ()) if semantic_judgment is not None else ()
    )
    targets = semantic_judgment.get("targets", ()) if semantic_judgment is not None else ()
    state_target_count = (
        sum(
            isinstance(target, Mapping) and target.get("kind") == "resource_state"
            for target in targets
        )
        if isinstance(targets, Sequence) and not isinstance(targets, (str, bytes))
        else 0
    )
    if (
        semantic_judgment is None
        or semantic_judgment.get("primary_intent") != "query.resource_current_state"
        or not isinstance(requested_facets, Sequence)
        or isinstance(requested_facets, (str, bytes))
        or "cause" in requested_facets
        or bool({"resource_state_inventory", "state_grouping"}.intersection(requested_facets))
        or state_target_count > 1
    ):
        return None
    proposal = normalize_current_state_proposal(
        SemanticFrameProposal(
            operation=SemanticOperation.SELECT,
            subject_constraints=("Resource",),
            measure_concepts=(),
            temporal_scope={},
            output_shape=SemanticOutputShape.TARGET_CURRENT_STATE,
            evidence_requirements=("authoritative_inventory",),
            unresolved_terms=(),
            clarification_requirements=(),
            clarification=None,
            investigation=None,
            confidence=confidence,
        ),
        utterance=utterance,
        descriptors=descriptors,
    )
    return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)


__all__ = [
    "AGGRESSIVE_T2_ESCALATION_POLICY",
    "BOUNDED_T2_ESCALATION_POLICY",
    "NO_T2_ESCALATION_POLICY",
    "ProposalRejectedError",
    "SemanticPlanningCascade",
    "SemanticPlanningEscalationPolicy",
    "SemanticPlanningEscalationTrigger",
    "_judgment_link_subjects",
    "_judgment_object_subjects",
    "_validate_frame_proposal",
]
