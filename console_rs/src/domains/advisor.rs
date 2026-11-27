//! Advisor & Well-Architected Posture Pure-Rust API + legacy `/advisor/*` redirects.
//!
//! Serves `/api/v4/advisor/*` for in-place integration across the existing 8 domains
//! (65 panels) without adding any separate top-level rail menu.

use axum::{
    extract::{Path as AxumPath, Query, State},
    http::{header, HeaderMap, HeaderValue, StatusCode},
    response::{IntoResponse, Redirect, Response},
    routing::{get, post},
    Json, Router,
};
use serde::Deserialize;
use serde_json::{json, Value};

use crate::{
    domains::settings::is_valid_iana_timezone,
    repos::advisor::{
        self as adv_repo, AdvisorAlertItem, AdvisorConfigState, AdvisorDigestItem,
        EvaluatedRuleSummary, FORMULA_VERSION,
    },
    AppState,
};

const MAX_AUTH_HEADER_BYTES: usize = 4096;
const MAX_RESOURCE_IDS: usize = 100;
const MAX_IQL_LEN: usize = 512;
const MAX_CHANNELS: usize = 8;
const ALLOWED_ALERT_SIGNALS: [&str; 5] = [
    "new_recommendation",
    "score_regression",
    "retirement_approaching",
    "postpone_expired",
    "waste_threshold",
];
const ALLOWED_PILLARS: [&str; 6] = [
    "all",
    "cost",
    "security",
    "reliability",
    "operational_excellence",
    "performance",
];
const ALLOWED_IMPACTS: [&str; 4] = ["all", "high", "medium", "low"];
const ALLOWED_DIGEST_FREQS: [&str; 4] = ["weekly", "biweekly", "monthly", "custom_cron"];
const ALLOWED_DIGEST_LOCALES: [&str; 2] = ["ko", "en"];
const ALLOWED_DIGEST_PERSONAS: [&str; 3] = ["executive", "engineering", "finops"];
const ALLOWED_ASSESS_FRAMEWORKS: [&str; 5] = [
    "azure-wara",
    "azure-waf",
    "azure-mcsb",
    "azure-caf",
    "finops",
];

fn is_safe_rule_id(rule_id: &str) -> bool {
    !rule_id.is_empty()
        && rule_id.len() <= 160
        && rule_id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.' | ':'))
}

fn has_control_chars(s: &str) -> bool {
    s.chars().any(|c| c.is_control() && c != '\n')
}

fn extract_auth(headers: &HeaderMap) -> Option<String> {
    headers
        .get(header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok())
        .map(str::trim)
        .filter(|s| !s.is_empty() && s.len() <= MAX_AUTH_HEADER_BYTES)
        .map(ToString::to_string)
}

pub fn router() -> Router<AppState> {
    Router::new()
        // Permanent redirects from legacy standalone /advisor/* routes to native integrated panels
        .route("/advisor", get(|| async { Redirect::permanent("/overview/dashboard") }))
        .route("/advisor/overview", get(|| async { Redirect::permanent("/overview/dashboard") }))
        .route("/advisor/score", get(|| async { Redirect::permanent("/overview/verticals") }))
        .route("/advisor/recommendations", get(|| async { Redirect::permanent("/governance/rules") }))
        .route("/advisor/retirements", get(|| async { Redirect::permanent("/governance/rules?advisor_view=retirements") }))
        .route("/advisor/assessments", get(|| async { Redirect::permanent("/governance/rules?advisor_view=assessments") }))
        .route("/advisor/workbooks", get(|| async { Redirect::permanent("/governance/ontology") }))
        .route("/advisor/alerts", get(|| async { Redirect::permanent("/operations/alert-quality") }))
        .route("/advisor/digests", get(|| async { Redirect::permanent("/evidence/reports") }))
        .route("/advisor/config", get(|| async { Redirect::permanent("/settings/runtime") }))
        .route("/api/v4/advisor/overview", get(api_advisor_overview))
        .route("/api/v4/advisor/score", get(api_advisor_score))
        .route(
            "/api/v4/advisor/recommendations",
            get(api_advisor_recommendations),
        )
        .route(
            "/api/v4/advisor/recommendations/{rule_id}",
            get(api_advisor_recommendation_detail),
        )
        .route(
            "/api/v4/advisor/recommendations/{rule_id}/disposition",
            post(api_advisor_disposition),
        )
        .route(
            "/api/v4/advisor/recommendations/{rule_id}/review-fix",
            post(api_advisor_review_fix),
        )
        .route(
            "/api/v4/advisor/recommendations/{rule_id}/feedback",
            post(api_advisor_feedback),
        )
        .route("/api/v4/advisor/retirements", get(api_advisor_retirements))
        .route(
            "/api/v4/advisor/assessments",
            get(api_advisor_assessments).post(api_advisor_create_assessment),
        )
        .route("/api/v4/advisor/workbooks", get(api_advisor_workbooks))
        .route(
            "/api/v4/advisor/workbooks/query",
            post(api_advisor_workbook_query),
        )
        .route(
            "/api/v4/advisor/alerts",
            get(api_advisor_alerts).post(api_advisor_upsert_alert),
        )
        .route(
            "/api/v4/advisor/alerts/batch",
            post(api_advisor_batch_alerts),
        )
        .route(
            "/api/v4/advisor/digests",
            get(api_advisor_digests).post(api_advisor_upsert_digest),
        )
        .route(
            "/api/v4/advisor/digests/batch",
            post(api_advisor_batch_digests),
        )
        .route(
            "/api/v4/advisor/config",
            get(api_advisor_config).post(api_advisor_update_config),
        )
        .route("/api/v4/advisor/export", get(api_advisor_export))
}

fn json_no_store(status: StatusCode, payload: Value) -> Response {
    (
        status,
        [
            (header::CACHE_CONTROL, HeaderValue::from_static("no-store")),
            (
                header::X_CONTENT_TYPE_OPTIONS,
                HeaderValue::from_static("nosniff"),
            ),
            (header::VARY, HeaderValue::from_static("Authorization")),
        ],
        Json(payload),
    )
        .into_response()
}

#[derive(Debug, Default, Deserialize)]
struct ScopeQuery {
    rg: Option<String>,
    ri_term: Option<String>,
    ri_lookback: Option<u32>,
    refresh: Option<String>,
}

#[derive(Debug, Default, Deserialize)]
struct RecsQuery {
    rg: Option<String>,
    pillar: Option<String>,
    viewing: Option<String>,
    subcategory: Option<String>,
    impact: Option<String>,
    resource_type: Option<String>,
    search: Option<String>,
    sort: Option<String>,
    ri_term: Option<String>,
    ri_lookback: Option<u32>,
    refresh: Option<String>,
}

fn is_refresh_requested(flag: Option<&str>) -> bool {
    matches!(flag, Some("1") | Some("true") | Some("yes"))
}

