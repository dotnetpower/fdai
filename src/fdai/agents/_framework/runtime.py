"""Composition-root wiring for the pantheon runtime.

The pantheon subclasses ship their behavior wave-by-wave, but until this
module they were only ever wired together inside tests. ``PantheonRuntime``
is the seam that lets the headless control plane
(:mod:`fdai.__main__`) run all 15 agents against a real
:class:`~fdai.shared.providers.event_bus.EventBus` provider:

- instantiate the 15 agents (:func:`fdai.agents._framework.factory.instantiate_pantheon`),
- bind every publishing agent to a single
  :class:`~fdai.agents._framework.bus_bridge.EventBusBridge` over the injected
  provider,
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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from fdai.agents._framework.base import Agent
from fdai.agents._framework.bus_bridge import EventBusBridge
from fdai.agents._framework.divergence import ShadowDivergenceLedger
from fdai.agents._framework.factory import instantiate_pantheon
from fdai.agents._framework.pantheon import HARD_DEPENDENCY_AGENTS, PANTHEON_NAMES
from fdai.agents._framework.registry import PantheonRegistry, load_pantheon
from fdai.agents.bragi import Bragi, Turn
from fdai.agents.forseti import Forseti
from fdai.agents.heimdall import Heimdall, IncidentCandidateHook
from fdai.agents.huginn import Huginn
from fdai.agents.norns import Norns
from fdai.agents.saga import Saga, compute_fingerprint
from fdai.agents.thor import ActionExecutor, ActionRunStore, Thor
from fdai.agents.vidar import RollbackExecutor, Vidar
from fdai.core.chaos.coverage import ScenarioCoverageAggregator
from fdai.shared.providers.event_bus import EventBus

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
    _ingress_dropped: int = 0
    shadow_decisions: Counter[str] = field(default_factory=Counter)
    disabled: frozenset[str] = frozenset()
    divergence: ShadowDivergenceLedger | None = None
    _bragi: Bragi | None = None

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
        disabled_agents: frozenset[str] | None = None,
        divergence: ShadowDivergenceLedger | None = None,
        thor_executor: ActionExecutor | None = None,
        thor_state_store: ActionRunStore | None = None,
        rollback_executors: dict[str, RollbackExecutor] | None = None,
        operator_rbac: dict[str, frozenset[str]] | None = None,
        incident_candidate_hook: IncidentCandidateHook | None = None,
        scenario_coverage_aggregator: ScenarioCoverageAggregator | None = None,
    ) -> PantheonRuntime:
        """Instantiate + wire the pantheon against ``provider``.

        ``raw_event_topic`` is the ingress topic (the same
        ``kafka.topic_events`` the P1 loop consumes); its records are fed
        into Huginn under a distinct consumer group, so the pantheon runs
        as a parallel shadow of the P1 pipeline rather than stealing its
        records.

        ``enforce`` defaults to ``False`` (shadow): Thor is forced
        judge-and-log only so the pantheon never mutates alongside the P1
        loop. Set ``True`` only after an explicit, separately reviewed
        promotion.

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
        )
        instantiated = instantiate_pantheon()
        if scenario_coverage_aggregator is not None:
            instantiated["Norns"] = Norns(coverage_aggregator=scenario_coverage_aggregator)
        if operator_rbac is not None:
            instantiated["Forseti"] = Forseti(rbac=operator_rbac)
        if saga is not None:
            instantiated["Saga"] = saga
        if rollback_executors is not None:
            instantiated["Vidar"] = Vidar(executors=rollback_executors)
        heimdall = instantiated["Heimdall"]
        norns = instantiated["Norns"]
        if (
            (incident_candidate_hook is not None or scenario_coverage_aggregator is not None)
            and isinstance(heimdall, Heimdall)
            and isinstance(norns, Norns)
        ):

            async def observe_and_open(candidate: dict[str, Any]) -> None:
                if scenario_coverage_aggregator is not None:
                    norns.observe_incident_symptom(
                        incident_id=str(
                            candidate.get("correlation_id") or candidate.get("evidence_key") or ""
                        ),
                        signal=str(candidate.get("event_type") or ""),
                        target_type=str(candidate.get("target_type") or "unknown"),
                        severity=str(candidate.get("severity") or "medium"),
                    )
                if incident_candidate_hook is not None:
                    await incident_candidate_hook(candidate)

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

        # Conversational port: wire Bragi (the narrator) to every other
        # active agent's conversational handler, so an operator NL query
        # routes to the right primary agent. Deterministic + LLM-free at
        # this layer (routing is keyword/similarity); agents answer via
        # their own on_conversation_turn. Absent when Bragi is disabled.
        bragi_ref: Bragi | None = None
        maybe_bragi = agents.get("Bragi")
        if isinstance(maybe_bragi, Bragi):
            bragi_ref = maybe_bragi
            for name, agent in agents.items():
                if name != "Bragi":
                    bragi_ref.register_responder(name, agent.on_conversation_turn)
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
            disabled=disabled,
            divergence=divergence,
            _bragi=bragi_ref,
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
        await self.bridge.stop()

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
        )
        if materialize_handoff:
            await self._maybe_escalate_handoff(turn, question=question, session_id=session_id)
        return turn

    async def _maybe_escalate_handoff(self, turn: Turn, *, question: str, session_id: str) -> None:
        """Materialize a Saga handoff issue for an unresolved conversational turn.

        When Bragi abstains with no route (``handoff_needed``), no agent could
        serve the operator's question. Saga - the single writer of Issue and
        the executor of ``governance.escalate-to-github-issue`` - opens (or
        comments, deduped by fingerprint) an issue and publishes
        ``object.issue``, so recurring unanswerable questions feed Norns'
        fingerprint learner and can become a rule candidate (the discovery
        loop's handoff trigger). This is NOT the operator's requested action
        (which re-enters the typed pipeline, 7.7) - it is the system recording
        that it could not help, so it never bypasses the pipeline. No-op when
        the turn was resolved or Saga is unavailable. Best-effort: a handoff
        bookkeeping failure MUST NOT break the operator's answer.
        """
        answer = turn.answer if isinstance(turn.answer, dict) else {}
        if not answer.get("handoff_needed"):
            return
        saga = self.agents.get("Saga")
        if not isinstance(saga, Saga):
            return
        reason = str(answer.get("abstain_reason") or "no_route")
        # Normalize the question so a repeated identical ask deduplicates to
        # one fingerprint (Saga comments rather than reopening), while distinct
        # questions stay distinct discovery signals.
        normalized = " ".join(question.split()).casefold()
        fingerprint = compute_fingerprint(
            intent_category=reason,
            resource_type="",
            normalized_selector=normalized,
            primary_agent="Bragi",
            failure_reason_code=reason,
        )
        try:
            await saga.escalate_to_github_issue(
                fingerprint=fingerprint,
                emitting_agent="Bragi",
                intent_category=reason,
                failure_reason_code=reason,
                correlation_id=session_id,
            )
        except Exception as exc:  # noqa: BLE001 - handoff bookkeeping must not break the answer
            _LOG.warning(
                "handoff_escalation_failed",
                extra={"session_id": session_id, "error_type": type(exc).__name__},
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
        return {
            "agents": len(self.agents),
            "disabled": sorted(self.disabled),
            "enforce": self.enforce,
            "ingress_dropped": self._ingress_dropped,
            "shadow_decisions": dict(self.shadow_decisions),
            "agent_health": {
                name: self._safe_agent_health(name, a) for name, a in self.agents.items()
            },
            "divergence": self.divergence.report() if self.divergence else None,
            "conversational_port": self._bragi is not None,
            **snap,
        }

    @staticmethod
    def _safe_agent_health(name: str, agent: Agent) -> dict[str, Any]:
        """Read one agent's health, isolating a raising probe.

        A single agent whose ``health()`` raises MUST NOT collapse the
        whole snapshot (which Heimdall's probe and the heartbeat depend
        on); surface the error for that agent instead. The measurable-
        behavior snapshot is merged in even for agents that override
        ``health()`` (Thor / Huginn) so every agent's observed behaviour is
        visible uniformly.
        """
        try:
            snap = agent.health()
            snap.setdefault("behavior", agent.behavior_snapshot())
            return snap
        except Exception as exc:  # noqa: BLE001 - health probe must not crash
            _LOG.warning("pantheon_agent_health_error", extra={"agent": name, "error": str(exc)})
            return {"agent": name, "status": "error", "error": str(exc)}

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
        """Return the raw-event handler that feeds Huginn.

        Huginn.ingest normalizes + dedups + republishes as ``object.event``.
        A raw event missing a stable key is dropped with a warning (not
        dead-lettered): the P1 loop still processes the same record, so
        flooding the DLQ from the shadow pantheon would be noise.
        """
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
