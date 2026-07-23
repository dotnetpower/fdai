"""The fixed 15-agent pantheon.

This module is the single source of truth for agent names, layer
assignment, ownership, and topic subscriptions. Forks MUST NOT modify
this file - the pantheon is upstream-locked. Forks tune bindings and
enable / disable via config (see `agent-pantheon.md` \u00a710).
"""

from __future__ import annotations

from fdai.agents._framework.base import AgentSpec, Layer

# ---------------------------------------------------------------------------
# Odin - Master Planner (governance)
# ---------------------------------------------------------------------------
_ODIN = AgentSpec(
    name="Odin",
    layer=Layer.GOVERNANCE,
    reports_to=None,
    owns=("ArbitrationDecision",),
    executes=("governance.arbitrate-domain-conflict",),
    initiates=(),
    subscribes=(
        "object.arbitration-request",
        "object.verdict",  # portfolio outcome monitor
    ),
    question_domains=("priority_conflict", "portfolio_status"),
    owns_code_paths=("src/fdai/agents/odin.py",),
)

# ---------------------------------------------------------------------------
# Thor - Responder (pipeline; sole privileged executor)
# ---------------------------------------------------------------------------
_THOR = AgentSpec(
    name="Thor",
    layer=Layer.PIPELINE,
    reports_to="Odin",
    owns=("ActionRun", "ActionAttempt"),
    executes=(),  # dispatches; specific action executors bind per ActionType
    initiates=(),
    subscribes=("object.verdict", "object.approval", "object.rollback"),
    question_domains=("action_status", "execution_history_recent"),
    owns_code_paths=("src/fdai/agents/thor.py",),
)

# ---------------------------------------------------------------------------
# Forseti - Judge (pipeline; only T2-abstain hot-path LLM)
# ---------------------------------------------------------------------------
_FORSETI = AgentSpec(
    name="Forseti",
    layer=Layer.PIPELINE,
    reports_to="Odin",
    owns=("Verdict", "RCA", "SecurityEvent", "ArbitrationRequest"),
    executes=(),
    initiates=(
        "governance.arbitrate-domain-conflict",
        "governance.escalate-to-github-issue",
    ),
    subscribes=(
        "object.event",
        "object.anomaly",
        "object.drift",
        "object.cost-anomaly",
        "object.capacity-forecast",
        "object.arbitration-decision",
        "object.rule",  # cache reload on Mimir update
    ),
    question_domains=("why_denied", "why_rca", "verdict_explain"),
    owns_code_paths=("src/fdai/agents/forseti.py",),
    hot_path_llm=True,
)

# ---------------------------------------------------------------------------
# Huginn - Event Collector (pipeline)
# ---------------------------------------------------------------------------
_HUGINN = AgentSpec(
    name="Huginn",
    layer=Layer.PIPELINE,
    reports_to="Forseti",
    owns=("Event",),
    executes=(),
    initiates=(),
    subscribes=(),  # ingested from external adapters, not from bus
    question_domains=("event_source_health", "resource_discovery"),
    owns_code_paths=("src/fdai/agents/huginn.py",),
)

# ---------------------------------------------------------------------------
# Heimdall - Observer (pipeline)
# ---------------------------------------------------------------------------
_HEIMDALL = AgentSpec(
    name="Heimdall",
    layer=Layer.PIPELINE,
    reports_to="Forseti",
    owns=("Anomaly", "Drift", "Forecast"),
    executes=(),
    initiates=(
        "governance.notify-admin-privilege-violation",
        "governance.escalate-to-github-issue",
    ),
    subscribes=("object.event", "object.security-event", "object.chaos-experiment"),
    question_domains=(
        "resource_change_history",
        "anomaly",
        "drift",
        "forecast",
        "external_actor",
        "security_alert_history",
        "privilege_escalation_status",
    ),
    owns_code_paths=("src/fdai/agents/heimdall.py",),
)

# ---------------------------------------------------------------------------
# Vidar - Recovery (pipeline; hard dependency)
# ---------------------------------------------------------------------------
_VIDAR = AgentSpec(
    name="Vidar",
    layer=Layer.PIPELINE,
    reports_to="Thor",
    owns=("Rollback",),
    executes=(),
    initiates=(),
    subscribes=("object.action-run",),  # picks up failures
    question_domains=("rollback_status", "dr_readiness"),
    owns_code_paths=("src/fdai/agents/vidar.py",),
    hard_dependency=True,
)

# ---------------------------------------------------------------------------
# Var - Approver (pipeline)
# ---------------------------------------------------------------------------
_VAR = AgentSpec(
    name="Var",
    layer=Layer.PIPELINE,
    reports_to="Thor",
    owns=("Approval",),
    executes=("governance.notify-admin-privilege-violation",),
    initiates=(),
    subscribes=("object.action-run", "object.audit-entry"),  # action + document HIL
    question_domains=("hil_pending", "approval_backlog"),
    owns_code_paths=("src/fdai/agents/var.py",),
)

# ---------------------------------------------------------------------------
# Bragi - Narrator (pipeline; translator-only hot-path LLM)
# ---------------------------------------------------------------------------
_BRAGI = AgentSpec(
    name="Bragi",
    layer=Layer.PIPELINE,
    reports_to="Thor",
    owns=("Conversation", "Turn", "UserPreference"),
    executes=(),
    initiates=("governance.escalate-to-github-issue",),
    subscribes=("object.verdict", "object.action-run"),  # for progress rendering
    question_domains=("help", "capability_list"),
    owns_code_paths=("src/fdai/agents/bragi.py",),
    hot_path_llm=True,
)

