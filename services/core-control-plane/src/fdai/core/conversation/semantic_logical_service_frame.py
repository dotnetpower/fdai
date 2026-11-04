"""Build exact and clarification frames for logical-service state reads."""

from __future__ import annotations

import re

from fdai_service_contracts.ontology_query import SemanticOperation, SemanticProblemFrame
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal

from .semantic_planning_frame_core import build_semantic_frame
from .semantic_planning_frame_facets import _facets_describe_service_current_health
from .semantic_planning_models import (
    ClarificationRequirement,
    SemanticFrameProposal,
    SemanticOutputShape,
)


def build_service_current_health_clarification(
    judgment: SemanticJudgmentProposal | None,
    *,
    utterance: str,
    context: tuple[str, ...],
    candidate_services: tuple[str, ...] = (),
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Preserve service-to-resource health meaning until one service is identified."""

    if judgment is None or not _is_service_current_health_request(judgment):
        return None
    facets = {facet.replace("-", "_") for facet in judgment.requested_facets}
    if not _facets_describe_service_current_health(facets):
        return None
    if _exact_operating_target(judgment, utterance=utterance) is not None:
        return None
    candidates_suffix_ko = f" (후보: {', '.join(candidate_services)})" if candidate_services else ""
    candidates_suffix_en = (
        f" (candidates: {', '.join(candidate_services)})" if candidate_services else ""
    )
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.SELECT,
        subject_constraints=("BusinessService", "Resource", "Workload"),
        measure_concepts=tuple(sorted(facets)),
        temporal_scope={"kind": "current"},
        output_shape=SemanticOutputShape.ONTOLOGY_RELATIONSHIPS,
        evidence_requirements=(),
        unresolved_terms=("BusinessService identity",),
        clarification_requirements=(ClarificationRequirement.SUBJECT,),
        clarification=(
            (
                "현재 상태를 확인할 정확한 BusinessService 이름 또는 ID를 알려주세요"
                f"{candidates_suffix_ko}?"
            )
            if re.search(r"[가-힣]", utterance) is not None
            else (
                "Provide the exact BusinessService name or ID whose current state "
                f"should be checked{candidates_suffix_en}?"
            )
        ),
        investigation=None,
        confidence=judgment.confidence,
    )
    return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)


def build_logical_service_current_state_frame(
    judgment: SemanticJudgmentProposal | None,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Bind one exact source-grounded service or workload to current runtime state."""

    if judgment is None or not _is_service_current_health_request(judgment):
        return None
    facets = {facet.replace("-", "_") for facet in judgment.requested_facets}
    target = _exact_operating_target(judgment, utterance=utterance)
    if not _facets_describe_service_current_health(facets) or target is None:
        return None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.SELECT,
        subject_constraints=(
            "BusinessService",
            "Workload",
            "Resource",
            f"OperatingTarget.type={target[0]}",
            f"OperatingTarget.value={target[1]}",
        ),
        measure_concepts=tuple(sorted(facets)),
        temporal_scope={"kind": "current"},
        output_shape=SemanticOutputShape.LOGICAL_SERVICE_CURRENT_STATE,
        evidence_requirements=("authoritative_operating_model", "authoritative_inventory"),
        unresolved_terms=(),
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=judgment.confidence,
    )
    return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)


def _is_service_current_health_request(judgment: SemanticJudgmentProposal) -> bool:
    return bool(
        judgment.action_posture == "advise_only"
        and judgment.primary_intent == "query.ontology_relationships"
        and all(
            target.canonical_value in {None, "BusinessService", "Resource", "Workload"}
            for target in judgment.targets
        )
    )