fn summarize_rule_for_list(r: &EvaluatedRuleSummary) -> Value {
    json!({
        "id": r.id,
        "pillar": r.pillar,
        "pillar_label_ko": adv_repo::pillar_meta(&r.pillar).0,
        "subcategory": r.subcategory,
        "title_ko": r.title_ko,
        "title_en": r.title_en,
        "impact": r.impact,
        "owner_agent": r.owner_agent,
        "action_type_ref": r.action_type_ref,
        "action_label_ko": r.action_label_ko,
        "automation_mode": r.automation_mode,
        "risk_tier": r.risk_tier,
        "downtime_class": r.downtime_class,
        "waf_ref": r.waf_ref,
        "cost_implication_tier": r.cost_implication_tier,
        "cost_factors": r.cost_factors,
        "pricing_basis": r.pricing_basis,
        "estimate_basis": r.estimate_basis,
        "target_resource_label_ko": r.target_resource_label_ko,
        "retirement_date": r.retirement_date,
        "retirement_days_left": r.retirement_days_left,
        "replacement_target": r.replacement_target,
        "active_count": r.active_count,
        "completed_count": r.completed_count,
        "postponed_count": r.postponed_count,
        "dismissed_count": r.dismissed_count,
        "total_evaluated": r.total_evaluated,
        "completion_pct": r.completion_pct,
        "potential_score_increase_pct": r.potential_score_increase_pct,
        "total_yearly_savings_usd": r.total_yearly_savings_usd,
        "total_yearly_carbon_kg_co2e": r.total_yearly_carbon_kg_co2e,
        "last_refreshed_at": r.last_refreshed_at,
        "cluster_hints": r.cluster_hints,
        "resource_types": r.instances.iter().map(|i| i.resource_type.as_str()).collect::<std::collections::BTreeSet<_>>().into_iter().collect::<Vec<_>>()
    })
}

async fn api_advisor_overview(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<ScopeQuery>,
) -> Response {
    let _auth = extract_auth(&headers);
    let force_refresh = is_refresh_requested(q.refresh.as_deref());
    let snap = adv_repo::evaluate_live(
        &state.db,
        q.rg.as_deref(),
        q.ri_term.as_deref(),
        q.ri_lookback,
        force_refresh,
    )
    .await;

    let mut quick_wins: Vec<Value> = snap
        .rules
        .iter()
        .filter(|r| r.active_count > 0)
        .filter(|r| {
            r.cost_implication_tier == "no_cost_impact"
                || r.total_yearly_savings_usd > 0.0
                || r.risk_tier == "A0"
                || r.risk_tier == "A1"
        })
        .map(summarize_rule_for_list)
        .collect();
    quick_wins.sort_by(|a, b| {
        let sa = a
            .get("potential_score_increase_pct")
            .and_then(Value::as_f64)
            .unwrap_or(0.0)
            + a.get("total_yearly_savings_usd")
                .and_then(Value::as_f64)
                .unwrap_or(0.0)
                / 500.0;
        let sb = b
            .get("potential_score_increase_pct")
            .and_then(Value::as_f64)
            .unwrap_or(0.0)
            + b.get("total_yearly_savings_usd")
                .and_then(Value::as_f64)
                .unwrap_or(0.0)
                / 500.0;
        sb.partial_cmp(&sa).unwrap_or(std::cmp::Ordering::Equal)
    });
    quick_wins.truncate(4);

    let total_active_recs = snap.rules.iter().filter(|r| r.active_count > 0).count();
    let total_active_res: usize = snap.rules.iter().map(|r| r.active_count).sum();
    let total_eval_res: usize = snap.rules.iter().map(|r| r.total_evaluated).sum();
    let total_yearly_savings: f64 = snap.rules.iter().map(|r| r.total_yearly_savings_usd).sum();
    let total_yearly_carbon: f64 = snap
        .rules
        .iter()
        .map(|r| r.total_yearly_carbon_kg_co2e)
        .sum();
    let retirement_count = snap
        .rules
        .iter()
        .filter(|r| r.retirement_date.is_some() && r.active_count > 0)
        .count();

    let pillars_ordered = [
        "cost",
        "security",
        "reliability",
        "operational_excellence",
        "performance",
    ]
    .iter()
    .filter_map(|p| snap.pillar_scores.get(*p).cloned())
    .collect::<Vec<_>>();

    // Honest Service Health state: never fabricate region outage events without live Service Health collector rows.
    let service_health_events: Vec<Value> = Vec::new();
    let service_health_status = json!({
        "state": "not-measured",
        "reason": "azure_service_health_collector_not_bound",
        "message": "Azure Service Health 실시간 수집기 미연결 — 미수집 상태에서는 장애 이벤트를 합성 표시하지 않습니다."
    });

    json_no_store(
        StatusCode::OK,
        json!({
            "measured": snap.measured,
            "data_state": if snap.measured { "measured" } else { "not-measured" },
            "reason": snap.reason,
            "source": "postgres_live_ontology_t0",
            "formula_version": FORMULA_VERSION,
            "snapshot_id": snap.snapshot_id,
            "observed_at": snap.observed_at,
            "cache_age_seconds": snap.cache_age_seconds,
            "freshness_contract": "Huginn 실시간 인벤토리 스냅샷 + T0 결정론적 즉시 평가 (Azure 기본 48~72시간 배치 지연 제거)",
            "overall_score_pct": snap.overall_score_pct,
            "summary": {
                "total_inventory_resources": snap.total_inventory_resources,
                "excluded_resources_count": snap.excluded_resources_count,
                "active_recommendations": total_active_recs,
                "total_rules_evaluated": snap.rules.len(),
                "active_resource_findings": total_active_res,
                "evaluated_resource_checks": total_eval_res,
                "total_yearly_savings_usd": total_yearly_savings.round(),
                "savings_estimate_basis": "sku_heuristic_estimate",
                "total_yearly_carbon_kg_co2e": (total_yearly_carbon * 100.0).round() / 100.0,
                "active_retirements": retirement_count,
            },
            "pillars": pillars_ordered,
            "quick_wins": quick_wins,
            "service_health_events": service_health_events,
            "service_health_status": service_health_status,
            "resource_groups": snap.resource_groups,
            "config": snap.config,
        }),
    )
}

