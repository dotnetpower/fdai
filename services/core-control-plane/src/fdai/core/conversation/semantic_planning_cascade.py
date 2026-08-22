"""Deterministically evaluate T1 semantic proposals before bounded T2 escalation."""

from __future__ import annotations

import copy
import logging
import re
from collections.abc import Mapping
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
from .semantic_current_state_planning import (
    exact_target_from_constraints,
    normalize_current_state_proposal,
)
from .semantic_ingress_planning import normalize_ingress_proposal
from .semantic_investigation import (
    VerifiedInvestigationIntent,
    normalize_investigation_competitors,
    normalize_investigation_relationships,
    normalize_investigation_symptom,
    normalize_investigation_target,
    verify_investigation_intent,
)
from .semantic_planning_alignment import (
    DECLARATION_SECTIONS_BY_MEASURE,
    verify_frame_plan_alignment,
)
from .semantic_planning_models import (
    ClarificationRequirement,
    QueryPlanProposal,
    SemanticFrameProposal,
    SemanticOutputShape,
    SemanticPlanningModel,
)
from .semantic_planning_value_filters import stated_value_filters
from .semantic_resource_metric_planning import normalize_exact_resource_metric_proposal
from .semantic_resource_state_planning import normalize_resource_state_proposal
from .semantic_target_candidate_planning import (
    build_resource_target_candidates_fallback,
    resource_target_candidates_apply_to_proposal,
)
from .session import Principal