# ---------------------------------------------------------------------------
# Saga - Auditor (governance; hard dependency)
# ---------------------------------------------------------------------------
_SAGA = AgentSpec(
    name="Saga",
    layer=Layer.GOVERNANCE,
    reports_to="Odin",
    owns=("AuditEntry", "Issue"),
    executes=("governance.escalate-to-github-issue",),
    initiates=(),
    subscribes=(
        "object.action-run",
        "object.rollback",
        "object.verdict",
        "object.approval",
        "object.security-event",
        "object.issue",
    ),
    question_domains=("fdai_action_history", "audit_log", "approval_history"),
    owns_code_paths=("src/fdai/agents/saga.py",),
    hard_dependency=True,
)

# ---------------------------------------------------------------------------
# Mimir - Rule Steward (governance)
# ---------------------------------------------------------------------------
_MIMIR = AgentSpec(
    name="Mimir",
    layer=Layer.GOVERNANCE,
    reports_to="Odin",
    owns=("Rule", "Policy"),
    executes=("governance.propose-rule-candidate",),
    initiates=("governance.propose-rule-candidate",),
    subscribes=("object.rule-candidate", "object.issue"),
    question_domains=("rule_lookup", "policy_explain", "rule_history"),
    owns_code_paths=("src/fdai/agents/mimir.py", "rule-catalog/**"),
)

# ---------------------------------------------------------------------------
# Muninn - Memory (governance)
# ---------------------------------------------------------------------------
_MUNINN = AgentSpec(
    name="Muninn",
    layer=Layer.GOVERNANCE,
    reports_to="Odin",
    owns=("StateSnapshot", "ContextIndex"),
    executes=(),
    initiates=(),
    subscribes=("object.turn", "object.audit-entry"),  # turns + governed document index
    question_domains=("current_state", "bitemporal_state", "resource_context"),
    owns_code_paths=("src/fdai/agents/muninn.py",),
)

# ---------------------------------------------------------------------------
# Norns - Learner (governance; only off-path LLM)
# ---------------------------------------------------------------------------
_NORNS = AgentSpec(
    name="Norns",
    layer=Layer.GOVERNANCE,
    reports_to="Odin",
    owns=("RuleCandidate", "PatternObservation"),
    executes=("governance.propose-rule-candidate",),
    initiates=("governance.propose-rule-candidate",),
    subscribes=("object.audit-entry", "object.issue", "object.approval", "object.turn"),
    question_domains=("pattern", "recurring_issue", "discovery_status"),
    owns_code_paths=("src/fdai/agents/norns.py",),
    off_path_llm=True,
)

# ---------------------------------------------------------------------------
# Njord - Cost (domain)
# ---------------------------------------------------------------------------
_NJORD = AgentSpec(
    name="Njord",
    layer=Layer.DOMAIN,
    reports_to="Forseti",
    owns=("CostAnomaly", "Budget"),
    executes=(),
    initiates=(),
    subscribes=(),  # cost signals ingested from adapter
    question_domains=("cost_breakdown", "budget_status", "cost_anomaly"),
    owns_code_paths=("src/fdai/agents/njord.py",),
)

# ---------------------------------------------------------------------------
# Freyr - Capacity (domain)
# ---------------------------------------------------------------------------
_FREYR = AgentSpec(
    name="Freyr",
    layer=Layer.DOMAIN,
    reports_to="Forseti",
    owns=("CapacityForecast", "SizingRecommendation"),
    executes=(),
    initiates=(),
    subscribes=(),  # utilization ingested from adapter
    question_domains=("capacity_status", "sizing_recommendation"),
    owns_code_paths=("src/fdai/agents/freyr.py",),
)

# ---------------------------------------------------------------------------
# Loki - Chaos (domain; ALWAYS HIL for execution)
# ---------------------------------------------------------------------------
_LOKI = AgentSpec(
    name="Loki",
    layer=Layer.DOMAIN,
    reports_to="Forseti",
    owns=("ChaosExperiment", "ResilienceScore"),
    executes=(),
    initiates=(),
    subscribes=(),  # schedule-driven
    question_domains=("chaos_experiment_status", "resilience_score"),
    owns_code_paths=("src/fdai/agents/loki.py",),
)


PANTHEON_SPECS: tuple[AgentSpec, ...] = (
    _ODIN,
    _THOR,
    _FORSETI,
    _HUGINN,
    _HEIMDALL,
    _VIDAR,
    _VAR,
    _BRAGI,
    _SAGA,
    _MIMIR,
    _MUNINN,
    _NORNS,
    _NJORD,
    _FREYR,
    _LOKI,
)

PANTHEON_NAMES: frozenset[str] = frozenset(s.name for s in PANTHEON_SPECS)

# `agent-pantheon.md` \u00a74.3: Saga and Vidar are hard dependencies for
# any mutation. Their degradation is fail-safe closed: no execution
# proceeds without them.
HARD_DEPENDENCY_AGENTS: frozenset[str] = frozenset(
    s.name for s in PANTHEON_SPECS if s.hard_dependency
)

# `agent-pantheon.md` \u00a78: hot-path LLM invocation is restricted to
# these three agents. Any other agent invoking an LLM synchronously is a
# defect.
LLM_HOT_PATH_ALLOWLIST: frozenset[str] = frozenset(
    s.name for s in PANTHEON_SPECS if s.hot_path_llm
) | frozenset(s.name for s in PANTHEON_SPECS if s.off_path_llm)


__all__ = [
    "PANTHEON_SPECS",
    "PANTHEON_NAMES",
    "HARD_DEPENDENCY_AGENTS",
    "LLM_HOT_PATH_ALLOWLIST",
]