async fn api_advisor_score(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<ScopeQuery>,
) -> Response {
    let _auth = extract_auth(&headers);
    let force_refresh = is_refresh_requested(q.refresh.as_deref());
    let snap = adv_repo::evaluate_live(
        &state.db,
        q.rg.as_deref(),
        q.ri_term.as_deref(),
        q.ri_lookback,
        force_refresh,
    )
    .await;

    let mut ranked: Vec<Value> = snap
        .rules
        .iter()
        .filter(|r| r.active_count > 0)
        .map(summarize_rule_for_list)
        .collect();
    ranked.sort_by(|a, b| {
        let sa = a
            .get("potential_score_increase_pct")
            .and_then(Value::as_f64)
            .unwrap_or(0.0);
        let sb = b
            .get("potential_score_increase_pct")
            .and_then(Value::as_f64)
            .unwrap_or(0.0);
        sb.partial_cmp(&sa).unwrap_or(std::cmp::Ordering::Equal)
    });

    // Honest history series: emit ONLY measured current snapshot anchor (never synthesize fake past days).
    let history = if let Some(curr) = snap.overall_score_pct {
        let rel = snap
            .pillar_scores
            .get("reliability")
            .and_then(|v| v.get("score_pct"))
            .and_then(Value::as_f64);
        let cost = snap
            .pillar_scores
            .get("cost")
            .and_then(|v| v.get("score_pct"))
            .and_then(Value::as_f64);
        let sec = snap
            .pillar_scores
            .get("security")
            .and_then(|v| v.get("score_pct"))
            .and_then(Value::as_f64);
        vec![json!({
            "label": "현재 실측 스냅샷",
            "timestamp": snap.observed_at,
            "overall": curr,
            "reliability": rel,
            "cost": cost,
            "security": sec,
            "anchored_live": true,
            "change_event": snap.audit_changes.first().cloned(),
        })]
    } else {
        Vec::new()
    };

    let pillars_ordered: Vec<Value> = [
        "cost",
        "security",
        "reliability",
        "operational_excellence",
        "performance",
    ]
    .iter()
    .filter_map(|p| snap.pillar_scores.get(*p).cloned())
    .collect();

    json_no_store(
        StatusCode::OK,
        json!({
            "measured": snap.measured,
            "data_state": if snap.measured { "measured" } else { "not-measured" },
            "reason": snap.reason,
            "formula_version": FORMULA_VERSION,
            "observed_at": snap.observed_at,
            "cache_age_seconds": snap.cache_age_seconds,
            "overall_score_pct": snap.overall_score_pct,
            "pillars": pillars_ordered,
            "ranked_recommendations": ranked,
            "history": history,
            "history_state": if history.is_empty() { "not-measured" } else { "single_measured_anchor" },
            "history_notice": "과거 일별 AdvisorScoreSnapshot 원장이 누적되기 전까지 합성 과거 추세를 위조하지 않고 실측 현재 스냅샷만 표시합니다.",
            "audit_changes": snap.audit_changes.iter().take(10).cloned().collect::<Vec<_>>(),
            "formula_transparency": {
                "version": FORMULA_VERSION,
                "weights": { "high": 3.0, "medium": 2.0, "low": 1.0 },
                "rule": "각 필러 점수 = (영향도 가중 준수 리소스 합 ÷ 영향도 가중 평가 대상 리소스 합) × 100. 미측정 필러는 0%로 위조하지 않고 종합 평균에서 제외합니다.",
                "excluded_resources_count": snap.excluded_resources_count,
                "disposition_policy": "Postponed는 분모에 유지(만료 시 자동 복귀), Dismissed(예외 승인)는 분모에서 제외, Manually Completed는 재검증 전까지 임시 준수로 집계됩니다."
            },
            "resource_groups": snap.resource_groups,
        }),
    )
}

async fn api_advisor_recommendations(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<RecsQuery>,
) -> Response {
    let _auth = extract_auth(&headers);
    let force_refresh = is_refresh_requested(q.refresh.as_deref());
    let snap = adv_repo::evaluate_live(
        &state.db,
        q.rg.as_deref(),
        q.ri_term.as_deref(),
        q.ri_lookback,
        force_refresh,
    )
    .await;

    let pillar_f = q.pillar.as_deref().unwrap_or("all").to_ascii_lowercase();
    let viewing_f = q.viewing.as_deref().unwrap_or("active").to_ascii_lowercase();
    let subcat_f = q
        .subcategory
        .as_deref()
        .unwrap_or("all")
        .to_ascii_lowercase();
    let impact_f = q.impact.as_deref().unwrap_or("all").to_ascii_lowercase();
    let rtype_f = q
        .resource_type
        .as_deref()
        .unwrap_or("all")
        .to_ascii_lowercase();
    let search_f = q.search.as_deref().unwrap_or("").trim().to_ascii_lowercase();

    let mut items: Vec<Value> = Vec::new();
    let mut subcats: std::collections::BTreeSet<String> = std::collections::BTreeSet::new();

    for r in &snap.rules {
        if pillar_f != "all" && r.pillar != pillar_f {
            continue;
        }
        subcats.insert(r.subcategory.clone());
        if subcat_f != "all" && r.subcategory != subcat_f {
            continue;
        }
        if impact_f != "all" && r.impact != impact_f {
            continue;
        }
        if rtype_f != "all"
            && !r
                .instances
                .iter()
                .any(|i| i.resource_type.eq_ignore_ascii_case(&rtype_f))
        {
            continue;
        }
        if !search_f.is_empty() {
            let hay = format!(
                "{} {} {} {} {} {}",
                r.id, r.title_ko, r.title_en, r.subcategory, r.waf_ref, r.owner_agent
            )
            .to_ascii_lowercase();
            let res_match = r.instances.iter().any(|i| {
                i.resource_name.to_ascii_lowercase().contains(&search_f)
                    || i.resource_group.to_ascii_lowercase().contains(&search_f)
            });
            if !hay.contains(&search_f) && !res_match {
                continue;
            }
        }
        let matches_viewing = match viewing_f.as_str() {
            "active" => r.active_count > 0,
            "completed" => r.completed_count > 0,
            "postponed" => r.postponed_count > 0,
            "dismissed" => r.dismissed_count > 0,
            _ => r.total_evaluated > 0 || r.dismissed_count > 0,
        };
        if !matches_viewing {
            continue;
        }
        items.push(summarize_rule_for_list(r));
    }

    let sort_f = q.sort.as_deref().unwrap_or("score_desc").to_ascii_lowercase();
    match sort_f.as_str() {
        "savings_desc" => items.sort_by(|a, b| {
            b.get("total_yearly_savings_usd")
                .and_then(Value::as_f64)
                .unwrap_or(0.0)
                .partial_cmp(
                    &a.get("total_yearly_savings_usd")
                        .and_then(Value::as_f64)
                        .unwrap_or(0.0),
                )
                .unwrap_or(std::cmp::Ordering::Equal)
        }),
        "active_desc" => items.sort_by(|a, b| {
            b.get("active_count")
                .and_then(Value::as_u64)
                .unwrap_or(0)
                .cmp(&a.get("active_count").and_then(Value::as_u64).unwrap_or(0))
        }),
        "completion_asc" => items.sort_by(|a, b| {
            a.get("completion_pct")
                .and_then(Value::as_f64)
                .unwrap_or(0.0)
                .partial_cmp(
                    &b.get("completion_pct")
                        .and_then(Value::as_f64)
                        .unwrap_or(0.0),
                )
                .unwrap_or(std::cmp::Ordering::Equal)
        }),
        "impact_desc" => {
            let rank = |v: &Value| match v.get("impact").and_then(Value::as_str).unwrap_or("low") {
                "high" => 3,
                "medium" => 2,
                _ => 1,
            };
            items.sort_by(|a, b| rank(b).cmp(&rank(a)));
        }
        _ => items.sort_by(|a, b| {
            b.get("potential_score_increase_pct")
                .and_then(Value::as_f64)
                .unwrap_or(0.0)
                .partial_cmp(
                    &a.get("potential_score_increase_pct")
                        .and_then(Value::as_f64)
                        .unwrap_or(0.0),
                )
                .unwrap_or(std::cmp::Ordering::Equal)
        }),
    }

    let active_res_sum: usize = items
        .iter()
        .filter_map(|v| v.get("active_count").and_then(Value::as_u64))
        .map(|n| n as usize)
        .sum();
    let eval_res_sum: usize = items
        .iter()
        .filter_map(|v| v.get("total_evaluated").and_then(Value::as_u64))
        .map(|n| n as usize)
        .sum();
    let savings_sum: f64 = items
        .iter()
        .filter_map(|v| v.get("total_yearly_savings_usd").and_then(Value::as_f64))
        .sum();
    let carbon_sum: f64 = items
        .iter()
        .filter_map(|v| v.get("total_yearly_carbon_kg_co2e").and_then(Value::as_f64))
        .sum();

    json_no_store(
        StatusCode::OK,
        json!({
            "measured": snap.measured,
            "data_state": if snap.measured { "measured" } else { "not-measured" },
            "reason": snap.reason,
            "observed_at": snap.observed_at,
            "filters": {
                "pillar": pillar_f,
                "viewing": viewing_f,
                "subcategory": subcat_f,
                "impact": impact_f,
                "resource_type": rtype_f,
                "ri_term": q.ri_term.unwrap_or_else(|| snap.config.ri_term.clone()),
                "ri_lookback": q.ri_lookback.unwrap_or(snap.config.lookback_days),
            },
            "kpi": {
                "matching_recommendations": items.len(),
                "active_resources": active_res_sum,
                "evaluated_resources": eval_res_sum,
                "active_ratio_pct": if eval_res_sum > 0 { ((active_res_sum as f64 / eval_res_sum as f64) * 1000.0).round() / 10.0 } else { 0.0 },
                "total_yearly_savings_usd": savings_sum.round(),
                "total_yearly_carbon_kg_co2e": (carbon_sum * 100.0).round() / 100.0,
            },
            "subcategories": subcats.into_iter().collect::<Vec<_>>(),
            "resource_groups": snap.resource_groups,
            "resource_types": snap.resource_types,
            "items": items,
        }),
    )
}