_LOGGER = logging.getLogger(__name__)
_SERVER_BOUND_REQUIREMENTS = frozenset(
    {ClarificationRequirement.PRINCIPAL_SCOPE, ClarificationRequirement.PURPOSE}
)
_SCHEMA_LEVEL_OUTPUT_SHAPES = frozenset(
    {"ontology_declaration", "ontology_manifest", "ontology_relationships"}
)
# Provider inventory names one concrete instance with joined segments
# (`aks-fdai-observe-lab`). A declaration name is dotted or a single word, and a
# two-segment token is a product word (`gpt-4o`), so neither shape matches.
_RUNTIME_INSTANCE_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_.-])[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+){2,}(?![A-Za-z0-9_.-])"
)
_MAX_SCANNED_TOKENS = 32
_SPECIALIZED_OPERATIONS_BY_OUTPUT_SHAPE = {
    "contextual_resource_list": SemanticOperation.SELECT,
    "inventory_impact": SemanticOperation.SELECT,
    "resource_event_history": SemanticOperation.SELECT,
    "resource_health_list": SemanticOperation.SELECT,
    "resource_metric_list": SemanticOperation.SELECT,
    "resource_state_list": SemanticOperation.SELECT,
    "resource_target_candidates": SemanticOperation.SELECT,
    "subscription_service_health": SemanticOperation.SELECT,
    "target_activity": SemanticOperation.SELECT,
    "target_current_state": SemanticOperation.SELECT,
    "target_error_activity_correlation": SemanticOperation.COMPARE,
    "target_health_assessment": SemanticOperation.VALIDATE,
    "target_ingress_configuration": SemanticOperation.SELECT,
    "target_resource_metric": SemanticOperation.SELECT,
    "target_resource_metric_series": SemanticOperation.SELECT,
}
_SAFE_FRAME_REJECTION_REASONS = frozenset(
    {
        "causal investigation requires a diagnosis answer shape",
        "causal investigation requires an onset or change-point cue",
        "causal investigation requires support and refutation evidence",
        "explicit aggregation request requires aggregation_table output",
        "explicit impact request requires inventory_impact output",
        "explicit listing request cannot use aggregation_table output",
        "historical semantic request requires a temporal capability",
        "investigation entity ids MUST be unique",
        "investigation entity type is absent from the principal manifest",
        "investigation hypothesis competitors are invalid",
        "investigation hypothesis effect measure is unknown",
        "investigation hypothesis ids MUST be unique",
        "investigation hypothesis metric concept is unavailable",
        "investigation hypothesis relationship is unknown",
        "investigation intent MUST use explain_change",
        "investigation intent requires one affected target",
        "investigation measure ids MUST be unique",
        "investigation measure target is unknown",
        "investigation metric concept is unavailable",
        "investigation primary symptom measure is unknown",
        "investigation relationship endpoint is unknown",
        "investigation relationship ids MUST be unique",
        "investigation relationship side is absent from the manifest",
        "investigation relationship source type does not match",
        "investigation relationship target type does not match",
        "investigation source span does not match the utterance",
        "investigation utterance MUST be non-empty and bounded",
        "schema-level semantic frame names a runtime resource instance",
        "semantic aggregate operation requires aggregation_table output",
        "semantic clarification requests server-bound context",
        "semantic declaration frame requires an exact declaration measure",
        "semantic explain_change operation requires causal_evidence output",
        "semantic property-filter plan cannot use multiple existence-only predicates",
        "semantic Rule state frame requires the exact Rule declaration",
        "resource target candidates are server-owned",
        "specialized semantic output requires its fixed operation",
        "semantic validate operation requires evidence_validation output",
        "structured investigation intent requires semantic causal evidence",
        "target-bound causal evidence requires structured investigation intent",
    }
)


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
NO_T2_ESCALATION_POLICY = SemanticPlanningEscalationPolicy(allowed_triggers=frozenset())


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
        escalation_policy: SemanticPlanningEscalationPolicy | None = None,
    ) -> (
        tuple[
            SemanticFrameProposal,
            SemanticProblemFrame,
            VerifiedInvestigationIntent | None,
        ]
        | None
    ):
        for tier, model in self._planning_models():
            raw = model.propose_frame(
                utterance=utterance,
                context=context,
                descriptors=copy.deepcopy(descriptors),
                metric_concepts=metric_concepts,
                principal_role=principal.role.value,
                purpose=purpose,
            )
            if raw is None:
                if tier == "t1":
                    fallback = build_resource_target_candidates_fallback(
                        utterance=utterance,
                        context=context,
                        descriptors=descriptors,
                        confidence=0.0,
                        inventory_query_language=self._inventory_query_language,
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
                if self._should_escalate(
                    tier=tier,
                    trigger=SemanticPlanningEscalationTrigger.FRAME_UNAVAILABLE,
                    escalation_policy=escalation_policy,
                ):
                    continue
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
                proposal = normalize_ingress_proposal(
                    proposal,
                    descriptors=descriptors,
                )
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
                    utterance=utterance,
                    context=context,
                    descriptors=descriptors,
                    inventory_query_language=self._inventory_query_language,
                )
                if fallback is not None:
                    return (*fallback, None)
                if self._should_escalate(
                    tier=tier,
                    trigger=SemanticPlanningEscalationTrigger.FRAME_SCHEMA_INVALID,
                    escalation_policy=escalation_policy,
                    validation_reason=_safe_frame_rejection_reason(exc),
                ):
                    continue
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
                    utterance=utterance,
                    context=context,
                    descriptors=descriptors,
                    inventory_query_language=self._inventory_query_language,
                )
                if fallback is not None:
                    return (*fallback, None)
                if self._should_escalate(
                    tier=tier,
                    trigger=SemanticPlanningEscalationTrigger.FRAME_BUILD_REJECTED,
                    escalation_policy=escalation_policy,
                ):
                    continue
                raise ProposalRejectedError("frame_build", type(exc).__name__) from exc
            return proposal, frame, investigation_intent
        return None

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
        for tier, model in self._planning_models():
            raw = model.propose_plan(
                frame=frame,
                descriptors=copy.deepcopy(descriptors),
                metric_concepts=metric_concepts,
                principal_role=principal.role.value,
                purpose=purpose,
                evaluation_time=evaluation_time,
            )
            if raw is None:
                if self._should_escalate(
                    tier=tier,
                    trigger=SemanticPlanningEscalationTrigger.PLAN_UNAVAILABLE,
                    escalation_policy=escalation_policy,
                ):
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
        if not policy.allows(trigger):
            _LOGGER.info(
                "semantic_planning_t2_withheld",
                extra={
                    "trigger": trigger.value,
                    "validation_reason": validation_reason,
                },
            )
            return False
        _LOGGER.info(
            "semantic_planning_t2_escalated",
            extra={
                "trigger": trigger.value,
                "validation_reason": validation_reason,
            },
        )
        return True


