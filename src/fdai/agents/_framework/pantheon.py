"""The fixed 15-agent pantheon.

This module is the single source of truth for agent names, layer
assignment, ownership, and topic subscriptions. Forks MUST NOT modify
this file - the pantheon is upstream-locked. Forks tune bindings and
enable / disable via config (see `agent-pantheon.md` \u00a710).
"""

from __future__ import annotations

from fdai.agents._framework.base import (
    AgentSpec,
    Layer,
)
from fdai.agents._framework.charters import (
    conversation_charter,
    conversation_tool,
)

# ---------------------------------------------------------------------------
# Odin - Master Planner (governance)
# ---------------------------------------------------------------------------
_ODIN = AgentSpec(
    name="Odin",
    layer=Layer.GOVERNANCE,
    reports_to=None,
    owns=("ArbitrationDecision",),
    conversation=conversation_charter(
        "Odin",
        "Explain portfolio arbitration, priority conflicts, and observed portfolio outcomes.",
        "How are portfolio priority conflicts arbitrated?",
        "포트폴리오 우선순위 충돌과 중재 결과를 설명합니다.",
        conversation_tool(
            "read_arbitration_history",
            "Recorded arbitration history.",
            "arbitration_history_available",
        ),
        conversation_tool(
            "read_portfolio_policy",
            "Portfolio priority policy.",
            "priority_order",
            "temporal_policy",
            "history_window",
        ),
        conversation_tool(
            "read_arbitration_decision",
            "Latest arbitration outcome with the scores and margin behind it.",
            "winning_domain",
            "losing_domains",
            "objective_scores",
            "margin",
            "escalate_hil",
            "history_considered",
        ),
        conversation_tool(
            "read_portfolio_outcomes",
            "Verdict outcomes observed across the portfolio.",
            "verdicts_observed",
            "verdict_outcomes",
        ),
    ),
    executes=(),
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
    conversation=conversation_charter(
        "Thor",
        "Explain action-run state and recent execution evidence.",
        "What is the current action execution status?",
        "액션 실행 상태와 최근 실행 근거를 설명합니다.",
        conversation_tool(
            "read_action_runs",
            "Action-run state.",
            "total_runs",
            "active_runs",
            "correlation_id",
            "action_type",
            "resource_id",
            "state",
            "state_history",
            "verdict",
            "quorum_required",
            "outcome",
        ),
        conversation_tool(
            "read_execution_history",
            "Execution safety configuration.",
            "shadow_forced",
            "shadow_mode",
            "rollback_contract",
            "rollback_ref",
        ),
    ),
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
    conversation=conversation_charter(
        "Forseti",
        "Explain verdicts and grounded root-cause judgments.",
        "Why was this action denied, and what evidence supports the judgment?",
        "판정과 근거가 확인된 원인 분석을 설명합니다.",
        conversation_tool(
            "read_verdicts",
            "Deterministic risk verdicts.",
            "known_action_verdicts",
            "action_type",
            "risk_verdict",
        ),
        conversation_tool(
            "read_judgment_context",
            "Rule and arbitration judgment context.",
            "rule_matches",
            "arbitrations_recorded",
            "unresolved_arbitrations",
            "readiness_limited_resources",
        ),
        conversation_tool(
            "read_rca_evidence",
            "Grounded root-cause evidence.",
            "rca_evidence_available",
        ),
    ),
    executes=(),
    initiates=(),
    subscribes=(
        "object.event",
        "object.anomaly",
        "object.drift",
        "object.forecast",
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
    owns=("Event", "Change"),
    conversation=conversation_charter(
        "Huginn",
        "Explain ingress health and resource discovery intake.",
        "Is real-time event ingress healthy?",
        "이벤트 수집 상태와 리소스 발견 수신 상태를 설명합니다.",
        conversation_tool(
            "read_ingress_health",
            "Ingress activity.",
            "dedup_size",
            "ingested_count",
            "deduped_count",
        ),
        conversation_tool(
            "read_dedup_status",
            "Deduplication capacity.",
            "dedup_capacity",
            "dedup_window_full",
        ),
    ),
    executes=(),
    initiates=(),
    subscribes=(),  # ingested from external adapters, not from bus
    question_domains=(
        "event_source_health",
        "resource_discovery",
        "resource_discovery_status",
    ),
    owns_code_paths=("src/fdai/agents/huginn.py",),
)

# ---------------------------------------------------------------------------
# Heimdall - Observer (pipeline)
# ---------------------------------------------------------------------------
_HEIMDALL = AgentSpec(
    name="Heimdall",
    layer=Layer.PIPELINE,
    reports_to="Forseti",
    owns=("Anomaly", "Drift", "Forecast", "ForecastOutcome"),
    conversation=conversation_charter(
        "Heimdall",
        "Explain observed signals, anomalies, drift, and forecasts.",
        "What anomalies or drift have been observed for this resource?",
        "관측 신호, 이상, 드리프트, 예측을 설명합니다.",
        conversation_tool(
            "read_observations",
            "Observed resource signals.",
            "watched_resources",
            "watched_resources_count",
            "rate_threshold",
            "resource_id",
            "recent_event_count",
            "recent_event_types",
        ),
        conversation_tool(
            "read_security_window",
            "Observed security-signal window.",
            "security_events_window",
        ),
        conversation_tool(
            "read_forecast_status",
            "Retained forecast episode evidence.",
            "forecast_evidence_available",
        ),
        conversation_tool(
            "read_drift_status",
            "Retained drift finding evidence.",
            "drift_evidence_available",
        ),
    ),
    executes=(),
    initiates=(),
    subscribes=("object.event", "object.security-event", "object.chaos-experiment"),
    question_domains=(
        "resource_change_history",
        "anomaly",
        "drift",
        "forecast",
        "external_actor",
        "security_alert_history",
        "privilege_escalation_status",
        "discovery_health",
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
    conversation=conversation_charter(
        "Vidar",
        "Explain rollback history and disaster-recovery readiness.",
        "What is the latest rollback and recovery safety status?",
        "롤백 이력과 재해 복구 준비 상태를 설명합니다.",
        conversation_tool(
            "read_rollback_history",
            "Rollback history.",
            "rollbacks_recorded",
            "last_correlation_id",
            "last_action_type",
            "last_state",
            "last_contract",
            "last_rollback_ref",
        ),
        conversation_tool(
            "read_recovery_safety",
            "Recovery safety dependency status.",
            "hard_dependency",
        ),
    ),
    executes=(),
    initiates=(),
    subscribes=("object.action-run",),  # picks up failures
    question_domains=("rollback_status", "dr_readiness", "rollback_dependency_health"),
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
    conversation=conversation_charter(
        "Var",
        "Explain pending approvals and approval outcomes.",
        "Which human approvals are pending?",
        "승인 대기와 승인 결과를 설명합니다.",
        conversation_tool(
            "read_pending_approvals",
            "Pending human approvals.",
            "pending_hil",
            "correlations",
            "correlation_id",
            "action_type",
            "quorum_required",
            "approvals",
            "rejected",
        ),
        conversation_tool(
            "read_approval_policy",
            "Approval-role separation policy.",
            "reports_to",
            "owns",
        ),
    ),
    executes=(),
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
    owns=(
        "Conversation",
        "Turn",
        "UserPreference",
        "HandoffEscalation",
        "PostTurnReview",
    ),
    conversation=conversation_charter(
        "Bragi",
        "Route questions and explain the fixed agent capability roster.",
        "Which FDAI agent can answer this question?",
        "질문을 라우팅하고 고정된 에이전트 역할과 기능을 설명합니다.",
        conversation_tool("list_agent_capabilities", "Agent capability roster.", "roster"),
        conversation_tool(
            "read_routing_policy",
            "Bragi routing scope.",
            "question_domains",
            "conversation_tools",
        ),
    ),
    executes=(),
    initiates=(),
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
    conversation=conversation_charter(
        "Saga",
        "Explain append-only audit evidence and issue handoffs.",
        "Show the audit trail and any issue handoff for this correlation.",
        "추가 전용 감사 근거와 이슈 인계 상태를 설명합니다.",
        conversation_tool(
            "read_audit_chain",
            "Append-only audit evidence.",
            "audit_entries",
            "correlation_id",
            "matched_entries",
            "chain_head_seq",
            "chain_head_hash",
        ),
        conversation_tool(
            "read_issue_handoffs",
            "Governed issue handoffs.",
            "issues_total",
            "issues_open",
        ),
    ),
    executes=(),
    initiates=(),
    subscribes=(
        "object.action-run",
        "object.rollback",
        "object.verdict",
        "object.approval",
        "object.security-event",
        "object.state-snapshot",
        "object.issue",
        "object.forecast-outcome",
        "object.handoff-escalation",
        "object.rule",
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
    conversation=conversation_charter(
        "Mimir",
        "Explain governed rules, policies, and rule history.",
        "What is the current governed rule status?",
        "거버넌스 규칙, 정책, 규칙 변경 이력을 설명합니다.",
        conversation_tool(
            "read_rule_catalog",
            "Governed rule states.",
            "tracked_rules",
            "tracked_rules_count",
            "rule_id",
            "state",
            "source",
            "updated_at",
        ),
        conversation_tool(
            "read_candidate_queue",
            "Rule-candidate queue status.",
            "pending_candidates",
            "quarantined_candidates",
        ),
        conversation_tool(
            "read_policy_history",
            "Governed policy history.",
            "policy_history_available",
        ),
    ),
    executes=(),
    initiates=(),
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
    conversation=conversation_charter(
        "Muninn",
        "Explain current, bitemporal, and case-history context.",
        "What state and case-history context is available?",
        "현재 상태, 이중 시간 상태, 사례 이력 컨텍스트를 설명합니다.",
        conversation_tool(
            "read_state_context",
            "State and context index inventory.",
            "buckets",
            "buckets_count",
            "total_keys",
            "bucket",
            "key_count",
        ),
        conversation_tool(
            "read_case_history",
            "Case-history service availability.",
            "case_history_available",
            "case_history_retention_available",
        ),
    ),
    executes=(),
    initiates=(),
    subscribes=(
        "object.turn",
        "object.audit-entry",
        "object.drift",
        "object.forecast-outcome",
        "object.event",
        "object.change",
    ),
    question_domains=(
        "current_state",
        "bitemporal_state",
        "resource_context",
        "case_history",
    ),
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
    conversation=conversation_charter(
        "Norns",
        "Explain recurring patterns and inert learning candidates.",
        "What recurring patterns and inert candidates were observed?",
        "반복 패턴과 비활성 학습 후보를 설명합니다.",
        conversation_tool(
            "read_pattern_observations",
            "Recurring pattern observations.",
            "fingerprints_tracked",
            "outcomes_tracked",
            "outcomes_tracked_count",
        ),
        conversation_tool(
            "read_candidate_holds",
            "Inert candidate and consensus holds.",
            "pending_candidates",
            "consensus_holds",
        ),
    ),
    executes=(),
    initiates=(),
    subscribes=(
        "object.audit-entry",
        "object.issue",
        "object.approval",
        "object.post-turn-review",
        "object.context-index",
    ),
    question_domains=(
        "pattern",
        "recurring_issue",
        "learning_discovery_status",
        "rule_candidate_status",
    ),
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
    conversation=conversation_charter(
        "Njord",
        "Explain observed cost samples, budgets, and anomalies.",
        "What cost samples or anomalies are present for this scope?",
        "관측 비용, 예산 상태, 비용 이상을 설명합니다.",
        conversation_tool(
            "read_cost_samples",
            "Observed cost samples and anomaly threshold.",
            "tracked_scopes",
            "tracked_scopes_count",
            "anomaly_ratio",
            "scope",
            "sample_count",
            "baseline_usd",
            "latest_usd",
        ),
        conversation_tool(
            "read_cost_model",
            "Known action cost model.",
            "known_action_costs",
            "action_type",
            "monthly_delta_usd",
            "confidence",
        ),
        conversation_tool(
            "read_budget_status",
            "Bound budget projection status.",
            "budget_data_available",
        ),
    ),
    executes=(),
    initiates=(),
    subscribes=("object.event",),  # canonical cost samples from an adapter
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
    conversation=conversation_charter(
        "Freyr",
        "Explain capacity forecasts and sizing recommendations.",
        "What capacity forecast and sizing recommendation is available?",
        "용량 예측과 크기 조정 권고를 설명합니다.",
        conversation_tool(
            "read_capacity_forecasts",
            "Capacity forecast state.",
            "tracked_resources",
            "tracked_resources_count",
            "current_util",
            "forecast_util",
        ),
        conversation_tool(
            "read_sizing_recommendations",
            "Sizing recommendation policy and result.",
            "scale_up_threshold",
            "scale_down_threshold",
            "resource_id",
            "recommendation",
        ),
    ),
    executes=(),
    initiates=(),
    subscribes=("object.event",),  # canonical utilization samples from an adapter
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
    conversation=conversation_charter(
        "Loki",
        "Explain governed chaos experiments and resilience scores.",
        "What chaos experiments are proposed and how is impact bounded?",
        "거버넌스 카오스 실험과 복원력 점수를 설명합니다.",
        conversation_tool(
            "read_chaos_experiments",
            "Chaos experiment proposal status.",
            "proposals_total",
            "proposals_accepted",
        ),
        conversation_tool(
            "read_chaos_safety",
            "Chaos impact-scope safety status.",
            "blast_radius_cap",
            "in_flight_targets",
        ),
        conversation_tool(
            "read_resilience_scores",
            "Retained resilience score evidence.",
            "resilience_score_available",
        ),
    ),
    executes=(),
    initiates=(),
    subscribes=("object.event",),  # canonical schedule triggers
    question_domains=(
        "chaos_experiment_status",
        "resilience_score",
        "chaos_execution_policy",
    ),
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
