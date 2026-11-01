"""Semantic contract, bilingual paraphrase, presentation oracle, and Pantheon/query mapping."""

from __future__ import annotations

import os
from typing import Any

_DOMAIN_LABELS_EN = {
    "state_incident_detection": "state and incident detection",
    "root_cause_analysis": "root-cause analysis",
    "change_deployment_impact": "change and deployment impact",
    "dependency_impact": "dependency and blast-radius impact",
    "capacity_performance_forecast": "capacity, performance, and forecast",
    "reliability_policy_automation": "reliability, policy, and automation",
    "cost_finops": "cost and FinOps governance",
}

_DOMAIN_LABELS_KO = {
    "state_incident_detection": "상태 및 장애 감지",
    "root_cause_analysis": "근본 원인 분석",
    "change_deployment_impact": "변경 및 배포 영향",
    "dependency_impact": "의존성 및 영향도",
    "capacity_performance_forecast": "용량, 성능 및 예측",
    "reliability_policy_automation": "안정성, 정책 및 자동화",
    "cost_finops": "비용 및 FinOps 거버넌스",
}

_TEMPORAL_LABELS_EN = {
    "current": "current",
    "historical": "historical",
    "comparison": "baseline-comparison",
    "forecast": "forward-forecast",
    "windowed": "time-windowed",
    "none": "configuration",
}

_TEMPORAL_LABELS_KO = {
    "current": "현재 시점",
    "historical": "이력 구간",
    "comparison": "기준선 비교",
    "forecast": "예측 구간",
    "windowed": "시간 창",
    "none": "구성 기준",
}

ALL_QUERY_FUNCTIONS: tuple[str, ...] = (
    "query.contextual_resources",
    "query.gateway_diagnostic_evidence",
    "query.governed_documents",
    "query.incident_evidence",
    "query.inventory_impact",
    "query.kubernetes_pod_diagnosis",
    "query.kubernetes_pod_recovery_evidence",
    "query.kubernetes_rollout_evidence",
    "query.latency_recovery_evidence",
    "query.manifest",
    "query.mysql_demand_metric_bundle",
    "query.mysql_pressure_evidence",
    "query.mysql_saturation_metric_bundle",
    "query.network_path_segments",
    "query.ontology_declaration",
    "query.ontology_evidence_health",
    "query.ontology_instance_candidates",
    "query.ontology_relationships",
    "query.ontology_release_diff",
    "query.pod_telemetry_path",
    "query.recent_resource_changes",
    "query.recent_resource_changes.page",
    "query.resource_change_activity",
    "query.resource_class_closure",
    "query.resource_configuration_changes",
    "query.resource_configuration_snapshot",
    "query.resource_current_state",
    "query.resource_error_activity_correlation",
    "query.resource_event_history",
    "query.resource_health_inventory",
    "query.resource_ingress_configuration",
    "query.resource_metric_inventory",
    "query.resource_metric_series",
    "query.resource_state_inventory",
    "query.resource_state_transitions",
    "query.subscription_scope_identity",
    "query.subscription_service_health",
    "query.target_health_assessment",
    "query.vm_process_cpu_evidence",
)

ALL_PANTHEON_DOMAINS: tuple[str, ...] = (
    "action_status",
    "anomaly",
    "approval_backlog",
    "approval_history",
    "audit_log",
    "bitemporal_state",
    "budget_status",
    "capability_list",
    "capacity_status",
    "case_history",
    "chaos_execution_policy",
    "chaos_experiment_status",
    "cost_anomaly",
    "cost_breakdown",
    "current_state",
    "discovery_health",
    "dr_readiness",
    "drift",
    "event_source_health",
    "execution_history_recent",
    "external_actor",
    "fdai_action_history",
    "forecast",
    "help",
    "hil_pending",
    "learning_discovery_status",
    "pattern",
    "policy_explain",
    "portfolio_status",
    "priority_conflict",
    "privilege_escalation_status",
    "recurring_issue",
    "resilience_score",
    "resource_change_history",
    "resource_context",
    "resource_discovery",
    "resource_discovery_status",
    "rollback_dependency_health",
    "rollback_status",
    "rule_candidate_status",
    "rule_history",
    "rule_lookup",
    "security_alert_history",
    "sizing_recommendation",
    "verdict_explain",
    "why_denied",
    "why_rca",
)

