"""Cross-agent workflows registry (Wave 7).

Each workflow declared in `docs/roadmap/agents/agent-workflows.md` gets a
:class:`WorkflowSpec` entry here. The specs are metadata only - actual
workflow behavior is composed from the agent methods that ship in
Wave 2 through Wave 6. This module exists so:

- Runtime + tests can enumerate the shipped workflows.
- Promotion tooling (Wave 8) knows which workflows have exit-gate
  criteria to measure.
- Bragi's operator briefing can present the workflow catalog.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WorkflowSpec:
    id: str
    name: str
    primary_agent: str
    participating_agents: tuple[str, ...]
    trigger: str
    default_mode: str  # shadow | enforce
    promotion_gate: str  # brief description; machine gate lives in Wave 8
    trace_ref: str  # executable pytest node proving the shadow path
    trace_assertions: tuple[str, ...] = ()
    planned_agents: tuple[str, ...] = ()


WORKFLOWS: tuple[WorkflowSpec, ...] = (
    WorkflowSpec(
        id="cost-aware-remediation",
        name="Cost-aware remediation",
        primary_agent="Heimdall",
        participating_agents=("Njord", "Forseti", "Thor", "Saga"),
        trigger="object.drift or object.anomaly with a matched rule",
        default_mode="shadow",
        promotion_gate=("14d shadow; Njord cost forecast MAPE < 20%; zero missing cost_annotation"),
        trace_ref="services/core-control-plane/tests/agents/test_wave7_workflows.py::test_workflow_cost_aware_remediation_shadow_trace",
        trace_assertions=(
            "cost_advisory_measured",
            "cost_ceiling_blocks_auto",
            "cost_annotation_attached_to_verdict",
            "terminal_action_run_audited",
        ),
        planned_agents=("Heimdall",),
    ),
    WorkflowSpec(
        id="predictive-scale",
        name="Predictive scale",
        primary_agent="Freyr",
        participating_agents=("Freyr", "Heimdall", "Njord", "Odin", "Forseti"),
        trigger="Freyr forecast threshold breach within predictive_horizon",
        default_mode="shadow",
        promotion_gate=("30d shadow; Freyr forecast MAPE < 15%; false-positive scale rate < 5%"),
        trace_ref="services/core-control-plane/tests/agents/test_wave7_workflows.py::test_workflow_predictive_scale_shadow_trace",
        trace_assertions=(
            "forecast_leads_reactive_baseline",
            "false_positive_baseline_checked",
            "arbitration_request_on_cost_conflict",
            "recurring_sample_maps_to_shadow_scale_verdict",
        ),
        planned_agents=("Thor",),
    ),
    WorkflowSpec(
        id="dr-drill-orchestration",
        name="DR drill orchestration",
        primary_agent="Loki",
        participating_agents=("Loki", "Thor", "Vidar", "Saga"),
        trigger="Loki weekly schedule",
        default_mode="shadow",
        promotion_gate=(
            "3 successful drills in shadow; drill duration < declared budget; "
            "zero unplanned prod side-effects"
        ),
        trace_ref="services/core-control-plane/tests/agents/test_wave7_workflows.py::test_workflow_dr_drill_orchestration_respects_blast_radius",
        trace_assertions=(
            "blast_radius_capped",
            "recurring_scheduler_publishes_hil_drill_window",
            "proposal_audited",
            "vidar_dr_contract_gates_failover_recovery_time",
        ),
        planned_agents=("Forseti", "Var", "Heimdall", "Norns"),
    ),
    WorkflowSpec(
        id="override-discovery",
        name="Override -> Discovery",
        primary_agent="Var",
        participating_agents=("Var", "Saga", "Norns", "Mimir"),
        trigger="Var records Approval that differs from Forseti verdict",
        default_mode="shadow",
        promotion_gate=(
            "60d shadow; override-to-candidate conversion pattern captured; "
            "false-candidate rate < 10%"
        ),
        trace_ref="services/core-control-plane/tests/agents/test_wave7_workflows.py::test_workflow_override_to_discovery_via_norns",
        trace_assertions=("approval_override_source", "deduped_rule_candidate"),
    ),
    WorkflowSpec(
        id="security-escalation",
        name="Security escalation",
        primary_agent="Forseti",
        participating_agents=("Forseti", "Heimdall", "Var"),
        trigger="Forseti emits SecurityEvent",
        default_mode="shadow",
        promotion_gate="30d shadow (bootstrap); zero critical false-negative; high FP < 5%",
        trace_ref="services/core-control-plane/tests/agents/test_wave7_workflows.py::test_workflow_security_escalation_reaches_admin_channel",
        trace_assertions=(
            "duplicate_same_user_action_upserts_one_card",
            "per_user_rate_limit_blocks_sixth_card",
            "critical_pattern_pages_admin",
        ),
        planned_agents=("Odin", "Saga"),
    ),
    WorkflowSpec(
        id="handoff-capability",
        name="Handoff -> Capability",
        primary_agent="Saga",
        participating_agents=("Saga", "Norns", "Mimir"),
        trigger="Saga writes object.issue (via escalate_to_github_issue)",
        default_mode="shadow",
        promotion_gate=(
            "90d shadow; conversion (handoff -> promoted rule) baseline; false-close rate < 2%"
        ),
        trace_ref="services/core-control-plane/tests/agents/test_wave7_workflows.py::test_workflow_handoff_capability_keeps_issue_open_without_promotion",
        trace_assertions=(
            "candidate_deduped",
            "failed_promotion_keeps_issue_open",
            "norns_quiet_window_signal_is_inert",
            "promotion_evidence_closes_after_clean_window",
        ),
        planned_agents=("Bragi",),
    ),
    WorkflowSpec(
        id="agent-health-degradation",
        name="Agent health degradation",
        primary_agent="Heimdall",
        participating_agents=("Heimdall", "Odin"),
        trigger="Heimdall per-minute agent-health probe",
        default_mode="shadow",
        promotion_gate=(
            "30d shadow; every declared degradation policy tested at least once; "
            "briefing latency p99 < 60s"
        ),
        trace_ref="services/core-control-plane/tests/agents/test_wave7_workflows.py::test_workflow_agent_health_degradation_reports_via_odin",
        trace_assertions=("odin_arbitrates_degradation_priority",),
        planned_agents=("Bragi", "Saga"),
    ),
    WorkflowSpec(
        id="judgment-coherence-audit",
        name="Judgment coherence audit",
        primary_agent="Forseti",
        participating_agents=("Forseti", "Saga", "Norns"),
        trigger="Forseti daily self-test",
        default_mode="shadow",
        promotion_gate="60d shadow; mismatch rate baseline captured; false-drift-alert rate < 5%",
        trace_ref="services/core-control-plane/tests/agents/test_wave7_workflows.py::test_workflow_judgment_coherence_deterministic_verdict",
        trace_assertions=("audit_sample_replayed", "forced_mismatch_creates_one_candidate"),
        planned_agents=("Mimir",),
    ),
    WorkflowSpec(
        id="rollback-rehearsal",
        name="Rollback rehearsal",
        primary_agent="Loki",
        participating_agents=("Loki", "Vidar", "Saga"),
        trigger="Loki monthly schedule",
        default_mode="shadow",
        promotion_gate="3 successful rehearsals per ActionType before enforce eligibility",
        trace_ref="services/core-control-plane/tests/agents/test_wave7_workflows.py::test_workflow_rollback_rehearsal_blocks_overlapping_loki_targets",
        trace_assertions=(
            "blast_radius_full_blocks_overlap",
            "proposal_audited",
            "vidar_records_non_mutating_rehearsal_receipt",
        ),
        planned_agents=("Forseti", "Var", "Heimdall"),
    ),
    WorkflowSpec(
        id="retrospective-what-if",
        name="Retrospective what-if",
        primary_agent="Bragi",
        participating_agents=("Saga", "Forseti"),
        trigger="Operator via Bragi or scheduled post-incident",
        default_mode="shadow",
        promotion_gate="inherently shadow - never promoted",
        trace_ref="services/core-control-plane/tests/agents/test_wave7_workflows.py::test_workflow_retrospective_what_if_is_judge_only",
        trace_assertions=(
            "overlay_rejudgment_reproducible",
            "no_action_run_published",
            "versioned_what_if_disagreement_evidence_inert",
        ),
        planned_agents=("Bragi", "Norns", "Mimir"),
    ),
    WorkflowSpec(
        id="operational-readiness-handoff",
        name="Operational readiness handoff",
        primary_agent="Forseti",
        participating_agents=("Forseti", "Var", "Thor", "Saga"),
        trigger="Huginn normalizes an ownership_transfer signal",
        default_mode="shadow",
        promotion_gate=(
            "30d shadow per environment; zero critical false-negative; "
            "blocking false-positive rate < 5%"
        ),
        trace_ref="services/core-control-plane/tests/composition/test_readiness_service.py::test_blocking_posture_finding_gates_enforce_handoff",
        trace_assertions=("composition_handoff_blocks_on_critical_finding",),
        planned_agents=("Huginn", "Mimir"),
    ),
    WorkflowSpec(
        id="scheduled-governed-python-task",
        name="Scheduled governed Python task",
        primary_agent="Forseti",
        participating_agents=("Forseti", "Var", "Thor", "Saga"),
        trigger="Strict cron schedule with a PythonTask artifact binding",
        default_mode="shadow",
        promotion_gate=(
            "14d and 30 shadow plans; accuracy >= 99%; zero policy escapes; Owner review"
        ),
        trace_ref="services/core-control-plane/tests/core/test_control_loop_operator_request.py::test_raw_proposal_reaches_vm_runner_after_owner_approval",
        trace_assertions=("control_loop_owner_approval_reaches_runner",),
        planned_agents=("Bragi",),
    ),
    WorkflowSpec(
        id="detection-readiness-assurance",
        name="Detection readiness assurance",
        primary_agent="Heimdall",
        participating_agents=("Huginn", "Heimdall", "Muninn", "Forseti", "Saga"),
        trigger="detection.readiness.observed on the raw ingress topic",
        default_mode="shadow",
        promotion_gate=(
            "30d shadow per target; zero false-ready snapshots; stale detection p99 < 15m"
        ),
        trace_ref="services/core-control-plane/tests/agents/test_detection_readiness.py::test_huginn_to_heimdall_reduces_readiness_in_shadow",
        trace_assertions=("readiness_reduced_in_shadow",),
        planned_agents=("Bragi",),
    ),
)

WORKFLOWS_BY_ID: dict[str, WorkflowSpec] = {w.id: w for w in WORKFLOWS}


def workflow(id: str) -> WorkflowSpec:
    return WORKFLOWS_BY_ID[id]


__all__ = ["WORKFLOWS", "WORKFLOWS_BY_ID", "WorkflowSpec", "workflow"]