async fn api_advisor_recommendation_detail(
    State(state): State<AppState>,
    headers: HeaderMap,
    AxumPath(rule_id): AxumPath<String>,
    Query(q): Query<ScopeQuery>,
) -> Response {
    let _auth = extract_auth(&headers);
    if !is_safe_rule_id(&rule_id) {
        return json_no_store(StatusCode::BAD_REQUEST, json!({ "error": "invalid_rule_id" }));
    }
    let snap = adv_repo::evaluate_live(
        &state.db,
        q.rg.as_deref(),
        q.ri_term.as_deref(),
        q.ri_lookback,
        is_refresh_requested(q.refresh.as_deref()),
    )
    .await;
    if !snap.measured {
        return json_no_store(
            StatusCode::OK,
            json!({
                "measured": false,
                "data_state": "not-measured",
                "reason": snap.reason,
                "rule_id": rule_id
            }),
        );
    }
    let Some(rule) = snap.rules.iter().find(|r| r.id == rule_id) else {
        return json_no_store(
            StatusCode::NOT_FOUND,
            json!({ "error": "recommendation_not_found", "rule_id": rule_id }),
        );
    };
    json_no_store(
        StatusCode::OK,
        json!({
            "measured": true,
            "data_state": "measured",
            "observed_at": snap.observed_at,
            "cache_age_seconds": snap.cache_age_seconds,
            "rule": rule,
            "tabs": {
                "active": rule.active_count,
                "completed": rule.completed_count,
                "postponed": rule.postponed_count,
                "dismissed": rule.dismissed_count,
            }
        }),
    )
}

#[derive(Debug, Deserialize)]
struct DispositionReq {
    resource_ids: Vec<String>,
    action: String,
    #[serde(default)]
    reason: String,
    postpone_days: Option<u64>,
}

async fn api_advisor_disposition(
    headers: HeaderMap,
    AxumPath(rule_id): AxumPath<String>,
    Json(body): Json<DispositionReq>,
) -> Response {
    let _auth = extract_auth(&headers);
    if !is_safe_rule_id(&rule_id) {
        return json_no_store(StatusCode::BAD_REQUEST, json!({ "error": "invalid_rule_id" }));
    }
    if body.resource_ids.is_empty() || body.resource_ids.len() > MAX_RESOURCE_IDS {
        return json_no_store(
            StatusCode::BAD_REQUEST,
            json!({ "error": "resource_ids count must be between 1 and 100" }),
        );
    }
    if has_control_chars(&body.reason) {
        return json_no_store(
            StatusCode::BAD_REQUEST,
            json!({ "error": "invalid_control_characters" }),
        );
    }
    match adv_repo::apply_disposition(
        &rule_id,
        &body.resource_ids,
        &body.action,
        &body.reason,
        body.postpone_days,
    ) {
        Ok(val) => json_no_store(StatusCode::OK, val),
        Err(msg) => json_no_store(StatusCode::BAD_REQUEST, json!({ "error": msg })),
    }
}

#[derive(Debug, Default, Deserialize)]
struct ReviewFixReq {
    #[serde(default)]
    resource_ids: Vec<String>,
}

async fn api_advisor_review_fix(
    State(state): State<AppState>,
    headers: HeaderMap,
    AxumPath(rule_id): AxumPath<String>,
    Json(body): Json<ReviewFixReq>,
) -> Response {
    let _auth = extract_auth(&headers);
    if !is_safe_rule_id(&rule_id) {
        return json_no_store(StatusCode::BAD_REQUEST, json!({ "error": "invalid_rule_id" }));
    }
    if body.resource_ids.len() > MAX_RESOURCE_IDS {
        return json_no_store(
            StatusCode::BAD_REQUEST,
            json!({ "error": "resource_ids_exceeded" }),
        );
    }
    let snap = adv_repo::evaluate_live(&state.db, None, None, None, false).await;
    if !snap.measured {
        return json_no_store(
            StatusCode::OK,
            json!({ "measured": false, "data_state": "not-measured", "reason": snap.reason }),
        );
    }
    let Some(rule) = snap.rules.iter().find(|r| r.id == rule_id) else {
        return json_no_store(
            StatusCode::NOT_FOUND,
            json!({ "error": "recommendation_not_found", "rule_id": rule_id }),
        );
    };
    json_no_store(
        StatusCode::OK,
        adv_repo::build_review_fix_plan(rule, &body.resource_ids),
    )
}

#[derive(Debug, Deserialize)]
struct FeedbackReq {
    helpful: bool,
    #[serde(default)]
    reason: String,
}

async fn api_advisor_feedback(
    headers: HeaderMap,
    AxumPath(rule_id): AxumPath<String>,
    Json(body): Json<FeedbackReq>,
) -> Response {
    let _auth = extract_auth(&headers);
    if !is_safe_rule_id(&rule_id) || has_control_chars(&body.reason) {
        return json_no_store(StatusCode::BAD_REQUEST, json!({ "error": "invalid_input" }));
    }
    match adv_repo::record_feedback(&rule_id, body.helpful, &body.reason) {
        Ok(v) => json_no_store(StatusCode::OK, v),
        Err(msg) => json_no_store(StatusCode::BAD_REQUEST, json!({ "error": msg })),
    }
}

async fn api_advisor_retirements(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<ScopeQuery>,
) -> Response {
    let _auth = extract_auth(&headers);
    let snap = adv_repo::evaluate_live(
        &state.db,
        q.rg.as_deref(),
        None,
        None,
        is_refresh_requested(q.refresh.as_deref()),
    )
    .await;
    let mut items: Vec<Value> = snap
        .rules
        .iter()
        .filter(|r| r.retirement_date.is_some())
        .map(summarize_rule_for_list)
        .collect();
    items.sort_by_key(|v| {
        v.get("retirement_days_left")
            .and_then(Value::as_i64)
            .unwrap_or(9999)
    });
    let urgent = items
        .iter()
        .filter(|v| {
            v.get("retirement_days_left")
                .and_then(Value::as_i64)
                .is_some_and(|d| d <= 45)
                && v.get("active_count").and_then(Value::as_u64).unwrap_or(0) > 0
        })
        .count();
    let impacted_total: usize = items
        .iter()
        .filter_map(|v| v.get("active_count").and_then(Value::as_u64))
        .map(|n| n as usize)
        .sum();
    json_no_store(
        StatusCode::OK,
        json!({
            "measured": snap.measured,
            "data_state": if snap.measured { "measured" } else { "not-measured" },
            "observed_at": snap.observed_at,
            "summary": {
                "total_retirements": items.len(),
                "urgent_within_45d": urgent,
                "impacted_resources": impacted_total,
            },
            "items": items,
        }),
    )
}

