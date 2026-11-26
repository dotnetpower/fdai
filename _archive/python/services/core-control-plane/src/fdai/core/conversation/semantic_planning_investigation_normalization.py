"""Normalize evidence-specific semantic investigation frames."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from fdai_service_contracts.ontology_query import SemanticOperation

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
from .semantic_planning_models import (
    BoundInvestigationContinuation,
    ClarificationRequirement,
    SemanticFrameProposal,
    SemanticOutputShape,
)
from .semantic_target_identity import exact_target_from_constraints

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


def normalize_missing_resource_slowness_investigation(
    proposal: SemanticFrameProposal,
    *,
    utterance: str,
    descriptors: tuple[dict[str, Any], ...],
    metric_concepts: Sequence[str],
    inventory_query_language: InventoryQueryLanguageRegistry | None,
    semantic_judgment: Mapping[str, Any] | None,
) -> SemanticFrameProposal:
    """Complete a typed exact-Resource slowness diagnosis from reviewed spans."""

    facets_raw = semantic_judgment.get("requested_facets", ()) if semantic_judgment else ()
    facets = {str(item) for item in facets_raw} if isinstance(facets_raw, (list, tuple)) else set()
    explicit_hypothesis_signals = (
        "hypothesis_network_latency",
        "hypothesis_application_latency",
        "hypothesis_mysql_saturation",
        "hypothesis_request_growth",
    )
    declared_types = {
        str(descriptor["name"])
        for descriptor in descriptors
        if descriptor.get("kind") == "object" and isinstance(descriptor.get("name"), str)
    }
    proposal_types = tuple(
        constraint for constraint in proposal.subject_constraints if constraint in declared_types
    )
    target = exact_target_from_constraints(
        proposal.subject_constraints,
        utterance=utterance,
        descriptors=descriptors,
    )
    judgment_targets = semantic_judgment.get("targets", ()) if semantic_judgment else ()
    judgment_resource_target = (
        target is not None
        and isinstance(judgment_targets, (list, tuple))
        and len(judgment_targets) == 1
        and isinstance(judgment_targets[0], Mapping)
        and judgment_targets[0].get("kind") == "resource"
        and isinstance(judgment_targets[0].get("value"), str)
        and judgment_targets[0]["value"].casefold() == target.casefold()
        and judgment_targets[0].get("canonical_value") in {None, "Resource"}
    )
    resource_type_grounded = proposal_types == ("Resource",) or (
        not proposal_types and judgment_resource_target
    )
    query_sides = service_impact_query_sides(descriptors)
    spans = {
        signal: query_signal_span(utterance, inventory_query_language, signal)
        for signal in ("causal_diagnosis", "symptom_slowness", "temporal_onset")
    }
    target_start = utterance.casefold().find(target.casefold()) if target is not None else -1
    target_unique = (
        target is not None
        and target_start >= 0
        and utterance.casefold().count(target.casefold()) == 1
    )
    target_end = target_start + len(target) if target_unique and target is not None else -1
    spans_available = all(value is not None for value in spans.values())
    spans_outside_target = (
        target_unique
        and spans_available
        and not any(
            match is not None and match[0] < target_end and match[1] > target_start
            for match in spans.values()
        )
    )
    no_negation = inventory_query_language is not None and not query_signal_matches(
        utterance,
        inventory_query_language,
        "slowness_negation",
    )
    no_competing_event = inventory_query_language is not None and not query_signal_matches(
        utterance,
        inventory_query_language,
        "competing_change_event",
    )
    no_explicit_hypothesis = inventory_query_language is not None and not any(
        query_signal_matches(utterance, inventory_query_language, signal)
        for signal in explicit_hypothesis_signals
    )
    checks = (
        ("operation_explain_change", proposal.operation is SemanticOperation.EXPLAIN_CHANGE),
        ("resource_type_grounded", resource_type_grounded),
        ("unresolved_terms_empty", not proposal.unresolved_terms),
        ("clarification_requirements_empty", not proposal.clarification_requirements),
        ("clarification_absent", proposal.clarification is None),
        ("cause_facet_present", "cause" in facets),
        ("judgment_present", semantic_judgment is not None),
        (
            "advise_only",
            semantic_judgment is not None
            and semantic_judgment.get("action_posture") == "advise_only",
        ),
        (
            "execution_authority_false",
            semantic_judgment is not None and semantic_judgment.get("execution_authority") is False,
        ),
        ("inventory_language_bound", inventory_query_language is not None),
        ("service_latency_available", "service.latency" in metric_concepts),
        ("dependency_latency_available", "dependency.latency" in metric_concepts),
        ("request_volume_available", "request.volume" in metric_concepts),
        ("non_negated", no_negation),
        ("no_competing_event", no_competing_event),
        ("no_explicit_hypothesis", no_explicit_hypothesis),
        ("exact_target_resolved", target_unique),
        ("query_sides_available", query_sides is not None),
        ("signal_spans_available", spans_available),
        ("signal_spans_outside_target", spans_outside_target),
    )
    failed_preconditions = tuple(name for name, passed in checks if not passed)
    if (
        proposal.investigation is None
        and proposal.output_shape is SemanticOutputShape.CAUSAL_EVIDENCE
    ):
        _LOGGER.info(
            "semantic_planning_resource_slowness_recovery_evaluated",
            extra={
                "failed_preconditions": ",".join(failed_preconditions) or "none",
                "failed_precondition_count": len(failed_preconditions),
            },
        )
    if failed_preconditions:
        return proposal
    if target is None or query_sides is None:  # pragma: no cover - precondition invariant
        raise RuntimeError("resource slowness recovery preconditions drifted")

    def source(signal: str) -> IntentSourceSpan:
        match = spans[signal]
        if match is None:
            raise ValueError("resource slowness signal span is unavailable")
        return IntentSourceSpan(start=match[0], end=match[1], text=match[2])

    target_span = IntentSourceSpan(
        start=target_start,
        end=target_end,
        text=utterance[target_start:target_end],
    )
    causal_span = source("causal_diagnosis")
    symptom_span = source("symptom_slowness")
    onset_span = source("temporal_onset")
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
                measure_id="service-latency",
                span=symptom_span,
                concept_id="service.latency",
                target_mention_id="target",
                direction=InvestigationMeasureDirection.INCREASE,
            ),
        ),
        primary_symptom_measure_id="service-latency",
        temporal_cues=(
            InvestigationTemporalCue(
                cue_id="onset",
                span=onset_span,
                role=InvestigationTemporalRole.ONSET,
            ),
        ),
        relationship_intents=(
            InvestigationRelationshipIntent(
                relationship_id="dependencies",
                span=causal_span,
                source_mention_id="target",
                query_side_candidates=query_sides,
            ),
        ),
        hypotheses=(
            InvestigationHypothesis(
                hypothesis_id="dependency-latency",
                span=causal_span,
                relationship_id="dependencies",
                cause_measure_concept="dependency.latency",
                effect_measure_id="service-latency",
                competing_explanations=("traffic-load",),
            ),
            InvestigationHypothesis(
                hypothesis_id="traffic-load",
                span=causal_span,
                relationship_id="dependencies",
                cause_measure_concept="request.volume",
                effect_measure_id="service-latency",
                competing_explanations=("dependency-latency",),
            ),
        ),
        evidence_standard=InvestigationEvidenceStandard.SUPPORT_AND_REFUTATION,
        answer_shape=InvestigationAnswerShape.DIAGNOSIS,
        confidence=proposal.confidence,
    )
    return proposal.model_copy(
        update={
            "subject_constraints": ("Resource", target),
            "measure_concepts": ("service.latency",),
            "evidence_requirements": ("support_and_refutation",),
            "investigation": investigation,
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


__all__ = [
    "normalize_bound_latency_recovery",
    "normalize_missing_mysql_pressure_investigation",
    "normalize_missing_resource_slowness_investigation",
    "normalize_missing_vm_cpu_investigation",
    "normalize_network_application_latency_investigation",
]
