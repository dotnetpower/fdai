"""Isolated health probing for pantheon runtime snapshots."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from fdai.agents._framework.base import Agent
from fdai.agents._framework.kpi import DECLARED_AGENT_KPIS, KpiCollector

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AgentDegradationPolicy:
    safe_effect: str
    blocks_mutation: bool = False
    portfolio_category: str = "agent_degradation"


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
    facts: dict[str, dict[str, object]]
    blocks_mutation: bool
    unavailable_sources: dict[str, tuple[str, ...]]

    def to_mapping(self) -> dict[str, object]:
        return {
            "unavailable_agents": list(self.unavailable_agents),
            "effects": dict(self.effects),
            "facts": {agent: dict(facts) for agent, facts in self.facts.items()},
            "blocks_mutation": self.blocks_mutation,
            "effective_mode": "shadow" if self.blocks_mutation else "configured",
            "unavailable_sources": {
                agent: list(sources) for agent, sources in self.unavailable_sources.items()
            },
        }


def evaluate_degradation(
    unavailable_agents: set[str],
    *,
    unavailable_sources: Mapping[str, Iterable[str]] | None = None,
) -> DegradationDecision:
    unknown = unavailable_agents - set(AGENT_DEGRADATION_POLICIES)
    if unknown:
        raise ValueError(f"unknown degraded agents: {sorted(unknown)}")
    ordered = tuple(sorted(unavailable_agents))
    source_map = {
        name: tuple(sorted(set((unavailable_sources or {}).get(name, ("runtime",)))))
        for name in ordered
    }
    return DegradationDecision(
        unavailable_agents=ordered,
        effects={name: AGENT_DEGRADATION_POLICIES[name].safe_effect for name in ordered},
        facts={name: _degradation_facts(name) for name in ordered},
        blocks_mutation=any(AGENT_DEGRADATION_POLICIES[name].blocks_mutation for name in ordered),
        unavailable_sources=source_map,
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
        error_type = type(exc).__name__
        _LOG.warning(
            "pantheon_agent_health_error",
            extra={
                "agent": name,
                "error_type": error_type,
                "failure_code": "health_probe_failed",
            },
        )
        return {
            "agent": name,
            "status": "error",
            "error_type": error_type,
            "failure_code": "health_probe_failed",
        }


def snapshot_agent_health(agents: Mapping[str, Agent]) -> dict[str, dict[str, Any]]:
    return {name: safe_agent_health(name, agent) for name, agent in agents.items()}


def report_agent_kpis(
    collector: KpiCollector,
    agent_health: dict[str, dict[str, Any]],
) -> None:
    """Report every active agent's declared KPIs with truthful evidence state."""
    for name, health in agent_health.items():
        values, metric_tags = _available_kpi_values(name, health)
        collector.report_declared(
            agent=name,
            values=values,
            tags={"source": "agent_health", "status": str(health.get("status", "unknown"))},
            metric_tags=metric_tags,
        )


def _available_kpi_values(
    agent: str, health: Mapping[str, Any]
) -> tuple[dict[str, float], dict[str, dict[str, str]]]:
    """Map health/behavior facts into declared KPI samples when available.

    Missing observations stay explicit ``not_observed`` samples. We only report
    a value when the agent already exposes a bounded behavior/health value that
    directly matches the KPI semantics; no zeros are fabricated from absence.
    """
    behavior = health.get("behavior")
    if not isinstance(behavior, Mapping):
        return {}, {}
    kpis = health.get("kpis")
    if isinstance(kpis, Mapping):
        measured: dict[str, float] = {}
        metric_tags: dict[str, dict[str, str]] = {}
        for metric, evidence in kpis.items():
            if not isinstance(metric, str) or not isinstance(evidence, Mapping):
                continue
            if evidence.get("evidence_state") != "measured":
                continue
            value = evidence.get("value")
            if isinstance(value, bool) or not isinstance(value, int | float):
                continue
            measured[metric] = float(value)
            tags = _metric_tags_from_evidence(metric, evidence)
            if tags:
                metric_tags[metric] = tags
        if measured:
            return measured, metric_tags
    if agent == "Saga":
        verified = behavior.get("maintenance_tick:audit_chain_verified")
        failed = behavior.get("maintenance_tick:failed")
        if isinstance(verified, int) and verified > 0 and not failed:
            return {"audit_chain_integrity_rate": 1.0}, {
                "audit_chain_integrity_rate": {"denominator": str(verified)}
            }
    if agent == "Mimir":
        passed = behavior.get("promotion:passed")
        reviewed_required = behavior.get("promotion:reviewed_change_required")
        failed_operational = behavior.get("promotion:failed_operational_candidate")
        failed_dwell = behavior.get("promotion:failed_shadow_dwell")
        if isinstance(passed, int):
            total = passed + sum(
                value
                for value in (reviewed_required, failed_operational, failed_dwell)
                if isinstance(value, int)
            )
            if total:
                return {"promotion_pass_rate": passed / total}, {
                    "promotion_pass_rate": {"denominator": str(total)}
                }
    if agent == "Muninn":
        hits = behavior.get("context_fetch:hit")
        misses = behavior.get("context_fetch:miss")
        if isinstance(hits, int) and isinstance(misses, int):
            total = hits + misses
            if total:
                return {"cache_hit_rate": hits / total}, {
                    "cache_hit_rate": {"denominator": str(total)}
                }
    if agent == "Norns":
        published = behavior.get("rule_candidate_published")
        held = behavior.get("rule_candidate_consensus_held")
        disabled = behavior.get("rule_candidate_publication_disabled")
        invalidated = behavior.get("operational_case_candidate_source_invalidated")
        rate_limited = behavior.get("rate_limit_exceeded")
        if isinstance(published, int) and published >= 0:
            total = published + sum(
                value
                for value in (held, disabled, invalidated, rate_limited)
                if isinstance(value, int)
            )
            if total:
                return {"rule_candidate_adoption_rate": published / total}, {
                    "rule_candidate_adoption_rate": {"denominator": str(total)}
                }
    if agent == "Bragi":
        materialized = behavior.get("handoff:materialized")
        unavailable = behavior.get("handoff:transport_unavailable")
        if isinstance(materialized, int) and isinstance(unavailable, int):
            total = materialized + unavailable
            if total:
                return {"handoff_rate": materialized / total}, {
                    "handoff_rate": {"denominator": str(total)}
                }
    return {}, {}


