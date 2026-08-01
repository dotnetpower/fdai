"""Composition-root wiring for the pantheon runtime.

The pantheon subclasses ship their behavior wave-by-wave, but until this
module they were only ever wired together inside tests. ``PantheonRuntime``
is the seam that lets the headless control plane
(:mod:`fdai.__main__`) run all 15 agents against a real
:class:`~fdai.shared.providers.event_bus.EventBus` provider:

- instantiate the 15 agents (:func:`fdai.agents._framework.factory.instantiate_pantheon`),
- bind every publishing agent to one injected ``EventBusBridge``,
- register each agent's declared typed subscriptions
  (``AgentSpec.subscribes``) so a published ``object.<type>`` record
  fans out to every subscriber immediately (distinct Kafka consumer
  groups),
- route raw ingress events (the same topic the P1 control loop consumes)
  into Huginn, the Event Collector, which normalizes and republishes them
  as ``object.event``.

The runtime is **shadow by default**: it forces Thor into shadow mode
(``enforce=False``) so the pantheon never double-executes alongside the
P1 control loop, and the agents use the in-memory audit / issue / admin
adapters from :mod:`fdai.agents.adapters`. A fork promotes to enforce
explicitly (``enforce=True``) and swaps the in-memory adapters for
durable backends by injecting its own ``Saga`` - see
``docs/roadmap/agents/agent-pantheon-implementation.md``.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from fdai.agents._framework import runtime_health
from fdai.agents._framework.action_semantics import ActionSemanticsCatalog
from fdai.agents._framework.base import Agent
from fdai.agents._framework.bus_bridge import AgentHandlerObserver, EventBusBridge
from fdai.agents._framework.catalog_review_wiring import CatalogReviewBindings, bind_catalog_review
from fdai.agents._framework.conversation_tools import (
    AgentConversationToolRegistry,
    AgentToolResult,
)
from fdai.agents._framework.deliberation import T2ConversationSynthesizer
from fdai.agents._framework.divergence import ShadowDivergenceLedger
from fdai.agents._framework.factory import instantiate_pantheon
from fdai.agents._framework.kpi import KpiCollector
from fdai.agents._framework.pantheon import (
    HARD_DEPENDENCY_AGENTS,
    PANTHEON_NAMES,
    PANTHEON_SPECS,
)
from fdai.agents._framework.registry import PantheonRegistry, load_pantheon
from fdai.agents._framework.semantic_routing import SemanticAgentRouter, SemanticRouterConfig
from fdai.agents._framework.tool_answer import answer_from_owned_tools
from fdai.agents._framework.tool_planner import (
    MAX_TOOL_PLANS,
    ConversationToolPlan,
    plan_conversation_tools,
)
from fdai.agents._framework.tool_prefetch import prefetch_tools
from fdai.agents._framework.tool_semantic import SemanticToolPlanner
from fdai.agents.bragi import Bragi, RoutingDecision, Turn
from fdai.agents.forseti import Forseti
from fdai.agents.heimdall import Heimdall, IncidentCandidateHook, ReadInvestigationHook
from fdai.agents.huginn import DiscoveryProjector, Huginn
from fdai.agents.muninn import Muninn
from fdai.agents.norns import Norns
from fdai.agents.saga import Saga
from fdai.agents.thor import ActionExecutor, ActionRunStore, Thor
from fdai.agents.vidar import RollbackExecutor, Vidar
from fdai.core.case_history import (
    CaseHistoryAnalyzer,
    CaseHistoryMaterializer,
    CaseHistoryRetentionService,
)
from fdai.core.chaos.coverage import ScenarioCoverageAggregator
from fdai.core.detection.forecast_closure import ForecastClosureCoordinator
from fdai.core.detection.forecast_episode import ForecastEpisodeStore
from fdai.core.detection.forecast_evaluation import ForecastEpisodeEvaluator
from fdai.core.learning import PostTurnReviewCoordinator
from fdai.core.metering.budget import BudgetLedger, ModelBudget
from fdai.core.metering.pricing import PricingTable
from fdai.core.metering.sink import MeteringSink
from fdai.core.operational_context import OperationalContextMaterializer
from fdai.core.operational_learning import OperatingPatternCompiler
from fdai.core.tiers.t1_lightweight.tier import EmbeddingModel
from fdai.shared.contracts.models import OntologyActionType
from fdai.shared.providers.event_bus import EventBus
from fdai.shared.providers.state_store import StateStore

_LOG = logging.getLogger(__name__)

_INGRESS_PRINCIPAL = "Huginn"
_DEFAULT_GROUP_PREFIX = "fdai-pantheon"
_OBSERVER_PRINCIPAL = "runtime-observer"


@dataclass
class PantheonRuntime:
    """Live wiring of the 15 pantheon agents over an ``EventBus`` provider.

    Build with :meth:`build`, then drive the perpetual consumer with
    :meth:`run` (cancel via :meth:`stop`). ``run`` blocks forever against
    a real broker - one Kafka consumer task per (topic, agent) pair - so
    the caller runs it as a background task alongside the P1 control loop.
    """

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
    _bragi: Bragi | None = None
    _conversation_tools: AgentConversationToolRegistry | None = None
    _semantic_tool_planner: SemanticToolPlanner | None = None
    _continuity_failures: dict[str, str] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        *,
        provider: EventBus,
        raw_event_topic: str,
        registry: PantheonRegistry | None = None,
        enforce: bool = False,
        consumer_group_prefix: str = _DEFAULT_GROUP_PREFIX,
        saga: Saga | None = None,
        muninn_state_store: StateStore | None = None,
        disabled_agents: frozenset[str] | None = None,
        divergence: ShadowDivergenceLedger | None = None,
        kpi_collector: KpiCollector | None = None,
        thor_executor: ActionExecutor | None = None,
        thor_state_store: ActionRunStore | None = None,
        rollback_executors: dict[str, RollbackExecutor] | None = None,
        operator_rbac: dict[str, frozenset[str]] | None = None,
        incident_candidate_hook: IncidentCandidateHook | None = None,
        heimdall_rate_threshold: int = 5,
        heimdall_rate_window: int = 300,
        read_investigation_hook: ReadInvestigationHook | None = None,
        discovery_projector: DiscoveryProjector | None = None,
        scenario_coverage_aggregator: ScenarioCoverageAggregator | None = None,
        post_turn_review: PostTurnReviewCoordinator | None = None,
        case_history_materializer: CaseHistoryMaterializer | None = None,
        operating_pattern_compiler: OperatingPatternCompiler | None = None,
        case_history_analyzer: CaseHistoryAnalyzer | None = None,
        operational_context_materializer: OperationalContextMaterializer | None = None,
        catalog_review: CatalogReviewBindings | None = None,
        case_history_retention: CaseHistoryRetentionService | None = None,
        forecast_evaluator: ForecastEpisodeEvaluator | None = None,
        forecast_closer: ForecastClosureCoordinator | None = None,
        forecast_store: ForecastEpisodeStore | None = None,
        case_retention_days: int = 30,
        case_deletion_days: int = 60,
        action_types: tuple[OntologyActionType, ...] = (),
        handler_observer: AgentHandlerObserver | None = None,
        conversation_embedding_model: EmbeddingModel | None = None,
        conversation_t2_synthesizer: T2ConversationSynthesizer | None = None,
        conversation_escalation_budget: ModelBudget | None = None,
        conversation_escalation_ledger: BudgetLedger | None = None,
        conversation_pricing: PricingTable | None = None,
        conversation_metering: MeteringSink | None = None,
        conversation_t2_model_key: str = "",
        semantic_router_config: SemanticRouterConfig | None = None,
        conversation_tool_timeout_seconds: float = 5.0,
    ) -> PantheonRuntime:
        """Instantiate + wire the pantheon against ``provider``.

        ``raw_event_topic`` is the P1 ingress topic. Huginn consumes it under a
        distinct group, so the pantheon remains a parallel shadow.

        ``enforce`` defaults to ``False`` so Thor is judge-and-log only. Set it
        only after explicit, separately reviewed promotion.

        ``saga`` injects a durable auditor (a fork wires an append-only
        StateStore-backed ``Saga``); the default is the in-memory audit
        chain, adequate for shadow but lost on restart.

        ``disabled_agents`` lets a fork run a partial pantheon
        (agent-pantheon.md 10). Unknown names and the hard-dependency
        agents (Saga / Vidar) are rejected - disabling audit or rollback
        would break the mutation safety invariants. Disabling Huginn
        turns off ingress (warned), which effectively idles the pantheon.
        """
        if not raw_event_topic or not raw_event_topic.strip():
            raise ValueError("raw_event_topic MUST be a non-empty topic name")

        if enforce:
            missing = []
            if thor_executor is None:
                missing.append("thor_executor")
            if thor_state_store is None:
                missing.append("thor_state_store")
            if saga is None or not saga.durable_audit:
                missing.append("durable_saga")
            if not rollback_executors:
                missing.append("rollback_executors")
            if missing:
                raise ValueError(
                    "pantheon enforce mode requires explicit durable safety bindings: "
                    + ", ".join(missing)
                )

        disabled = frozenset(disabled_agents or frozenset())
        unknown = disabled - PANTHEON_NAMES
        if unknown:
            raise ValueError(f"unknown agents in disabled set: {sorted(unknown)}")
        forbidden = disabled & HARD_DEPENDENCY_AGENTS
        if forbidden:
            raise ValueError(
                "hard-dependency agents cannot be disabled (audit / rollback "
                f"are mutation safety invariants): {sorted(forbidden)}"
            )

        reg = registry or load_pantheon()
        bridge = EventBusBridge(
            provider=provider,
            registry=reg,
            consumer_group_prefix=consumer_group_prefix,
            handler_max_retries=2,
            handler_observer=handler_observer,
        )
        instantiated = instantiate_pantheon()
        bind_catalog_review(instantiated, catalog_review)
        if conversation_embedding_model is not None or conversation_t2_synthesizer is not None:
            instantiated["Bragi"] = Bragi(
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
            )
        if discovery_projector is not None:
            instantiated["Huginn"] = Huginn(discovery_projector=discovery_projector)
        action_semantics = (
            ActionSemanticsCatalog.from_action_types(action_types) if action_types else None
        )
        if (
            scenario_coverage_aggregator is not None
            or post_turn_review is not None
            or case_history_analyzer is not None
            or operating_pattern_compiler is not None
        ):
            instantiated["Norns"] = Norns(
                coverage_aggregator=scenario_coverage_aggregator,
                post_turn_review=post_turn_review,
                case_history_analyzer=case_history_analyzer,
                operating_pattern_compiler=operating_pattern_compiler,
            )
        if (
            muninn_state_store is not None
            or case_history_materializer is not None
            or case_history_retention is not None
        ):
            instantiated["Muninn"] = Muninn(
                durable_state_store=muninn_state_store,
                case_history=case_history_materializer,
                case_history_retention=case_history_retention,
                case_retention_days=case_retention_days,
                case_deletion_days=case_deletion_days,
            )
        if any(
            value is not None
            for value in (operator_rbac, action_semantics, operational_context_materializer)
        ):
            instantiated["Forseti"] = Forseti(
                rbac=operator_rbac,
                action_semantics=action_semantics,
                operational_context=operational_context_materializer,
            )
        if (forecast_evaluator is None) != (forecast_closer is None) or (
            forecast_evaluator is None
        ) != (forecast_store is None):
            raise ValueError("forecast runtime bindings MUST be supplied together")
        instantiated["Heimdall"] = Heimdall(
            rate_threshold=heimdall_rate_threshold,
            rate_window=heimdall_rate_window,
            action_semantics=action_semantics,
            forecast_evaluator=forecast_evaluator,
            forecast_closer=forecast_closer,
            forecast_store=forecast_store,
        )
        if saga is not None:
            instantiated["Saga"] = saga
        if rollback_executors is not None:
            instantiated["Vidar"] = Vidar(executors=rollback_executors)
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

        # Safety: force Thor to shadow unless an explicit promotion opts
        # into enforce. Without this the pantheon Thor would auto-execute
        # every 'auto' verdict in parallel with the P1 loop - a double
        # mutation and a "shadow before enforce" violation.
        thor = instantiated["Thor"]
        if isinstance(thor, Thor):
            if thor_executor is not None:
                thor.set_executor(thor_executor)
            thor.set_shadow(not enforce)
            if thor_state_store is not None:
                thor.set_state_store(thor_state_store)

        # Apply the disabled filter: disabled agents are neither bound nor
        # subscribed, so nobody publishes their owned topics and their
        # handlers never fire.
        agents = {n: a for n, a in instantiated.items() if n not in disabled}

        # Bind every active agent to the shared bridge. base Agent.bind_bus
        # is a safe setter, so agents that never publish simply hold an
        # unused reference rather than needing special-casing.
        for agent in agents.values():
            agent.bind_bus(bridge)

        # Register each active agent's declared typed subscriptions.
        # Subscription has no single-writer check (only publish does), so a
        # topic may fan out to several agents (e.g. object.event ->
        # Heimdall + Forseti).
        subscription_count = 0
        for name, agent in agents.items():
            for topic in agent.spec.subscribes:
                bridge.subscribe(topic, name, agent.on_typed_message)
                subscription_count += 1

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

        # Conversational port: wire Bragi (the narrator) to every active
        # agent's read-only conversational handler, including Bragi itself.
        # Routing is deterministic here; each agent owns its answer policy.
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
                    # Bragi has already selected and confidence-gated the
                    # owner, so meaning chooses only among that owner's
                    # read tools. This is not the global ranker deciding
                    # whether the system owns the question.
                    semantic=semantic_tool_planner,
                )

            bragi_ref.register_tool_answer(answer_with_owned_tools)
            # Conversational-port re-entry (agent-pantheon.md 7.7): an operator
            # command routes into the typed pipeline through Huginn (the sole
            # writer of object.event). Bragi builds the ActionProposal and
            # submits it here - it never calls an executor. Absent when Huginn
            # is disabled (ingress off), in which case an action request falls
            # back to the requires_typed_pipeline signal.
            maybe_huginn = agents.get(_INGRESS_PRINCIPAL)
            if isinstance(maybe_huginn, Huginn):
                bragi_ref.register_proposal_sink(maybe_huginn.ingest)

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
            _bragi=bragi_ref,
            _conversation_tools=conversation_tools,
            _semantic_tool_planner=semantic_tool_planner,
        )

        # Ingress: raw events on the P1 topic -> Huginn.ingest -> normalized
        # object.event (published via the bound bridge). Huginn's spec
        # subscribes to nothing (it is fed from external adapters), so the
        # ingress bridge is wired explicitly here. If Huginn is disabled
        # there is no ingress - the pantheon idles.
        if huginn_active:
            bridge.subscribe(raw_event_topic, _INGRESS_PRINCIPAL, runtime._make_ingress(agents))
        else:
            _LOG.warning("pantheon_ingress_disabled_no_huginn")

        # Shadow observation: a dedicated observer consumer group tallies
        # what the pantheon *would* decide (verdict risk split + ActionRun
        # terminal states) so "shadow before enforce" has a measurable
        # baseline. A distinct group means it never steals records from
        # the real subscribers (Thor / Saga / Odin / Var).
        bridge.subscribe("object.verdict", _OBSERVER_PRINCIPAL, runtime._observe_verdict)
        bridge.subscribe("object.action-run", _OBSERVER_PRINCIPAL, runtime._observe_action_run)
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
        """Start the perpetual consumer (one task per subscription).

        ``heartbeat_interval`` (seconds) optionally starts a companion
        task that logs :meth:`health` on a fixed cadence - the minimal
        form of Heimdall's per-minute agent-health probe until the full
        probe lands. ``None`` disables it.
        """
        await self._rehydrate()
        if heartbeat_interval is None or heartbeat_interval <= 0:
            await self.bridge.run()
            return
        heartbeat = asyncio.create_task(
            self._heartbeat(heartbeat_interval), name="pantheon-heartbeat"
        )
        try:
            await self.bridge.run()
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except (asyncio.CancelledError, Exception):  # noqa: BLE001, S110 - cleanup
                pass

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

    async def ask(
        self,
        *,
        session_id: str,
        user_id: str,
        question: str,
        initiator_role: str | None = None,
        allow_action_proposal: bool = True,
        materialize_handoff: bool = True,
    ) -> Turn | None:
        """Operator conversational-port entry point.

        Routes a natural-language question through Bragi to the right
        primary agent, tracking a per-user session (Bragi enforces the
        no-cross-user invariant). Returns ``None`` when Bragi is disabled
        (the conversational port is off). Distinct from the typed
        pub/sub port: a conversational request that wants an action must
        re-enter the typed pipeline, never bypass it.

        ``initiator_role`` (the console session's Entra role) drives the entry
        RBAC gate for an action command - a Reader cannot submit an action.
        Read-only channel adapters disable ``allow_action_proposal`` and
        ``materialize_handoff`` so the narrator can contribute evidence without
        creating a proposal or a discovery issue behind that channel's back.
        """
        if self._bragi is None:
            return None
        turn = await self._bragi.ask(
            session_id=session_id,
            user_id=user_id,
            question=question,
            initiator_role=initiator_role,
            allow_action_proposal=allow_action_proposal,
            materialize_handoff=materialize_handoff,
        )
        return turn

    def route_conversation(self, question: str) -> RoutingDecision | None:
        """Return Bragi's deterministic route without exposing agent instances."""
        if self._bragi is None:
            return None
        return self._bragi.route(question)

    async def ingest_raw_event(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        huginn = self.agents.get(_INGRESS_PRINCIPAL)
        if not isinstance(huginn, Huginn):
            raise RuntimeError("Pantheon raw ingress requires active Huginn")
        return await huginn.ingest(payload)

    def should_delegate_conversation(
        self,
        question: str,
        view_context: dict[str, Any],
    ) -> bool:
        """Return Bragi's current-screen versus agent-owned scope decision."""
        if self._bragi is None:
            return False
        return self._bragi.should_delegate(question, view_context)

    async def contribute_conversation(
        self,
        agent_name: str,
        question: str,
        *,
        requester: str = "Bragi",
    ) -> dict[str, Any] | None:
        """Collect one read-only contribution through Bragi's A2A boundary."""
        if self._bragi is None:
            return None
        return await self._bragi.introspect_agent(
            agent_name,
            question,
            requester=requester,
            context={"answer_planning": "shadow", "nested_round": False},
        )

    async def introspect(
        self,
        agent_name: str,
        question: str,
        *,
        requester: str,
        correlation_id: str = "",
    ) -> dict[str, Any] | None:
        """Agent-to-agent (A2A) conversational-port entry point.

        Lets one pantheon agent (``requester``) ask another a
        natural-language question through Bragi (agent-pantheon.md 6.2) -
        e.g. Odin asking Saga "who executed correlation abc" when the typed
        schema is not a fit. Read-only: the answer never mutates, and a
        request phrased as a command re-enters the typed pipeline (7.7).
        Returns ``None`` when Bragi is disabled (the conversational port is
        off). ``correlation_id`` threads the shared trace so the A2A answer
        stays correlated with the incident it is about.
        """
        if self._bragi is None:
            return None
        return await self._bragi.introspect_agent(
            agent_name,
            question,
            requester=requester,
            context={"correlation_id": correlation_id} if correlation_id else None,
        )

    async def deliberate(
        self,
        *,
        question: str,
        requester: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        """Run bounded read-only T1/T2 discussion through Bragi."""
        if self._bragi is None:
            return {
                "status": "abstain",
                "reason": "conversational_port_unavailable",
                "authority": "presentation_only",
                "rounds": [],
                "trace_ref": correlation_id,
            }
        return await self._bragi.deliberate(
            question=question,
            requester=requester,
            correlation_id=correlation_id,
        )

    def plan_conversation_tools(
        self,
        question: str,
        *,
        agents: Sequence[str] = (),
        limit: int = MAX_TOOL_PLANS,
    ) -> tuple[ConversationToolPlan, ...]:
        """Return the owned read tools this question asks for.

        Deterministic and side-effect free, so a caller may show the plan
        before spending anything on it.
        """
        return plan_conversation_tools(question, agents=agents, limit=limit)

    async def prefetch_conversation_tools(
        self,
        question: str,
        *,
        agents: Sequence[str] = (),
        limit: int = MAX_TOOL_PLANS,
        trace_ref: str = "",
    ) -> tuple[AgentToolResult, ...]:
        """Run the tools this question asks for and return their results.

        Bounded in count, depth, per-dispatch time, and total time. Never
        raises for a tool that fails: a prefetch is supplementary
        evidence, so an abstain or a timeout leaves the answering turn
        untouched. See :mod:`fdai.agents._framework.tool_prefetch`.
        """
        registry = self._conversation_tools
        if registry is None:
            return ()
        return await prefetch_tools(
            question,
            registry=registry,
            semantic=self._semantic_tool_planner,
            agents=agents,
            limit=limit,
            trace_ref=trace_ref,
        )

    async def invoke_conversation_tool(
        self,
        *,
        agent_name: str,
        tool_id: str,
        question: str,
        trace_ref: str = "",
    ) -> AgentToolResult:
        """Invoke one exact-owner read tool through the agent's guarded port."""
        registry = self._conversation_tools
        if registry is None:
            raise RuntimeError("agent conversation tool registry is unavailable")
        return await registry.invoke(
            agent_name=agent_name,
            tool_id=tool_id,
            question=question,
            trace_ref=trace_ref,
        )

    async def _rehydrate(self) -> None:
        """Restore durable agent state (in-flight ActionRuns) on startup.

        Runs before the consumer starts so a restart cannot start a
        second run on a resource that already had one in flight. No-op
        when no durable store is wired.
        """
        thor = self.agents.get("Thor")
        if isinstance(thor, Thor):
            restored = await thor.rehydrate()
            if restored:
                _LOG.info("pantheon_thor_rehydrated", extra={"in_flight_runs": restored})

    def health(self) -> dict[str, Any]:
        """Return a health snapshot (agents, mode, bridge metrics).

        Includes a per-agent ``agent_health`` map so Heimdall's probe (and
        the KPI collectors) can see individual agent state - active
        ActionRuns, dedup pressure, etc. - not just bridge-level counters.
        """
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
        unavailable_agents = set(self.disabled)
        unavailable_agents.update(
            name for name, health in agent_health.items() if health.get("status") == "error"
        )
        unavailable_agents.update(
            consumer.split(":", 1)[0] for consumer in self._continuity_failures
        )
        degradation = runtime_health.evaluate_degradation(unavailable_agents)
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
            "conversational_port": self._bragi is not None,
            "conversation_tools": (
                self._conversation_tools.snapshot()
                if self._conversation_tools is not None
                else {"registered": 0, "available": 0, "disabled": 0, "by_agent": {}}
            ),
            **snap,
        }

    def _observe_consumer_state(self, agent: str, topic: str, state: str) -> None:
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
            _LOG.info("pantheon_heartbeat", extra=self.health())

    async def _observe_verdict(self, _topic: str, payload: dict[str, Any]) -> None:
        risk = str(payload.get("risk_verdict", "unknown"))
        self.shadow_decisions[f"verdict:{risk}"] += 1
        if self.divergence is not None:
            self.divergence.record_pantheon(str(payload.get("correlation_id", "")), risk)

    async def _observe_action_run(self, _topic: str, payload: dict[str, Any]) -> None:
        self.shadow_decisions[f"action_run:{payload.get('state', 'unknown')}"] += 1

    def _make_ingress(
        self, agents: dict[str, Agent]
    ) -> Callable[[str, dict[str, Any]], Awaitable[None]]:
        """Return the raw-event handler that feeds Huginn without DLQ noise."""
        huginn = agents[_INGRESS_PRINCIPAL]
        if not isinstance(huginn, Huginn):  # pragma: no cover - factory guarantees it
            raise TypeError("Huginn agent is missing from the pantheon")

        async def _ingress(_topic: str, payload: dict[str, Any]) -> None:
            try:
                await huginn.ingest(payload)
            except ValueError as exc:
                self._ingress_dropped += 1
                _LOG.warning(
                    "pantheon_ingress_unkeyed_event",
                    extra={"error": str(exc), "raw_event_topic": self.raw_event_topic},
                )

        return _ingress


__all__ = ["PantheonRuntime"]