async fn api_advisor_assessments(State(state): State<AppState>, headers: HeaderMap) -> Response {
    let _auth = extract_auth(&headers);
    let snap = adv_repo::evaluate_live(&state.db, None, None, None, false).await;
    let list = adv_repo::list_assessments();
    let in_prog = list.iter().filter(|a| a.status == "in_progress").count();
    let completed = list.iter().filter(|a| a.status == "completed").count();
    json_no_store(
        StatusCode::OK,
        json!({
            "measured": snap.measured,
            "data_state": if snap.measured { "measured" } else { "not-measured" },
            "observed_at": snap.observed_at,
            "summary": {
                "total_assessments": list.len(),
                "in_progress": in_prog,
                "completed": completed,
                "wara_catalog_checks": 393,
                "waf_best_practices": 59,
            },
            "items": list,
        }),
    )
}

#[derive(Debug, Deserialize)]
struct CreateAssessmentReq {
    name: String,
    framework: String,
    workload: String,
}

async fn api_advisor_create_assessment(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(body): Json<CreateAssessmentReq>,
) -> Response {
    let _auth = extract_auth(&headers);
    let name = body.name.trim();
    let framework = body.framework.trim();
    let workload = body.workload.trim();
    if name.is_empty() || name.len() > 160 || workload.is_empty() || workload.len() > 160 || has_control_chars(name) {
        return json_no_store(
            StatusCode::BAD_REQUEST,
            json!({ "error": "invalid assessment name or workload" }),
        );
    }
    if !ALLOWED_ASSESS_FRAMEWORKS.contains(&framework) {
        return json_no_store(
            StatusCode::BAD_REQUEST,
            json!({ "error": "unsupported assessment framework" }),
        );
    }
    let snap = adv_repo::evaluate_live(&state.db, None, None, None, false).await;
    match adv_repo::create_assessment(
        name.to_string(),
        framework.to_string(),
        workload.to_string(),
        &snap,
    ) {
        Ok(created) => json_no_store(
            StatusCode::CREATED,
            json!({
                "ok": true,
                "persisted": false,
                "persistence_mode": "session_overlay",
                "item": created
            }),
        ),
        Err(msg) => json_no_store(StatusCode::TOO_MANY_REQUESTS, json!({ "error": msg })),
    }
}

async fn api_advisor_workbooks(State(state): State<AppState>, headers: HeaderMap) -> Response {
    let _auth = extract_auth(&headers);
    let snap = adv_repo::evaluate_live(&state.db, None, None, None, false).await;
    let templates = vec![
        json!({
            "id": "wb-reliability-az",
            "category": "Azure Advisor",
            "title": "Reliability & Availability Zones 워크북",
            "description": "워크로드·리소스 유형별 가용성 영역 적용률, SPOF, WARA 393 준수 현황을 추적합니다.",
            "default_iql": "pillar == 'reliability' | sort active_count desc",
            "badge": "내장 템플릿"
        }),
        json!({
            "id": "wb-service-retirement",
            "category": "Azure Advisor",
            "title": "Service & API Retirement 워크북",
            "description": "은퇴 예정 서비스/API(Key Vault API, Logs Ingestion DCR, Basic SKU)의 D-day와 영향 리소스를 집계합니다.",
            "default_iql": "subcategory == 'service_retirement' | sort retirement_days_left asc",
            "badge": "내장 템플릿"
        }),
        json!({
            "id": "wb-cost-carbon",
            "category": "Azure Advisor",
            "title": "Cost Optimization & GreenOps 탄소 워크북",
            "description": "연간 절감액(Contractual/Retail), RI/Savings Plan, 고아 리소스, 탄소 감축량(kgCO2e)을 통합 분석합니다.",
            "default_iql": "pillar == 'cost' | sort total_yearly_savings_usd desc",
            "badge": "내장 템플릿"
        }),
        json!({
            "id": "wb-cross-pillar-tradeoff",
            "category": "FDAI Ontology",
            "title": "Cross-Pillar Trade-off & Odin 중재 워크북",
            "description": "비용 영향이 없는(No Cost Impact) 고효율 신뢰성·보안·성능 개선 항목을 최우선 선별합니다.",
            "default_iql": "cost_implication_tier == 'no_cost_impact' | sort potential_score_increase_pct desc",
            "badge": "온톨로지 특화"
        }),
        json!({
            "id": "wb-security-hardening",
            "category": "FDAI Ontology",
            "title": "Security & Zero-Trust 하드닝 워크북",
            "description": "Key Vault Purge Protection, Storage TLS/Public Access, VM 암호화/MI, NSG 갭을 추적합니다.",
            "default_iql": "pillar == 'security' | sort active_count desc",
            "badge": "온톨로지 특화"
        }),
        json!({
            "id": "wb-agent-automation",
            "category": "FDAI Agentic",
            "title": "에이전트 자동화 · Fix PR 준비도 워크북",
            "description": "A0/A1 저위험 또는 IaC Fix PR 자동 생성이 가능한 권장사항을 선별해 즉시 실행 후보를 집계합니다.",
            "default_iql": "automation_mode == 'fix_pr' | sort potential_score_increase_pct desc",
            "badge": "에이전트 특화"
        }),
    ];
    json_no_store(
        StatusCode::OK,
        json!({
            "measured": snap.measured,
            "data_state": if snap.measured { "measured" } else { "not-measured" },
            "observed_at": snap.observed_at,
            "templates": templates,
        }),
    )
}

#[derive(Debug, Deserialize)]
struct WorkbookQueryReq {
    iql: String,
}

fn evaluate_iql_predicates(r: &EvaluatedRuleSummary, raw_filter: &str) -> bool {
    let filter_part = raw_filter.split('|').next().unwrap_or("").trim();
    if filter_part.is_empty() || filter_part == "*" || filter_part == "all" {
        return true;
    }
    for clause in filter_part.split(" and ") {
        let c = clause.trim();
        if c.is_empty() {
            continue;
        }
        let matched = if let Some((lhs, rhs)) = c.split_once("!=") {
            let k = lhs.trim();
            let v = rhs.trim().trim_matches('\'').trim_matches('"');
            match k {
                "pillar" => r.pillar != v,
                "impact" => r.impact != v,
                "subcategory" => r.subcategory != v,
                "owner_agent" => !r.owner_agent.eq_ignore_ascii_case(v),
                "automation_mode" => r.automation_mode != v,
                "cost_implication_tier" => r.cost_implication_tier != v,
                _ => true,
            }
        } else if let Some((lhs, rhs)) = c.split_once("==") {
            let k = lhs.trim();
            let v = rhs.trim().trim_matches('\'').trim_matches('"');
            match k {
                "pillar" => r.pillar == v,
                "impact" => r.impact == v,
                "subcategory" => r.subcategory == v,
                "owner_agent" => r.owner_agent.eq_ignore_ascii_case(v),
                "automation_mode" => r.automation_mode == v,
                "cost_implication_tier" => r.cost_implication_tier == v,
                "risk_tier" => r.risk_tier.eq_ignore_ascii_case(v),
                _ => false,
            }
        } else if let Some((lhs, rhs)) = c.split_once(">=") {
            let k = lhs.trim();
            let n: f64 = rhs.trim().parse().unwrap_or(0.0);
            match k {
                "active_count" => (r.active_count as f64) >= n,
                "potential_score_increase_pct" => r.potential_score_increase_pct >= n,
                "total_yearly_savings_usd" => r.total_yearly_savings_usd >= n,
                _ => false,
            }
        } else {
            let hay = format!(
                "{} {} {} {} {}",
                r.id, r.pillar, r.subcategory, r.title_ko, r.owner_agent
            )
            .to_ascii_lowercase();
            hay.contains(c)
        };
        if !matched {
            return false;
        }
    }
    true
}

