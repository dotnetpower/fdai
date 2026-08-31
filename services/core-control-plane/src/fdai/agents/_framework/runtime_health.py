"""Isolated health probing for pantheon runtime snapshots."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from fdai.agents._framework.base import Agent
from fdai.agents._framework.kpi import KpiCollector

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AgentDegradationPolicy:
    safe_effect: str
    blocks_mutation: bool = False


AGENT_DEGRADATION_POLICIES: dict[str, AgentDegradationPolicy] = {
    "Odin": AgentDegradationPolicy("conflicts_require_hil"),
    "Thor": AgentDegradationPolicy("verdicts_queued", blocks_mutation=True),
    "Forseti": AgentDegradationPolicy("judgment_paused_events_retained", blocks_mutation=True),
    "Huginn": AgentDegradationPolicy("ingress_retained_for_replay"),
    "Heimdall": AgentDegradationPolicy("rule_only_judgment_continues"),
    "Vidar": AgentDegradationPolicy("new_mutations_shadow", blocks_mutation=True),
    "Var": AgentDegradationPolicy("hil_queue_preserved"),
    "Bragi": AgentDegradationPolicy("read_only_fallback"),
    "Saga": AgentDegradationPolicy("mutation_refused_without_audit", blocks_mutation=True),
    "Mimir": AgentDegradationPolicy("cached_rules_updates_deferred"),
    "Muninn": AgentDegradationPolicy("context_unavailable_recorded"),
    "Norns": AgentDegradationPolicy("learning_paused"),
    "Njord": AgentDegradationPolicy("cost_actions_require_hil"),
    "Freyr": AgentDegradationPolicy("capacity_actions_require_hil"),
    "Loki": AgentDegradationPolicy("chaos_actions_require_hil"),
}


@dataclass(frozen=True, slots=True)
class DegradationDecision:
    unavailable_agents: tuple[str, ...]
    effects: dict[str, str]
    blocks_mutation: bool

    def to_mapping(self) -> dict[str, object]:
        return {
            "unavailable_agents": list(self.unavailable_agents),
            "effects": dict(self.effects),
            "blocks_mutation": self.blocks_mutation,
            "effective_mode": "shadow" if self.blocks_mutation else "configured",
        }


def evaluate_degradation(unavailable_agents: set[str]) -> DegradationDecision:
    unknown = unavailable_agents - set(AGENT_DEGRADATION_POLICIES)
    if unknown:
        raise ValueError(f"unknown degraded agents: {sorted(unknown)}")
    ordered = tuple(sorted(unavailable_agents))
    return DegradationDecision(
        unavailable_agents=ordered,
        effects={name: AGENT_DEGRADATION_POLICIES[name].safe_effect for name in ordered},
        blocks_mutation=any(AGENT_DEGRADATION_POLICIES[name].blocks_mutation for name in ordered),
    )


def derive_unavailable_agents(
    *,
    disabled: Iterable[str],
    continuity_failures: Iterable[str],
) -> frozenset[str]:
    """Return the pantheon agents a runtime cannot currently reach.

    Derived from the two facts a runtime already owns: the agents a fork
    disabled at composition, and the consumers whose bus continuity failed.
    Names outside the degradation policy table are dropped so the result is
    always a valid :func:`evaluate_degradation` input. Cheap and re-entrant,
    so an agent may probe it inline on a decision path.
    """
    unavailable = set(disabled)
    unavailable.update(consumer.split(":", 1)[0] for consumer in continuity_failures)
    return frozenset(name for name in unavailable if name in AGENT_DEGRADATION_POLICIES)


def bind_availability_probe(
    agents: Mapping[str, Agent],
    *,
    disabled: Iterable[str],
    continuity_failures: Mapping[str, Any],
) -> None:
    """Give agents that fail closed on an unreachable peer a live probe.

    ``continuity_failures`` is read on every probe call, so an agent bound at
    wiring time observes failures recorded later. The binding is duck-typed on
    the ``bind_agent_availability`` seam because this module must not import a
    concrete agent: agents import this module.
    """
    fixed_disabled = frozenset(disabled)

    def probe() -> frozenset[str]:
        return derive_unavailable_agents(
            disabled=fixed_disabled,
            continuity_failures=continuity_failures,
        )

    for agent in agents.values():
        bind = getattr(agent, "bind_agent_availability", None)
        if callable(bind):
            bind(probe)


def safe_agent_health(name: str, agent: Agent) -> dict[str, Any]:
    """Read one agent's health without allowing a failed probe to fan out."""
    try:
        snapshot = agent.health()
        snapshot.setdefault("behavior", agent.behavior_snapshot())
        return snapshot
    except Exception as exc:  # noqa: BLE001 - health probe must isolate failures
        _LOG.warning("pantheon_agent_health_error", extra={"agent": name, "error": str(exc)})
        return {"agent": name, "status": "error", "error": str(exc)}


def snapshot_agent_health(agents: Mapping[str, Agent]) -> dict[str, dict[str, Any]]:
    return {name: safe_agent_health(name, agent) for name, agent in agents.items()}


def report_agent_kpis(
    collector: KpiCollector,
    agent_health: dict[str, dict[str, Any]],
) -> None:
    """Report every active agent's declared KPIs with truthful evidence state."""
    for name, health in agent_health.items():
        collector.report_declared(
            agent=name,
            tags={"source": "agent_health", "status": str(health.get("status", "unknown"))},
        )


__all__ = [
    "AGENT_DEGRADATION_POLICIES",
    "AgentDegradationPolicy",
    "DegradationDecision",
    "bind_availability_probe",
    "derive_unavailable_agents",
    "evaluate_degradation",
    "report_agent_kpis",
    "safe_agent_health",
    "snapshot_agent_health",
]
