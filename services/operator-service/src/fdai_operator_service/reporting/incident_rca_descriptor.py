"""Immutable descriptor for the built-in Incident RCA dossier."""

from __future__ import annotations

REPORT_ID = "incident-rca-dossier"
REPORT_NAME = "Incident RCA Dossier"
REPORT_DESCRIPTION = (
    "Correlation-scoped incident and root-cause evidence package. Combines grounded "
    "hypotheses, causal-chain hops, citations, response history, and the append-only "
    "audit chronology without inferring missing evidence."
)
REPORT_TAGS = ("incident", "rca", "post-incident")
TABLE_SPECS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "incident-profile",
        "Incident profile and document scope",
        "profile",
        (
            "correlation_id",
            "incident_id",
            "title",
            "severity",
            "status",
            "vertical",
            "opened_at",
            "last_updated_at",
            "audit_records",
        ),
    ),
    (
        "impact-assessment",
        "Impact assessment",
        "rca_impact",
        (
            "metric",
            "baseline",
            "observed",
            "threshold",
            "unit",
            "impact",
            "evidence_ref",
        ),
    ),
    (
        "event-chronology",
        "Incident chronology",
        "milestones",
        (
            "recorded_at",
            "actor",
            "action_kind",
            "decision",
            "outcome",
            "mode",
            "summary",
        ),
    ),
    (
        "root-cause-hypotheses",
        "Root-cause hypotheses",
        "hypotheses",
        (
            "tier",
            "outcome",
            "cause",
            "confidence",
            "reason",
            "remediation_ref",
            "mode",
            "recorded_at",
        ),
    ),
    (
        "causal-chain",
        "Deterministic causal chain",
        "causal_hops",
        (
            "hop",
            "cause_event_id",
            "cause_resource_ref",
            "relationship",
            "effect_event_id",
            "effect_resource_ref",
            "lead_seconds",
            "confidence",
        ),
    ),
    (
        "contributing-factors",
        "Contributing factors",
        "rca_contributing_factors",
        (
            "category",
            "factor",
            "effect",
            "confidence",
            "evidence_ref",
        ),
    ),
    (
        "alternative-hypotheses",
        "Alternative hypotheses and exclusion rationale",
        "rca_alternative_hypotheses",
        (
            "hypothesis",
            "status",
            "support",
            "contradiction",
            "reason",
            "evidence_refs",
        ),
    ),
    (
        "grounded-citations",
        "Grounded evidence register",
        "citations",
        (
            "tier",
            "kind",
            "ref",
            "summary",
            "source_at",
            "freshness",
            "recorded_at",
        ),
    ),
    (
        "response-plan",
        "Response and remediation history",
        "response",
        (
            "action_kind",
            "decision",
            "outcome",
            "mode",
            "rollback_reference",
            "actor",
            "recorded_at",
        ),
    ),
    (
        "recovery-validation",
        "Recovery validation",
        "rca_recovery_validation",
        (
            "metric",
            "before",
            "after",
            "target",
            "status",
            "evidence_ref",
        ),
    ),
    (
        "control-gaps",
        "Control-gap analysis",
        "rca_control_gaps",
        (
            "control",
            "expected",
            "observed",
            "gap",
            "evidence_ref",
        ),
    ),
    (
        "recommendations",
        "Corrective and preventive actions",
        "rca_recommendations",
        (
            "priority",
            "action",
            "owner_role",
            "due",
            "verification",
            "status",
            "evidence_refs",
        ),
    ),
    (
        "limitations",
        "Limitations and unknowns",
        "rca_limitations",
        (
            "limitation",
            "effect",
            "next_evidence",
            "status",
        ),
    ),
    (
        "audit-chronology",
        "Append-only audit chronology",
        "audit",
        (
            "seq",
            "recorded_at",
            "actor",
            "action_kind",
            "mode",
            "entry_hash",
        ),
    ),
)

__all__ = ["REPORT_DESCRIPTION", "REPORT_ID", "REPORT_NAME", "REPORT_TAGS", "TABLE_SPECS"]