async fn api_advisor_workbook_query(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(body): Json<WorkbookQueryReq>,
) -> Response {
    let _auth = extract_auth(&headers);
    if body.iql.len() > MAX_IQL_LEN || has_control_chars(&body.iql) {
        return json_no_store(
            StatusCode::BAD_REQUEST,
            json!({ "error": "iql_query_invalid_or_too_long" }),
        );
    }
    let snap = adv_repo::evaluate_live(&state.db, None, None, None, false).await;
    let q = body.iql.trim().to_ascii_lowercase();
    let mut rows: Vec<Value> = snap
        .rules
        .iter()
        .filter(|r| evaluate_iql_predicates(r, &q))
        .map(summarize_rule_for_list)
        .collect();

    if q.contains("savings") {
        rows.sort_by(|a, b| {
            b.get("total_yearly_savings_usd")
                .and_then(Value::as_f64)
                .unwrap_or(0.0)
                .partial_cmp(
                    &a.get("total_yearly_savings_usd")
                        .and_then(Value::as_f64)
                        .unwrap_or(0.0),
                )
                .unwrap_or(std::cmp::Ordering::Equal)
        });
    } else if q.contains("score") {
        rows.sort_by(|a, b| {
            b.get("potential_score_increase_pct")
                .and_then(Value::as_f64)
                .unwrap_or(0.0)
                .partial_cmp(
                    &a.get("potential_score_increase_pct")
                        .and_then(Value::as_f64)
                        .unwrap_or(0.0),
                )
                .unwrap_or(std::cmp::Ordering::Equal)
        });
    } else {
        rows.sort_by(|a, b| {
            b.get("active_count")
                .and_then(Value::as_u64)
                .unwrap_or(0)
                .cmp(&a.get("active_count").and_then(Value::as_u64).unwrap_or(0))
        });
    }

    json_no_store(
        StatusCode::OK,
        json!({
            "measured": snap.measured,
            "iql": body.iql,
            "row_count": rows.len(),
            "rows": rows,
        }),
    )
}

async fn api_advisor_alerts() -> Response {
    let items = adv_repo::list_alerts();
    json_no_store(
        StatusCode::OK,
        json!({
            "count": items.len(),
            "items": items
        }),
    )
}

#[derive(Debug, Deserialize)]
struct CreateAlertReq {
    name: String,
    #[serde(default)]
    description: String,
    signal: String,
    scope: String,
    category: String,
    subcategory: String,
    impact: String,
    rule_id: Option<String>,
    action_group: String,
    channels: Vec<String>,
    #[serde(default = "default_true")]
    steward_escalation: bool,
    #[serde(default = "default_true")]
    enabled: bool,
}

fn default_true() -> bool {
    true
}

async fn api_advisor_upsert_alert(
    headers: HeaderMap,
    Json(body): Json<CreateAlertReq>,
) -> Response {
    let _auth = extract_auth(&headers);
    let name = body.name.trim();
    if name.is_empty() || name.len() > 160 || has_control_chars(name) || has_control_chars(&body.description) {
        return json_no_store(
            StatusCode::BAD_REQUEST,
            json!({ "error": "invalid alert name or description" }),
        );
    }
    if !ALLOWED_ALERT_SIGNALS.contains(&body.signal.as_str()) {
        return json_no_store(StatusCode::BAD_REQUEST, json!({ "error": "invalid_alert_signal" }));
    }
    if !ALLOWED_PILLARS.contains(&body.category.as_str()) {
        return json_no_store(StatusCode::BAD_REQUEST, json!({ "error": "invalid_alert_category" }));
    }
    if !ALLOWED_IMPACTS.contains(&body.impact.as_str()) {
        return json_no_store(StatusCode::BAD_REQUEST, json!({ "error": "invalid_alert_impact" }));
    }
    if body.channels.len() > MAX_CHANNELS {
        return json_no_store(StatusCode::BAD_REQUEST, json!({ "error": "too_many_channels" }));
    }
    let clean_rule_id = body.rule_id.filter(|s| !s.trim().is_empty());
    if let Some(ref rid) = clean_rule_id {
        if !is_safe_rule_id(rid) {
            return json_no_store(StatusCode::BAD_REQUEST, json!({ "error": "invalid_rule_id" }));
        }
    }
    let item = AdvisorAlertItem {
        id: format!("adv-alert-{}", adv_repo::now_epoch_s()),
        name: name.to_string(),
        description: body.description.trim().chars().take(400).collect(),
        signal: body.signal,
        scope: body.scope.trim().chars().take(160).collect(),
        category: body.category,
        subcategory: body.subcategory.trim().chars().take(80).collect(),
        impact: body.impact,
        rule_id: clean_rule_id,
        action_group: body.action_group.trim().chars().take(120).collect(),
        channels: if body.channels.is_empty() {
            vec!["Email".to_string()]
        } else {
            body.channels
        },
        steward_escalation: body.steward_escalation,
        enabled: body.enabled,
        created_at: adv_repo::now_iso(),
    };
    match adv_repo::upsert_alert(item) {
        Ok(saved) => json_no_store(
            StatusCode::CREATED,
            json!({
                "ok": true,
                "persisted": false,
                "persistence_mode": "session_overlay",
                "item": saved
            }),
        ),
        Err(msg) => json_no_store(StatusCode::TOO_MANY_REQUESTS, json!({ "error": msg })),
    }
}

#[derive(Debug, Deserialize)]
struct BatchOpReq {
    ids: Vec<String>,
    op: String,
}

async fn api_advisor_batch_alerts(
    headers: HeaderMap,
    Json(body): Json<BatchOpReq>,
) -> Response {
    let _auth = extract_auth(&headers);
    if !matches!(body.op.as_str(), "enable" | "disable" | "delete") || body.ids.len() > MAX_RESOURCE_IDS {
        return json_no_store(StatusCode::BAD_REQUEST, json!({ "error": "invalid_batch_op" }));
    }
    let affected = adv_repo::mutate_alerts(&body.ids, &body.op);
    json_no_store(
        StatusCode::OK,
        json!({
            "ok": true,
            "persisted": false,
            "persistence_mode": "session_overlay",
            "op": body.op,
            "affected": affected
        }),
    )
}

async fn api_advisor_digests() -> Response {
    let items = adv_repo::list_digests();
    json_no_store(
        StatusCode::OK,
        json!({
            "count": items.len(),
            "items": items
        }),
    )
}

