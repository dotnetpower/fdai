"""Focused optional bindings for operational planning and memory agents."""

from __future__ import annotations

import logging
from typing import cast

from fdai.agents._framework import factory
from fdai.agents._framework.action_semantics import ActionSemanticsCatalog
from fdai.agents._framework.anomaly_action import AnomalyActionSource
from fdai.agents._framework.base import Agent
from fdai.agents.mimir import Mimir
from fdai.agents.muninn import Muninn
from fdai.agents.norns import Norns
from fdai.agents.saga import Saga
from fdai.agents.thor import Thor
from fdai.agents.var import Var
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
from fdai.core.operational_context.test_context import TestContextSource
from fdai.core.operational_learning import OperatingPatternCompiler
from fdai.core.operational_planning.prospective_lineage import (
    ProspectiveLineageFinalizer,
    ProspectiveLineageMaterializer,
)
from fdai.rule_catalog.schema.rule_semantic_feedback import SemanticFeedbackCandidateSink
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmissionProvider
from fdai.shared.providers.state_store import StateStore

_LOG = logging.getLogger(__name__)
_MAX_NORNS_STARTUP_RECOVERY = 5_000


async def rehydrate_operational_agents(agents: dict[str, Agent]) -> None:
    """Restore durable executor and learner work before consumers start."""
    thor = agents.get("Thor")
    if isinstance(thor, Thor):
        restored = await thor.rehydrate()
        if restored:
            _LOG.info("pantheon_thor_rehydrated", extra={"in_flight_runs": restored})
    norns = agents.get("Norns")
    if isinstance(norns, Norns):
        recovered_total = 0
        published_total = 0
        for index in range(_MAX_NORNS_STARTUP_RECOVERY + 1):
            recovered = await norns.recover_issue_learning()
            if not recovered:
                break
            if index == _MAX_NORNS_STARTUP_RECOVERY:
                raise RuntimeError("Norns pending candidate recovery capacity exceeded")
            recovered_total += recovered
            published_total += await norns.flush_candidates()
        if recovered_total:
            _LOG.info(
                "pantheon_norns_issue_learning_rehydrated",
                extra={
                    "pending_candidates": recovered_total,
                    "published": published_total,
                },
            )
    saga = agents.get("Saga")
    if isinstance(saga, Saga):
        restored = await saga.rehydrate_issue_tracker()
        if restored:
            _LOG.info("pantheon_saga_issues_rehydrated", extra={"issues": restored})
    var = agents.get("Var")
    if isinstance(var, Var):
        finalized, published = await var.recover_approvals()
        if finalized or published:
            _LOG.info(
                "pantheon_var_approvals_recovered",
                extra={"finalized": finalized, "published": published},
            )


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
    test_context_source: TestContextSource | None = None,
    test_context_admission: DecisionEvidenceAdmissionProvider | None = None,
    anomaly_action_sources: dict[str, AnomalyActionSource] | None = None,
) -> None:
    """Replace baseline instances only when runtime bindings are available."""

    if case_history_materializer is not None:
        cast(Mimir, agents["Mimir"]).bind_case_history(case_history_materializer)

    if any(
        value is not None
        for value in (
            scenario_coverage_aggregator,
            post_turn_review,
            case_history_analyzer,
            operating_pattern_compiler,
            semantic_feedback_store,
            muninn_state_store,
        )
    ):
        agents["Norns"] = Norns(
            coverage_aggregator=scenario_coverage_aggregator,
            post_turn_review=post_turn_review,
            case_history_analyzer=case_history_analyzer,
            operating_pattern_compiler=operating_pattern_compiler,
            semantic_feedback_store=semantic_feedback_store,
            issue_state_store=muninn_state_store,
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
        test_context_source=test_context_source,
        test_context_admission=test_context_admission,
        anomaly_action_sources=anomaly_action_sources,
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
