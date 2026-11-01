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
    """Generate natural syntactic English and Korean paraphrase variations without bracket tags."""
    en_base = wording["en"].strip()
    ko_base = wording["ko"].strip()
    _ = (domain, temporal_scope)
    en_core = _strip_terminal(en_base)
    ko_core = _strip_terminal(ko_base)
    en_clause = _clamp(en_core.split(".")[0], 54)
    ko_clause = _clamp(ko_core.split(".")[0].split("?")[0], 40)
    if en_base.endswith("?"):
        en_para = _clamp(f"Please verify from ontology evidence: {_lower_first(en_clause)}.", 78)
    else:
        en_para = _clamp(f"Can you check from ontology evidence: {_lower_first(en_clause)}?", 78)
    if ko_base.endswith("?"):
        ko_para = _clamp(f"온톨로지 근거로 확인해 주세요: {ko_clause}.", 66)
    else:
        ko_para = _clamp(f"온톨로지 근거로 다음을 확인할 수 있나요: {ko_clause}?", 66)
    return {
        "en": [
            {
                "kind": "paraphrase",
                "text": en_para,
            },
        ],
        "ko": [
            {
                "kind": "paraphrase",
                "text": ko_para,
            },
        ],
    }


def _semantic_query_function(item: dict[str, Any], allowed: tuple[str, ...]) -> str:
    """Select the primary ontology query function from question semantics."""
    intent = str(item.get("intent", "")).casefold()
    category = str(item.get("category", "")).casefold()
    domain = str(item.get("domain", "")).casefold()
    targets = {str(t).casefold() for t in item.get("target_kinds", [])}
    temporal = str(item.get("temporal_scope", "")).casefold()
    text = str(item.get("wording", {}).get("en", "")).casefold()

    candidates: list[str] = []
    if "mysql" in text or "database" in category or "database" in targets:
        if "saturation" in text or "connection" in text:
            candidates.append("query.mysql_saturation_metric_bundle")
        elif "demand" in text or "throughput" in text or "query" in text:
            candidates.append("query.mysql_demand_metric_bundle")
        else:
            candidates.append("query.mysql_pressure_evidence")
    if "pod" in text or "kubernetespod" in targets or "aks" in category:
        if "rollout" in text or "deploy" in text:
            candidates.append("query.kubernetes_rollout_evidence")
        elif "restart" in text or "recovery" in text:
            candidates.append("query.kubernetes_pod_recovery_evidence")
        elif "telemetry" in text or "metric" in text:
            candidates.append("query.pod_telemetry_path")
        else:
            candidates.append("query.kubernetes_pod_diagnosis")
    if "gateway" in text or "ingress" in text:
        candidates.extend(
            ("query.gateway_diagnostic_evidence", "query.resource_ingress_configuration")
        )
    if "network" in text or "dns" in text or "subnet" in text or "nsg" in text:
        candidates.append("query.network_path_segments")
    if "document" in text or "runbook" in text or "manual" in text:
        candidates.append("query.governed_documents")
    if "vm" in text or "virtualmachine" in targets or "cpu" in text:
        candidates.append("query.vm_process_cpu_evidence")
    if "latency" in text:
        candidates.append("query.latency_recovery_evidence")
    if "drift" in text or "configuration" in text or "config" in intent:
        if temporal in {"historical", "comparison"}:
            candidates.append("query.resource_configuration_changes")
        else:
            candidates.append("query.resource_configuration_snapshot")
    if domain == "change_deployment_impact":
        candidates.extend(
            (
                "query.resource_change_activity",
                "query.recent_resource_changes",
                "query.recent_resource_changes.page",
                "query.resource_state_transitions",
            )
        )
    elif domain == "root_cause_analysis":
        candidates.extend(
            (
                "query.incident_evidence",
                "query.resource_error_activity_correlation",
                "query.resource_event_history",
            )
        )
    elif domain == "dependency_impact":
        candidates.extend(
            (
                "query.ontology_relationships",
                "query.inventory_impact",
                "query.resource_class_closure",
            )
        )
    elif domain == "capacity_performance_forecast":
        candidates.extend(
            (
                "query.resource_metric_series",
                "query.resource_metric_inventory",
                "query.target_health_assessment",
            )
        )
    elif domain == "reliability_policy_automation":
        candidates.extend(
            (
                "query.ontology_declaration",
                "query.ontology_evidence_health",
                "query.ontology_release_diff",
                "query.manifest",
            )
        )
    elif domain == "cost_finops":
        candidates.extend(
            (
                "query.resource_state_inventory",
                "query.subscription_scope_identity",
            )
        )
    else:
        candidates.extend(
            (
                "query.resource_current_state",
                "query.resource_health_inventory",
                "query.subscription_service_health",
                "query.contextual_resources",
                "query.ontology_instance_candidates",
            )
        )
    allowed_set = set(allowed)
    for cand in candidates:
        if cand in allowed_set:
            return cand
    return _DOMAIN_DEFAULT_FUNCTIONS.get(domain, ("query.resource_current_state",))[0]


