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


WORKFLOWS: tuple[WorkflowSpec, ...] = (
    WorkflowSpec(
        id="cost-aware-remediation",
        name="Cost-aware remediation",
        primary_agent="Heimdall",
        participating_agents=("Heimdall", "Njord", "Forseti", "Thor", "Saga"),
        trigger="object.drift or object.anomaly with a matched rule",
        default_mode="shadow",
        promotion_gate=("14d shadow; Njord cost forecast MAPE < 20%; zero missing cost_annotation"),
    ),
    WorkflowSpec(
        id="predictive-scale",
        name="Predictive scale",
        primary_agent="Freyr",
        participating_agents=("Freyr", "Heimdall", "Njord", "Odin", "Forseti", "Thor"),
        trigger="Freyr forecast threshold breach within predictive_horizon",
        default_mode="shadow",
        promotion_gate=("30d shadow; Freyr forecast MAPE < 15%; false-positive scale rate < 5%"),
    ),
    WorkflowSpec(
        id="dr-drill-orchestration",
        name="DR drill orchestration",
        primary_agent="Loki",
        participating_agents=("Loki", "Vidar", "Heimdall", "Norns", "Saga", "Var"),
        trigger="Loki weekly schedule",
        default_mode="shadow",
        promotion_gate=(
            "3 successful drills in shadow; drill duration < declared budget; "
            "zero unplanned prod side-effects"
        ),
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
    ),
    WorkflowSpec(
        id="security-escalation",
        name="Security escalation",
        primary_agent="Forseti",
        participating_agents=("Forseti", "Heimdall", "Odin", "Var", "Saga"),
        trigger="Forseti emits SecurityEvent",
        default_mode="enforce",  # only workflow shipped enforce-mode by default
        promotion_gate="30d shadow (bootstrap); zero critical false-negative; high FP < 5%",
    ),
    WorkflowSpec(
        id="handoff-capability",
        name="Handoff -> Capability",
        primary_agent="Saga",
        participating_agents=("Saga", "Norns", "Mimir", "Bragi"),
        trigger="Saga writes object.issue (via escalate_to_github_issue)",
        default_mode="shadow",
        promotion_gate=(
            "90d shadow; conversion (handoff -> promoted rule) baseline; false-close rate < 2%"
        ),
    ),
    WorkflowSpec(
        id="agent-health-degradation",
        name="Agent health degradation",
        primary_agent="Heimdall",
        participating_agents=("Heimdall", "Odin", "Bragi", "Saga"),
        trigger="Heimdall per-minute agent-health probe",
        default_mode="shadow",
        promotion_gate=(
            "30d shadow; every declared degradation policy tested at least once; "
            "briefing latency p99 < 60s"
        ),
    ),
    WorkflowSpec(
        id="judgment-coherence-audit",
        name="Judgment coherence audit",
        primary_agent="Forseti",
        participating_agents=("Forseti", "Norns", "Mimir", "Saga"),
        trigger="Forseti daily self-test",
        default_mode="shadow",
        promotion_gate="60d shadow; mismatch rate baseline captured; false-drift-alert rate < 5%",
    ),
    WorkflowSpec(
        id="rollback-rehearsal",
        name="Rollback rehearsal",
        primary_agent="Loki",
        participating_agents=("Loki", "Vidar", "Heimdall", "Saga", "Var"),
        trigger="Loki monthly schedule",
        default_mode="shadow",
        promotion_gate="3 successful rehearsals per ActionType before enforce eligibility",
    ),
    WorkflowSpec(
        id="retrospective-what-if",
        name="Retrospective what-if",
        primary_agent="Bragi",
        participating_agents=("Bragi", "Saga", "Forseti", "Norns", "Mimir"),
        trigger="Operator via Bragi or scheduled post-incident",
        default_mode="shadow",
        promotion_gate="inherently shadow - never promoted",
    ),
    WorkflowSpec(
        id="detection-readiness-assurance",
        name="Detection readiness assurance",
        primary_agent="Heimdall",
        participating_agents=("Huginn", "Heimdall", "Muninn", "Forseti", "Saga", "Bragi"),
        trigger="detection.readiness.observed on the raw ingress topic",
        default_mode="shadow",
        promotion_gate=(
            "30d shadow per target; zero false-ready snapshots; stale detection p99 < 15m"
        ),
    ),
)

WORKFLOWS_BY_ID: dict[str, WorkflowSpec] = {w.id: w for w in WORKFLOWS}


def workflow(id: str) -> WorkflowSpec:
    return WORKFLOWS_BY_ID[id]


__all__ = ["WORKFLOWS", "WORKFLOWS_BY_ID", "WorkflowSpec", "workflow"]
