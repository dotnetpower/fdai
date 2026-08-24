"""Expose classifiers, exact outputs list, and target clarification queries."""

from __future__ import annotations

import re
from typing import Any

from fdai_service_contracts.ontology_query import (
    SemanticOperation,
    SemanticProblemFrame,
)

from .semantic_planning_frame_core import build_semantic_frame
from .semantic_planning_frame_facets import (
    _facet_affirms_concept,
    _facets_describe_configuration_drift_evidence,
    _facets_describe_historical_topology,
    _facets_describe_incident_triage,
    _facets_describe_network_path,
    _facets_describe_resource_classification,
)
from .semantic_planning_models import (
    ClarificationRequirement,
    SemanticFrameProposal,
    SemanticOutputShape,
)
from .semantic_planning_value_filters import stated_subject_fragment, stated_value_filters
from .semantic_target_identity import exact_target_from_constraints

_EXACT_RESOURCE_TARGET_OUTPUTS = frozenset(
    {
        SemanticOutputShape.CAUSAL_EVIDENCE,
        SemanticOutputShape.INVENTORY_IMPACT,
        SemanticOutputShape.TARGET_ACTIVITY,
        SemanticOutputShape.TARGET_CURRENT_STATE,
        SemanticOutputShape.TARGET_ERROR_ACTIVITY_CORRELATION,
        SemanticOutputShape.TARGET_HEALTH_ASSESSMENT,
        SemanticOutputShape.TARGET_INGRESS_CONFIGURATION,
        SemanticOutputShape.TARGET_RESOURCE_METRIC,
        SemanticOutputShape.TARGET_RESOURCE_METRIC_SERIES,
        SemanticOutputShape.TEMPORAL_COMPARISON,
        SemanticOutputShape.TOPOLOGY_GRAPH,
    }
)


def resource_target_clarification(
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
    descriptors: tuple[dict[str, Any], ...],
) -> str | None:
    """Ask for one exact Resource before a target-scoped first-turn read."""
    if context or frame.output_shape in {
        SemanticOutputShape.RESOURCE_STATE_LIST,
        SemanticOutputShape.RESOURCE_TARGET_CANDIDATES,
    }:
        return None
    filters = stated_value_filters(utterance, descriptors)
    resource_filters = {
        property_name: values
        for (object_type, property_name), values in filters.items()
        if object_type == "Resource"
    }
    residual_subject = stated_subject_fragment(
        utterance,
        frame.subject_constraints,
        descriptors,
    )
    target_scoped = frame.output_shape in _EXACT_RESOURCE_TARGET_OUTPUTS or (
        residual_subject is not None and bool(frame.measure_concepts)
    )
    if (
        not resource_filters
        or not target_scoped
        or exact_target_from_constraints(
            frame.subject_constraints,
            utterance=utterance,
            descriptors=descriptors,
        )
        is not None
    ):
        return None
    korean = re.search(r"[가-힣]", utterance) is not None
    if frame.output_shape == SemanticOutputShape.TEMPORAL_COMPARISON:
        return (
            "확인할 리소스의 정확한 이름 또는 리소스 ID를 알려주세요. "
            "대상을 지정하면 요청한 기간의 변경 이력과 사용 가능한 근거를 검증하고, "
            "확인할 수 없는 항목은 한계로 구분하겠습니다."
            if korean
            else (
                "Provide the exact resource name or resource ID. Once identified, I will verify "
                "the change history for the requested period against available evidence and "
                "separate any unverified fields as limitations."
            )
        )
    return (
        "확인할 리소스의 정확한 이름 또는 리소스 ID를 알려주세요. "
        "대상을 지정하면 요청한 상태와 사용 가능한 근거를 검증하고, "
        "확인할 수 없는 항목은 한계로 구분하겠습니다."
        if korean
        else (
            "Provide the exact resource name or resource ID. Once identified, I will verify "
            "the requested state against available evidence and separate any unverified fields "
            "as limitations."
        )
    )


def is_ontology_trace_frame(frame: SemanticProblemFrame) -> bool:
    """Return whether a frame is the bounded no-authority schema trace."""

    facets = set(frame.measure_concepts)
    return (
        frame.operation is SemanticOperation.SELECT
        and frame.subject_constraints == ("ActionType", "ResourceType", "Rule", "SignalType")
        and frame.temporal_scope == {}
        and frame.output_shape == SemanticOutputShape.ONTOLOGY_RELATIONSHIPS
        and all(
            any(_facet_affirms_concept(facet, concept) for facet in facets)
            for concept in (
                "resource_type",
                "signal_type",
                "action_type",
            )
        )
        and (
            bool({"explore", "relationships", "trace", "trace_relationships"}.intersection(facets))
            or any(_facet_affirms_concept(facet, "controlled_action_type") for facet in facets)
        )
    )


