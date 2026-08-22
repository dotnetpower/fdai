"""Build verified semantic frames and resolve server-owned clarification context."""

from __future__ import annotations

import re
from typing import Any

from fdai_service_contracts.ontology_query import (
    SemanticOperation,
    SemanticProblemFrame,
    canonical_json,
    content_digest,
)

from .semantic_investigation import VerifiedInvestigationIntent
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


def build_semantic_frame(
    proposal: SemanticFrameProposal,
    *,
    utterance: str,
    context: tuple[str, ...],
    investigation_intent: VerifiedInvestigationIntent | None = None,
) -> SemanticProblemFrame:
    """Bind a candidate frame to exact input and investigation identities."""

    input_digest = content_digest({"utterance": utterance, "context": context})
    payload = {
        "schema_version": "1.0.0",
        "operation": proposal.operation.value,
        "subject_constraints": proposal.subject_constraints,
        "measure_concepts": proposal.measure_concepts,
        "temporal_scope": proposal.temporal_scope,
        "output_shape": proposal.output_shape.value,
        "evidence_requirements": proposal.evidence_requirements,
        "unresolved_terms": proposal.unresolved_terms,
        "input_digest": input_digest,
        "authority": "candidate_only",
        "execution_authority": False,
    }
    if investigation_intent is not None:
        payload["investigation_intent_digest"] = investigation_intent.intent_digest
    return SemanticProblemFrame(
        operation=proposal.operation,
        subject_constraints=proposal.subject_constraints,
        measure_concepts=proposal.measure_concepts,
        temporal_scope_json=canonical_json(proposal.temporal_scope),
        output_shape=proposal.output_shape.value,
        evidence_requirements=proposal.evidence_requirements,
        unresolved_terms=proposal.unresolved_terms,
        investigation_intent_digest=(
            investigation_intent.intent_digest if investigation_intent is not None else None
        ),
        input_digest=input_digest,
        frame_digest=content_digest(payload),
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


__all__ = [
    "build_semantic_frame",
    "resource_target_clarification",
    "resolve_incident_reference",
    "resolve_principal_scope_evidence_subject",
]