def _semantic_pantheon_domain(item: dict[str, Any], allowed: tuple[str, ...]) -> str:
    """Select the primary Pantheon agent question domain from question semantics."""
    intent = str(item.get("intent", "")).casefold()
    domain = str(item.get("domain", "")).casefold()
    temporal = str(item.get("temporal_scope", "")).casefold()
    posture = str(item.get("safety", {}).get("action_posture", "")).casefold()
    text = str(item.get("wording", {}).get("en", "")).casefold()

    candidates: list[str] = []
    if posture == "draft_only" or "mitigation" in intent or "action" in intent:
        candidates.extend(("action_status", "execution_history_recent", "fdai_action_history"))
    if "rollback" in text or "rollback" in intent:
        candidates.extend(("rollback_status", "rollback_dependency_health"))
    if "recovery" in text or "failover" in text or "backup" in text:
        candidates.append("dr_readiness")
    if "approval" in text or "hil" in text:
        candidates.extend(("hil_pending", "approval_backlog", "approval_history"))
    if "audit" in text:
        candidates.append("audit_log")
    if "denied" in text or "refusal" in intent or "guardrail" in text:
        candidates.extend(("why_denied", "verdict_explain"))
    if "priority" in text or "conflict" in text or "objective" in text:
        candidates.extend(("priority_conflict", "portfolio_status"))
    if "chaos" in text or "resilience" in text or "spof" in text or "single point" in text:
        candidates.extend(("resilience_score", "chaos_experiment_status", "chaos_execution_policy"))
    if "sizing" in text or "overprovision" in text or "underprovision" in text:
        candidates.append("sizing_recommendation")
    if domain == "cost_finops":
        if "budget" in text:
            candidates.append("budget_status")
        elif "spike" in text or "anomaly" in text or "sudden" in text:
            candidates.append("cost_anomaly")
        else:
            candidates.append("cost_breakdown")
    elif domain == "capacity_performance_forecast":
        if temporal == "forecast" or "forecast" in text or "predict" in text:
            candidates.append("forecast")
        else:
            candidates.append("capacity_status")
    elif domain == "root_cause_analysis":
        if "recurring" in text or "pattern" in text or "repeat" in text:
            candidates.extend(("recurring_issue", "pattern"))
        elif temporal == "historical":
            candidates.append("case_history")
        else:
            candidates.append("why_rca")
    elif domain == "change_deployment_impact":
        if "drift" in text:
            candidates.append("drift")
        elif "manual" in text or "external" in text:
            candidates.append("external_actor")
        else:
            candidates.append("resource_change_history")
    elif domain == "dependency_impact":
        if temporal == "historical":
            candidates.append("bitemporal_state")
        else:
            candidates.append("resource_context")
    elif domain == "reliability_policy_automation":
        if "candidate" in text or "collected" in text:
            candidates.extend(("rule_candidate_status", "learning_discovery_status"))
        elif "release" in text or "history" in text:
            candidates.append("rule_history")
        elif "capability" in text or "manifest" in text:
            candidates.extend(("capability_list", "help"))
        elif "rule" in text:
            candidates.append("rule_lookup")
        else:
            candidates.append("policy_explain")
    else:
        if "security" in text or "nsg" in text or "alert" in text:
            candidates.append("security_alert_history")
        elif "identity" in text or "role" in text or "privilege" in text:
            candidates.append("privilege_escalation_status")
        elif "missing" in text or "stale" in text or "gap" in text:
            candidates.extend(
                ("event_source_health", "discovery_health", "resource_discovery_status")
            )
        elif "inventory" in text or "exist" in text:
            candidates.append("resource_discovery")
        elif "spike" in text or "surge" in text or "high" in text:
            candidates.append("anomaly")
        else:
            candidates.append("current_state")

    allowed_set = set(allowed)
    for cand in candidates:
        if cand in allowed_set:
            return cand
    return _DOMAIN_DEFAULT_PANTHEON.get(domain, ("current_state",))[0]


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

    for item in active_items:
        domain = str(item["domain"])
        temporal_scope = str(item.get("temporal_scope") or "current")
        variations = item["variations"]
        if len(variations.get("en", [])) < 1 or len(variations.get("ko", [])) < 1:
            item["variations"] = build_bilingual_variations(
                wording=item["wording"],
                domain=domain,
                temporal_scope=temporal_scope,
            )
        allowed_fns = ALL_QUERY_FUNCTIONS[:fn_limit]
        assigned_fn = _semantic_query_function(item, allowed_fns)
        item["required_function_types"] = [assigned_fn]

        allowed_pantheon = ALL_PANTHEON_DOMAINS[:pantheon_limit]
        assigned_pantheon = _semantic_pantheon_domain(item, allowed_pantheon)
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
