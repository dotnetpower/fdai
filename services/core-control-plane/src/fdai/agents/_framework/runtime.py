"""Composition-root wiring for the fixed shadow-first Pantheon runtime."""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from fdai.agents._framework import architecture_review_runtime as arb_runtime
from fdai.agents._framework import assignment_wiring as assignment_runtime
from fdai.agents._framework import execution_safety, factory, runtime_health, runtime_subscriptions
from fdai.agents._framework.action_semantics import ActionSemanticsCatalog
from fdai.agents._framework.anomaly_action import AnomalyActionSource
from fdai.agents._framework.base import Agent
from fdai.agents._framework.bus_bridge import AgentHandlerObserver, EventBusBridge
from fdai.agents._framework.catalog_review_wiring import CatalogReviewBindings, bind_catalog_review
from fdai.agents._framework.conversation_tools import AgentConversationToolRegistry
from fdai.agents._framework.deliberation import T2ConversationSynthesizer
from fdai.agents._framework.divergence import ShadowDivergenceLedger
from fdai.agents._framework.huginn_operator_receipt import OperatorRequestReceiptGate
from fdai.agents._framework.kpi import KpiCollector
from fdai.agents._framework.mimir_maintenance import (
    MimirCatalogPromotionOutcomeReader,
    MimirRegressionRunner,
    MimirRuleDeprecationReader,
    MimirRuleSourcePoller,
)
from fdai.agents._framework.pantheon import (
    HARD_DEPENDENCY_AGENTS,
    PANTHEON_NAMES,
    PANTHEON_SPECS,
)
from fdai.agents._framework.registry import PantheonRegistry, load_pantheon
from fdai.agents._framework.runtime_conversation import RuntimeConversationPort
from fdai.agents._framework.semantic_routing import SemanticAgentRouter, SemanticRouterConfig
from fdai.agents._framework.thor_dispatch_validation import missing_wire_safeguards
from fdai.agents._framework.thor_preflight import ThorPreflightSimulator
from fdai.agents._framework.tool_answer import answer_from_owned_tools
from fdai.agents._framework.tool_semantic import SemanticToolPlanner
from fdai.agents.bragi import Bragi
from fdai.agents.heimdall import (
    ActionObservationHook,
    Heimdall,
    IncidentCandidateHook,
    OperationalEvidenceHook,
    ReadInvestigationHook,
)
from fdai.agents.huginn import DiscoveryProjector, Huginn
from fdai.agents.mimir import Mimir
from fdai.agents.norns import Norns
from fdai.agents.saga import Saga
from fdai.agents.thor import ActionExecutor, ActionRunStore, Thor
from fdai.agents.var import ApproverAuthorizer
from fdai.agents.vidar import RollbackExecutor
from fdai.core.architecture_review import ArchitectureReviewTraceObserver
from fdai.core.capacity import CapacityGraduationController
from fdai.core.case_history import (
    CaseHistoryAnalyzer,
    CaseHistoryMaterializer,
    CaseHistoryRetentionService,
)
from fdai.core.chaos.coverage import ScenarioCoverageAggregator
from fdai.core.conversation.semantic_judgment import SemanticJudgmentBoundary
from fdai.core.detection.forecast_closure import ForecastClosureCoordinator
from fdai.core.detection.forecast_episode import ForecastEpisodeStore
from fdai.core.detection.forecast_evaluation import ForecastEpisodeEvaluator
from fdai.core.impact_analysis import ChangeAssessmentService
from fdai.core.learning import PostTurnReviewCoordinator
from fdai.core.metering.budget import BudgetLedger, ModelBudget
from fdai.core.metering.pricing import PricingTable
from fdai.core.metering.sink import MeteringSink
from fdai.core.ontology_platform.evidence_conflict import EvidenceConflictSink
from fdai.core.operational_context import OperationalContextMaterializer
from fdai.core.operational_learning import OperatingPatternCompiler
from fdai.core.operational_planning.prospective_lineage import (
    ProspectiveLineageFinalizer,
    ProspectiveLineageMaterializer,
)
from fdai.core.rule_semantic_generation import RuleGenerationActivationBinder
from fdai.core.tiers.t1_lightweight.tier import EmbeddingModel
from fdai.rule_catalog.schema.rule_semantic_feedback import SemanticFeedbackCandidateSink
from fdai.shared.contracts.models import OntologyActionType
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.resource_lock import ResourceLock
from fdai.shared.providers.state_store import StateStore

