"""Normalize action drafts, proposals, and temporal scopes for semantic planning frames."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any

from fdai_service_contracts.ontology_query import (
    SemanticOperation,
    SemanticProblemFrame,
)
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal

from fdai.core.ontology_platform.resource_event_queries import KUBERNETES_EVENT_FAMILY
from fdai.rule_catalog.schema.inventory_query_language import (
    InventoryQueryLanguageRegistry,
    query_signal_matches,
    query_signal_span,
)

from .semantic_impact_planning import (
    service_impact_query_sides,
    service_resource_query_sides,
)
from .semantic_investigation import (
    IntentSourceSpan,
    InvestigationAnswerShape,
    InvestigationEntityMention,
    InvestigationEntityRole,
    InvestigationEvidenceStandard,
    InvestigationHypothesis,
    InvestigationIntentProposal,
    InvestigationMeasureDirection,
    InvestigationRelationshipIntent,
    InvestigationSymptomMeasure,
    InvestigationTemporalCue,
    InvestigationTemporalRole,
)
from .semantic_planning_frame_core import build_semantic_frame
from .semantic_planning_frame_facets import (
    _facet_affirms_concept,
    _facets_describe_configuration_drift_evidence,
    _facets_describe_historical_topology,
    _facets_describe_incident_triage,
    _facets_describe_network_path,
    _facets_describe_operating_objectives,
    _facets_describe_resource_classification,
    _facets_describe_resource_evidence_health,
    _facets_describe_service_relationship_assessment,
    _facets_describe_service_relationship_evidence_gap,
)
from .semantic_planning_models import (
    BoundInvestigationContinuation,
    ClarificationRequirement,
    SemanticFrameProposal,
    SemanticOutputShape,
)
from .semantic_planning_value_filters import stated_value_filters
from .semantic_target_identity import exact_target_from_constraints

_ACTION_DRAFT_TEMPORAL_SCOPE = {
    "ActionType": {},
    "Change": {"kind": "historical"},
    "Incident": {"kind": "current"},
    "RecoveryPlan": {"kind": "current"},
    "Rule": {},
}
_LOGGER = logging.getLogger(__name__)
_VM_CPU_SYMPTOM_CONCEPT = "resource.cpu.utilization_pct"


def normalize_bound_latency_recovery(
    proposal: SemanticFrameProposal,
    *,
    continuation: BoundInvestigationContinuation | None,
    semantic_judgment: Mapping[str, Any] | None,
) -> SemanticFrameProposal:
    """Bind one typed recovery frame to an Operator-verified S3 continuation."""

    facets_raw = semantic_judgment.get("requested_facets", ()) if semantic_judgment else ()
    facets = {str(item) for item in facets_raw} if isinstance(facets_raw, (list, tuple)) else set()
    if (
        continuation is None
        or continuation.target_type != "BusinessService"
        or continuation.recovery_measure_concepts != ("dependency.latency", "service.latency")
        or proposal.operation is not SemanticOperation.VALIDATE
        or proposal.output_shape
        not in {
            SemanticOutputShape.EVIDENCE_VALIDATION,
            SemanticOutputShape.TARGET_HEALTH_ASSESSMENT,
        }
        or "recovery" not in facets
        or not facets.intersection({"dependency", "dependency_state"})
    ):
        return proposal
    return proposal.model_copy(
        update={
            "subject_constraints": ("BusinessService", continuation.target_value),
            "measure_concepts": continuation.recovery_measure_concepts,
            "temporal_scope": {"kind": "windowed"},
            "output_shape": SemanticOutputShape.EVIDENCE_VALIDATION,
            "evidence_requirements": ("recovery_verification",),
            "unresolved_terms": (),
            "clarification_requirements": (),
            "clarification": None,
            "investigation": None,
        }
    )


def normalize_missing_vm_cpu_investigation(
    proposal: SemanticFrameProposal,
    *,
    utterance: str,
    descriptors: tuple[dict[str, Any], ...],
    metric_concepts: Sequence[str],
    inventory_query_language: InventoryQueryLanguageRegistry | None,
) -> SemanticFrameProposal:
    """Complete one fully typed exact-VM CPU diagnosis without selecting a new capability."""

    required_metrics = {
        _VM_CPU_SYMPTOM_CONCEPT,
        "dependency.latency",
        "request.volume",
    }
    candidate = (
        proposal.investigation is None
        and proposal.output_shape == SemanticOutputShape.CAUSAL_EVIDENCE
        and inventory_query_language is not None
        and query_signal_matches(
            utterance,
            inventory_query_language,
            "symptom_cpu_spike",
        )
    )
    if candidate:
        _LOGGER.info(
            "semantic_planning_vm_cpu_recovery_evaluated",
            extra={
                "operation_matches": proposal.operation is SemanticOperation.EXPLAIN_CHANGE,
                "metrics_available": required_metrics.issubset(metric_concepts),
                "service_impact_matches": query_signal_matches(
                    utterance,
                    inventory_query_language,
                    "service_impact",
                ),
            },
        )
    if (
        proposal.investigation is not None
        or proposal.operation is not SemanticOperation.EXPLAIN_CHANGE
        or proposal.output_shape != SemanticOutputShape.CAUSAL_EVIDENCE
        or inventory_query_language is None
        or not required_metrics.issubset(metric_concepts)
        or not query_signal_matches(
            utterance,
            inventory_query_language,
            "symptom_cpu_spike",
        )
        or not query_signal_matches(
            utterance,
            inventory_query_language,
            "service_impact",
        )
    ):
        return proposal
    target = exact_target_from_constraints(
        proposal.subject_constraints,
        utterance=utterance,
        descriptors=descriptors,
    )
    query_sides = service_impact_query_sides(descriptors)
    symptom_match = query_signal_span(
        utterance,
        inventory_query_language,
        "symptom_cpu_spike",
    )
    impact_match = query_signal_span(
        utterance,
        inventory_query_language,
        "service_impact",
    )
    if target is None or query_sides is None or symptom_match is None or impact_match is None:
        _LOGGER.info(
            "semantic_planning_vm_cpu_recovery_unavailable",
            extra={
                "target_available": target is not None,
                "query_sides_available": query_sides is not None,
                "symptom_span_available": symptom_match is not None,
                "impact_span_available": impact_match is not None,
            },
        )
        return proposal
    target_start = utterance.casefold().find(target.casefold())
    if target_start < 0 or utterance.casefold().count(target.casefold()) != 1:
        return proposal
    target_span = IntentSourceSpan(
        start=target_start,
        end=target_start + len(target),
        text=utterance[target_start : target_start + len(target)],
    )
    symptom_span = IntentSourceSpan(
        start=symptom_match[0],
        end=symptom_match[1],
        text=symptom_match[2],
    )
    impact_span = IntentSourceSpan(
        start=impact_match[0],
        end=impact_match[1],
        text=impact_match[2],
    )
    investigation = InvestigationIntentProposal(
        operation=SemanticOperation.EXPLAIN_CHANGE,
        entities=(
            InvestigationEntityMention(
                mention_id="target",
                span=target_span,
                role=InvestigationEntityRole.AFFECTED_TARGET,
                object_type_candidates=("Resource",),
            ),
        ),
        symptom_measures=(
            InvestigationSymptomMeasure(
                measure_id="cpu-spike",
                span=symptom_span,
                concept_id=_VM_CPU_SYMPTOM_CONCEPT,
                target_mention_id="target",
                direction=InvestigationMeasureDirection.INCREASE,
            ),
        ),
        primary_symptom_measure_id="cpu-spike",
        temporal_cues=(
            InvestigationTemporalCue(
                cue_id="onset",
                span=symptom_span,
                role=InvestigationTemporalRole.ONSET,
            ),
        ),
        relationship_intents=(
            InvestigationRelationshipIntent(
                relationship_id="service-impact",
                span=impact_span,
                source_mention_id="target",
                query_side_candidates=query_sides,
            ),
        ),
        hypotheses=(
            InvestigationHypothesis(
                hypothesis_id="traffic-load",
                span=symptom_span,
                relationship_id="service-impact",
                cause_measure_concept="request.volume",
                effect_measure_id="cpu-spike",
                competing_explanations=("dependency-latency",),
            ),
            InvestigationHypothesis(
                hypothesis_id="dependency-latency",
                span=impact_span,
                relationship_id="service-impact",
                cause_measure_concept="dependency.latency",
                effect_measure_id="cpu-spike",
                competing_explanations=("traffic-load",),
            ),
        ),
        evidence_standard=InvestigationEvidenceStandard.SUPPORT_AND_REFUTATION,
        answer_shape=InvestigationAnswerShape.DIAGNOSIS,
        confidence=proposal.confidence,
    )
    _LOGGER.info(
        "semantic_planning_vm_cpu_investigation_recovered",
        extra={"hypothesis_count": len(investigation.hypotheses)},
    )
    return proposal.model_copy(
        update={
            "measure_concepts": (_VM_CPU_SYMPTOM_CONCEPT,),
            "investigation": investigation,
        }
    )


def normalize_missing_mysql_pressure_investigation(
    proposal: SemanticFrameProposal,
    *,
    utterance: str,
    descriptors: tuple[dict[str, Any], ...],
    metric_concepts: Sequence[str],
    inventory_query_language: InventoryQueryLanguageRegistry | None,
) -> SemanticFrameProposal:
    """Complete one fully typed exact MySQL pressure comparison without widening scope."""

    required_metrics = {
        "database.mysql.active_connections",
        "database.mysql.cpu.utilization_pct",
        "database.mysql.query.count",
        "database.mysql.slow_query.count",
        "dependency.latency",
    }
    signal_names = (
        "symptom_database_latency",
        "hypothesis_mysql_saturation",
        "hypothesis_request_growth",
    )
    if (
        proposal.investigation is not None
        or proposal.operation is not SemanticOperation.EXPLAIN_CHANGE
        or proposal.output_shape != SemanticOutputShape.CAUSAL_EVIDENCE
        or inventory_query_language is None
        or not required_metrics.issubset(metric_concepts)
        or any(
            not query_signal_matches(utterance, inventory_query_language, signal_name)
            for signal_name in signal_names
        )
    ):
        return proposal
    target = exact_target_from_constraints(
        proposal.subject_constraints,
        utterance=utterance,
        descriptors=descriptors,
    )
    query_sides = service_impact_query_sides(descriptors)
    spans = {
        signal_name: query_signal_span(
            utterance,
            inventory_query_language,
            signal_name,
        )
        for signal_name in signal_names
    }
    if target is None or query_sides is None or any(value is None for value in spans.values()):
        return proposal
    target_start = utterance.casefold().find(target.casefold())
    if target_start < 0 or utterance.casefold().count(target.casefold()) != 1:
        return proposal

    def source(signal_name: str) -> IntentSourceSpan:
        match = spans[signal_name]
        if match is None:
            raise ValueError("MySQL pressure signal span is unavailable")
        return IntentSourceSpan(start=match[0], end=match[1], text=match[2])

    target_span = IntentSourceSpan(
        start=target_start,
        end=target_start + len(target),
        text=utterance[target_start : target_start + len(target)],
    )
    latency_span = source("symptom_database_latency")
    saturation_span = source("hypothesis_mysql_saturation")
    request_span = source("hypothesis_request_growth")
    investigation = InvestigationIntentProposal(
        operation=SemanticOperation.EXPLAIN_CHANGE,
        entities=(
            InvestigationEntityMention(
                mention_id="target",
                span=target_span,
                role=InvestigationEntityRole.AFFECTED_TARGET,
                object_type_candidates=("Resource",),
            ),
        ),
        symptom_measures=(
            InvestigationSymptomMeasure(
                measure_id="database-latency",
                span=latency_span,
                concept_id="dependency.latency",
                target_mention_id="target",
                direction=InvestigationMeasureDirection.INCREASE,
            ),
        ),
        primary_symptom_measure_id="database-latency",
        temporal_cues=(
            InvestigationTemporalCue(
                cue_id="onset",
                span=latency_span,
                role=InvestigationTemporalRole.ONSET,
            ),
        ),
        relationship_intents=(
            InvestigationRelationshipIntent(
                relationship_id="service-impact",
                span=request_span,
                source_mention_id="target",
                query_side_candidates=query_sides,
            ),
        ),
        hypotheses=(
            InvestigationHypothesis(
                hypothesis_id="mysql-saturation",
                span=saturation_span,
                relationship_id="service-impact",
                cause_measure_concept="database.mysql.cpu.utilization_pct",
                effect_measure_id="database-latency",
                competing_explanations=("request-growth",),
            ),
            InvestigationHypothesis(
                hypothesis_id="request-growth",
                span=request_span,
                relationship_id="service-impact",
                cause_measure_concept="database.mysql.query.count",
                effect_measure_id="database-latency",
                competing_explanations=("mysql-saturation",),
            ),
        ),
        evidence_standard=InvestigationEvidenceStandard.SUPPORT_AND_REFUTATION,
        answer_shape=InvestigationAnswerShape.DIAGNOSIS,
        confidence=proposal.confidence,
    )
    return proposal.model_copy(
        update={
            "subject_constraints": ("Resource", target),
            "measure_concepts": ("dependency.latency",),
            "investigation": investigation,
        }
    )


def normalize_network_application_latency_investigation(
    proposal: SemanticFrameProposal,
    *,
    utterance: str,
    descriptors: tuple[dict[str, Any], ...],
    metric_concepts: Sequence[str],
    inventory_query_language: InventoryQueryLanguageRegistry | None,
) -> SemanticFrameProposal:
    """Ground exact S3 evidence or require an affected service before provider I/O."""

    required_metrics = {"dependency.latency", "network.change", "service.latency"}
    signals = (
        "symptom_response_latency",
        "hypothesis_network_latency",
        "hypothesis_application_latency",
    )
    if (
        proposal.operation
        not in {
            SemanticOperation.COMPARE,
            SemanticOperation.EXPLAIN_CHANGE,
            SemanticOperation.VALIDATE,
        }
        or inventory_query_language is None
        or not required_metrics.issubset(metric_concepts)
        or any(
            not query_signal_matches(utterance, inventory_query_language, signal)
            for signal in signals
        )
    ):
        return proposal
    target = exact_target_from_constraints(
        proposal.subject_constraints,
        utterance=utterance,
        descriptors=descriptors,
    )
    if target is None:
        korean = any("가" <= character <= "힣" for character in utterance)
        return proposal.model_copy(
            update={
                "subject_constraints": ("BusinessService",),
                "measure_concepts": ("service.latency",),
                "unresolved_terms": ("service_identity",),
                "clarification_requirements": (ClarificationRequirement.RESOURCE_IDENTITY,),
                "clarification": (
                    "응답 지연을 조사할 정확한 서비스 이름 또는 ID를 알려주세요?"
                    if korean
                    else "Provide the exact service name or ID for the latency investigation?"
                ),
            }
        )
    query_sides = service_resource_query_sides(descriptors)
    spans = {
        signal: query_signal_span(utterance, inventory_query_language, signal) for signal in signals
    }
    if query_sides is None or any(value is None for value in spans.values()):
        return proposal
    target_start = utterance.casefold().find(target.casefold())
    if target_start < 0 or utterance.casefold().count(target.casefold()) != 1:
        return proposal

    def source(signal: str) -> IntentSourceSpan:
        match = spans[signal]
        if match is None:
            raise ValueError("S3 signal span is unavailable")
        return IntentSourceSpan(start=match[0], end=match[1], text=match[2])

    target_span = IntentSourceSpan(
        start=target_start,
        end=target_start + len(target),
        text=utterance[target_start : target_start + len(target)],
    )
    latency_span = source("symptom_response_latency")
    network_span = source("hypothesis_network_latency")
    application_span = source("hypothesis_application_latency")
    investigation = InvestigationIntentProposal(
        operation=SemanticOperation.EXPLAIN_CHANGE,
        entities=(
            InvestigationEntityMention(
                mention_id="target",
                span=target_span,
                role=InvestigationEntityRole.AFFECTED_TARGET,
                object_type_candidates=("BusinessService",),
            ),
        ),
        symptom_measures=(
            InvestigationSymptomMeasure(
                measure_id="response-latency",
                span=latency_span,
                concept_id="service.latency",
                target_mention_id="target",
                direction=InvestigationMeasureDirection.INCREASE,
            ),
        ),
        primary_symptom_measure_id="response-latency",
        temporal_cues=(
            InvestigationTemporalCue(
                cue_id="lookback",
                span=latency_span,
                role=InvestigationTemporalRole.ONSET,
            ),
        ),
        relationship_intents=(
            InvestigationRelationshipIntent(
                relationship_id="service-resources",
                span=application_span,
                source_mention_id="target",
                query_side_candidates=query_sides,
            ),
        ),
        hypotheses=(
            InvestigationHypothesis(
                hypothesis_id="network-latency",
                span=network_span,
                relationship_id="service-resources",
                cause_measure_concept="network.change",
                effect_measure_id="response-latency",
                competing_explanations=("application-latency",),
            ),
            InvestigationHypothesis(
                hypothesis_id="application-latency",
                span=application_span,
                relationship_id="service-resources",
                cause_measure_concept="dependency.latency",
                effect_measure_id="response-latency",
                competing_explanations=("network-latency",),
            ),
        ),
        evidence_standard=InvestigationEvidenceStandard.SUPPORT_AND_REFUTATION,
        answer_shape=InvestigationAnswerShape.DIAGNOSIS,
        confidence=proposal.confidence,
    )
    return proposal.model_copy(
        update={
            "operation": SemanticOperation.EXPLAIN_CHANGE,
            "subject_constraints": ("BusinessService", target),
            "measure_concepts": ("service.latency",),
            "output_shape": SemanticOutputShape.CAUSAL_EVIDENCE,
            "evidence_requirements": ("support_and_refutation",),
            "unresolved_terms": (),
            "clarification_requirements": (),
            "clarification": None,
            "investigation": investigation,
        }
    )


def _action_draft_subject_types(constraints: tuple[str, ...]) -> set[str]:
    return {
        constraint.split(":", 1)[0]
        for constraint in constraints
        if constraint.split(":", 1)[0] in _ACTION_DRAFT_TEMPORAL_SCOPE
    }


def resolve_bound_incident_action_subject(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Bind the trusted Incident type to an otherwise subject-empty action draft."""

    if (
        frame.operation is not SemanticOperation.ACTION_DRAFT
        or frame.output_shape != SemanticOutputShape.ACTION_DRAFT
        or _action_draft_subject_types(proposal.subject_constraints)
    ):
        return proposal, frame
    resolved = proposal.model_copy(
        update={"subject_constraints": ("Incident", *proposal.subject_constraints)}
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


def resolve_semantic_judgment_action_draft(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    judgment: SemanticJudgmentProposal | None,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Rebuild a candidate-only action frame from one accepted draft judgment."""

    judgment_facets = (
        {facet.replace("-", "_") for facet in judgment.requested_facets}
        if judgment is not None
        else set()
    )
    trace_axes = all(
        any(_facet_affirms_concept(facet, concept) for facet in judgment_facets)
        for concept in ("resource_type", "signal_type", "action_type", "trace")
    )
    trace_posture = "governed" in judgment_facets or bool(
        {
            "no_current_finding",
            "without_asserting_current_finding",
            "without_current_finding",
        }.intersection(judgment_facets)
    )
    if (
        judgment is not None
        and judgment.action_posture == "advise_only"
        and frame.operation is SemanticOperation.ACTION_DRAFT
        and frame.output_shape == SemanticOutputShape.ACTION_DRAFT
        and set(proposal.subject_constraints)
        == {"ActionType", "ResourceType", "Rule", "SignalType"}
        and trace_axes
        and trace_posture
    ):
        resolved = proposal.model_copy(
            update={
                "operation": SemanticOperation.SELECT,
                "subject_constraints": ("ActionType", "ResourceType", "Rule", "SignalType"),
                "measure_concepts": tuple(sorted(judgment_facets)),
                "temporal_scope": {},
                "output_shape": SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
                "evidence_requirements": (),
                "unresolved_terms": (),
                "clarification_requirements": (),
                "clarification": None,
                "investigation": None,
            }
        )
        return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)
    if judgment is None or judgment.action_posture != "draft_only":
        return proposal, frame
    frame_subjects = _action_draft_subject_types(proposal.subject_constraints)
    preserve_frame_subject = (
        frame.operation is SemanticOperation.ACTION_DRAFT
        and frame.output_shape == SemanticOutputShape.ACTION_DRAFT
        and frame_subjects == {judgment.action_subject}
        and not proposal.unresolved_terms
        and not proposal.clarification_requirements
    )
    subject_constraints = (
        proposal.subject_constraints if preserve_frame_subject else (judgment.action_subject,)
    )
    resolved = proposal.model_copy(
        update={
            "operation": SemanticOperation.ACTION_DRAFT,
            "subject_constraints": subject_constraints,
            "measure_concepts": (),
            "temporal_scope": {},
            "output_shape": SemanticOutputShape.ACTION_DRAFT,
            "evidence_requirements": (),
            "unresolved_terms": (),
            "clarification_requirements": (),
            "clarification": None,
            "investigation": None,
        }
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


def resolve_default_action_draft_subject(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Use ActionType for an action draft with no narrower typed subject."""

    if (
        frame.operation is not SemanticOperation.ACTION_DRAFT
        or frame.output_shape != SemanticOutputShape.ACTION_DRAFT
        or _action_draft_subject_types(proposal.subject_constraints)
        or proposal.subject_constraints
        or proposal.unresolved_terms
        or proposal.clarification_requirements
    ):
        return proposal, frame
    resolved = proposal.model_copy(
        update={"subject_constraints": ("ActionType", *proposal.subject_constraints)}
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


def normalize_action_draft_temporal_scope(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Derive an action draft's temporal scope from its canonical subject type."""

    if (
        frame.operation is not SemanticOperation.ACTION_DRAFT
        or frame.output_shape != SemanticOutputShape.ACTION_DRAFT
    ):
        return proposal, frame
    subject_types = _action_draft_subject_types(proposal.subject_constraints)
    if len(subject_types) != 1:
        return proposal, frame
    temporal_scope = _ACTION_DRAFT_TEMPORAL_SCOPE[next(iter(subject_types))]
    if temporal_scope is None or proposal.temporal_scope == temporal_scope:
        return proposal, frame
    resolved = proposal.model_copy(update={"temporal_scope": temporal_scope})
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


CHANGE_ACTIVITY_COMPARISON_MEASURE = "change_activity_correlation"


def canonicalize_semantic_judgment_frame_proposal(
    proposal: SemanticFrameProposal,
    *,
    judgment: Mapping[str, Any] | None,
) -> SemanticFrameProposal:
    """Preserve one accepted typed draft before validating the model frame."""

    if (
        judgment is None
        or judgment.get("action_posture") != "draft_only"
        or judgment.get("authority") != "candidate_only"
        or judgment.get("execution_authority") is not False
    ):
        return proposal
    action_subject = judgment.get("action_subject")
    if not isinstance(action_subject, str) or action_subject not in _ACTION_DRAFT_TEMPORAL_SCOPE:
        return proposal
    frame_subjects = _action_draft_subject_types(proposal.subject_constraints)
    preserve_subject = (
        frame_subjects == {action_subject}
        and not proposal.unresolved_terms
        and not proposal.clarification_requirements
    )
    return proposal.model_copy(
        update={
            "operation": SemanticOperation.ACTION_DRAFT,
            "subject_constraints": (
                proposal.subject_constraints if preserve_subject else (action_subject,)
            ),
            "measure_concepts": (),
            "temporal_scope": _ACTION_DRAFT_TEMPORAL_SCOPE[action_subject],
            "output_shape": SemanticOutputShape.ACTION_DRAFT,
            "evidence_requirements": (),
            "unresolved_terms": (),
            "clarification_requirements": (),
            "clarification": None,
            "investigation": None,
        }
    )


def resolve_semantic_judgment_bound_read(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    judgment: SemanticJudgmentProposal | None,
    bound_incident: bool,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Preserve validated bound read intent when the candidate frame drifts."""

    if judgment is None or judgment.action_posture != "advise_only":
        return proposal, frame
    facets = {facet.replace("-", "_") for facet in judgment.requested_facets}
    lookback_seconds = proposal.temporal_scope.get("lookback_seconds")
    lookback_hours = proposal.temporal_scope.get("lookback_hours")
    resource_targets = tuple(target for target in judgment.targets if target.kind == "resource")
    time_range_targets = tuple(target for target in judgment.targets if target.kind == "time_range")
    event_type_targets = tuple(target for target in judgment.targets if target.kind == "event_type")
    temporal_keys = set(proposal.temporal_scope)
    bounded_event_window = temporal_keys == {"lookback_seconds"} or (
        temporal_keys
        in (
            {"kind", "lookback_seconds"},
            {"kind", "lookback_seconds", "order"},
            {"kind", "lookback_seconds", "ordering"},
        )
        and proposal.temporal_scope.get("kind") in {"historical", "windowed"}
    )
    if (
        temporal_keys == {"kind", "lookback_hours", "order"}
        and proposal.temporal_scope.get("kind") in {"historical", "windowed"}
        and isinstance(lookback_hours, int)
        and not isinstance(lookback_hours, bool)
        and 1 <= lookback_hours <= 24
    ):
        lookback_seconds = lookback_hours * 3_600
        bounded_event_window = True
    kubernetes_event_family = "kubernetes_events" in facets
    judgment_lookback_seconds = (
        _canonical_duration_seconds(time_range_targets[0].canonical_value)
        if len(time_range_targets) == 1
        else None
    )
    kubernetes_event_history = (
        judgment.primary_intent == "query.resource_event_history"
        and kubernetes_event_family
        and bool(facets & {"time_order", "chronological_order", "ordering"})
        and len(resource_targets) == 1
        and len(time_range_targets) == 1
        and len(event_type_targets) == 1
        and len(judgment.targets)
        == len(resource_targets) + len(time_range_targets) + len(event_type_targets)
        and resource_targets[0].canonical_value in {None, "Resource"}
        and proposal.operation is SemanticOperation.SELECT
        and proposal.output_shape == SemanticOutputShape.RESOURCE_EVENT_HISTORY
        and "Resource" in proposal.subject_constraints
        and bounded_event_window
        and isinstance(lookback_seconds, int)
        and not isinstance(lookback_seconds, bool)
        and 60 <= lookback_seconds <= 86_400
        and judgment_lookback_seconds == lookback_seconds
        and not proposal.unresolved_terms
        and not proposal.clarification_requirements
    )
    if kubernetes_event_history:
        resolved = proposal.model_copy(
            update={
                "measure_concepts": (KUBERNETES_EVENT_FAMILY,),
                "temporal_scope": {"lookback_seconds": lookback_seconds},
            }
        )
        return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)
    configuration_drift_evidence = _facets_describe_configuration_drift_evidence(facets)
    if configuration_drift_evidence:
        resolved = proposal.model_copy(
            update={
                "operation": SemanticOperation.VALIDATE,
                "subject_constraints": ("Resource",),
                "measure_concepts": tuple(sorted(facets)),
                "temporal_scope": {"kind": "current"},
                "output_shape": SemanticOutputShape.EVIDENCE_VALIDATION,
            }
        )
        return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)
    resource_evidence_health = (
        judgment.primary_intent
        in {"query.resource_health_inventory", "query.target_health_assessment"}
        and all(target.canonical_value in {None, "Resource"} for target in judgment.targets)
        and _facets_describe_resource_evidence_health(facets)
    )
    if resource_evidence_health:
        resolved = proposal.model_copy(
            update={
                "operation": SemanticOperation.VALIDATE,
                "subject_constraints": ("Resource",),
                "measure_concepts": tuple(sorted(facets)),
                "temporal_scope": {"kind": "current"},
                "output_shape": SemanticOutputShape.EVIDENCE_VALIDATION,
                "evidence_requirements": (),
                "unresolved_terms": (),
                "clarification_requirements": (),
                "clarification": None,
                "investigation": None,
            }
        )
        return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)
    service_relationship_evidence = (
        judgment.primary_intent == "query.resource_state_inventory"
        and _facets_describe_service_relationship_evidence_gap(facets)
    ) or (
        judgment.primary_intent == "query.target_health_assessment"
        and (
            _facets_describe_service_relationship_evidence_gap(facets)
            or _facets_describe_service_relationship_assessment(facets)
        )
    )
    if service_relationship_evidence:
        resolved = proposal.model_copy(
            update={
                "operation": SemanticOperation.VALIDATE,
                "subject_constraints": ("BusinessService", "Workload", "Resource"),
                "measure_concepts": tuple(sorted(facets)),
                "temporal_scope": {"kind": "current"},
                "output_shape": SemanticOutputShape.EVIDENCE_VALIDATION,
                "evidence_requirements": (),
                "unresolved_terms": (),
                "clarification_requirements": (),
                "clarification": None,
                "investigation": None,
            }
        )
        return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)
    if (
        bound_incident
        and judgment.primary_intent in {"query.incident_evidence", "query.target_health_assessment"}
        and _facets_describe_incident_triage(facets)
    ):
        resolved = proposal.model_copy(
            update={
                "operation": SemanticOperation.VALIDATE,
                "subject_constraints": ("Incident",),
                "measure_concepts": tuple(sorted(facets)),
                "temporal_scope": {"kind": "current"},
                "output_shape": SemanticOutputShape.INCIDENT_EVIDENCE,
                "evidence_requirements": (),
                "unresolved_terms": (),
                "clarification_requirements": (),
                "clarification": None,
                "investigation": None,
            }
        )
        return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)
    if not bound_incident:
        return proposal, frame
    non_causal_comparison = any(
        (facet.startswith("no_") and "caus" in facet)
        or ("without" in facet and "caus" in facet)
        or "not_caus" in facet
        for facet in facets
    ) and any("window" in facet for facet in facets)
    windowed_change_activity = any("window" in facet for facet in facets) and any(
        "change" in facet for facet in facets
    )
    windowed_incident_change_activity = any("window" in facet for facet in facets) and any(
        "incident" in facet for facet in facets
    )
    completed_change_outcome = any(
        _facet_affirms_concept(facet, "completed_change") for facet in facets
    ) and any(
        _facet_affirms_concept(facet, token)
        for facet in facets
        for token in (
            "recovery",
            "regression",
            "unresolved_outcome",
            "observed_result",
            "observed_results",
        )
    )
    update: dict[str, object] | None = None
    if judgment.primary_intent in {
        "query.incident_evidence",
        "query.resource_error_activity_correlation",
        "query.resource_event_history",
    } and any(_facet_affirms_concept(facet, "recurrence") for facet in facets):
        update = {
            "operation": SemanticOperation.COMPARE,
            "subject_constraints": ("Incident",),
            "measure_concepts": tuple(sorted(facets)),
            "temporal_scope": {"kind": "historical"},
            "output_shape": SemanticOutputShape.INCIDENT_EVIDENCE,
        }
    elif (
        judgment.primary_intent
        in {
            "query.incident_evidence",
            "query.resource_change_activity",
            "query.resource_event_history",
        }
        and completed_change_outcome
    ):
        update = {
            "operation": SemanticOperation.SELECT,
            "subject_constraints": ("Change",),
            "measure_concepts": tuple(sorted(facets)),
            "temporal_scope": {"kind": "historical"},
            "output_shape": SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
        }
    elif judgment.primary_intent == "query.resource_change_activity" and (
        any("correlation" in facet for facet in facets)
        or any("temporal_order" in facet and "caus" in facet for facet in facets)
        or non_causal_comparison
        or windowed_change_activity
        or windowed_incident_change_activity
    ):
        update = {
            "operation": SemanticOperation.COMPARE,
            "subject_constraints": ("Change",),
            "measure_concepts": tuple(sorted({CHANGE_ACTIVITY_COMPARISON_MEASURE, *facets})),
            "temporal_scope": {"kind": "windowed"},
            "output_shape": SemanticOutputShape.TEMPORAL_COMPARISON,
        }
    if update is None:
        return proposal, frame
    resolved = proposal.model_copy(
        update={
            **update,
            "evidence_requirements": (),
            "unresolved_terms": (),
            "clarification_requirements": (),
            "clarification": None,
            "investigation": None,
        }
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


def _canonical_duration_seconds(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.fullmatch(r"duration\.PT(?:(\d{1,2})H)?(?:(\d{1,2})M)?(?:(\d{1,2})S)?", value)
    if match is None or all(part is None for part in match.groups()):
        return None
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    if minutes >= 60 or seconds >= 60:
        return None
    duration_seconds = hours * 3_600 + minutes * 60 + seconds
    return duration_seconds if 60 <= duration_seconds <= 86_400 else None


def normalize_resource_classification_frame(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Restore current Resource classification from complete candidate facets."""

    facets = {facet.replace("-", "_") for facet in proposal.measure_concepts}
    if (
        frame.operation is not SemanticOperation.SELECT
        or not proposal.subject_constraints
        or any(
            subject not in {"Resource", "ResourceType"} for subject in proposal.subject_constraints
        )
        or not _facets_describe_resource_classification(facets)
    ):
        return proposal, frame
    resolved = proposal.model_copy(
        update={
            "subject_constraints": ("Resource",),
            "measure_concepts": tuple(sorted(facets)),
            "temporal_scope": {"kind": "current"},
            "output_shape": SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
            "evidence_requirements": (),
            "unresolved_terms": (),
            "clarification_requirements": (),
            "clarification": None,
            "investigation": None,
        }
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


def normalize_ontology_trace_frame(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    judgment: SemanticJudgmentProposal | None,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Normalize an exact schema trace from complementary frame and judgment evidence."""

    candidate_facets = {facet.replace("-", "_") for facet in proposal.measure_concepts}
    judgment_facets = (
        {facet.replace("-", "_") for facet in judgment.requested_facets}
        if judgment is not None
        else set()
    )

    def describes_trace(facets: set[str]) -> bool:
        axes = all(
            any(_facet_affirms_concept(facet, concept) for facet in facets)
            for concept in ("resource_type", "signal_type", "action_type")
        )
        relationship = bool({"explore", "relationships", "trace"}.intersection(facets)) or any(
            _facet_affirms_concept(facet, "controlled_action_type") for facet in facets
        )
        return axes and relationship

    judgment_trace = (
        judgment is not None
        and judgment.action_posture == "advise_only"
        and judgment.primary_intent == "query.ontology_relationships"
        and describes_trace(judgment_facets)
    )
    candidate_trace = describes_trace(candidate_facets)
    facets = judgment_facets if judgment_trace else candidate_facets
    if (
        (not judgment_trace and not candidate_trace)
        or proposal.operation is not SemanticOperation.SELECT
        or proposal.output_shape != SemanticOutputShape.ONTOLOGY_RELATIONSHIPS
        or set(proposal.subject_constraints) != {"ActionType", "ResourceType", "Rule", "SignalType"}
    ):
        return proposal, frame
    resolved = proposal.model_copy(
        update={
            "subject_constraints": ("ActionType", "ResourceType", "Rule", "SignalType"),
            "measure_concepts": tuple(sorted(facets)),
            "temporal_scope": {},
            "evidence_requirements": (),
            "unresolved_terms": (),
            "clarification_requirements": (),
            "clarification": None,
            "investigation": None,
        }
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


def normalize_operating_objectives_frame(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Restore scoped objective semantics from a valid evidence-validation proposal."""

    facets = {facet.replace("-", "_") for facet in proposal.measure_concepts}
    if (
        frame.operation is not SemanticOperation.VALIDATE
        or frame.output_shape != SemanticOutputShape.EVIDENCE_VALIDATION
        or not _facets_describe_operating_objectives(facets)
    ):
        return proposal, frame
    resolved = proposal.model_copy(
        update={
            "subject_constraints": (
                "BusinessService",
                "RecoveryObjective",
                "ServiceObjective",
            ),
            "measure_concepts": tuple(sorted(facets)),
            "temporal_scope": {"kind": "current"},
            "evidence_requirements": (),
            "unresolved_terms": (),
            "clarification_requirements": (),
            "clarification": None,
            "investigation": None,
        }
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


def normalize_historical_topology_clarification(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Preserve retained topology comparison until one exact Resource is supplied."""

    facets = {facet.replace("-", "_") for facet in proposal.measure_concepts}
    typed_topology_comparison = (
        frame.operation is SemanticOperation.COMPARE
        and frame.output_shape == SemanticOutputShape.TOPOLOGY_GRAPH
        and frame.temporal_scope in ({"kind": "historical"}, {"kind": "windowed"})
    )
    if (
        frame.operation is not SemanticOperation.COMPARE
        or not (typed_topology_comparison or _facets_describe_historical_topology(facets))
        or exact_target_from_constraints(
            frame.subject_constraints,
            utterance=utterance,
            descriptors=descriptors,
        )
        is not None
    ):
        return proposal, frame
    korean = re.search(r"[가-힣]", utterance) is not None
    resolved = proposal.model_copy(
        update={
            "subject_constraints": ("Resource",),
            "measure_concepts": tuple(sorted(facets)),
            "temporal_scope": {"kind": "historical"},
            "output_shape": SemanticOutputShape.TEMPORAL_COMPARISON,
            "evidence_requirements": (),
            "unresolved_terms": ("Resource identity",),
            "clarification_requirements": (ClarificationRequirement.SUBJECT,),
            "clarification": (
                "비교할 정확한 Resource 이름 또는 ID를 알려주세요?"
                if korean
                else "Provide the exact Resource name or ID to compare?"
            ),
            "investigation": None,
        }
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


def normalize_network_path_clarification(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Preserve a model-proposed network path until exact endpoint identities are supplied."""

    facets = {facet.replace("-", "_") for facet in proposal.measure_concepts}
    targetless_topology = frame.output_shape == SemanticOutputShape.TOPOLOGY_GRAPH and (
        bool(stated_value_filters(utterance, descriptors).get(("Resource", "type")))
        or ("Resource" in frame.subject_constraints and len(frame.subject_constraints) > 1)
    )
    declared_object_types = {
        name
        for descriptor in descriptors
        if descriptor.get("kind") == "object"
        if isinstance((name := descriptor.get("name")), str)
    }
    frame_object_types = declared_object_types.intersection(frame.subject_constraints)
    multi_object_topology = (
        frame.output_shape
        in {
            SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
            SemanticOutputShape.TOPOLOGY_GRAPH,
        }
        and "Resource" in frame_object_types
        and len(frame_object_types) > 1
    )
    if (
        frame.operation is not SemanticOperation.SELECT
        or frame.output_shape
        not in {
            SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
            SemanticOutputShape.TOPOLOGY_GRAPH,
        }
        or not (
            targetless_topology or multi_object_topology or _facets_describe_network_path(facets)
        )
        or exact_target_from_constraints(
            frame.subject_constraints,
            utterance=utterance,
            descriptors=descriptors,
        )
        is not None
    ):
        return proposal, frame
    korean = re.search(r"[가-힣]", utterance) is not None
    resolved_facets = {
        *facets,
        *(("topology_graph",) if targetless_topology or multi_object_topology else ()),
    }
    resolved = proposal.model_copy(
        update={
            "operation": SemanticOperation.SELECT,
            "subject_constraints": ("Resource",),
            "measure_concepts": tuple(sorted(resolved_facets)),
            "temporal_scope": {"kind": "current"},
            "output_shape": SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
            "evidence_requirements": (),
            "unresolved_terms": ("Resource identity",),
            "clarification_requirements": (ClarificationRequirement.SUBJECT,),
            "clarification": (
                "추적할 정확한 시작 및 대상 Resource 이름 또는 ID를 알려주세요?"
                if korean
                else "Provide the exact source and target Resource names or IDs to trace?"
            ),
            "investigation": None,
        }
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)
