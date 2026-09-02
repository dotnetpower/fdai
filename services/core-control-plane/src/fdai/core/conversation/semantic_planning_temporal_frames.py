"""Construct historical and activity-oriented semantic frames."""

from __future__ import annotations

import re

from fdai_service_contracts.ontology_query import (
    SemanticOperation,
    SemanticProblemFrame,
)
from fdai_service_contracts.semantic_judgment import SemanticJudgmentProposal

from .semantic_planning_frame_core import build_semantic_frame
from .semantic_planning_frame_facets import (
    _facets_describe_historical_relationship_change,
    _facets_describe_historical_topology,
    _facets_describe_ontology_release_health,
    _facets_describe_resource_activity,
    _facets_describe_resource_activity_types,
)
from .semantic_planning_models import (
    ClarificationRequirement,
    SemanticFrameProposal,
    SemanticOutputShape,
)


def build_historical_topology_clarification(
    judgment: SemanticJudgmentProposal | None,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Build a retained-topology clarification from accepted candidate-only meaning."""

    if (
        judgment is None
        or judgment.action_posture != "advise_only"
        or judgment.primary_intent
        not in {
            "query.ontology_relationships",
            "query.resource_change_activity",
            "query.resource_event_history",
        }
        or any(
            target.canonical_value not in {"ChangeWindow", "Resource"}
            for target in judgment.targets
        )
    ):
        return None
    facets = {facet.replace("-", "_") for facet in judgment.requested_facets}
    if not (
        _facets_describe_historical_topology(facets)
        or _facets_describe_historical_relationship_change(facets)
    ):
        return None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.COMPARE,
        subject_constraints=("Resource",),
        measure_concepts=tuple(sorted(facets)),
        temporal_scope={"kind": "historical"},
        output_shape=SemanticOutputShape.TEMPORAL_COMPARISON,
        evidence_requirements=(),
        unresolved_terms=("Resource identity",),
        clarification_requirements=(ClarificationRequirement.SUBJECT,),
        clarification=(
            "비교할 정확한 Resource 이름 또는 ID를 알려주세요?"
            if re.search(r"[가-힣]", utterance) is not None
            else "Provide the exact Resource name or ID to compare?"
        ),
        investigation=None,
        confidence=judgment.confidence,
    )
    return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)


def build_resource_activity_clarification(
    judgment: SemanticJudgmentProposal | None,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Preserve bounded Resource activity until one exact target is supplied."""

    if (
        judgment is None
        or judgment.action_posture != "advise_only"
        or judgment.primary_intent != "query.resource_change_activity"
        or any(
            (
                target.canonical_value not in {None, "Resource"}
                and not (
                    target.kind == "resource_type" and target.canonical_value == "ResourceType"
                )
            )
            and not (
                target.kind == "time_range"
                and target.canonical_value is not None
                and target.canonical_value.startswith("duration.")
            )
            for target in judgment.targets
        )
    ):
        return None
    facets = {facet.replace("-", "_") for facet in judgment.requested_facets}
    has_duration_target = any(
        target.kind == "time_range"
        and target.canonical_value is not None
        and target.canonical_value.startswith("duration.")
        for target in judgment.targets
    )
    if not _facets_describe_resource_activity(facets) and not (
        has_duration_target and _facets_describe_resource_activity_types(facets)
    ):
        return None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.SELECT,
        subject_constraints=("Resource",),
        measure_concepts=tuple(sorted(facets)),
        temporal_scope={"kind": "windowed"},
        output_shape=SemanticOutputShape.TARGET_ACTIVITY,
        evidence_requirements=(),
        unresolved_terms=("Resource identity",),
        clarification_requirements=(ClarificationRequirement.SUBJECT,),
        clarification=(
            "활동을 조회할 정확한 Resource 이름 또는 ID를 알려주세요?"
            if re.search(r"[가-힣]", utterance) is not None
            else "Provide the exact Resource name or ID whose activity should be queried?"
        ),
        investigation=None,
        confidence=judgment.confidence,
    )
    return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)


def build_resource_event_history_clarification(
    judgment: SemanticJudgmentProposal | None,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> tuple[SemanticFrameProposal, SemanticProblemFrame] | None:
    """Preserve event-history meaning until one exact Resource is supplied."""

    if (
        judgment is None
        or judgment.action_posture != "advise_only"
        or judgment.primary_intent != "query.resource_event_history"
        or any(
            target.canonical_value not in {None, "Resource"}
            and not (
                target.kind == "time_range"
                and target.canonical_value is not None
                and target.canonical_value.startswith("duration.")
            )
            for target in judgment.targets
        )
    ):
        return None
    facets = {facet.replace("-", "_") for facet in judgment.requested_facets}
    if not _facets_describe_resource_activity(facets):
        return None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.SELECT,
        subject_constraints=("Resource",),
        measure_concepts=tuple(sorted(facets)),
        temporal_scope={"kind": "windowed"},
        output_shape=SemanticOutputShape.RESOURCE_EVENT_HISTORY,
        evidence_requirements=(),
        unresolved_terms=("Resource identity",),
        clarification_requirements=(ClarificationRequirement.SUBJECT,),
        clarification=(
            "이벤트를 조회할 정확한 Resource 이름 또는 ID를 알려주세요?"
            if re.search(r"[가-힣]", utterance) is not None
            else "Provide the exact Resource name or ID whose events should be queried?"
        ),
        investigation=None,
        confidence=judgment.confidence,
    )
    return proposal, build_semantic_frame(proposal, utterance=utterance, context=context)


def build_ontology_release_health_frame(
    judgment: SemanticJudgmentProposal | None,
    *,
    utterance: str,
    context: tuple[str, ...],
) -> SemanticProblemFrame | None:
    """Build a no-authority historical release evidence-health frame."""

    if (
        judgment is None
        or judgment.action_posture != "advise_only"
        or judgment.primary_intent
        not in {
            "query.ontology_declaration",
            "query.ontology_evidence_health",
            "query.ontology_relationships",
            "query.ontology_release_diff",
        }
        or any(
            target.canonical_value not in {None, "Ontology", "PolicyArtifact", "Resource", "Rule"}
            for target in judgment.targets
        )
    ):
        return None
    facets = {facet.replace("-", "_") for facet in judgment.requested_facets}
    if not _facets_describe_ontology_release_health(facets):
        return None
    proposal = SemanticFrameProposal(
        operation=SemanticOperation.VALIDATE,
        subject_constraints=("Resource",),
        measure_concepts=tuple(sorted(facets)),
        temporal_scope={"kind": "historical"},
        output_shape=SemanticOutputShape.ONTOLOGY_RELEASE_EVIDENCE_HEALTH,
        evidence_requirements=(),
        unresolved_terms=(),
        clarification_requirements=(),
        clarification=None,
        investigation=None,
        confidence=judgment.confidence,
    )
    return build_semantic_frame(proposal, utterance=utterance, context=context)