from . import development_authority_runtime as development_runtime
from . import runtime_sensing
from .runtime_operational_agents import (
    bind_durable_governance_stores,
    bind_operational_agents,
    rehydrate_operational_agents,
)

_LOG = logging.getLogger(__name__)
_INGRESS_PRINCIPAL = "Huginn"
_DEFAULT_GROUP_PREFIX = "fdai-pantheon"
_OBSERVER_PRINCIPAL = "runtime-observer"
_EXECUTABLE_VERDICTS = frozenset({"auto", "hil"})
_VERDICT_EVIDENCE_KEYS = frozenset(
    {"arbitration", "change_assessment", "decision_case", "kind", "risk_verdict", "decision"}
)
RecoveryEffectObserver = Callable[[str, dict[str, Any]], Awaitable[None]]


@dataclass
class PantheonRuntime(RuntimeConversationPort):
    """Live wiring of the 15 pantheon agents over an ``EventBus`` provider."""

    bridge: EventBusBridge
    agents: dict[str, Agent]
    raw_event_topic: str
    subscription_count: int
    enforce: bool
    kpi_collector: KpiCollector = field(default_factory=KpiCollector)
    _ingress_dropped: int = 0
    shadow_decisions: Counter[str] = field(default_factory=Counter)
    disabled: frozenset[str] = frozenset()
    divergence: ShadowDivergenceLedger | None = None
    architecture_review_trace_observer: ArchitectureReviewTraceObserver | None = None
    _bragi: Bragi | None = None
    _conversation_tools: AgentConversationToolRegistry | None = None
    _semantic_tool_planner: SemanticToolPlanner | None = None
    _continuity_failures: dict[str, str] = field(default_factory=dict)
    _context_index_workers: runtime_subscriptions.ContextIndexWorkerBindings | None = None

    @classmethod
    def build(
        cls,
        *,
        provider: EventBus,
        raw_event_topic: str,
        registry: PantheonRegistry | None = None,
        enforce: bool = False,
        governed_execution_selected: bool = False,
        consumer_group_prefix: str = _DEFAULT_GROUP_PREFIX,
        saga: Saga | None = None,
        muninn_state_store: StateStore | None = None,
        huginn_state_store: StateStore | None = None,
        operator_request_receipt_gate: OperatorRequestReceiptGate | None = None,
        huginn_schema_learning_enabled: bool = False,
        heimdall_state_store: StateStore | None = None,
        njord_state_store: StateStore | None = None,
        freyr_state_store: StateStore | None = None,
        loki_state_store: StateStore | None = None,
        evidence_conflict_sink: EvidenceConflictSink | None = None,
        rule_generation_workers: runtime_subscriptions.RuleGenerationWorkerBindings | None = None,
        rule_generation_activation_binder: RuleGenerationActivationBinder | None = None,
        rule_generation_state_store: StateStore | None = None,
        context_index_workers: runtime_subscriptions.ContextIndexWorkerBindings | None = None,
        disabled_agents: frozenset[str] | None = None,
        divergence: ShadowDivergenceLedger | None = None,
        kpi_collector: KpiCollector | None = None,
        thor_executor: ActionExecutor | None = None,
        thor_preflight_simulator: ThorPreflightSimulator | None = None,
        thor_state_store: ActionRunStore | None = None,
        rollback_executors: dict[str, RollbackExecutor] | None = None,
        vidar_state_store: StateStore | None = None,
        var_state_store: StateStore | None = None,
        forseti_state_store: StateStore | None = None,
        bragi_state_store: StateStore | None = None,
        odin_state_store: StateStore | None = None,
        proposal_rate_limit_state_store: StateStore | None = None,
        ordered_poison_halt_state_store: StateStore | None = None,
        operator_rbac: dict[str, frozenset[str]] | None = None,
        approver_authorizer: ApproverAuthorizer | None = None,
        development_authority: development_runtime.DevelopmentRuntimeBindings | None = None,
        execution_resource_lock: ResourceLock | None = None,
        incident_candidate_hook: IncidentCandidateHook | None = None,
        heimdall_rate_threshold: int = 5,
        heimdall_rate_window: int = 300,
        heimdall_security_high_threshold: int = 5,
        heimdall_security_window_events: int = 100,
        heimdall_alert_rate_per_hour: int = 5,
        read_investigation_hook: ReadInvestigationHook | None = None,
        operational_evidence_hook: OperationalEvidenceHook | None = None,
        heimdall_action_observation_hook: ActionObservationHook | None = None,
        discovery_projector: DiscoveryProjector | None = None,
        scenario_coverage_aggregator: ScenarioCoverageAggregator | None = None,
        post_turn_review: PostTurnReviewCoordinator | None = None,
        case_history_materializer: CaseHistoryMaterializer | None = None,
        operating_pattern_compiler: OperatingPatternCompiler | None = None,
        semantic_feedback_store: SemanticFeedbackCandidateSink | None = None,
        case_history_analyzer: CaseHistoryAnalyzer | None = None,
        operational_context_materializer: OperationalContextMaterializer | None = None,
        test_context_source: factory.TestContextSource | None = None,
        test_context_admission: factory.DecisionEvidenceAdmissionProvider | None = None,
        operational_planner: factory.PlanningCoordinator | None = None,
        kinetic_proposal_source: factory.KineticProposalSource | None = None,
        anomaly_action_sources: dict[str, AnomalyActionSource] | None = None,
        prospective_lineage_finalizer: ProspectiveLineageFinalizer | None = None,
        prospective_lineage_materializer: ProspectiveLineageMaterializer | None = None,
        change_assessor: ChangeAssessmentService | None = None,
        catalog_review: CatalogReviewBindings | None = None,
        mimir_promotion_outcome_reader: MimirCatalogPromotionOutcomeReader | None = None,
        mimir_regression_runner: MimirRegressionRunner | None = None,
        mimir_rule_source_poller: MimirRuleSourcePoller | None = None,
        mimir_rule_deprecation_reader: MimirRuleDeprecationReader | None = None,
        case_history_retention: CaseHistoryRetentionService | None = None,
        forecast_evaluator: ForecastEpisodeEvaluator | None = None,
        forecast_closer: ForecastClosureCoordinator | None = None,
        forecast_store: ForecastEpisodeStore | None = None,
        case_retention_days: int = 30,
        case_deletion_days: int = 60,
        action_types: tuple[OntologyActionType, ...] = (),
        handler_observer: AgentHandlerObserver | None = None,
        recovery_effect_observer: RecoveryEffectObserver | None = None,
        conversation_semantic_judgment: SemanticJudgmentBoundary | None = None,
        conversation_embedding_model: EmbeddingModel | None = None,
        conversation_t2_synthesizer: T2ConversationSynthesizer | None = None,
        conversation_escalation_budget: ModelBudget | None = None,
        conversation_escalation_ledger: BudgetLedger | None = None,
        conversation_pricing: PricingTable | None = None,
        conversation_metering: MeteringSink | None = None,
        conversation_t2_model_key: str = "",
        semantic_router_config: SemanticRouterConfig | None = None,
        conversation_tool_timeout_seconds: float = 5.0,
        cost_runtime: factory.CostRuntimeBindings = factory.DEFAULT_COST_RUNTIME_BINDINGS,
        capacity_graduation_controller: CapacityGraduationController | None = None,
        assignment_workflow: assignment_runtime.AssignmentWorkflowBindings | None = None,
    ) -> PantheonRuntime:
        if not raw_event_topic or not raw_event_topic.strip():
            raise ValueError("raw_event_topic MUST be a non-empty topic name")

        human_access = assignment_workflow.human_access if assignment_workflow is not None else None
        human_access_bound = human_access is not None and human_access.execution_bound
        execution_safety.validate_enforce_bindings(
            enforce=enforce or development_authority is not None,
            has_executor=thor_executor is not None or human_access_bound,
            has_state_store=thor_state_store is not None,
            saga=saga,
            has_rollback=bool(rollback_executors) or human_access_bound,
            has_vidar_state_store=vidar_state_store is not None,
            has_var_state_store=var_state_store is not None,
            has_forseti_state_store=forseti_state_store is not None,
            has_approver_authorizer=(
                approver_authorizer is not None or development_authority is not None
            ),
            resource_lock=execution_resource_lock,
            has_action_semantics=bool(action_types),
            has_preflight_simulator=thor_preflight_simulator is not None,
        )
        disabled = execution_safety.validate_disabled_agents(disabled_agents)
        reg = registry or load_pantheon()
        bridge = EventBusBridge(
            provider=provider,
            registry=reg,
            consumer_group_prefix=consumer_group_prefix,
            handler_max_retries=2,
            handler_observer=handler_observer,
            halt_state_store=ordered_poison_halt_state_store,
            payload_validator=_default_payload_validator,
        )
        instantiated = factory.instantiate_pantheon()
        instantiated["Huginn"] = factory.configured_huginn(
            discovery_projector,
            huginn_state_store,
            operator_request_receipt_gate=operator_request_receipt_gate,
            schema_learning_enabled=huginn_schema_learning_enabled,
        )
        instantiated["Loki"] = factory.configured_loki(loki_state_store)
        bind_catalog_review(instantiated, catalog_review)
        if (
            conversation_semantic_judgment is not None
            or conversation_embedding_model is not None
            or conversation_t2_synthesizer is not None
            or bragi_state_store is not None
        ):
            instantiated["Bragi"] = Bragi(
                semantic_judgment=conversation_semantic_judgment,
                action_type_names=tuple(action_type.name for action_type in action_types),
                semantic_router=(
                    SemanticAgentRouter(
                        embedding_model=conversation_embedding_model,
                        specs=PANTHEON_SPECS,
                        config=semantic_router_config,
                    )
                    if conversation_embedding_model is not None
                    else None
                ),
                t2_synthesizer=conversation_t2_synthesizer,
                escalation_budget=conversation_escalation_budget,
                escalation_ledger=conversation_escalation_ledger,
                pricing=conversation_pricing,
                metering=conversation_metering,
                t2_model_key=conversation_t2_model_key,
                state_store=bragi_state_store,
            )
        bind_durable_governance_stores(
            instantiated,
            odin_state_store=odin_state_store,
            proposal_rate_limit_state_store=proposal_rate_limit_state_store,
        )
        action_semantics = (
            ActionSemanticsCatalog.from_action_types(action_types) if action_types else None
        )
        bind_operational_agents(
            instantiated,
            scenario_coverage_aggregator=scenario_coverage_aggregator,
            post_turn_review=post_turn_review,
            case_history_analyzer=case_history_analyzer,
            operating_pattern_compiler=operating_pattern_compiler,
            semantic_feedback_store=semantic_feedback_store,
            muninn_state_store=muninn_state_store,
            case_history_materializer=case_history_materializer,
            case_history_retention=case_history_retention,
            case_retention_days=case_retention_days,
            case_deletion_days=case_deletion_days,
            evidence_conflict_sink=evidence_conflict_sink,
            prospective_lineage_materializer=prospective_lineage_materializer,
            operator_rbac=operator_rbac,
            action_semantics=action_semantics,
            operational_context_materializer=operational_context_materializer,
            test_context_source=test_context_source,
            test_context_admission=test_context_admission,
            operational_planner=operational_planner,
            kinetic_proposal_source=kinetic_proposal_source,
            anomaly_action_sources=anomaly_action_sources,
            prospective_lineage_finalizer=prospective_lineage_finalizer,
            change_assessor=change_assessor,
            cost_runtime=cost_runtime,
            njord_state_store=njord_state_store,
            capacity_graduation_controller=capacity_graduation_controller,
            freyr_state_store=freyr_state_store,
            development=development_authority,
            action_types=action_types,
            governed_execution_selected=governed_execution_selected,
            forseti_state_store=forseti_state_store,
        )
        runtime_sensing.configure_heimdall(
            instantiated,
            rate_threshold=heimdall_rate_threshold,
            rate_window=heimdall_rate_window,
            security_high_threshold=heimdall_security_high_threshold,
            security_window_events=heimdall_security_window_events,
            alert_rate_per_hour=heimdall_alert_rate_per_hour,
            action_semantics=action_semantics,
            forecast_evaluator=forecast_evaluator,
            forecast_closer=forecast_closer,
            forecast_store=forecast_store,
            operational_evidence_hook=operational_evidence_hook,
            action_observation_hook=heimdall_action_observation_hook,
            state_store=heimdall_state_store,
        )
        development_runtime.configure_authority_agents(
            instantiated,
            approver_authorizer=approver_authorizer,
            var_state_store=var_state_store,
            rollback_executors=rollback_executors,
            vidar_state_store=vidar_state_store,
            development=development_authority,
        )
        maybe_var = instantiated.get("Var")
        if maybe_var is not None and hasattr(maybe_var, "bind_action_semantics"):
            maybe_var.bind_action_semantics(action_semantics)
        if saga is not None:
            instantiated["Saga"] = saga
        maybe_mimir = instantiated.get("Mimir")
        if isinstance(maybe_mimir, Mimir):
            if mimir_promotion_outcome_reader is not None:
                maybe_mimir.bind_catalog_promotion_outcome_reader(mimir_promotion_outcome_reader)
            if mimir_regression_runner is not None:
                maybe_mimir.bind_regression_runner(mimir_regression_runner)
            if mimir_rule_source_poller is not None:
                maybe_mimir.bind_rule_source_poller(mimir_rule_source_poller)
            if mimir_rule_deprecation_reader is not None:
                maybe_mimir.bind_rule_deprecation_reader(mimir_rule_deprecation_reader)
        maybe_saga = instantiated.get("Saga")
        if (
            mimir_promotion_outcome_reader is not None
            and mimir_regression_runner is not None
            and isinstance(maybe_saga, Saga)
        ):
            maybe_saga.bind_issue_close_promotion_evidence_producer()
        if context_index_workers is not None and not getattr(
            instantiated["Saga"], "durable_audit", False
        ):
            raise RuntimeError("ontology ContextIndex requires durable Saga audit")
        assignment_runtime.bind_assignment_workflow(instantiated, assignment_workflow)
        heimdall = instantiated["Heimdall"]
        if read_investigation_hook is not None and isinstance(heimdall, Heimdall):
            heimdall.register_read_investigation(read_investigation_hook)
        norns = instantiated["Norns"]
        if (
            (incident_candidate_hook is not None or scenario_coverage_aggregator is not None)
            and isinstance(heimdall, Heimdall)
            and isinstance(norns, Norns)
        ):

            async def observe_and_open(candidate: dict[str, Any]) -> bool:
                if scenario_coverage_aggregator is not None:
                    norns.observe_incident_symptom(
                        incident_id=str(
                            candidate.get("correlation_id") or candidate.get("evidence_key") or ""
                        ),
                        signal=str(candidate.get("event_type") or ""),
                        target_type=str(candidate.get("target_type") or "unknown"),
                        severity=str(candidate.get("severity") or "medium"),
                    )
                if incident_candidate_hook is None:
                    return True
                return await incident_candidate_hook(candidate)

            heimdall.register_incident_candidate(observe_and_open)
        # Only explicit promotion permits Thor enforce; parallel P1 dispatch could double-mutate.
        thor = instantiated["Thor"]
        if isinstance(thor, Thor):
            development_runtime.bind_thor_development_authority(thor, development_authority)
            execution_safety.configure_thor_execution(
                thor=thor,
                executor=thor_executor,
                state_store=thor_state_store,
                resource_lock=execution_resource_lock,
                saga=saga,
                enforce=enforce,
                human_access_bound=human_access_bound,
                preflight_simulator=thor_preflight_simulator,
            )
        agents = {n: a for n, a in instantiated.items() if n not in disabled}
        overflow_auditor: Saga | None = saga
        saga_agent = agents.get("Saga")
        if overflow_auditor is None and isinstance(saga_agent, Saga):
            overflow_auditor = saga_agent
        for agent in agents.values():
            agent.bind_bus(bridge)
            if overflow_auditor is not None:
                agent.bind_rate_limit_overflow_auditor(overflow_auditor.record_rate_limit_overflow)
        subscription_count = runtime_subscriptions.bind_runtime_subscriptions(
            bridge=bridge,
            instantiated=instantiated,
            agents=agents,
            rule_generation_workers=rule_generation_workers,
            rule_generation_activation_binder=rule_generation_activation_binder,
            rule_generation_state_store=rule_generation_state_store,
            context_index_workers=context_index_workers,
            human_access=assignment_workflow.human_access
            if assignment_workflow is not None
            else None,
        )
        subscription_count += runtime_subscriptions.bind_recovery_effect_observation(
            bridge,
            recovery_effect_observer,
        )

        conversation_tools = AgentConversationToolRegistry(
            agents=agents,
            disabled_agents=disabled,
            timeout_seconds=conversation_tool_timeout_seconds,
        )
        semantic_tool_planner = (
            SemanticToolPlanner(embedding_model=conversation_embedding_model, specs=PANTHEON_SPECS)
            if conversation_embedding_model is not None
            else None
        )

        bragi_ref: Bragi | None = None
        maybe_bragi = agents.get("Bragi")
        if isinstance(maybe_bragi, Bragi):
            bragi_ref = maybe_bragi
            for name, agent in agents.items():
                bragi_ref.register_responder(name, agent.on_conversation_turn)

            async def answer_with_owned_tools(
                agent_name: str,
                question: str,
                trace_ref: str,
            ) -> dict[str, Any] | None:
                return await answer_from_owned_tools(
                    agent_name=agent_name,
                    question=question,
                    trace_ref=trace_ref,
                    registry=conversation_tools,
                    semantic=semantic_tool_planner,
                )

            bragi_ref.register_tool_answer(answer_with_owned_tools)
            maybe_huginn = agents.get(_INGRESS_PRINCIPAL)
            if isinstance(maybe_huginn, Huginn):
                bragi_ref.register_proposal_sink(maybe_huginn.ingest_operator_proposal)

        huginn_active = _INGRESS_PRINCIPAL in agents
        runtime = cls(
            bridge=bridge,
            agents=agents,
            raw_event_topic=raw_event_topic,
            subscription_count=subscription_count + (1 if huginn_active else 0),
            enforce=enforce,
            kpi_collector=kpi_collector or KpiCollector(),
            disabled=disabled,
            divergence=divergence,
            architecture_review_trace_observer=ArchitectureReviewTraceObserver(),
            _bragi=bragi_ref,
            _conversation_tools=conversation_tools,
            _semantic_tool_planner=semantic_tool_planner,
            _context_index_workers=context_index_workers,
        )

        runtime_health.bind_availability_probe(
            agents, disabled=runtime.disabled, continuity_failures=runtime._continuity_failures
        )

        if huginn_active:
            bridge.subscribe(
                raw_event_topic,
                _INGRESS_PRINCIPAL,
                runtime_subscriptions.build_ingress_handler(
                    agent=agents[_INGRESS_PRINCIPAL],
                    on_unkeyed=runtime._record_ingress_drop,
                ),
            )
        else:
            _LOG.warning("pantheon_ingress_disabled_no_huginn")

        bridge.subscribe("object.verdict", _OBSERVER_PRINCIPAL, runtime._observe_verdict)
        bridge.subscribe("object.action-run", _OBSERVER_PRINCIPAL, runtime._observe_action_run)
        arb_runtime.bind_architecture_review_observer(
            bridge,
            runtime.architecture_review_trace_observer,
        )
        bridge.consumer_state_observer = runtime._observe_consumer_state

        _LOG.info(
            "pantheon_wired",
            extra={
                "agents": len(agents),
                "disabled": sorted(disabled),
                "subscriptions": runtime.subscription_count,
                "raw_event_topic": raw_event_topic,
                "enforce": enforce,
            },
        )
        return runtime

    async def run(self, *, heartbeat_interval: float | None = None) -> None:
        """Start the perpetual consumer with optional periodic health logging."""
        await self._rehydrate()
        await execution_safety.run_with_maintenance(
            run_consumers=self.bridge.run,
            agents=self.agents,
            heartbeat=self._heartbeat,
            heartbeat_interval=heartbeat_interval,
        )

    async def stop(self) -> None:
        """Cancel every consumer task and drain cleanly."""
        try:
            await self.bridge.stop()
        finally:
            # One cleanup failure must not strand an unrelated provider
            # task. The bridge error still propagates after this drain.
            try:
                if self._conversation_tools is not None:
                    await self._conversation_tools.stop()
            finally:
                if self._semantic_tool_planner is not None:
                    await self._semantic_tool_planner.stop()

    async def ingest_raw_event(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        huginn = self.agents.get(_INGRESS_PRINCIPAL)
        if not isinstance(huginn, Huginn):
            raise RuntimeError("Pantheon raw ingress requires active Huginn")
        return await huginn.ingest(payload)

    async def _rehydrate(self) -> None:
        await rehydrate_operational_agents(
            self.agents,
            context_index_workers=self._context_index_workers,
        )

    def health(self) -> dict[str, Any]:
        snap = self.bridge.snapshot()
        agent_health = runtime_health.snapshot_agent_health(self.agents)
        runtime_health.report_agent_kpis(self.kpi_collector, agent_health)
        for agent_name in HARD_DEPENDENCY_AGENTS:
            health = agent_health.get(agent_name)
            if isinstance(health, dict) and health.get("status") == "error":
                self._continuity_failures.setdefault(f"{agent_name}:health", "error")
                thor = self.agents.get("Thor")
                if isinstance(thor, Thor):
                    thor.set_shadow(True)
        hard_dependency_failures = {
            consumer: state
            for consumer, state in self._continuity_failures.items()
            if consumer.split(":", 1)[0] in HARD_DEPENDENCY_AGENTS
        }
        unavailable_sources: dict[str, set[str]] = {}
        for agent_name in self.disabled:
            unavailable_sources.setdefault(agent_name, set()).add("disabled")
        for consumer in self._continuity_failures:
            agent_name = consumer.split(":", 1)[0]
            unavailable_sources.setdefault(agent_name, set()).add("continuity_failure")
        bridge_unavailable = snap.get("unavailable_agents", [])
        if isinstance(bridge_unavailable, list):
            for agent_name in bridge_unavailable:
                if isinstance(agent_name, str):
                    unavailable_sources.setdefault(agent_name, set()).add("bridge_snapshot")
        for name, item in agent_health.items():
            if item.get("status") == "error":
                unavailable_sources.setdefault(name, set()).add("health_probe")
            learning = item.get("learning")
            if (
                name == "Norns"
                and isinstance(learning, dict)
                and isinstance(learning.get("post_turn_review"), dict)
                and learning["post_turn_review"].get("status") == "unavailable"
                and isinstance(item.get("behavior"), dict)
                and item["behavior"].get("post_turn_review_unavailable", 0)
            ):
                unavailable_sources.setdefault(name, set()).add("post_turn_review_unbound")
        unavailable_agents = {
            *runtime_health.derive_unavailable_agents(
                disabled=self.disabled, continuity_failures=self._continuity_failures
            ),
            *(name for name, item in agent_health.items() if item.get("status") == "error"),
            *(
                name
                for name in unavailable_sources
                if name in runtime_health.AGENT_DEGRADATION_POLICIES
            ),
        }
        degradation = runtime_health.evaluate_degradation(
            unavailable_agents,
            unavailable_sources=unavailable_sources,
        )
        if degradation.blocks_mutation:
            thor = self.agents.get("Thor")
            if isinstance(thor, Thor):
                thor.set_shadow(True)
        return {
            "agents": len(self.agents),
            "disabled": sorted(self.disabled),
            "enforce": self.enforce,
            "effective_enforce": self.enforce and not degradation.blocks_mutation,
            "continuity_failures": dict(sorted(self._continuity_failures.items())),
            "hard_dependency_failures": dict(sorted(hard_dependency_failures.items())),
            "ingress_dropped": self._ingress_dropped,
            "shadow_decisions": dict(self.shadow_decisions),
            "agent_health": agent_health,
            "kpi_coverage": self.kpi_collector.coverage(),
            "degradation": degradation.to_mapping(),
            "divergence": self.divergence.report() if self.divergence else None,
            "architecture_review_observation": arb_runtime.architecture_review_observation_snapshot(
                self.architecture_review_trace_observer
            ),
            "conversational_port": self._bragi is not None,
            "conversation_tools": (
                self._conversation_tools.snapshot()
                if self._conversation_tools is not None
                else {"registered": 0, "available": 0, "disabled": 0, "by_agent": {}}
            ),
            **snap,
        }

    def _observe_consumer_state(self, agent: str, topic: str, state: str) -> None:
        if state == "stopped":
            self._continuity_failures.pop(f"{agent}:{topic}", None)
            return
        if agent not in PANTHEON_NAMES:
            arb_runtime.handle_architecture_review_consumer_state(
                self.architecture_review_trace_observer,
                agent=agent,
                topic=topic,
                state=state,
            )
            return
        consumer = f"{agent}:{topic}"
        self._continuity_failures[consumer] = state
        if agent not in HARD_DEPENDENCY_AGENTS:
            return
        thor = self.agents.get("Thor")
        if isinstance(thor, Thor):
            thor.set_shadow(True)
        _LOG.error(
            "pantheon_hard_dependency_consumer_terminal",
            extra={"agent": agent, "topic": topic, "state": state},
        )

    async def _heartbeat(self, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            _LOG.info(
                "pantheon_heartbeat",
                extra=runtime_health.heartbeat_log_summary(self.health()),
            )

    async def _observe_verdict(self, _topic: str, payload: dict[str, Any]) -> None:
        risk = str(payload.get("risk_verdict", "unknown"))
        self.shadow_decisions[f"verdict:{risk}"] += 1
        if self.divergence is not None:
            self.divergence.record_pantheon(str(payload.get("correlation_id", "")), risk)

    async def _observe_action_run(self, _topic: str, payload: dict[str, Any]) -> None:
        state = str(payload.get("state", "unknown"))
        prefix = "shadow_action_run" if payload.get("shadow_mode") is True else "action_run"
        self.shadow_decisions[f"{prefix}:{state}"] += 1

    def _record_ingress_drop(self, error: ValueError) -> None:
        self._ingress_dropped += 1
        _LOG.warning(
            "pantheon_ingress_unkeyed_event",
            extra={"error_type": type(error).__name__, "raw_event_topic": self.raw_event_topic},
        )


def _default_payload_validator(topic: str, payload: Any) -> None:
    """Default-on pantheon object payload validator.

    Deployments can disable this only by constructing ``EventBusBridge``
    directly with ``payload_validator=None``; ``PantheonRuntime.build`` keeps
    the authority-bearing validator enabled so live delivery and redrive share
    the same fail-closed boundary.
    """

    if not isinstance(payload, dict):
        raise ValueError("pantheon payload MUST be a mapping")
    if topic == "object.verdict":
        _validate_verdict_payload(payload)
        return
    if topic == "object.action-run":
        if payload.get("kind") == "human_access_execution" and isinstance(
            payload.get("human_access"), dict
        ):
            return
        _require_non_empty_strings(payload, "state", "action_type")
        return
    if topic == "object.approval":
        if payload.get("kind") == "human_assignment" and isinstance(
            payload.get("assignment"), dict
        ):
            return
        if payload.get("kind") == "human_access_execution" and isinstance(
            payload.get("human_access"), dict
        ):
            return
        if not str(payload.get("state") or payload.get("decision") or "").strip():
            raise ValueError("approval payload MUST carry state or decision")


def _validate_verdict_payload(payload: dict[str, Any]) -> None:
    decision = str(payload.get("risk_verdict") or payload.get("decision") or "").strip()
    if not decision and not any(key in payload for key in _VERDICT_EVIDENCE_KEYS):
        raise ValueError("verdict payload MUST carry risk_verdict, decision, or kind")
    enforce_ceiling = str(payload.get("resolved_autonomy_ceiling") or "").strip()
    executable = enforce_ceiling == "enforce_auto" or payload.get("execution_authority") is True
    if (
        executable
        and decision in _EXECUTABLE_VERDICTS
        and str(payload.get("action_type") or "").strip()
    ):
        missing = missing_wire_safeguards(payload)
        if missing:
            raise ValueError("executable verdict missing safeguard(s): " + ", ".join(missing))


def _require_non_empty_strings(payload: dict[str, Any], *fields: str) -> None:
    missing = [field for field in fields if not str(payload.get(field) or "").strip()]
    if missing:
        raise ValueError("payload missing required field(s): " + ", ".join(missing))


__all__ = ["PantheonRuntime"]