#[derive(Debug, Deserialize)]
struct CreateDigestReq {
    name: String,
    scope: String,
    categories: Vec<String>,
    frequency: String,
    #[serde(default)]
    cron_expression: String,
    timezone: String,
    locale: String,
    persona: String,
    channels: Vec<String>,
    #[serde(default = "default_true")]
    enabled: bool,
}

async fn api_advisor_upsert_digest(
    headers: HeaderMap,
    Json(body): Json<CreateDigestReq>,
) -> Response {
    let _auth = extract_auth(&headers);
    let name = body.name.trim();
    if name.is_empty() || name.len() > 160 || has_control_chars(name) {
        return json_no_store(
            StatusCode::BAD_REQUEST,
            json!({ "error": "digest name required" }),
        );
    }
    if !is_valid_iana_timezone(&body.timezone) {
        return json_no_store(
            StatusCode::BAD_REQUEST,
            json!({ "error": "invalid_iana_timezone" }),
        );
    }
    if !ALLOWED_DIGEST_FREQS.contains(&body.frequency.as_str())
        || !ALLOWED_DIGEST_LOCALES.contains(&body.locale.as_str())
        || !ALLOWED_DIGEST_PERSONAS.contains(&body.persona.as_str())
        || body.channels.len() > MAX_CHANNELS
    {
        return json_no_store(
            StatusCode::BAD_REQUEST,
            json!({ "error": "invalid_digest_parameters" }),
        );
    }
    let cron = if !body.cron_expression.trim().is_empty() {
        body.cron_expression.trim().chars().take(64).collect()
    } else {
        match body.frequency.as_str() {
            "biweekly" => "0 9 1,15 * *".to_string(),
            "monthly" => "0 9 1 * *".to_string(),
            _ => "0 9 * * 1".to_string(),
        }
    };
    let next_label = match body.frequency.as_str() {
        "biweekly" => format!("격주 1일·15일 09:00 ({})", body.timezone),
        "monthly" => format!("매월 1일 09:00 ({})", body.timezone),
        _ => format!("매주 월요일 09:00 ({})", body.timezone),
    };
    let item = AdvisorDigestItem {
        id: format!("adv-digest-{}", adv_repo::now_epoch_s()),
        name: name.to_string(),
        scope: body.scope.trim().chars().take(160).collect(),
        categories: body.categories,
        frequency: body.frequency,
        cron_expression: cron,
        timezone: body.timezone,
        locale: body.locale,
        persona: body.persona,
        channels: if body.channels.is_empty() {
            vec!["Email".to_string()]
        } else {
            body.channels
        },
        enabled: body.enabled,
        next_run_at: next_label,
    };
    match adv_repo::upsert_digest(item) {
        Ok(saved) => json_no_store(
            StatusCode::CREATED,
            json!({
                "ok": true,
                "persisted": false,
                "persistence_mode": "session_overlay",
                "item": saved
            }),
        ),
        Err(msg) => json_no_store(StatusCode::TOO_MANY_REQUESTS, json!({ "error": msg })),
    }
}

async fn api_advisor_batch_digests(
    headers: HeaderMap,
    Json(body): Json<BatchOpReq>,
) -> Response {
    let _auth = extract_auth(&headers);
    if !matches!(body.op.as_str(), "enable" | "disable" | "delete") || body.ids.len() > MAX_RESOURCE_IDS {
        return json_no_store(StatusCode::BAD_REQUEST, json!({ "error": "invalid_batch_op" }));
    }
    let affected = adv_repo::mutate_digests(&body.ids, &body.op);
    json_no_store(
        StatusCode::OK,
        json!({
            "ok": true,
            "persisted": false,
            "persistence_mode": "session_overlay",
            "op": body.op,
            "affected": affected
        }),
    )
}

async fn api_advisor_config(State(state): State<AppState>, headers: HeaderMap) -> Response {
    let _auth = extract_auth(&headers);
    let snap = adv_repo::evaluate_live(&state.db, None, None, None, false).await;
    json_no_store(
        StatusCode::OK,
        json!({
            "config": adv_repo::get_config(),
            "resource_groups": snap.resource_groups,
            "excluded_resources_count": snap.excluded_resources_count,
            "total_inventory_resources": snap.total_inventory_resources,
        }),
    )
}

async fn api_advisor_update_config(
    headers: HeaderMap,
    Json(body): Json<AdvisorConfigState>,
) -> Response {
    let _auth = extract_auth(&headers);
    match adv_repo::update_config(body) {
        Ok(saved) => json_no_store(
            StatusCode::OK,
            json!({
                "ok": true,
                "persisted": false,
                "persistence_mode": "session_overlay",
                "config": saved
            }),
        ),
        Err(msg) => json_no_store(StatusCode::BAD_REQUEST, json!({ "error": msg })),
    }
}

#[derive(Debug, Default, Deserialize)]
struct ExportQuery {
    format: Option<String>,
    pillar: Option<String>,
    rg: Option<String>,
}

fn csv_neutralize_formula(s: &str) -> String {
    let trimmed = s.trim_start();
    if trimmed.starts_with('=')
        || trimmed.starts_with('+')
        || trimmed.starts_with('-')
        || trimmed.starts_with('@')
        || s.starts_with('\t')
        || s.starts_with('\r')
    {
        format!("'{s}")
    } else {
        s.to_string()
    }
}

fn csv_escape(s: &str) -> String {
    let safe = csv_neutralize_formula(s);
    if safe.contains(',') || safe.contains('"') || safe.contains('\n') || safe.contains('\r') {
        format!("\"{}\"", safe.replace('"', "\"\""))
    } else {
        safe
    }
}

