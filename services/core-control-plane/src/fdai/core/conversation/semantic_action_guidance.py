"""Resolve typed action guidance without creating operational authority."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fdai_service_contracts.ontology_query import SemanticOperation, SemanticProblemFrame
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal

from .semantic_planning_frame_core import build_semantic_frame
from .semantic_planning_models import (
    ClarificationRequirement,
    SemanticAdvisoryResponseIntent,
    SemanticFrameProposal,
    SemanticOutputShape,
)

_INCIDENT_MITIGATION_REQUIREMENTS_EN = (
    "A review-only incident mitigation draft needs the exact incident identity; verified "
    "symptoms, impact, affected scope, and evidence gaps; a registered ActionType with bounded "
    "arguments and expected effects; stop conditions, tested rollback, impact limits, and dry-run "
    "results; a logical-target lock and stable idempotency key; required human approval or valid "
    "standing authorization; two-phase audit; and an independent post-change verification plan. "
    "This guidance creates no draft, approval, or execution authority."
)
_INCIDENT_MITIGATION_REQUIREMENTS_KO = (
    "검토 전용 장애 완화 초안에는 정확한 장애 ID, 검증된 증상과 영향 및 영향 범위와 근거 공백, "
    "범위가 제한된 인자와 예상 효과가 있는 등록된 ActionType, 중지 조건과 검증된 롤백 및 영향 "
    "제한과 dry-run 결과, 논리적 대상 잠금과 안정적인 멱등성 키, 필요한 사람 승인 또는 유효한 "
    "상시 권한, 2단계 감사, 독립적인 변경 후 검증 계획이 필요합니다. 이 안내는 초안, 승인 또는 "
    "실행 권한을 만들지 않습니다."
)


def incident_mitigation_requirements_guidance(
    judgment: SemanticJudgmentProposal | None,
    *,
    judgment_accepted: bool,
    descriptors: Sequence[Mapping[str, Any]],
    locale: str,
) -> tuple[SemanticAdvisoryResponseIntent, str] | None:
    """Return generic guidance only for one manifest-grounded advisory intent."""

    if (
        not judgment_accepted
        or judgment is None
        or judgment.primary_intent != "action_requirements"
        or judgment.action_posture != "advise_only"
        or judgment.action_subject != "none"
        or not {"incident_mitigation", "requirements"}.issubset(
            {facet.strip().replace("-", "_") for facet in judgment.requested_facets}
        )
        or not any(
            target.kind == "object_type" and target.canonical_value == "Incident"
            for target in judgment.targets
        )
        or not any(
            descriptor.get("kind") == "object" and descriptor.get("name") == "Incident"
            for descriptor in descriptors
        )
    ):
        return None
    answer = (
        _INCIDENT_MITIGATION_REQUIREMENTS_KO
        if locale.strip().casefold().startswith("ko")
        else _INCIDENT_MITIGATION_REQUIREMENTS_EN
    )
    return SemanticAdvisoryResponseIntent.INCIDENT_MITIGATION_REQUIREMENTS, answer


def targetless_incident_mitigation_draft_clarification(
    judgment: SemanticJudgmentProposal | None,
    *,
    bound_incident: bool,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Build one typed clarification for an unbound incident mitigation draft."""

    if (
        bound_incident
        or judgment is None
        or judgment.primary_intent != "action_request"
        or judgment.action_posture != "draft_only"
        or judgment.action_subject != "Incident"
        or "incident_mitigation"
        not in {facet.strip().replace("-", "_") for facet in judgment.requested_facets}
        or any(target.kind == "incident_id" for target in judgment.targets)
        or not judgment.ambiguous
        or judgment.unresolved_terms != ("incident_identity",)
        or judgment.clarification is None
        or not judgment.clarification.strip()
    ):
        return None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.ACTION_DRAFT,
        subject_constraints=("Incident",),
        measure_concepts=tuple(judgment.requested_facets),
        temporal_scope={},
        output_shape=SemanticOutputShape.ACTION_DRAFT,
        evidence_requirements=(),
        unresolved_terms=("incident_identity",),
        clarification_requirements=(ClarificationRequirement.INCIDENT_REFERENCE,),
        clarification=judgment.clarification,
        investigation=None,
        confidence=judgment.confidence,
    )
    return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)