def is_resource_classification_frame(frame: SemanticProblemFrame) -> bool:
    """Return whether a frame requests current Resource classification evidence."""

    return (
        frame.operation is SemanticOperation.SELECT
        and frame.subject_constraints == ("Resource",)
        and frame.temporal_scope == {"kind": "current"}
        and frame.output_shape == SemanticOutputShape.ONTOLOGY_RELATIONSHIPS
        and _facets_describe_resource_classification(set(frame.measure_concepts))
    )


def is_historical_topology_clarification_frame(frame: SemanticProblemFrame) -> bool:
    """Return whether retained topology is waiting for one exact Resource identity."""

    return (
        frame.operation is SemanticOperation.COMPARE
        and frame.subject_constraints == ("Resource",)
        and frame.temporal_scope == {"kind": "historical"}
        and frame.output_shape == SemanticOutputShape.TEMPORAL_COMPARISON
        and _facets_describe_historical_topology(set(frame.measure_concepts))
        and frame.unresolved_terms == ("Resource identity",)
    )


def is_network_path_clarification_frame(frame: SemanticProblemFrame) -> bool:
    """Return whether a frame retains a network path pending exact endpoint identity."""

    return (
        frame.operation is SemanticOperation.SELECT
        and frame.subject_constraints == ("Resource",)
        and frame.temporal_scope == {"kind": "current"}
        and frame.output_shape == SemanticOutputShape.ONTOLOGY_RELATIONSHIPS
        and (
            "topology_graph" in frame.measure_concepts
            or _facets_describe_network_path(set(frame.measure_concepts))
        )
        and frame.unresolved_terms == ("Resource identity",)
    )


def is_completed_change_outcome_frame(frame: SemanticProblemFrame) -> bool:
    """Return whether a frame requires unavailable historical effect closure."""

    facets = set(frame.measure_concepts)
    return (
        frame.operation is SemanticOperation.SELECT
        and frame.subject_constraints == ("Change",)
        and frame.temporal_scope == {"kind": "historical"}
        and frame.output_shape == SemanticOutputShape.ONTOLOGY_RELATIONSHIPS
        and any(_facet_affirms_concept(facet, "completed_change") for facet in facets)
        and any(
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
    )


def is_configuration_drift_evidence_frame(frame: SemanticProblemFrame) -> bool:
    """Return whether a frame asks to validate configuration-drift evidence."""

    facets = set(frame.measure_concepts)
    return (
        frame.operation is SemanticOperation.VALIDATE
        and "Resource" in frame.subject_constraints
        and frame.temporal_scope == {"kind": "current"}
        and frame.output_shape == SemanticOutputShape.EVIDENCE_VALIDATION
        and _facets_describe_configuration_drift_evidence(facets)
    )


def is_incident_triage_frame(frame: SemanticProblemFrame) -> bool:
    """Return whether a frame requires unavailable structured incident triage."""

    return (
        frame.operation is SemanticOperation.VALIDATE
        and frame.subject_constraints == ("Incident",)
        and frame.temporal_scope == {"kind": "current"}
        and frame.output_shape == SemanticOutputShape.INCIDENT_EVIDENCE
        and _facets_describe_incident_triage(set(frame.measure_concepts))
    )


def resolve_incident_reference(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Resolve the incident question only when the typed frame reads that incident."""

    requirements = proposal.clarification_requirements
    if (
        requirements != (ClarificationRequirement.INCIDENT_REFERENCE,)
        or frame.output_shape != SemanticOutputShape.INCIDENT_EVIDENCE
    ):
        return proposal, frame
    resolved = proposal.model_copy(
        update={
            "unresolved_terms": (),
            "clarification_requirements": (),
            "clarification": None,
        }
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)


def resolve_principal_scope_evidence_subject(
    proposal: SemanticFrameProposal,
    frame: SemanticProblemFrame,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame]:
    """Use server-owned Resource scope for an otherwise complete evidence frame."""

    if (
        frame.operation is not SemanticOperation.VALIDATE
        or frame.output_shape != SemanticOutputShape.EVIDENCE_VALIDATION
        or proposal.clarification_requirements
        not in {
            (ClarificationRequirement.SUBJECT,),
            (ClarificationRequirement.RESOURCE_IDENTITY,),
        }
        or proposal.subject_constraints not in {(), ("Resource",)}
    ):
        return proposal, frame
    resolved = proposal.model_copy(
        update={
            "subject_constraints": ("Resource",),
            "unresolved_terms": (),
            "clarification_requirements": (),
            "clarification": None,
        }
    )
    return resolved, build_semantic_frame(resolved, utterance=utterance, context=context)