async fn api_advisor_export(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(q): Query<ExportQuery>,
) -> Response {
    let _auth = extract_auth(&headers);
    let snap = adv_repo::evaluate_live(&state.db, q.rg.as_deref(), None, None, false).await;
    let pillar_f = q.pillar.as_deref().unwrap_or("all").to_ascii_lowercase();
    let fmt = q.format.as_deref().unwrap_or("csv").to_ascii_lowercase();

    let rules: Vec<&EvaluatedRuleSummary> = snap
        .rules
        .iter()
        .filter(|r| pillar_f == "all" || r.pillar == pillar_f)
        .collect();

    if fmt == "json" {
        return (
            StatusCode::OK,
            [
                (
                    header::CONTENT_TYPE,
                    HeaderValue::from_static("application/json; charset=utf-8"),
                ),
                (
                    header::CONTENT_DISPOSITION,
                    HeaderValue::from_static("attachment; filename=\"fdai-advisor-report.json\""),
                ),
                (header::CACHE_CONTROL, HeaderValue::from_static("no-store")),
            ],
            serde_json::to_string_pretty(&json!({
                "formula_version": FORMULA_VERSION,
                "observed_at": snap.observed_at,
                "measured": snap.measured,
                "overall_score_pct": snap.overall_score_pct,
                "rules": rules.iter().map(|r| summarize_rule_for_list(r)).collect::<Vec<_>>()
            }))
            .unwrap_or_else(|_| "{}".to_string()),
        )
            .into_response();
    }

    let mut csv = String::from(
        "rule_id,pillar,subcategory,impact,title_ko,active_resources,evaluated_resources,completion_pct,potential_score_increase_pct,yearly_savings_usd,pricing_basis,carbon_kg_co2e,cost_implication,owner_agent,waf_ref,retirement_date\n",
    );
    for r in rules {
        csv.push_str(&format!(
            "{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{}\n",
            csv_escape(&r.id),
            csv_escape(&r.pillar),
            csv_escape(&r.subcategory),
            csv_escape(&r.impact),
            csv_escape(&r.title_ko),
            r.active_count,
            r.total_evaluated,
            r.completion_pct,
            r.potential_score_increase_pct,
            r.total_yearly_savings_usd,
            csv_escape(r.pricing_basis.as_deref().unwrap_or("-")),
            r.total_yearly_carbon_kg_co2e,
            csv_escape(&r.cost_implication_tier),
            csv_escape(&r.owner_agent),
            csv_escape(&r.waf_ref),
            csv_escape(r.retirement_date.as_deref().unwrap_or("-")),
        ));
    }

    (
        StatusCode::OK,
        [
            (
                header::CONTENT_TYPE,
                HeaderValue::from_static("text/csv; charset=utf-8"),
            ),
            (
                header::CONTENT_DISPOSITION,
                HeaderValue::from_static("attachment; filename=\"fdai-advisor-report.csv\""),
            ),
            (header::CACHE_CONTROL, HeaderValue::from_static("no-store")),
        ],
        csv,
    )
        .into_response()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::build_router;
    use axum::body::Body;
    use axum::http::Request;
    use http_body_util::BodyExt;
    use std::path::PathBuf;
    use tower::ServiceExt;

    fn test_app() -> Router {
        let state = AppState::from_repo_root(
            PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .parent()
                .unwrap()
                .to_path_buf(),
            "http://127.0.0.1:9".to_string(),
        );
        build_router(state)
    }

    #[tokio::test]
    async fn legacy_advisor_routes_redirect_308_to_native_existing_panels() {
        let app = test_app();
        for (src, dst) in [
            ("/advisor", "/overview/dashboard"),
            ("/advisor/overview", "/overview/dashboard"),
            ("/advisor/score", "/overview/verticals"),
            ("/advisor/recommendations", "/governance/rules"),
            ("/advisor/workbooks", "/governance/ontology"),
            ("/advisor/alerts", "/operations/alert-quality"),
            ("/advisor/digests", "/evidence/reports"),
            ("/advisor/config", "/settings/runtime"),
        ] {
            let resp = app
                .clone()
                .oneshot(Request::builder().uri(src).body(Body::empty()).unwrap())
                .await
                .unwrap();
            assert_eq!(resp.status(), StatusCode::PERMANENT_REDIRECT);
            let loc = resp
                .headers()
                .get(header::LOCATION)
                .and_then(|v| v.to_str().ok())
                .unwrap_or("");
            assert_eq!(loc, dst);
        }
    }

    #[tokio::test]
    async fn advisor_overview_honestly_reports_not_measured_when_db_unconfigured() {
        let app = test_app();
        let resp = app
            .oneshot(
                Request::builder()
                    .uri("/api/v4/advisor/overview")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(resp.status(), StatusCode::OK);
        let bytes = resp.into_body().collect().await.unwrap().to_bytes();
        let v: Value = serde_json::from_slice(&bytes).unwrap();
        assert_eq!(v["measured"], json!(false));
        assert_eq!(v["data_state"], json!("not-measured"));
        assert!(v["overall_score_pct"].is_null());
    }

    #[tokio::test]
    async fn advisor_disposition_and_feedback_and_config_endpoints_work() {
        let app = test_app();
        let disp = app
            .clone()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v4/advisor/recommendations/adv.rel.vm-availability-zones/disposition")
                    .header("content-type", "application/json")
                    .body(Body::from(
                        r#"{"resource_ids":["res-1"],"action":"postpone","reason":"다음 변경 창 적용","postpone_days":14}"#,
                    ))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(disp.status(), StatusCode::OK);
        let bytes = disp.into_body().collect().await.unwrap().to_bytes();
        let v: Value = serde_json::from_slice(&bytes).unwrap();
        assert_eq!(v["ok"], json!(true));
        assert_eq!(v["customer_state"], json!("postponed"));

        let cfg_resp = app
            .clone()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v4/advisor/config")
                    .header("content-type", "application/json")
                    .body(Body::from(
                        r#"{"excluded_resource_groups":[],"low_cpu_threshold_p95":10,"lookback_days":30,"ri_term":"P1Y","min_monthly_savings_usd":0,"environment_profile":"balanced","updated_at":""}"#,
                    ))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(cfg_resp.status(), StatusCode::OK);

        // Restore default config after test
        let _ = adv_repo::update_config(AdvisorConfigState::default());
        let _ = adv_repo::apply_disposition(
            "adv.rel.vm-availability-zones",
            &["res-1".to_string()],
            "open",
            "",
            None,
        );
    }

    #[tokio::test]
    async fn advisor_csv_export_returns_valid_header_and_neutralizes_formulas() {
        assert_eq!(csv_escape("=cmd|' /C calc'!A0"), "'=cmd|' /C calc'!A0");
        assert_eq!(csv_escape("+SUM(A1:A2)"), "'+SUM(A1:A2)");
        assert_eq!(csv_escape("@HYPERLINK"), "'@HYPERLINK");
        let app = test_app();
        let resp = app
            .oneshot(
                Request::builder()
                    .uri("/api/v4/advisor/export?format=csv")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(resp.status(), StatusCode::OK);
        let bytes = resp.into_body().collect().await.unwrap().to_bytes();
        let text = String::from_utf8(bytes.to_vec()).unwrap();
        assert!(text.starts_with("rule_id,pillar,subcategory,impact,title_ko,"));
    }

    #[tokio::test]
    async fn advisor_redteam_guards_reject_short_reason_bad_timezone_bad_signal_and_bad_rule_id() {
        let app = test_app();
        // Short dismiss reason -> 400
        let r1 = app
            .clone()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v4/advisor/recommendations/adv.rel.vm-availability-zones/disposition")
                    .header("content-type", "application/json")
                    .body(Body::from(
                        r#"{"resource_ids":["r1"],"action":"dismiss","reason":"short"}"#,
                    ))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(r1.status(), StatusCode::BAD_REQUEST);

        // Invalid IANA timezone on digest -> 400
        let r2 = app
            .clone()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v4/advisor/digests")
                    .header("content-type", "application/json")
                    .body(Body::from(
                        r#"{"name":"d1","scope":"all","categories":["cost"],"frequency":"weekly","timezone":"../etc/passwd","locale":"ko","persona":"executive","channels":["Email"]}"#,
                    ))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(r2.status(), StatusCode::BAD_REQUEST);

        // Invalid signal on alert -> 400
        let r3 = app
            .clone()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v4/advisor/alerts")
                    .header("content-type", "application/json")
                    .body(Body::from(
                        r#"{"name":"a1","signal":"evil_exec","scope":"all","category":"cost","subcategory":"all","impact":"high","action_group":"ag","channels":["Email"]}"#,
                    ))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(r3.status(), StatusCode::BAD_REQUEST);

        // Postponement expiration check
        assert!(!adv_repo::is_postponement_active(
            Some("2020-01-01T00:00:00Z"),
            "2026-11-27T00:00:00Z"
        ));
        assert!(adv_repo::is_postponement_active(
            Some("2030-01-01T00:00:00Z"),
            "2026-11-27T00:00:00Z"
        ));
    }
}