def _metric_tags_from_evidence(metric: str, evidence: Mapping[str, Any]) -> dict[str, str]:
    tags: dict[str, str] = {}
    denominator = evidence.get("denominator")
    if isinstance(denominator, int) and denominator > 0:
        tags["denominator"] = str(denominator)
    sample_count = evidence.get("sample_count")
    if isinstance(sample_count, int) and sample_count > 0:
        tags["sample_count"] = str(sample_count)
    if metric.endswith("_seconds"):
        tags["unit"] = "seconds"
    observed_at = evidence.get("observed_at")
    if isinstance(observed_at, str) and observed_at:
        tags["observed_at"] = observed_at
    return tags


def _degradation_facts(agent: str) -> dict[str, object]:
    policy = AGENT_DEGRADATION_POLICIES[agent]
    facts: dict[str, object] = {
        "safe_effect": policy.safe_effect,
        "evidence_state": "declared_degradation_policy",
        "workflow_7_category": policy.portfolio_category,
        "portfolio_reportable": True,
    }
    if agent == "Forseti":
        facts.update(
            {
                "no_verdict_fallback": True,
                "operator_alert": {"required": True, "status": "pending"},
                "events_retained": True,
            }
        )
    elif agent == "Var":
        facts.update(
            {
                "queue_preserved": True,
                "timeouts_auto_extended": True,
                "admin_alert": {"required": True, "status": "pending"},
                "allowed_action_classes": ["A1", "A2"],
                "blocked_action_classes": ["HIL", "A3-E"],
            }
        )
    elif agent == "Odin":
        facts.update(
            {
                "terminal_hil_closure": True,
                "terminal_hil_closure_count": {
                    "value": None,
                    "evidence_state": "not_observed",
                },
                "no_action_type": True,
                "no_initiator": True,
                "no_winning_domain": True,
                "no_action_authority": True,
            }
        )
    elif agent == "Bragi":
        facts.update(
            {
                "console_read_only_available": {
                    "value": None,
                    "evidence_state": "not_observed",
                },
                "direct_audit_query_available": {
                    "value": None,
                    "evidence_state": "not_observed",
                },
            }
        )
    return facts


def heartbeat_log_summary(snapshot: Mapping[str, Any]) -> dict[str, object]:
    degradation = snapshot.get("degradation")
    unavailable_agents: list[str] = []
    effective_mode = "unknown"
    blocks_mutation = False
    if isinstance(degradation, Mapping):
        raw_agents = degradation.get("unavailable_agents")
        if isinstance(raw_agents, list):
            unavailable_agents = [str(agent) for agent in raw_agents[: len(DECLARED_AGENT_KPIS)]]
        effective_mode = str(degradation.get("effective_mode", "unknown"))
        blocks_mutation = degradation.get("blocks_mutation") is True
    metrics = snapshot.get("metrics")
    bridge_failures: list[str] = []
    if isinstance(metrics, Mapping):
        bridge_failures = [
            key
            for key, value in metrics.items()
            if key
            in {
                "handler_errors",
                "dead_letter_errors",
                "publish_errors",
                "schema_violations",
                "producer_principal_mismatch",
                "ordered_poison_halts",
                "consumers_gave_up",
                "consumers_crashed",
            }
            and isinstance(value, int)
            and value > 0
        ][:16]
    return {
        "agents": snapshot.get("agents"),
        "bridge_status": snapshot.get("status"),
        "effective_enforce": snapshot.get("effective_enforce"),
        "degradation_unavailable_agents": unavailable_agents,
        "degradation_effective_mode": effective_mode,
        "degradation_blocks_mutation": blocks_mutation,
        "bridge_failure_counters": bridge_failures,
    }


__all__ = [
    "AGENT_DEGRADATION_POLICIES",
    "AgentDegradationPolicy",
    "DegradationDecision",
    "bind_availability_probe",
    "derive_unavailable_agents",
    "evaluate_degradation",
    "heartbeat_log_summary",
    "report_agent_kpis",
    "safe_agent_health",
    "snapshot_agent_health",
]