def _candidate_frame_fallback(
    *,
    tier: str,
    proposal: SemanticFrameProposal | None,
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
    inventory_query_language: InventoryQueryLanguageRegistry | None,
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    if (
        tier != "t1"
        or proposal is None
        or proposal.operation is SemanticOperation.ACTION_DRAFT
        or proposal.output_shape is SemanticOutputShape.RESOURCE_TARGET_CANDIDATES
        or not resource_target_candidates_apply_to_proposal(
            proposal,
            utterance=utterance,
            descriptors=descriptors,
            inventory_query_language=inventory_query_language,
        )
    ):
        return None
    fallback = build_resource_target_candidates_fallback(
        utterance=utterance,
        context=context,
        descriptors=descriptors,
        confidence=proposal.confidence,
        inventory_query_language=inventory_query_language,
    )
    if fallback is not None:
        _LOGGER.info(
            "semantic_planning_candidate_recovered",
            extra={"stage": "frame", "recovery": "resource_target_candidates"},
        )
    return fallback


def _safe_frame_rejection_reason(exc: Exception) -> str:
    message = str(exc)
    if type(exc) is ValueError and message in _SAFE_FRAME_REJECTION_REASONS:
        return message
    return type(exc).__name__


def _validate_frame_proposal(
    proposal: SemanticFrameProposal,
    *,
    utterance: str,
    descriptors: tuple[dict[str, Any], ...],
) -> None:
    _reject_server_owned_output_shape(proposal.output_shape)
    if _SERVER_BOUND_REQUIREMENTS.intersection(proposal.clarification_requirements):
        raise ValueError("semantic clarification requests server-bound context")
    is_evidence_validation = proposal.output_shape in {
        "evidence_validation",
        "target_health_assessment",
    }
    if (proposal.operation is SemanticOperation.VALIDATE) != is_evidence_validation:
        raise ValueError("semantic validate operation requires evidence_validation output")
    is_causal_evidence = proposal.output_shape == "causal_evidence"
    if (proposal.operation is SemanticOperation.EXPLAIN_CHANGE) != is_causal_evidence:
        raise ValueError("semantic explain_change operation requires causal_evidence output")
    is_aggregation = proposal.output_shape == "aggregation_table"
    if (proposal.operation is SemanticOperation.AGGREGATE) != is_aggregation:
        raise ValueError("semantic aggregate operation requires aggregation_table output")
    specialized_operation = _SPECIALIZED_OPERATIONS_BY_OUTPUT_SHAPE.get(proposal.output_shape)
    if specialized_operation is not None and proposal.operation is not specialized_operation:
        raise ValueError("specialized semantic output requires its fixed operation")
    if proposal.investigation is not None and not is_causal_evidence:
        raise ValueError("structured investigation intent requires semantic causal evidence")
    if (
        is_causal_evidence
        and proposal.investigation is None
        and _has_target_bound_subject(proposal, descriptors=descriptors)
        and not _is_resource_candidate_request(
            proposal,
            utterance=utterance,
            descriptors=descriptors,
        )
    ):
        raise ValueError("target-bound causal evidence requires structured investigation intent")
    if proposal.output_shape in _SCHEMA_LEVEL_OUTPUT_SHAPES and _names_runtime_instance(
        (utterance, *proposal.subject_constraints),
        descriptors=descriptors,
    ):
        raise ValueError("schema-level semantic frame names a runtime resource instance")
    if proposal.temporal_scope and proposal.output_shape in {
        SemanticOutputShape.CONTEXTUAL_RESOURCE_LIST,
        SemanticOutputShape.PROPERTY_FILTERED_RESOURCES,
        SemanticOutputShape.RESOURCE_LIST,
        SemanticOutputShape.RESOURCE_STATE_LIST,
        SemanticOutputShape.TARGET_CURRENT_STATE,
        SemanticOutputShape.TARGET_INGRESS_CONFIGURATION,
    }:
        raise ValueError("historical semantic request requires a temporal capability")
    if proposal.output_shape == "ontology_declaration":
        measures = frozenset(proposal.measure_concepts)
        if (
            proposal.operation is not SemanticOperation.SELECT
            or len(proposal.subject_constraints) != 1
            or not measures
            or not measures <= DECLARATION_SECTIONS_BY_MEASURE.keys()
        ):
            raise ValueError("semantic declaration frame requires an exact declaration measure")
        if "rule_state" in measures and (
            measures != {"rule_state"} or proposal.subject_constraints != ("Rule",)
        ):
            raise ValueError("semantic Rule state frame requires the exact Rule declaration")


def _reject_server_owned_output_shape(output_shape: SemanticOutputShape) -> None:
    if output_shape is SemanticOutputShape.RESOURCE_TARGET_CANDIDATES:
        raise ValueError("resource target candidates are server-owned")


def _names_runtime_instance(
    texts: tuple[str, ...],
    *,
    descriptors: tuple[dict[str, Any], ...],
) -> bool:
    """Report whether any text names a concrete resource the schema cannot hold.

    Every proposal stage below the frame is checked against the frame, so a
    frame that answers a different question than the operator asked produces a
    plan, a result, and an answer that all agree with each other and with
    nothing else. A schema family reads declarations, so an identifier-shaped
    token that matches no declared name, property, or value is evidence the
    frame left the question behind.
    """
    candidates = [
        match.group(0) for text in texts for match in _RUNTIME_INSTANCE_TOKEN.finditer(text)
    ][:_MAX_SCANNED_TOKENS]
    if not candidates:
        return False
    declared = _declared_vocabulary(descriptors)
    return any(candidate.casefold() not in declared for candidate in candidates)


def _has_target_bound_subject(
    proposal: SemanticFrameProposal,
    *,
    descriptors: tuple[dict[str, Any], ...],
) -> bool:
    declared_subjects = {
        name.casefold()
        for descriptor in descriptors
        if descriptor.get("kind") in {"object", "interface"}
        if isinstance((name := descriptor.get("name")), str)
    }
    return any(
        subject.casefold() not in declared_subjects for subject in proposal.subject_constraints
    )


def _is_resource_candidate_request(
    proposal: SemanticFrameProposal,
    *,
    utterance: str,
    descriptors: tuple[dict[str, Any], ...],
) -> bool:
    """Recognize a typed Resource category that still lacks one exact identity."""

    filters = stated_value_filters(utterance, descriptors)
    return bool(filters.get(("Resource", "type"))) and (
        exact_target_from_constraints(
            proposal.subject_constraints,
            utterance=utterance,
            descriptors=descriptors,
        )
        is None
    )


def _declared_vocabulary(descriptors: tuple[dict[str, Any], ...]) -> frozenset[str]:
    """Collect every word the supplied release lets a schema question name."""
    words: set[str] = set()
    for descriptor in descriptors:
        name = descriptor.get("name")
        if isinstance(name, str):
            words.add(name.casefold())
        properties = descriptor.get("properties")
        if isinstance(properties, Mapping):
            for property_name, facet in properties.items():
                if isinstance(property_name, str):
                    words.add(property_name.casefold())
                words.update(_declared_facet_words(facet))
        elif isinstance(properties, list):
            words.update(item.casefold() for item in properties if isinstance(item, str))
    return frozenset(words)


def _declared_facet_words(facet: object) -> set[str]:
    """Return the declared values and request terms of one property facet."""
    if not isinstance(facet, Mapping):
        return set()
    words = {value.casefold() for value in _string_list(facet.get("values"))}
    groups = facet.get("value_groups")
    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, Mapping):
                continue
            group_id = group.get("id")
            if isinstance(group_id, str):
                words.add(group_id.casefold())
            words.update(value.casefold() for value in _string_list(group.get("values")))
            words.update(term.casefold() for term in _string_list(group.get("terms")))
    return words


def _string_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


__all__ = [
    "BOUNDED_T2_ESCALATION_POLICY",
    "NO_T2_ESCALATION_POLICY",
    "ProposalRejectedError",
    "SemanticPlanningCascade",
    "SemanticPlanningEscalationPolicy",
    "SemanticPlanningEscalationTrigger",
]