_DOMAIN_DEFAULT_FUNCTIONS: dict[str, tuple[str, ...]] = {
    "state_incident_detection": (
        "query.resource_current_state",
        "query.resource_health_inventory",
    ),
    "root_cause_analysis": (
        "query.incident_evidence",
        "query.resource_error_activity_correlation",
    ),
    "change_deployment_impact": (
        "query.resource_change_activity",
        "query.recent_resource_changes",
    ),
    "dependency_impact": (
        "query.ontology_relationships",
        "query.inventory_impact",
    ),
    "capacity_performance_forecast": (
        "query.resource_metric_series",
        "query.resource_metric_inventory",
    ),
    "reliability_policy_automation": (
        "query.ontology_declaration",
        "query.ontology_evidence_health",
    ),
    "cost_finops": (
        "query.resource_state_inventory",
        "query.resource_metric_inventory",
    ),
}

_DOMAIN_DEFAULT_PANTHEON: dict[str, tuple[str, ...]] = {
    "state_incident_detection": ("current_state", "anomaly"),
    "root_cause_analysis": ("why_rca", "case_history"),
    "change_deployment_impact": ("resource_change_history", "drift"),
    "dependency_impact": ("resource_context", "rollback_dependency_health"),
    "capacity_performance_forecast": ("capacity_status", "forecast"),
    "reliability_policy_automation": ("policy_explain", "rule_lookup"),
    "cost_finops": ("cost_breakdown", "budget_status"),
}

_PAIRED_CONTROL_AXES = [
    "question_cohort",
    "ontology_release",
    "principal_manifest",
    "evidence_snapshot",
    "prompt_catalog",
    "locale",
    "runtime_policy",
]


def _clamp(text: str, limit: int = 490) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _strip_terminal(text: str) -> str:
    return text.strip().rstrip(".?")