def _exact_operating_target(
    judgment: SemanticJudgmentProposal,
    *,
    utterance: str,
) -> tuple[str, str] | None:
    if judgment.ambiguous:
        return None
    deduped: dict[tuple[str, str], tuple[str, str]] = {}
    for target in judgment.targets:
        if (
            target.canonical_value in {"BusinessService", "Workload"}
            and target.kind != "object_type"
            and 0 <= target.source_start < target.source_end <= len(utterance)
            and utterance[target.source_start : target.source_end] == target.value
            and target.value.strip()
        ):
            trimmed = target.value.strip()
            deduped.setdefault(
                (target.canonical_value, trimmed.casefold()), (target.canonical_value, trimmed)
            )
    candidates = tuple(deduped.values())
    return candidates[0] if len(candidates) == 1 else None


def build_business_service_posture_or_burn_frame(
    judgment: SemanticJudgmentProposal | None,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Build frames for business service posture, budget burn, or decision outcome comparison."""

    if judgment is None or judgment.action_posture != "advise_only":
        return None
    if judgment.primary_intent != "query.ontology_relationships":
        return None
    facets = {facet.replace("-", "_") for facet in judgment.requested_facets}
    if (
        "decision_expected_vs_observed_outcome" in facets
        or {
            "expected_effect",
            "observed_outcome",
        }
        <= facets
    ):
        dc_target = _exact_decision_case_target(judgment, utterance=utterance)
        constraints = (
            (
                "DecisionCase",
                "ExpectedEffect",
                "ObservedOutcome",
                "OperatingTarget.type=DecisionCase",
                f"OperatingTarget.value={dc_target}",
            )
            if dc_target is not None
            else ("DecisionCase", "ExpectedEffect", "ObservedOutcome")
        )
        proposal = SemanticFrameProposal(
            operation=SemanticOperation.SELECT,
            subject_constraints=constraints,
            measure_concepts=tuple(sorted(facets)),
            temporal_scope={"kind": "current"},
            output_shape=SemanticOutputShape.DECISION_EXPECTED_VS_OBSERVED_OUTCOME,
            evidence_requirements=("authoritative_operating_model",),
            unresolved_terms=(),
            clarification_requirements=(),
            clarification=None,
            investigation=None,
            confidence=judgment.confidence,
        )
        return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)

    target = _exact_operating_target(judgment, utterance=utterance)
    if target is None or target[0] != "BusinessService":
        return None
    subjects: tuple[str, ...]
    if "service_budget_burn" in facets or {"budget", "burn"} <= facets:
        shape = SemanticOutputShape.BUSINESS_SERVICE_BUDGET_BURN
        subjects = (
            "BusinessService",
            "Budget",
            "CostObjective",
            f"OperatingTarget.type={target[0]}",
            f"OperatingTarget.value={target[1]}",
        )
    elif (
        "service_objective_posture" in facets
        or {
            "service_objective",
            "recovery_objective",
            "cost_objective",
        }
        <= facets
    ):
        shape = SemanticOutputShape.BUSINESS_SERVICE_OBJECTIVE_POSTURE
        subjects = (
            "BusinessService",
            "ServiceObjective",
            "RecoveryObjective",
            "CostObjective",
            "Budget",
            f"OperatingTarget.type={target[0]}",
            f"OperatingTarget.value={target[1]}",
        )
    else:
        return None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.SELECT,
        subject_constraints=subjects,
        measure_concepts=tuple(sorted(facets)),
        temporal_scope={"kind": "current"},
        output_shape=shape,
        evidence_requirements=("authoritative_operating_model",),
        unresolved_terms=(),
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=judgment.confidence,
    )
    return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)


def _exact_decision_case_target(
    judgment: SemanticJudgmentProposal,
    *,
    utterance: str,
) -> str | None:
    if judgment.ambiguous:
        return None
    for target in judgment.targets:
        if (
            target.canonical_value == "DecisionCase"
            and target.kind != "object_type"
            and 0 <= target.source_start < target.source_end <= len(utterance)
            and utterance[target.source_start : target.source_end] == target.value
            and target.value.strip()
        ):
            return target.value.strip()
    return None


__all__ = [
    "build_business_service_posture_or_burn_frame",
    "build_logical_service_current_state_frame",
    "build_service_current_health_clarification",
]
