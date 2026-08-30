"""Focused optional bindings for operational planning and memory agents."""

from __future__ import annotations

from fdai.agents._framework import factory
from fdai.agents._framework.action_semantics import ActionSemanticsCatalog
from fdai.agents._framework.base import Agent
from fdai.agents.muninn import Muninn
from fdai.agents.norns import Norns
from fdai.core.capacity import CapacityGraduationController
from fdai.core.case_history import (
    CaseHistoryAnalyzer,
    CaseHistoryMaterializer,
    CaseHistoryRetentionService,
)
from fdai.core.chaos.coverage import ScenarioCoverageAggregator
from fdai.core.impact_analysis import ChangeAssessmentService
from fdai.core.learning import PostTurnReviewCoordinator
from fdai.core.ontology_platform.evidence_conflict import EvidenceConflictSink
from fdai.core.operational_context import OperationalContextMaterializer
from fdai.core.operational_learning import OperatingPatternCompiler
from fdai.core.operational_planning.prospective_lineage import (
    ProspectiveLineageFinalizer,
    ProspectiveLineageMaterializer,
)
from fdai.rule_catalog.schema.rule_semantic_feedback import SemanticFeedbackCandidateSink
from fdai.shared.providers.state_store import StateStore


def bind_operational_agents(
    agents: dict[str, Agent],
    *,
    scenario_coverage_aggregator: ScenarioCoverageAggregator | None,
    post_turn_review: PostTurnReviewCoordinator | None,
    case_history_analyzer: CaseHistoryAnalyzer | None,
    operating_pattern_compiler: OperatingPatternCompiler | None,
    semantic_feedback_store: SemanticFeedbackCandidateSink | None,
    muninn_state_store: StateStore | None,
    case_history_materializer: CaseHistoryMaterializer | None,
    case_history_retention: CaseHistoryRetentionService | None,
    case_retention_days: int,
    case_deletion_days: int,
    evidence_conflict_sink: EvidenceConflictSink | None,
    prospective_lineage_materializer: ProspectiveLineageMaterializer | None,
    operator_rbac: dict[str, frozenset[str]] | None,
    action_semantics: ActionSemanticsCatalog | None,
    operational_context_materializer: OperationalContextMaterializer | None,
    operational_planner: factory.PlanningCoordinator | None,
    kinetic_proposal_source: factory.KineticProposalSource | None,
    prospective_lineage_finalizer: ProspectiveLineageFinalizer | None,
    change_assessor: ChangeAssessmentService | None,
    cost_runtime: factory.CostRuntimeBindings,
    capacity_graduation_controller: CapacityGraduationController | None,
) -> None:
    """Replace baseline instances only when runtime bindings are available."""

    if any(
        value is not None
        for value in (
            scenario_coverage_aggregator,
            post_turn_review,
            case_history_analyzer,
            operating_pattern_compiler,
            semantic_feedback_store,
        )
    ):
        agents["Norns"] = Norns(
            coverage_aggregator=scenario_coverage_aggregator,
            post_turn_review=post_turn_review,
            case_history_analyzer=case_history_analyzer,
            operating_pattern_compiler=operating_pattern_compiler,
            semantic_feedback_store=semantic_feedback_store,
        )
    if any(
        value is not None
        for value in (
            muninn_state_store,
            case_history_materializer,
            case_history_retention,
            evidence_conflict_sink,
            prospective_lineage_materializer,
        )
    ):
        agents["Muninn"] = Muninn(
            durable_state_store=muninn_state_store,
            case_history=case_history_materializer,
            case_history_retention=case_history_retention,
            case_retention_days=case_retention_days,
            case_deletion_days=case_deletion_days,
            evidence_conflict_sink=evidence_conflict_sink,
            prospective_lineage_materializer=prospective_lineage_materializer,
        )
    forseti = factory.configured_forseti(
        rbac=operator_rbac,
        action_semantics=action_semantics,
        operational_context=operational_context_materializer,
        operational_planner=operational_planner,
        kinetic_proposal_source=kinetic_proposal_source,
        prospective_lineage_finalizer=prospective_lineage_finalizer,
        change_assessor=change_assessor,
    )
    if forseti is not None:
        agents["Forseti"] = forseti
    agents["Njord"] = factory.configured_njord(cost_runtime)
    agents["Freyr"] = factory.configured_freyr(capacity_graduation_controller)


__all__ = ["bind_operational_agents"]