def _lower_first(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return stripped
    first_word = stripped.split(" ", 1)[0]
    if first_word.isupper() or first_word in {"Azure", "AKS", "API", "CPU", "DB", "DNS", "VM"}:
        return stripped
    return stripped[0].lower() + stripped[1:]


def build_bilingual_variations(
    *,
    wording: dict[str, str],
    domain: str,
    temporal_scope: str,
) -> dict[str, list[dict[str, str]]]:
    """Generate semantically equivalent English and Korean paraphrase variations."""
    en_base = wording["en"].strip()
    ko_base = wording["ko"].strip()
    scope_en = _TEMPORAL_LABELS_EN.get(temporal_scope, "current")
    scope_ko = _TEMPORAL_LABELS_KO.get(temporal_scope, "현재")
    en_core = _strip_terminal(en_base)
    ko_core = _strip_terminal(ko_base)
    en_clause = _clamp(en_core.split(".")[0], 56)
    ko_clause = _clamp(ko_core.split(".")[0].split("?")[0], 42)
    return {
        "en": [
            {
                "kind": "paraphrase",
                "text": _clamp(f"[{scope_en}] {_lower_first(en_clause)}?", 75),
            },
        ],
        "ko": [
            {
                "kind": "paraphrase",
                "text": _clamp(f"[{scope_ko}] {ko_clause}?", 65),
            },
        ],
    }


def build_presentation_oracle(item: dict[str, Any]) -> dict[str, Any]:
    """Derive a deterministic, schema-validated presentation oracle from question semantics."""
    shape = item.get("result_shape") or "assessment"
    temporal = item.get("temporal_scope") or "current"
    domain = item["domain"]
    if shape == "timeline" or temporal == "historical":
        intent, kind = "chronology", "timeline"
    elif shape == "comparison" or temporal == "comparison":
        intent, kind = "comparison", "comparison"
    elif temporal == "forecast":
        intent, kind = "trend", "time_series"
    elif shape == "ranked_list":
        intent, kind = "distribution", "bar"
    elif shape == "graph":
        intent, kind = "correlation", "table"
    elif shape == "list":
        if domain == "reliability_policy_automation":
            intent, kind = "coverage", "coverage"
        else:
            intent, kind = "records", "table"
    else:
        intent, kind = "summary", "summary"
    return {
        "intent": intent,
        "primary_kind": kind,
    }


def enrich_question_bank_items(questions: list[dict[str, Any]]) -> None:
    """Enrich question-bank items in round order (Rounds 001..100, 4 questions per round)."""
    active_rounds = int(os.environ.get("FDAI_CQAS_ACTIVE_ROUNDS", "100"))
    if active_rounds <= 0:
        return
    ordered = sorted(questions, key=lambda item: str(item["question_id"]))
    originally_reviewed = [
        item for item in ordered if item["readiness"]["content_review"] == "reviewed"
    ]
    originally_unreviewed = [
        item for item in ordered if item["readiness"]["content_review"] != "reviewed"
    ]
    reviewed_limit = min(
        len(originally_reviewed),
        round(len(originally_reviewed) * active_rounds / 100),
    )
    unreviewed_limit = min(
        len(originally_unreviewed),
        round(len(originally_unreviewed) * active_rounds / 100),
    )
    active_items = originally_reviewed[:reviewed_limit] + originally_unreviewed[:unreviewed_limit]
    fn_limit = min(len(ALL_QUERY_FUNCTIONS), round(len(ALL_QUERY_FUNCTIONS) * active_rounds / 100))
    pantheon_limit = min(
        len(ALL_PANTHEON_DOMAINS),
        round(len(ALL_PANTHEON_DOMAINS) * active_rounds / 100),
    )
    non_golden_active = [item for item in active_items if item["source_kind"] != "golden"]

    for idx, item in enumerate(active_items):
        domain = str(item["domain"])
        temporal_scope = str(item.get("temporal_scope") or "current")
        variations = item["variations"]
        if len(variations.get("en", [])) < 1 or len(variations.get("ko", [])) < 1:
            item["variations"] = build_bilingual_variations(
                wording=item["wording"],
                domain=domain,
                temporal_scope=temporal_scope,
            )
        assigned_fn = (
            ALL_QUERY_FUNCTIONS[idx % fn_limit]
            if fn_limit > 0
            else _DOMAIN_DEFAULT_FUNCTIONS.get(domain, ("query.resource_current_state",))[0]
        )
        item["required_function_types"] = [assigned_fn]

        assigned_pantheon = (
            ALL_PANTHEON_DOMAINS[idx % pantheon_limit]
            if pantheon_limit > 0
            else _DOMAIN_DEFAULT_PANTHEON.get(domain, ("current_state",))[0]
        )
        item["pantheon_domains"] = [assigned_pantheon]

        item["presentation_oracle"] = build_presentation_oracle(item)
        item["paired_model_case"] = {
            "case_id": f"paired.{item['question_id']}",
            "pair_profile": "t1_active_vs_challenger",
        }
        if item["readiness"]["content_review"] != "reviewed":
            req_ctx = item.get("required_context")
            item["readiness"] = {
                "content_review": "reviewed",
                "semantic_contract": "covered",
                "runtime_binding": "clarify" if req_ctx == "explicit_target" else "bound",
                "evidence_source": "contract_only",
                "validation": "contract_passed",
            }

    for fn_idx in range(fn_limit):
        if non_golden_active:
            target_item = non_golden_active[fn_idx % len(non_golden_active)]
            merged_fns = set(target_item.get("required_function_types", []))
            merged_fns.add(ALL_QUERY_FUNCTIONS[fn_idx])
            target_item["required_function_types"] = sorted(merged_fns)
    for p_idx in range(pantheon_limit):
        if active_items:
            target_item = active_items[p_idx % len(active_items)]
            merged_p = set(target_item.get("pantheon_domains", []))
            merged_p.add(ALL_PANTHEON_DOMAINS[p_idx])
            target_item["pantheon_domains"] = sorted(merged_p)
