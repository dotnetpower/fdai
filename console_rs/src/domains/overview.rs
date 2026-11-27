//! Domain 1: 전체 현황 (`overview`, 7 panels).
//! Owned by the `overview` domain stream.
//!
//! Pure-Rust Axum handlers for `/` and `/overview`, plus 8 JSON API endpoints:
//! - `/api/v4/overview/summary`
//! - `/api/v4/overview/dashboard`
//! - `/api/v4/overview/resources`
//! - `/api/v4/overview/outcomes`
//! - `/api/v4/overview/control-assurance`
//! - `/api/v4/overview/verticals`
//! - `/api/v4/overview/cost-governance`
//! - `/api/v4/overview/llm-cost`
//!
//! Preserves honest `not-measured` semantics: unreachable, unauthenticated, or
//! unconfigured upstream collectors never fabricate `0` values.

use axum::{
    extract::{Query, State},
    http::{header, HeaderMap, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    routing::get,
    Json, Router,
};
use serde::Deserialize;
use serde_json::{json, Value};

use crate::{
    repos::overview as overview_repo,
    shell::{finalize_v4_html, html_response},
    upstream::UpstreamOutcome,
    AppState,
};

const TEMPLATE: &str = include_str!("../../templates/overview.html");

const PANELS: [&str; 7] = [
    "dashboard",
    "dashboard-v2",
    "operating-outcomes",
    "control-assurance",
    "verticals",
    "cost-governance",
    "llm-cost",
];

const API_ENDPOINTS: [&str; 8] = [
    "/api/v4/overview/summary",
    "/api/v4/overview/dashboard",
    "/api/v4/overview/resources",
    "/api/v4/overview/outcomes",
    "/api/v4/overview/control-assurance",
    "/api/v4/overview/verticals",
    "/api/v4/overview/cost-governance",
    "/api/v4/overview/llm-cost",
];

pub fn panel_ids() -> &'static [&'static str] {
    &PANELS
}

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/", get(page_overview))
        .route("/overview", get(page_overview))
        .route("/api/v4/overview/summary", get(api_overview_summary))
        .route("/api/v4/overview/dashboard", get(api_overview_dashboard))
        .route("/api/v4/overview/resources", get(api_overview_resources))
        .route("/api/v4/overview/outcomes", get(api_overview_outcomes))
        .route(
            "/api/v4/overview/control-assurance",
            get(api_overview_control_assurance),
        )
        .route("/api/v4/overview/verticals", get(api_overview_verticals))
        .route(
            "/api/v4/overview/cost-governance",
            get(api_overview_cost_governance),
        )
        .route("/api/v4/overview/llm-cost", get(api_overview_llm_cost))
}

#[derive(Debug, Default, Deserialize)]
struct DashboardQuery {
    subscription: Option<String>,
    window: Option<String>,
}

#[derive(Debug, Default, Deserialize)]
struct ResourcesQuery {
    subscription: Option<String>,
    resource_type: Option<String>,
    status: Option<String>,
    search: Option<String>,
    lens: Option<String>,
    limit: Option<usize>,
    offset: Option<usize>,
}

#[derive(Debug, Default, Deserialize)]
struct OutcomesQuery {
    period: Option<String>,
    metric: Option<String>,
}

#[derive(Debug, Default, Deserialize)]
struct VerticalsQuery {
    period: Option<String>,
}

#[derive(Debug, Default, Deserialize)]
struct CostGovernanceQuery {
    surface: Option<String>,
    budget: Option<String>,
}

#[derive(Debug, Default, Deserialize)]
struct LlmCostQuery {
    range: Option<String>,
}

const MAX_AUTH_HEADER_BYTES: usize = 8192;

fn auth_header(headers: &HeaderMap) -> Option<&str> {
    let raw = headers
        .get(header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok())
        .map(str::trim)?;
    if raw.is_empty() || raw.len() > MAX_AUTH_HEADER_BYTES {
        return None;
    }
    if raw.chars().any(char::is_control) {
        return None;
    }
    let mut parts = raw.split_whitespace();
    let scheme = parts.next()?;
    let token = parts.next()?;
    if parts.next().is_some() {
        return None;
    }
    if !scheme.eq_ignore_ascii_case("bearer") || token.is_empty() {
        return None;
    }
    Some(raw)
}

fn sanitize_window(raw: Option<&str>) -> &'static str {
    match raw.map(str::trim) {
        Some("1h") => "1h",
        Some("24h") => "24h",
        _ => "15m",
    }
}

fn sanitize_period(raw: Option<&str>) -> &'static str {
    match raw.map(str::trim) {
        Some("1d") => "1d",
        Some("7d") => "7d",
        Some("90d") => "90d",
        _ => "30d",
    }
}

fn sanitize_llm_range(raw: Option<&str>) -> &'static str {
    match raw.map(str::trim) {
        Some("24h") => "24h",
        Some("7d") => "7d",
        _ => "30d",
    }
}

fn sanitize_outcome_metric(raw: Option<&str>) -> &'static str {
    match raw.map(str::trim) {
        Some("human-touchpoints") => "human-touchpoints",
        Some("mttr") => "mttr",
        Some("change-lead-time") => "change-lead-time",
        Some("cost-per-event") | Some("cost-per-resolved-event") => "cost-per-event",
        _ => "auto-resolution",
    }
}

fn sanitize_lens(raw: Option<&str>) -> &'static str {
    match raw.map(str::trim) {
        Some("operation") => "operation",
        Some("provisioning") => "provisioning",
        Some("serving") => "serving",
        Some("availability") => "availability",
        Some("observation") => "observation",
        _ => "resource",
    }
}

fn sanitize_cost_surface(raw: Option<&str>) -> (&'static str, &'static str) {
    match raw.map(str::trim) {
        Some("efficiency") | Some("resource-efficiency") => ("efficiency", "resource-efficiency"),
        Some("cases") | Some("optimization-cases") => ("cases", "optimization-cases"),
        Some("outcomes") => ("outcomes", "outcomes"),
        _ => ("overview", "overview"),
    }
}

fn sanitize_filter_token(raw: Option<&str>, fallback: &str) -> String {
    let Some(s) = raw else {
        return fallback.to_string();
    };
    let cleaned: String = s
        .trim()
        .chars()
        .filter(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.'))
        .take(64)
        .collect();
    if cleaned.is_empty() {
        fallback.to_string()
    } else {
        cleaned
    }
}

fn sanitize_search_query(raw: Option<&str>) -> Option<String> {
    let s = raw?.trim();
    if s.is_empty() {
        return None;
    }
    let cleaned: String = s
        .chars()
        .filter(|c| !c.is_control())
        .take(120)
        .collect();
    if cleaned.is_empty() {
        None
    } else {
        Some(cleaned)
    }
}

fn percent_encode_query(input: &str) -> String {
    let mut out = String::with_capacity(input.len());
    for byte in input.as_bytes() {
        let b = *byte;
        if b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b'.' | b'~') {
            out.push(char::from(b));
        } else {
            out.push('%');
            let hi = (b >> 4) & 0x0f;
            let lo = b & 0x0f;
            out.push(hex_nibble(hi));
            out.push(hex_nibble(lo));
        }
    }
    out
}

fn hex_nibble(n: u8) -> char {
    match n {
        0..=9 => char::from(b'0' + n),
        10..=15 => char::from(b'A' + (n - 10)),
        _ => '0',
    }
}

fn is_measured(out: &UpstreamOutcome) -> bool {
    out.reachable && out.status == 200 && out.payload.is_some()
}

fn source_record(path: &str, out: &UpstreamOutcome) -> Value {
    let state = if is_measured(out) {
        "measured"
    } else if !out.reachable {
        "offline"
    } else if out.status == 401 || out.status == 403 {
        "unauthenticated"
    } else {
        "unavailable"
    };
    json!({
        "path": path,
        "state": state,
        "reachable": out.reachable,
        "status": out.status,
    })
}

fn failure_reason(outcomes: &[(&str, &UpstreamOutcome)]) -> String {
    if outcomes.iter().any(|(_, o)| o.reachable && (o.status == 401 || o.status == 403)) {
        return "operator-service requires authentication (401/403)".to_string();
    }
    if outcomes.iter().all(|(_, o)| !o.reachable) {
        return "operator-service offline or unreachable".to_string();
    }
    let unavailable: Vec<&str> = outcomes
        .iter()
        .filter(|(_, o)| !is_measured(o))
        .map(|(p, _)| *p)
        .collect();
    if unavailable.is_empty() {
        "upstream data unavailable".to_string()
    } else {
        format!(
            "upstream collector unavailable for {}",
            unavailable.join(", ")
        )
    }
}

fn with_security_headers(mut resp: Response) -> Response {
    let headers = resp.headers_mut();
    headers.insert(
        header::CACHE_CONTROL,
        HeaderValue::from_static("no-store"),
    );
    headers.insert(
        header::X_CONTENT_TYPE_OPTIONS,
        HeaderValue::from_static("nosniff"),
    );
    headers.insert(
        header::X_FRAME_OPTIONS,
        HeaderValue::from_static("SAMEORIGIN"),
    );
    headers.insert(
        header::REFERRER_POLICY,
        HeaderValue::from_static("strict-origin-when-cross-origin"),
    );
    resp
}

fn json_ok_no_store(body: Value) -> Response {
    with_security_headers((StatusCode::OK, Json(body)).into_response())
}

fn summarize_upstream_status(sources: &[(&str, &UpstreamOutcome)]) -> (u16, bool, bool) {
    let upstream_reachable = sources.iter().any(|(_, o)| o.reachable);
    let auth_status = sources
        .iter()
        .find(|(_, o)| o.reachable && (o.status == 401 || o.status == 403))
        .map(|(_, o)| o.status);
    if let Some(st) = auth_status {
        return (st, true, true);
    }
    if let Some(st) = sources
        .iter()
        .find(|(_, o)| o.reachable && o.status != 200)
        .map(|(_, o)| o.status)
    {
        return (st, true, false);
    }
    if sources.iter().any(|(_, o)| is_measured(o)) {
        return (200, true, false);
    }
    (0, upstream_reachable, false)
}

fn build_envelope(
    state: &AppState,
    panel: &str,
    endpoint: &str,
    sources: &[(&str, &UpstreamOutcome)],
    data: Option<Value>,
    extra_not_measured_fields: &[&str],
) -> Response {
    let measured_count = sources.iter().filter(|(_, o)| is_measured(o)).count();
    let total_sources = sources.len();
    let (upstream_status, upstream_reachable, auth_required) = summarize_upstream_status(sources);
    let upstream_sources: Vec<Value> = sources
        .iter()
        .map(|(p, o)| source_record(p, o))
        .collect();

    if data.is_none() || measured_count == 0 {
        return json_ok_no_store(json!({
            "source": "console-v4-rust",
            "domain": "overview",
            "panel": panel,
            "endpoint": endpoint,
            "measurement_state": "not-measured",
            "measurement_status": "not-measured",
            "zero_substitution_forbidden": true,
            "upstream_url": state.upstream.base_url(),
            "upstream_status": upstream_status,
            "upstream_reachable": upstream_reachable,
            "auth_required": auth_required,
            "upstream_sources": upstream_sources,
            "not_measured_fields": extra_not_measured_fields,
            "reason": failure_reason(sources),
            "data": Value::Null,
        }));
    }

    let measurement_state =
        if measured_count == total_sources && extra_not_measured_fields.is_empty() {
            "measured"
        } else {
            "partial"
        };

    let reason = if measurement_state == "partial" {
        Some(failure_reason(sources))
    } else {
        None
    };

    json_ok_no_store(json!({
        "source": "operator-service",
        "domain": "overview",
        "panel": panel,
        "endpoint": endpoint,
        "measurement_state": measurement_state,
        "measurement_status": measurement_state,
        "zero_substitution_forbidden": true,
        "upstream_url": state.upstream.base_url(),
        "upstream_status": upstream_status,
        "upstream_reachable": upstream_reachable,
        "auth_required": auth_required,
        "upstream_sources": upstream_sources,
        "not_measured_fields": extra_not_measured_fields,
        "reason": reason,
        "data": data.unwrap_or(Value::Null),
    }))
}

fn should_fallback_to_db(state: &AppState, sources: &[(&str, &UpstreamOutcome)]) -> bool {
    if !state.db.is_configured() {
        return false;
    }
    if sources.iter().any(|(_, o)| is_measured(o)) {
        return false;
    }
    let (_, _, auth_required) = summarize_upstream_status(sources);
    !auth_required
}

fn build_db_envelope(
    state: &AppState,
    panel: &str,
    endpoint: &str,
    sources: &[(&str, &UpstreamOutcome)],
    repo_val: Value,
    db_not_measured_fields: &[&str],
    offline_not_measured_fields: &[&str],
) -> Response {
    let status = repo_val
        .get("measurement_status")
        .and_then(Value::as_str)
        .unwrap_or("not-measured");
    if status != "measured" {
        return build_envelope(
            state,
            panel,
            endpoint,
            sources,
            None,
            offline_not_measured_fields,
        );
    }

    let (upstream_status, upstream_reachable, auth_required) = summarize_upstream_status(sources);
    let upstream_sources: Vec<Value> = sources
        .iter()
        .map(|(p, o)| source_record(p, o))
        .collect();
    let data = repo_val.get("data").cloned().unwrap_or(repo_val);

    json_ok_no_store(json!({
        "source": "postgres-direct",
        "domain": "overview",
        "panel": panel,
        "endpoint": endpoint,
        "measurement_state": "measured",
        "measurement_status": "measured",
        "zero_substitution_forbidden": true,
        "upstream_url": state.upstream.base_url(),
        "upstream_status": upstream_status,
        "upstream_reachable": upstream_reachable,
        "auth_required": auth_required,
        "upstream_sources": upstream_sources,
        "not_measured_fields": db_not_measured_fields,
        "reason": Value::Null,
        "data": data,
    }))
}

fn value_u64(v: &Value, key: &str) -> Option<u64> {
    v.get(key).and_then(Value::as_u64)
}

fn value_f64(v: &Value, key: &str) -> Option<f64> {
    v.get(key).and_then(Value::as_f64)
}

async fn page_overview(State(state): State<AppState>) -> Response {
    let html = finalize_v4_html(
        TEMPLATE,
        "overview",
        "dashboard",
        &state.operator_url,
        json!({
            "panels": PANELS,
            "endpoints": API_ENDPOINTS,
        }),
    );
    with_security_headers(html_response(html))
}

async fn api_overview_summary(State(state): State<AppState>, headers: HeaderMap) -> Response {
    let auth = auth_header(&headers);
    let (kpi, resources, hil, incidents, data_sources) = tokio::join!(
        state.upstream.get_json("/kpi", auth),
        state
            .upstream
            .get_json("/ontology/instances/states?summary=count", auth),
        state.upstream.get_json("/hil-queue", auth),
        state.upstream.get_json("/incidents", auth),
        state.upstream.get_json("/system/data-sources", auth),
    );

    let sources = [
        ("/kpi", &kpi),
        ("/ontology/instances/states?summary=count", &resources),
        ("/hil-queue", &hil),
        ("/incidents", &incidents),
        ("/system/data-sources", &data_sources),
    ];

    let any_measured = sources.iter().any(|(_, o)| is_measured(o));
    if !any_measured {
        if should_fallback_to_db(&state, &sources) {
            let db_val = overview_repo::fetch_summary(&state.db).await;
            return build_db_envelope(
                &state,
                "summary",
                "/api/v4/overview/summary",
                &sources,
                db_val,
                &[],
                &[
                    "observed_resources",
                    "active_risks",
                    "human_review_pending",
                    "audit_events",
                ],
            );
        }
        return build_envelope(
            &state,
            "summary",
            "/api/v4/overview/summary",
            &sources,
            None,
            &[
                "observed_resources",
                "active_risks",
                "human_review_pending",
                "audit_events",
            ],
        );
    }

    let mut missing = Vec::new();
    let observed_resources = resources
        .payload
        .as_ref()
        .and_then(|v| value_u64(v, "total_count"));
    if observed_resources.is_none() {
        missing.push("observed_resources");
    }

    let audit_events = kpi
        .payload
        .as_ref()
        .and_then(|v| value_u64(v, "event_count"));
    if audit_events.is_none() {
        missing.push("audit_events");
    }

    let human_review_pending = hil
        .payload
        .as_ref()
        .and_then(|v| {
            value_u64(v, "total").or_else(|| {
                v.get("items")
                    .and_then(Value::as_array)
                    .map(|arr| arr.len() as u64)
            })
        })
        .or_else(|| {
            kpi.payload
                .as_ref()
                .and_then(|v| value_u64(v, "hil_pending"))
        });
    if human_review_pending.is_none() {
        missing.push("human_review_pending");
    }

    let active_risks = incidents.payload.as_ref().and_then(|v| {
        v.get("items")
            .and_then(Value::as_array)
            .map(|arr| arr.len() as u64)
    });
    if active_risks.is_none() {
        missing.push("active_risks");
    }

    let payload = json!({
        "observed_resources": observed_resources,
        "active_risks": active_risks,
        "human_review_pending": human_review_pending,
        "audit_events": audit_events,
        "shadow_share": kpi.payload.as_ref().and_then(|v| value_f64(v, "shadow_share")),
        "enforce_share": kpi.payload.as_ref().and_then(|v| value_f64(v, "enforce_share")),
        "last_recorded_at": kpi.payload.as_ref().and_then(|v| v.get("last_recorded_at").cloned()).unwrap_or(Value::Null),
        "kpi": kpi.payload.clone().unwrap_or(Value::Null),
        "data_sources": data_sources.payload.clone().unwrap_or(Value::Null),
    });

    build_envelope(
        &state,
        "summary",
        "/api/v4/overview/summary",
        &sources,
        Some(payload),
        &missing,
    )
}

async fn api_overview_dashboard(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(query): Query<DashboardQuery>,
) -> Response {
    let auth = auth_header(&headers);
    let window = sanitize_window(query.window.as_deref());
    let subscription = sanitize_filter_token(query.subscription.as_deref(), "all");

    let (kpi, incidents, hil, rules_summary, autonomy, gates) = tokio::join!(
        state.upstream.get_json("/kpi", auth),
        state.upstream.get_json("/incidents", auth),
        state.upstream.get_json("/hil-queue", auth),
        state.upstream.get_json("/rules/findings-summary", auth),
        state.upstream.get_json("/kpi/autonomy", auth),
        state.upstream.get_json("/kpi/promotion-gates", auth),
    );

    let sources = [
        ("/kpi", &kpi),
        ("/incidents", &incidents),
        ("/hil-queue", &hil),
        ("/rules/findings-summary", &rules_summary),
        ("/kpi/autonomy", &autonomy),
        ("/kpi/promotion-gates", &gates),
    ];

    if !sources.iter().any(|(_, o)| is_measured(o)) {
        if should_fallback_to_db(&state, &sources) {
            let db_val = overview_repo::fetch_dashboard(&state.db, &subscription, window).await;
            return build_db_envelope(
                &state,
                "dashboard",
                "/api/v4/overview/dashboard",
                &sources,
                db_val,
                &[],
                &["kpi", "incidents", "hil_queue", "routing", "posture"],
            );
        }
        return build_envelope(
            &state,
            "dashboard",
            "/api/v4/overview/dashboard",
            &sources,
            None,
            &["kpi", "incidents", "hil_queue", "routing", "posture"],
        );
    }

    let mut missing = Vec::new();
    if !is_measured(&kpi) {
        missing.push("kpi");
    }
    if !is_measured(&autonomy) {
        missing.push("autonomy");
    }
    if !is_measured(&gates) {
        missing.push("promotion_gates");
    }

    let incident_count = incidents.payload.as_ref().and_then(|v| {
        v.get("items")
            .and_then(Value::as_array)
            .map(|arr| arr.len() as u64)
    });
    let hil_count = hil
        .payload
        .as_ref()
        .and_then(|v| {
            value_u64(v, "total").or_else(|| {
                v.get("items")
                    .and_then(Value::as_array)
                    .map(|arr| arr.len() as u64)
            })
        })
        .or_else(|| kpi.payload.as_ref().and_then(|v| value_u64(v, "hil_pending")));

    let payload = json!({
        "filters": {
            "subscription": subscription,
            "window": window,
        },
        "kpi": kpi.payload.clone().unwrap_or(Value::Null),
        "posture": {
            "event_count": kpi.payload.as_ref().and_then(|v| value_u64(v, "event_count")),
            "shadow_share": kpi.payload.as_ref().and_then(|v| value_f64(v, "shadow_share")),
            "enforce_share": kpi.payload.as_ref().and_then(|v| value_f64(v, "enforce_share")),
            "audit_sample": kpi.payload.as_ref().and_then(|v| v.get("audit_sample").cloned()).unwrap_or(Value::Null),
        },
        "routing": {
            "by_tier": kpi.payload.as_ref().and_then(|v| v.get("by_tier").cloned()).unwrap_or(Value::Null),
            "by_outcome": kpi.payload.as_ref().and_then(|v| v.get("by_outcome").cloned()).unwrap_or(Value::Null),
            "by_action_kind": kpi.payload.as_ref().and_then(|v| v.get("by_action_kind").cloned()).unwrap_or(Value::Null),
        },
        "signals": {
            "active_incidents": incident_count,
            "hil_pending": hil_count,
            "rules_findings": rules_summary.payload.clone().unwrap_or(Value::Null),
        },
        "autonomy": autonomy.payload.clone().unwrap_or(Value::Null),
        "promotion_gates": gates.payload.clone().unwrap_or(Value::Null),
        "scatter_points": [],
        "timeline_meta": {
            "window": window,
            "forecast_status": "not-measured",
            "forecast_reason": "실측 예측 시계열이 수집되지 않아 미래(+5m) 영역은 미측정으로 분리 표시합니다."
        },
        "forecast": {
            "measurement_status": "not-measured",
            "horizon": "+5m",
            "points": [],
            "reason": "no_measured_forecast_series"
        },
    });

    build_envelope(
        &state,
        "dashboard",
        "/api/v4/overview/dashboard",
        &sources,
        Some(payload),
        &missing,
    )
}

async fn api_overview_resources(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(query): Query<ResourcesQuery>,
) -> Response {
    let auth = auth_header(&headers);
    let subscription = sanitize_filter_token(query.subscription.as_deref(), "all");
    let resource_type = sanitize_filter_token(query.resource_type.as_deref(), "all");
    let status_filter = sanitize_filter_token(query.status.as_deref(), "all");
    let lens = sanitize_lens(query.lens.as_deref());
    let limit = query.limit.unwrap_or(100).clamp(1, 200);
    let search = sanitize_search_query(query.search.as_deref());

    let states_path = match &search {
        Some(q) => format!(
            "/ontology/instances/states?limit={limit}&search={}",
            percent_encode_query(q)
        ),
        None => format!("/ontology/instances/states?limit={limit}"),
    };

    let (states_out, coverage_out) = tokio::join!(
        state.upstream.get_json(&states_path, auth),
        state.upstream.get_json("/detection-coverage", auth),
    );

    let sources = [
        (states_path.as_str(), &states_out),
        ("/detection-coverage", &coverage_out),
    ];

    if !is_measured(&states_out) && !is_measured(&coverage_out) {
        if should_fallback_to_db(&state, &sources) {
            let filter = overview_repo::ResourceFilter {
                subscription: &subscription,
                resource_type: &resource_type,
                status: &status_filter,
                search: search.as_deref(),
                lens,
                limit: Some(limit),
                offset: query.offset,
            };
            let db_val = overview_repo::fetch_resources(&state.db, &filter).await;
            return build_db_envelope(
                &state,
                "dashboard-v2",
                "/api/v4/overview/resources",
                &sources,
                db_val,
                &[],
                &["resources", "total_count", "uncollected_count", "coverage"],
            );
        }
        return build_envelope(
            &state,
            "dashboard-v2",
            "/api/v4/overview/resources",
            &sources,
            None,
            &["resources", "total_count", "uncollected_count", "coverage"],
        );
    }

    let mut missing = Vec::new();
    if !is_measured(&states_out) {
        missing.push("resources");
    }
    if !is_measured(&coverage_out) {
        missing.push("detection_coverage");
    }

    let total_count = states_out
        .payload
        .as_ref()
        .and_then(|v| value_u64(v, "total_count"));
    let resources_list = states_out
        .payload
        .as_ref()
        .and_then(|v| v.get("resources").cloned())
        .unwrap_or(Value::Null);
    let source_cutoff = states_out
        .payload
        .as_ref()
        .and_then(|v| v.get("source_cutoff").cloned())
        .unwrap_or(Value::Null);
    let complete = states_out
        .payload
        .as_ref()
        .and_then(|v| v.get("complete").and_then(Value::as_bool));
    if complete == Some(false) {
        missing.push("incomplete_snapshot");
    }

    let unobserved_count = coverage_out.payload.as_ref().and_then(|v| {
        let counts = v.get("counts")?;
        let unknown = counts.get("unknown").and_then(Value::as_u64);
        let stale = counts.get("stale").and_then(Value::as_u64);
        match (unknown, stale) {
            (Some(u), Some(s)) => Some(u.saturating_add(s)),
            (Some(u), None) => Some(u),
            (None, Some(s)) => Some(s),
            (None, None) => None,
        }
    });

    let payload = json!({
        "filters": {
            "subscription": subscription,
            "resource_type": resource_type,
            "status": status_filter,
            "search": search,
            "lens": lens,
            "limit": limit,
        },
        "total_count": total_count,
        "unobserved_count": unobserved_count,
        "complete": complete,
        "source_cutoff": source_cutoff,
        "resources": resources_list,
        "detection_coverage": coverage_out.payload.clone().unwrap_or(Value::Null),
        "uncollected_policy": {
            "zero_substitution_forbidden": true,
            "recovery_route": "/settings/integrations",
        },
    });

    build_envelope(
        &state,
        "dashboard-v2",
        "/api/v4/overview/resources",
        &sources,
        Some(payload),
        &missing,
    )
}

async fn api_overview_outcomes(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(query): Query<OutcomesQuery>,
) -> Response {
    let auth = auth_header(&headers);
    let period = sanitize_period(query.period.as_deref());
    let metric = sanitize_outcome_metric(query.metric.as_deref());
    let assurance_path = format!("/kpi/outcome-assurance?period={period}");

    let (autonomy, assurance, kpi) = tokio::join!(
        state.upstream.get_json("/kpi/autonomy", auth),
        state.upstream.get_json(&assurance_path, auth),
        state.upstream.get_json("/kpi", auth),
    );

    let sources = [
        ("/kpi/autonomy", &autonomy),
        (assurance_path.as_str(), &assurance),
        ("/kpi", &kpi),
    ];

    if !sources.iter().any(|(_, o)| is_measured(o)) {
        if should_fallback_to_db(&state, &sources) {
            let db_val = overview_repo::fetch_outcomes(&state.db, period, metric).await;
            return build_db_envelope(
                &state,
                "operating-outcomes",
                "/api/v4/overview/outcomes",
                &sources,
                db_val,
                &["cost-per-event"],
                &[
                    "auto-resolution",
                    "human-touchpoints",
                    "mttr",
                    "change-lead-time",
                    "cost-per-event",
                ],
            );
        }
        return build_envelope(
            &state,
            "operating-outcomes",
            "/api/v4/overview/outcomes",
            &sources,
            None,
            &[
                "auto-resolution",
                "human-touchpoints",
                "mttr",
                "change-lead-time",
                "cost-per-event",
            ],
        );
    }

    let mut missing = Vec::new();
    if !is_measured(&autonomy) {
        missing.push("autonomy_outcomes");
    }
    if !is_measured(&assurance) {
        missing.push("outcome_assurance");
    }
    let has_metric = |field: &str| {
        autonomy
            .payload
            .as_ref()
            .and_then(|v| v.get(field))
            .is_some_and(|v| !v.is_null())
    };
    let has_auto = has_metric("auto_resolution_rate");
    let has_human = has_metric("human_touchpoints_per_100");
    let has_mttr = has_metric("mttr_seconds");
    let has_lead = has_metric("change_lead_time_seconds");
    let has_cost_per_event = has_metric("cost_per_resolved_event");

    if !has_auto {
        missing.push("auto-resolution");
    }
    if !has_human {
        missing.push("human-touchpoints");
    }
    if !has_mttr {
        missing.push("mttr");
    }
    if !has_lead {
        missing.push("change-lead-time");
    }
    if !has_cost_per_event {
        missing.push("cost-per-event");
    }

    let state_label = |present: bool| if present { "measured" } else { "not-measured" };

    let payload = json!({
        "filters": {
            "period": period,
            "metric": metric,
        },
        "metric_states": {
            "auto-resolution": state_label(has_auto),
            "human-touchpoints": state_label(has_human),
            "mttr": state_label(has_mttr),
            "change-lead-time": state_label(has_lead),
            "cost-per-event": state_label(has_cost_per_event),
        },
        "autonomy": autonomy.payload.clone().unwrap_or(Value::Null),
        "outcome_assurance": assurance.payload.clone().unwrap_or(Value::Null),
        "audit_sample": kpi.payload.as_ref().and_then(|v| v.get("audit_sample").cloned()).unwrap_or(Value::Null),
        "event_count": kpi.payload.as_ref().and_then(|v| value_u64(v, "event_count")),
        "unmeasured_boundaries": {
            "cost_per_event": {
                "measurement_state": state_label(has_cost_per_event),
                "reason": if has_cost_per_event { Value::Null } else { json!("missing_source:attributed_cost_usd") },
                "recovery_route": "/settings/integrations",
            }
        }
    });

    build_envelope(
        &state,
        "operating-outcomes",
        "/api/v4/overview/outcomes",
        &sources,
        Some(payload),
        &missing,
    )
}

async fn api_overview_control_assurance(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Response {
    let auth = auth_header(&headers);
    let (autonomy, gates, hil, kpi) = tokio::join!(
        state.upstream.get_json("/kpi/autonomy", auth),
        state.upstream.get_json("/kpi/promotion-gates", auth),
        state.upstream.get_json("/hil-queue", auth),
        state.upstream.get_json("/kpi", auth),
    );

    let sources = [
        ("/kpi/autonomy", &autonomy),
        ("/kpi/promotion-gates", &gates),
        ("/hil-queue", &hil),
        ("/kpi", &kpi),
    ];

    if !sources.iter().any(|(_, o)| is_measured(o)) {
        if should_fallback_to_db(&state, &sources) {
            let db_val = overview_repo::fetch_control_assurance(&state.db).await;
            let unmeasured_guards: &[&str] = if db_val
                .pointer("/data/guard_boundaries/external_settlement_guard/measurement_state")
                .and_then(Value::as_str)
                == Some("measured")
            {
                &[]
            } else {
                &["external_settlement_guard"]
            };
            return build_db_envelope(
                &state,
                "control-assurance",
                "/api/v4/overview/control-assurance",
                &sources,
                db_val,
                unmeasured_guards,
                &[
                    "shadow_enforce_maturity",
                    "deterministic_guards",
                    "intervention_signals",
                ],
            );
        }
        return build_envelope(
            &state,
            "control-assurance",
            "/api/v4/overview/control-assurance",
            &sources,
            None,
            &[
                "shadow_enforce_maturity",
                "deterministic_guards",
                "intervention_signals",
            ],
        );
    }

    let mut missing = Vec::new();
    if !is_measured(&autonomy) {
        missing.push("autonomy_guards");
    }
    if !is_measured(&gates) {
        missing.push("promotion_gates");
    }

    let hil_pending = hil
        .payload
        .as_ref()
        .and_then(|v| {
            value_u64(v, "total").or_else(|| {
                v.get("items")
                    .and_then(Value::as_array)
                    .map(|arr| arr.len() as u64)
            })
        })
        .or_else(|| kpi.payload.as_ref().and_then(|v| value_u64(v, "hil_pending")));

    let has_external_settlement = autonomy
        .payload
        .as_ref()
        .and_then(|v| v.get("external_settlement_guard"))
        .is_some_and(|v| !v.is_null());

    let payload = json!({
        "policy_escape_tolerance": 0,
        "maturity": {
            "shadow_share": kpi.payload.as_ref().and_then(|v| value_f64(v, "shadow_share")),
            "enforce_share": kpi.payload.as_ref().and_then(|v| value_f64(v, "enforce_share")),
            "recall_precedence": true,
        },
        "guard_boundaries": {
            "external_settlement_guard": {
                "measurement_state": if has_external_settlement { "measured" } else { "not-measured" },
                "recovery_route": "/settings/integrations",
            }
        },
        "autonomy": autonomy.payload.clone().unwrap_or(Value::Null),
        "promotion_gates": gates.payload.clone().unwrap_or(Value::Null),
        "intervention_signals": {
            "hil_pending": hil_pending,
            "hil_route": "/operations/hil-queue",
            "promotion_gates_route": "/governance/promotion-gates",
        },
        "control_path": kpi.payload.as_ref().and_then(|v| v.get("by_outcome").cloned()).unwrap_or(Value::Null),
    });

    build_envelope(
        &state,
        "control-assurance",
        "/api/v4/overview/control-assurance",
        &sources,
        Some(payload),
        &missing,
    )
}

async fn api_overview_verticals(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(query): Query<VerticalsQuery>,
) -> Response {
    let auth = auth_header(&headers);
    let period = sanitize_period(query.period.as_deref());

    let (autonomy, reports, incidents, kpi) = tokio::join!(
        state.upstream.get_json("/kpi/autonomy", auth),
        state.upstream.get_json("/reports", auth),
        state.upstream.get_json("/incidents", auth),
        state.upstream.get_json("/kpi", auth),
    );

    let sources = [
        ("/kpi/autonomy", &autonomy),
        ("/reports", &reports),
        ("/incidents", &incidents),
        ("/kpi", &kpi),
    ];

    if !sources.iter().any(|(_, o)| is_measured(o)) {
        if should_fallback_to_db(&state, &sources) {
            let db_val = overview_repo::fetch_verticals(&state.db, period).await;
            return build_db_envelope(
                &state,
                "verticals",
                "/api/v4/overview/verticals",
                &sources,
                db_val,
                &[],
                &[
                    "resilience",
                    "change-safety",
                    "cost-governance",
                    "unattributed_events",
                ],
            );
        }
        return build_envelope(
            &state,
            "verticals",
            "/api/v4/overview/verticals",
            &sources,
            None,
            &[
                "resilience",
                "change-safety",
                "cost-governance",
                "unattributed_events",
            ],
        );
    }

    let mut missing = Vec::new();
    if !is_measured(&autonomy) {
        missing.push("autonomy_verticals");
    }
    if !is_measured(&reports) {
        missing.push("reports");
    }

    let unattributed_events = autonomy
        .payload
        .as_ref()
        .and_then(|v| value_u64(v, "unattributed_events"))
        .or_else(|| {
            reports
                .payload
                .as_ref()
                .and_then(|v| value_u64(v, "unattributed_events"))
        });

    let payload = json!({
        "filters": {
            "period": period,
        },
        "axes": ["resilience", "change-safety", "cost-governance"],
        "unattributed_events": unattributed_events,
        "autonomy": autonomy.payload.clone().unwrap_or(Value::Null),
        "reports": reports.payload.clone().unwrap_or(Value::Null),
        "incidents": incidents.payload.clone().unwrap_or(Value::Null),
        "event_count": kpi.payload.as_ref().and_then(|v| value_u64(v, "event_count")),
        "unattributed_policy": {
            "separated": true,
            "zero_substitution_forbidden": true,
            "zero_events_is_not_zero_percent": true,
        },
    });

    build_envelope(
        &state,
        "verticals",
        "/api/v4/overview/verticals",
        &sources,
        Some(payload),
        &missing,
    )
}

async fn api_overview_cost_governance(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(query): Query<CostGovernanceQuery>,
) -> Response {
    let auth = auth_header(&headers);
    let (ui_surface, upstream_surface) = sanitize_cost_surface(query.surface.as_deref());
    let budget = sanitize_filter_token(query.budget.as_deref(), "all");
    let surface_path = format!("/cost-governance/{upstream_surface}");

    let (availability, surface_out, finops) = tokio::join!(
        state.upstream.get_json("/cost-governance/availability", auth),
        state.upstream.get_json(&surface_path, auth),
        state.upstream.get_json("/finops", auth),
    );

    let sources = [
        ("/cost-governance/availability", &availability),
        (surface_path.as_str(), &surface_out),
        ("/finops", &finops),
    ];

    if !sources.iter().any(|(_, o)| is_measured(o)) {
        if should_fallback_to_db(&state, &sources) {
            let db_val =
                overview_repo::fetch_cost_governance(&state.db, ui_surface, &budget).await;
            let uncollected: &[&str] = if db_val
                .pointer("/data/collector_available")
                .and_then(Value::as_bool)
                == Some(true)
            {
                &[]
            } else {
                &[
                    "observed_spend",
                    "forecast_spend",
                    "savings_candidates",
                    "verified_savings",
                ]
            };
            return build_db_envelope(
                &state,
                "cost-governance",
                "/api/v4/overview/cost-governance",
                &sources,
                db_val,
                uncollected,
                &[
                    "observed_spend",
                    "forecast_spend",
                    "savings_candidates",
                    "verified_savings",
                ],
            );
        }
        return build_envelope(
            &state,
            "cost-governance",
            "/api/v4/overview/cost-governance",
            &sources,
            None,
            &[
                "observed_spend",
                "forecast_spend",
                "savings_candidates",
                "verified_savings",
            ],
        );
    }

    let mut missing = Vec::new();
    if !is_measured(&availability) {
        missing.push("availability");
    }
    if !is_measured(&surface_out) {
        missing.push(ui_surface);
    }
    let collector_available = availability
        .payload
        .as_ref()
        .and_then(|v| v.get("available").and_then(Value::as_bool));
    if collector_available == Some(false) {
        missing.push("focus_cost_export");
        if !is_measured(&surface_out) && !is_measured(&finops) {
            return build_envelope(
                &state,
                "cost-governance",
                "/api/v4/overview/cost-governance",
                &sources,
                None,
                &missing,
            );
        }
    }

    let payload = json!({
        "filters": {
            "surface": ui_surface,
            "budget": budget,
        },
        "collector_available": collector_available,
        "availability": availability.payload.clone().unwrap_or(Value::Null),
        "surface_data": surface_out.payload.clone().unwrap_or(Value::Null),
        "finops": finops.payload.clone().unwrap_or(Value::Null),
        "uncollected_policy": {
            "zero_substitution_forbidden": true,
            "recovery_route": "/settings/integrations",
        },
    });

    build_envelope(
        &state,
        "cost-governance",
        "/api/v4/overview/cost-governance",
        &sources,
        Some(payload),
        &missing,
    )
}

async fn api_overview_llm_cost(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(query): Query<LlmCostQuery>,
) -> Response {
    let auth = auth_header(&headers);
    let range = sanitize_llm_range(query.range.as_deref());
    let upstream_path = format!("/kpi/llm-cost?range={range}");
    let llm_out = state.upstream.get_json(&upstream_path, auth).await;

    let sources = [(upstream_path.as_str(), &llm_out)];

    if !is_measured(&llm_out) {
        if should_fallback_to_db(&state, &sources) {
            let db_val = overview_repo::fetch_llm_cost(&state.db, range).await;
            return build_db_envelope(
                &state,
                "llm-cost",
                "/api/v4/overview/llm-cost",
                &sources,
                db_val,
                &["prompt_cache_hit_rate"],
                &[
                    "t0_share",
                    "daily_estimated_cost",
                    "prompt_cache_hit_rate",
                    "token_series",
                ],
            );
        }
        return build_envelope(
            &state,
            "llm-cost",
            "/api/v4/overview/llm-cost",
            &sources,
            None,
            &[
                "t0_share",
                "daily_estimated_cost",
                "prompt_cache_hit_rate",
                "token_series",
            ],
        );
    }

    let metering_source = llm_out
        .payload
        .as_ref()
        .and_then(|v| v.get("source").and_then(Value::as_str))
        .unwrap_or("unknown");
    let is_synthetic = metering_source.eq_ignore_ascii_case("synthetic-dev");

    let payload = json!({
        "filters": {
            "range": range,
        },
        "metering_source": metering_source,
        "is_synthetic": is_synthetic,
        "internal_unit_prices_disclosed": false,
        "csv_formula_injection_guarded": true,
        "metering": llm_out.payload.clone().unwrap_or(Value::Null),
    });

    build_envelope(
        &state,
        "llm-cost",
        "/api/v4/overview/llm-cost",
        &sources,
        Some(payload),
        &[],
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::build_router;
    use axum::{body::Body, http::Request, routing::get as axum_get};
    use http_body_util::BodyExt;
    use std::path::PathBuf;
    use tokio::net::TcpListener;
    use tower::ServiceExt;

    fn test_state_with_url(operator_url: String) -> AppState {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("."));
        let mut st = AppState::from_repo_root(root, operator_url);
        st.db = crate::db::DbHandle::from_dsn_opt(None, false);
        st
    }

    fn test_state_with_local_db(operator_url: String) -> AppState {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("."));
        AppState::from_repo_root_with_local_db(root, operator_url)
    }

    async fn get_text(app: &Router, uri: &str) -> Result<(StatusCode, String), String> {
        let req = Request::builder()
            .uri(uri)
            .body(Body::empty())
            .map_err(|e| format!("request build failed: {e}"))?;
        let resp = app
            .clone()
            .oneshot(req)
            .await
            .map_err(|e| format!("oneshot failed: {e}"))?;
        let status = resp.status();
        let bytes = resp
            .into_body()
            .collect()
            .await
            .map_err(|e| format!("body collect failed: {e}"))?
            .to_bytes();
        let text = String::from_utf8(bytes.to_vec()).map_err(|e| format!("utf8 failed: {e}"))?;
        Ok((status, text))
    }

    async fn get_json_with_auth(
        app: &Router,
        uri: &str,
        auth: Option<&str>,
    ) -> Result<(StatusCode, Value), String> {
        let mut builder = Request::builder().uri(uri);
        if let Some(a) = auth {
            builder = builder.header(header::AUTHORIZATION, a);
        }
        let req = builder
            .body(Body::empty())
            .map_err(|e| format!("request build failed: {e}"))?;
        let resp = app
            .clone()
            .oneshot(req)
            .await
            .map_err(|e| format!("oneshot failed: {e}"))?;
        let status = resp.status();
        let bytes = resp
            .into_body()
            .collect()
            .await
            .map_err(|e| format!("body collect failed: {e}"))?
            .to_bytes();
        let val: Value =
            serde_json::from_slice(&bytes).map_err(|e| format!("json parse failed: {e}"))?;
        Ok((status, val))
    }

    #[tokio::test]
    async fn overview_pages_render_all_7_panels_without_legacy_mockup_links() -> Result<(), String> {
        let app = build_router(test_state_with_url("http://127.0.0.1:9".to_string()));
        for path in ["/", "/overview"] {
            let (status, html) = get_text(&app, path).await?;
            assert_eq!(status, StatusCode::OK, "non-200 on {path}");
            for panel in PANELS {
                let marker = format!("data-panel-id=\"{panel}\"");
                assert!(html.contains(&marker), "missing {marker} in {path}");
            }
            assert!(
                !html.contains("mockup-"),
                "legacy mockup-*.html link leaked into {path}"
            );
            assert!(
                !html.contains("overview-components.html"),
                "legacy overview-components.html link leaked into {path}"
            );
            assert!(
                html.contains("/assets/fdai-console-shared.css"),
                "missing canonical CSS path"
            );
            assert!(
                html.contains("/assets/fdai-console-shell.js"),
                "missing canonical shell JS path"
            );
            assert!(
                html.contains("/assets/fdai-console-live.js"),
                "missing canonical live JS path"
            );
            assert!(
                html.contains("\"/code-security\""),
                "expected canonical /code-security route"
            );
        }
        Ok(())
    }

    #[tokio::test]
    async fn overview_all_8_apis_return_not_measured_when_upstream_offline() -> Result<(), String> {
        let app = build_router(test_state_with_url("http://127.0.0.1:9".to_string()));
        let urls = [
            "/api/v4/overview/summary",
            "/api/v4/overview/dashboard?subscription=prod-core-kr&window=1h",
            "/api/v4/overview/resources?lens=availability&limit=50&search=prod-aks",
            "/api/v4/overview/outcomes?period=90d&metric=mttr",
            "/api/v4/overview/control-assurance",
            "/api/v4/overview/verticals?period=7d",
            "/api/v4/overview/cost-governance?surface=efficiency&budget=prod-core-kr",
            "/api/v4/overview/llm-cost?range=24h",
        ];
        for url in urls {
            let (status, body) = get_json_with_auth(&app, url, None).await?;
            assert_eq!(status, StatusCode::OK, "expected 200 on {url}");
            assert_eq!(
                body.get("domain").and_then(Value::as_str),
                Some("overview"),
                "wrong domain on {url}"
            );
            assert_eq!(
                body.get("measurement_state").and_then(Value::as_str),
                Some("not-measured"),
                "offline upstream must return not-measured on {url}: {body}"
            );
            assert_eq!(
                body.get("zero_substitution_forbidden")
                    .and_then(Value::as_bool),
                Some(true),
                "zero_substitution_forbidden must be true on {url}"
            );
            assert_eq!(
                body.get("data"),
                Some(&Value::Null),
                "offline upstream must not fabricate numeric 0 data on {url}"
            );
        }
        Ok(())
    }

    #[tokio::test]
    async fn overview_all_8_apis_hydrate_from_live_upstream_and_forward_auth() -> Result<(), String> {
        let mock_upstream = Router::new()
            .route(
                "/kpi",
                axum_get(|headers: HeaderMap| async move {
                    let authed = headers
                        .get(header::AUTHORIZATION)
                        .and_then(|v| v.to_str().ok())
                        == Some("Bearer test-token");
                    if !authed {
                        return (StatusCode::UNAUTHORIZED, Json(json!({ "error": "unauthorized" })));
                    }
                    (
                        StatusCode::OK,
                        Json(json!({
                            "event_count": 1280,
                            "shadow_share": 0.62,
                            "enforce_share": 0.38,
                            "hil_pending": 12,
                            "by_tier": { "T0": 896, "T1": 320, "T2": 64 },
                            "by_outcome": { "auto": 922, "approval": 146, "deferred": 128, "denied": 84 },
                            "by_action_kind": { "scale": 410 },
                            "last_recorded_at": "2026-11-26T00:00:00Z",
                            "audit_sample": { "from_seq": 1001, "through_seq": 2280, "row_count": 1280, "limit": 1280 }
                        })),
                    )
                }),
            )
            .route(
                "/ontology/instances/states",
                axum_get(|| async {
                    Json(json!({
                        "total_count": 2213,
                        "complete": true,
                        "source_cutoff": "2026-11-26T00:00:00Z",
                        "resources": [
                            { "id": "prod-aks-02", "name": "prod-aks-02", "status": "sre" }
                        ]
                    }))
                }),
            )
            .route(
                "/detection-coverage",
                axum_get(|| async {
                    Json(json!({ "target_count": 2213, "counts": { "ready": 2187, "unknown": 14 } }))
                }),
            )
            .route(
                "/hil-queue",
                axum_get(|| async { Json(json!({ "total": 12, "items": [] })) }),
            )
            .route(
                "/incidents",
                axum_get(|| async {
                    Json(json!({ "items": [{ "id": "inc-1" }, { "id": "inc-2" }] }))
                }),
            )
            .route(
                "/system/data-sources",
                axum_get(|| async { Json(json!({ "sources": [{ "key": "state", "source": "postgres" }] })) }),
            )
            .route(
                "/rules/findings-summary",
                axum_get(|| async { Json(json!({ "active_rules": 52, "policy_escapes": 0 })) }),
            )
            .route(
                "/kpi/autonomy",
                axum_get(|| async {
                    Json(json!({
                        "auto_resolution_rate": 0.72,
                        "human_touchpoints_per_100": 4.2,
                        "cost_per_resolved_event": Value::Null
                    }))
                }),
            )
            .route(
                "/kpi/outcome-assurance",
                axum_get(|| async { Json(json!({ "objectives": [{ "ref": "obj.resilience.auto-recovery" }] })) }),
            )
            .route(
                "/kpi/promotion-gates",
                axum_get(|| async { Json(json!({ "ready": 3, "blocked": 1, "policy_escapes": 0 })) }),
            )
            .route(
                "/reports",
                axum_get(|| async { Json(json!({ "verticals": ["resilience", "change-safety", "cost-governance"] })) }),
            )
            .route(
                "/cost-governance/availability",
                axum_get(|| async { Json(json!({ "available": true, "freshness": "fresh" })) }),
            )
            .route(
                "/cost-governance/overview",
                axum_get(|| async { Json(json!({ "observed_usd": 42800, "forecast_usd": 48600 })) }),
            )
            .route(
                "/finops",
                axum_get(|| async { Json(json!({ "savings_candidates_usd": 4820, "verified_savings_usd": 2140 })) }),
            )
            .route(
                "/kpi/llm-cost",
                axum_get(|| async {
                    Json(json!({
                        "source": "metering",
                        "t0_share": 0.952,
                        "daily_cost_usd": 14.60,
                        "cache_hit_rate": 0.814
                    }))
                }),
            );

        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .map_err(|e| format!("bind failed: {e}"))?;
        let addr = listener
            .local_addr()
            .map_err(|e| format!("local_addr failed: {e}"))?;
        let server_handle = tokio::spawn(async move {
            let _ = axum::serve(listener, mock_upstream).await;
        });

        let app = build_router(test_state_with_url(format!("http://{addr}")));

        // 1. Summary with valid auth returns fully measured data
        let (st, summary) =
            get_json_with_auth(&app, "/api/v4/overview/summary", Some("Bearer test-token")).await?;
        assert_eq!(st, StatusCode::OK);
        assert_eq!(
            summary.get("measurement_state").and_then(Value::as_str),
            Some("measured")
        );
        assert_eq!(
            summary
                .pointer("/data/observed_resources")
                .and_then(Value::as_u64),
            Some(2213)
        );
        assert_eq!(
            summary
                .pointer("/data/human_review_pending")
                .and_then(Value::as_u64),
            Some(12)
        );

        // 2. Dashboard returns measured posture and forwards query filters
        let (st, dash) = get_json_with_auth(
            &app,
            "/api/v4/overview/dashboard?subscription=prod-core-kr&window=24h",
            Some("Bearer test-token"),
        )
        .await?;
        assert_eq!(st, StatusCode::OK);
        assert_eq!(
            dash.get("measurement_state").and_then(Value::as_str),
            Some("measured")
        );
        assert_eq!(
            dash.pointer("/data/filters/window").and_then(Value::as_str),
            Some("24h")
        );
        assert_eq!(
            dash.pointer("/data/posture/event_count")
                .and_then(Value::as_u64),
            Some(1280)
        );

        // 3. Resources returns measured snapshot
        let (st, res) = get_json_with_auth(
            &app,
            "/api/v4/overview/resources?lens=serving&limit=25&search=aks",
            Some("Bearer test-token"),
        )
        .await?;
        assert_eq!(st, StatusCode::OK);
        assert_eq!(
            res.get("measurement_state").and_then(Value::as_str),
            Some("measured")
        );
        assert_eq!(
            res.pointer("/data/total_count").and_then(Value::as_u64),
            Some(2213)
        );

        // 4. Outcomes preserves honest partial/not-measured boundary for cost-per-event
        let (st, out) = get_json_with_auth(
            &app,
            "/api/v4/overview/outcomes?period=30d&metric=cost-per-event",
            Some("Bearer test-token"),
        )
        .await?;
        assert_eq!(st, StatusCode::OK);
        assert_eq!(
            out.get("measurement_state").and_then(Value::as_str),
            Some("partial")
        );
        assert_eq!(
            out.pointer("/data/unmeasured_boundaries/cost_per_event/measurement_state")
                .and_then(Value::as_str),
            Some("not-measured")
        );

        // 5. Control assurance returns measured maturity and signals
        let (st, ctrl) = get_json_with_auth(
            &app,
            "/api/v4/overview/control-assurance",
            Some("Bearer test-token"),
        )
        .await?;
        assert_eq!(st, StatusCode::OK);
        assert_eq!(
            ctrl.get("measurement_state").and_then(Value::as_str),
            Some("measured")
        );
        assert_eq!(
            ctrl.pointer("/data/intervention_signals/hil_pending")
                .and_then(Value::as_u64),
            Some(12)
        );

        // 6. Verticals returns measured 3-axis payload
        let (st, verts) = get_json_with_auth(
            &app,
            "/api/v4/overview/verticals?period=30d",
            Some("Bearer test-token"),
        )
        .await?;
        assert_eq!(st, StatusCode::OK);
        assert_eq!(
            verts.get("measurement_state").and_then(Value::as_str),
            Some("measured")
        );

        // 7. Cost governance returns measured overview
        let (st, cost) = get_json_with_auth(
            &app,
            "/api/v4/overview/cost-governance?surface=overview&budget=all",
            Some("Bearer test-token"),
        )
        .await?;
        assert_eq!(st, StatusCode::OK);
        assert_eq!(
            cost.get("measurement_state").and_then(Value::as_str),
            Some("measured")
        );

        // 8. LLM cost returns measured metering with unit price protection
        let (st, llm) = get_json_with_auth(
            &app,
            "/api/v4/overview/llm-cost?range=7d",
            Some("Bearer test-token"),
        )
        .await?;
        assert_eq!(st, StatusCode::OK);
        assert_eq!(
            llm.get("measurement_state").and_then(Value::as_str),
            Some("measured")
        );
        assert_eq!(
            llm.pointer("/data/internal_unit_prices_disclosed")
                .and_then(Value::as_bool),
            Some(false)
        );

        server_handle.abort();
        Ok(())
    }

    #[test]
    fn overview_query_sanitizers_enforce_allowlists() {
        assert_eq!(sanitize_window(Some("1h")), "1h");
        assert_eq!(sanitize_window(Some("../etc")), "15m");
        assert_eq!(sanitize_period(Some("90d")), "90d");
        assert_eq!(sanitize_period(Some("bad")), "30d");
        assert_eq!(sanitize_llm_range(Some("24h")), "24h");
        assert_eq!(sanitize_llm_range(Some("invalid")), "30d");
        assert_eq!(sanitize_lens(Some("availability")), "availability");
        assert_eq!(sanitize_lens(Some("drop table")), "resource");
        assert_eq!(
            sanitize_cost_surface(Some("efficiency")),
            ("efficiency", "resource-efficiency")
        );
        assert_eq!(sanitize_cost_surface(Some("unknown")), ("overview", "overview"));
        assert_eq!(
            sanitize_filter_token(Some("prod-core-kr;rm -rf"), "all"),
            "prod-core-krrm-rf"
        );
        assert_eq!(sanitize_filter_token(Some("///"), "all"), "all");
        assert_eq!(percent_encode_query("prod aks/1"), "prod%20aks%2F1");
    }

    #[tokio::test]
    async fn overview_security_headers_and_auth_failures_preserve_upstream_status(
    ) -> Result<(), String> {
        let mock_401 = Router::new()
            .route(
                "/kpi",
                axum_get(|| async {
                    (StatusCode::UNAUTHORIZED, Json(json!({ "error": "auth_required" })))
                }),
            )
            .route(
                "/ontology/instances/states",
                axum_get(|| async {
                    (StatusCode::UNAUTHORIZED, Json(json!({ "error": "auth_required" })))
                }),
            )
            .route(
                "/hil-queue",
                axum_get(|| async {
                    (StatusCode::UNAUTHORIZED, Json(json!({ "error": "auth_required" })))
                }),
            )
            .route(
                "/incidents",
                axum_get(|| async {
                    (StatusCode::UNAUTHORIZED, Json(json!({ "error": "auth_required" })))
                }),
            )
            .route(
                "/system/data-sources",
                axum_get(|| async {
                    (StatusCode::UNAUTHORIZED, Json(json!({ "error": "auth_required" })))
                }),
            );

        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .map_err(|e| format!("bind failed: {e}"))?;
        let addr = listener
            .local_addr()
            .map_err(|e| format!("local_addr failed: {e}"))?;
        let handle = tokio::spawn(async move {
            let _ = axum::serve(listener, mock_401).await;
        });

        let app = build_router(test_state_with_url(format!("http://{addr}")));

        // Verify security headers on HTML page
        let html_req = Request::builder()
            .uri("/overview")
            .body(Body::empty())
            .map_err(|e| format!("req build failed: {e}"))?;
        let html_resp = app
            .clone()
            .oneshot(html_req)
            .await
            .map_err(|e| format!("oneshot failed: {e}"))?;
        assert_eq!(
            html_resp.headers().get(header::X_CONTENT_TYPE_OPTIONS),
            Some(&HeaderValue::from_static("nosniff"))
        );
        assert_eq!(
            html_resp.headers().get(header::X_FRAME_OPTIONS),
            Some(&HeaderValue::from_static("SAMEORIGIN"))
        );
        assert_eq!(
            html_resp.headers().get(header::REFERRER_POLICY),
            Some(&HeaderValue::from_static("strict-origin-when-cross-origin"))
        );

        // Verify 401 upstream preserves upstream_status=401 and auth_required=true
        let api_req = Request::builder()
            .uri("/api/v4/overview/summary")
            .body(Body::empty())
            .map_err(|e| format!("req build failed: {e}"))?;
        let api_resp = app
            .clone()
            .oneshot(api_req)
            .await
            .map_err(|e| format!("oneshot failed: {e}"))?;
        assert_eq!(
            api_resp.headers().get(header::X_CONTENT_TYPE_OPTIONS),
            Some(&HeaderValue::from_static("nosniff"))
        );
        assert_eq!(
            api_resp.headers().get(header::X_FRAME_OPTIONS),
            Some(&HeaderValue::from_static("SAMEORIGIN"))
        );
        let bytes = api_resp
            .into_body()
            .collect()
            .await
            .map_err(|e| format!("collect failed: {e}"))?
            .to_bytes();
        let body: Value =
            serde_json::from_slice(&bytes).map_err(|e| format!("json parse failed: {e}"))?;
        assert_eq!(
            body.get("measurement_state").and_then(Value::as_str),
            Some("not-measured")
        );
        assert_eq!(
            body.get("upstream_status").and_then(Value::as_u64),
            Some(401)
        );
        assert_eq!(
            body.get("auth_required").and_then(Value::as_bool),
            Some(true)
        );

        // Verify auth_header rejects non-Bearer, multi-part, and oversized headers
        let mut bad_headers = HeaderMap::new();
        if let Ok(v) = HeaderValue::from_str("Basic dXNlcjpwYXNz") {
            bad_headers.insert(header::AUTHORIZATION, v);
        }
        assert!(auth_header(&bad_headers).is_none());

        let mut ok_headers = HeaderMap::new();
        if let Ok(v) = HeaderValue::from_str("Bearer valid-token-123") {
            ok_headers.insert(header::AUTHORIZATION, v);
        }
        assert_eq!(auth_header(&ok_headers), Some("Bearer valid-token-123"));

        handle.abort();
        Ok(())
    }

    #[tokio::test]
    async fn overview_cost_unavailable_and_incomplete_resources_preserve_not_measured(
    ) -> Result<(), String> {
        let mock = Router::new()
            .route(
                "/cost-governance/availability",
                axum_get(|| async { Json(json!({ "available": false, "reason": "focus_not_linked" })) }),
            )
            .route(
                "/cost-governance/overview",
                axum_get(|| async { (StatusCode::SERVICE_UNAVAILABLE, Json(json!({ "error": "unavailable" }))) }),
            )
            .route(
                "/finops",
                axum_get(|| async { (StatusCode::SERVICE_UNAVAILABLE, Json(json!({ "error": "unavailable" }))) }),
            )
            .route(
                "/ontology/instances/states",
                axum_get(|| async {
                    Json(json!({
                        "total_count": 100,
                        "complete": false,
                        "resources": []
                    }))
                }),
            )
            .route(
                "/detection-coverage",
                axum_get(|| async {
                    Json(json!({
                        "counts": { "ready": 86, "unknown": 10, "stale": 4 }
                    }))
                }),
            );

        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .map_err(|e| format!("bind failed: {e}"))?;
        let addr = listener
            .local_addr()
            .map_err(|e| format!("local_addr failed: {e}"))?;
        let handle = tokio::spawn(async move {
            let _ = axum::serve(listener, mock).await;
        });

        let app = build_router(test_state_with_url(format!("http://{addr}")));

        let (st, cost) =
            get_json_with_auth(&app, "/api/v4/overview/cost-governance", None).await?;
        assert_eq!(st, StatusCode::OK);
        assert_eq!(
            cost.get("measurement_state").and_then(Value::as_str),
            Some("not-measured")
        );
        assert_eq!(cost.get("data"), Some(&Value::Null));

        let (st, res) = get_json_with_auth(&app, "/api/v4/overview/resources", None).await?;
        assert_eq!(st, StatusCode::OK);
        assert_eq!(
            res.get("measurement_state").and_then(Value::as_str),
            Some("partial")
        );
        assert_eq!(
            res.pointer("/data/unobserved_count").and_then(Value::as_u64),
            Some(14)
        );

        handle.abort();
        Ok(())
    }

    #[test]
    fn overview_repo_resource_filter_sql_guards_injection_and_escapes_wildcards() {
        let empty = overview_repo::ResourceFilter {
            subscription: "all",
            resource_type: "all",
            status: "all",
            search: None,
            lens: "resource",
            limit: Some(50),
            offset: Some(0),
        };
        assert_eq!(overview_repo::build_resource_where_sql(&empty), "");

        let malicious = overview_repo::ResourceFilter {
            subscription: "sub'; DROP TABLE audit_log; --",
            resource_type: "aks",
            status: "sre",
            search: Some("100%_test' OR '1'='1"),
            lens: "availability",
            limit: Some(999),
            offset: Some(10),
        };
        let sql = overview_repo::build_resource_where_sql(&malicious);
        assert!(sql.starts_with("WHERE "));
        assert!(sql.contains("''"));
        assert!(sql.contains("\\%"));
        assert!(sql.contains("\\_"));
        assert!(sql.contains("IN ('failed', 'degraded', 'unhealthy')"));
    }

    #[test]
    fn overview_repo_resource_icons_match_all_azure_types_and_exist_on_disk() {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("."));
        let icons_dir = root.join("tools/architecture-diagrams/assets/azure");

        let cases: &[(&str, &str, &str, &str)] = &[
            ("subscription", "microsoft.resources/subscriptions", "Resource", "/azure-icons/subscriptions.svg"),
            ("resource-group", "Microsoft.Resources/resourceGroups", "Resource", "/azure-icons/resource-groups.svg"),
            ("authorization.role-assignment", "microsoft.authorization/roleassignments", "Resource", "/azure-icons/users.svg"),
            ("managed-identity", "microsoft.managedidentity/userassignedidentities", "Resource", "/azure-icons/managed-identity.svg"),
            ("kubernetes-cluster", "microsoft.containerservice/managedclusters", "Resource", "/azure-icons/kubernetes-services.svg"),
            ("kubernetes-node-pool", "Microsoft.ContainerService/managedClusters/agentPools", "Resource", "/azure-icons/kubernetes-services.svg"),
            ("container-registry", "microsoft.containerregistry/registries", "Resource", "/azure-icons/container-registry.svg"),
            ("compute.container-app", "microsoft.app/containerapps", "Resource", "/azure-icons/container-apps.svg"),
            ("compute.container-app-job", "microsoft.app/jobs", "Resource", "/azure-icons/container-apps.svg"),
            ("compute.vm-scale-set", "microsoft.compute/virtualmachinescalesets", "Resource", "/azure-icons/vm-scale-sets.svg"),
            ("compute.vm", "microsoft.compute/virtualmachines", "Resource", "/azure-icons/virtual-machine.svg"),
            ("disk", "microsoft.compute/disks", "Resource", "/azure-icons/disks.svg"),
            ("object-storage", "microsoft.storage/storageaccounts", "Resource", "/azure-icons/storage-account.svg"),
            ("postgresql-server", "microsoft.dbforpostgresql/flexibleservers", "Resource", "/azure-icons/postgresql.svg"),
            ("secret-store", "microsoft.keyvault/vaults", "Resource", "/azure-icons/key-vault.svg"),
            ("network.nsg", "microsoft.network/networksecuritygroups", "Resource", "/azure-icons/network-security-group.svg"),
            ("network.vnet", "microsoft.network/virtualnetworks", "Resource", "/azure-icons/virtual-network.svg"),
            ("network.subnet", "Microsoft.Network/virtualNetworks/subnets", "Resource", "/azure-icons/subnet.svg"),
            ("network.interface", "microsoft.network/networkinterfaces", "Resource", "/azure-icons/network-interface.svg"),
            ("network.public-ip", "microsoft.network/publicipaddresses", "Resource", "/azure-icons/public-ip.svg"),
            ("network.private-endpoint", "microsoft.network/privateendpoints", "Resource", "/azure-icons/private-endpoint.svg"),
            ("network.private-dns-zone-group", "Microsoft.Network/privateEndpoints/privateDnsZoneGroups", "Resource", "/azure-icons/dns-zones.svg"),
            ("network.nat-gateway", "microsoft.network/natgateways", "Resource", "/azure-icons/nat.svg"),
            ("network.load-balancer", "microsoft.network/loadbalancers", "Resource", "/azure-icons/load-balancer.svg"),
            ("network.bastion-host", "microsoft.network/bastionhosts", "Resource", "/azure-icons/bastion.svg"),
            ("network.route-table", "microsoft.network/routetables", "Resource", "/azure-icons/route-table.svg"),
            ("network.firewall", "microsoft.network/azurefirewalls", "Resource", "/azure-icons/firewall.svg"),
            ("network.firewall-policy", "microsoft.network/firewallpolicies", "Resource", "/azure-icons/waf-policy.svg"),
            ("api-gateway", "microsoft.apimanagement/service", "Resource", "/azure-icons/api-management-services.svg"),
            ("event-hub", "microsoft.eventhub/namespaces", "Resource", "/azure-icons/event-hubs.svg"),
            ("static-web-app", "microsoft.web/staticsites", "Resource", "/azure-icons/static-web-app.svg"),
            ("app-service-plan", "microsoft.web/serverfarms", "Resource", "/azure-icons/app-service-plans.svg"),
            ("compute.function", "microsoft.web/sites", "Resource", "/azure-icons/function-apps.svg"),
            ("workflow.logic-app", "microsoft.logic/workflows", "Resource", "/azure-icons/logic-apps.svg"),
            ("llm-model-deployment", "Microsoft.CognitiveServices/accounts/deployments", "Resource", "/azure-icons/azure-openai.svg"),
            ("ai-project", "microsoft.cognitiveservices/accounts/projects", "Resource", "/azure-icons/ai-foundry.svg"),
            ("managed-sre-agent", "microsoft.app/agents", "Resource", "/azure-icons/ai-foundry.svg"),
            ("data-collection-rule", "microsoft.insights/datacollectionrules", "Resource", "/azure-icons/data-collection-rules.svg"),
            ("anomaly-alert-rule", "microsoft.alertsmanagement/smartdetectoralertrules", "Resource", "/azure-icons/alerts.svg"),
            ("communication-service", "microsoft.communication/communicationservices", "Resource", "/azure-icons/communication-services.svg"),
            ("", "Microsoft.Sql/servers", "ResourceType", "/azure-icons/sql-server.svg"),
            ("", "Microsoft.Sql/servers/databases", "ResourceType", "/azure-icons/sql-database.svg"),
            ("", "Microsoft.DBforMySQL/flexibleServers", "ResourceType", "/azure-icons/mysql-server.svg"),
            ("", "Microsoft.DocumentDB/databaseAccounts", "ResourceType", "/azure-icons/cosmos-db.svg"),
            ("", "Microsoft.Cache/redis", "ResourceType", "/azure-icons/cache-redis.svg"),
            ("", "Microsoft.EventGrid/topics", "ResourceType", "/azure-icons/event-grid-topics.svg"),
            ("", "Microsoft.ServiceBus/namespaces", "ResourceType", "/azure-icons/service-bus.svg"),
            ("", "Microsoft.Compute/snapshots", "ResourceType", "/azure-icons/disk-snapshots.svg"),
            ("", "Microsoft.Dashboard/grafana", "ResourceType", "/azure-icons/managed-grafana.svg"),
            ("", "Microsoft.Network/dnsResolvers", "ResourceType", "/azure-icons/dns-private-resolver.svg"),
            ("", "Microsoft.Network/expressRouteCircuits", "ResourceType", "/azure-icons/expressroute-circuit.svg"),
            ("", "Microsoft.Network/virtualNetworkGateways", "ResourceType", "/azure-icons/virtual-network-gateway.svg"),
            ("", "Microsoft.Network/applicationGateways", "ResourceType", "/azure-icons/application-gateway.svg"),
            ("", "", "Rule", "/azure-icons/waf-policy.svg"),
            ("", "", "ResourceClass", "/azure-icons/resource-graph.svg"),
        ];

        for &(rt, pt, ot, expected) in cases {
            let actual = overview_repo::resource_icon_for(rt, pt, ot);
            assert_eq!(actual, expected, "wrong icon for ({rt}, {pt}, {ot})");
            let filename = actual.strip_prefix("/azure-icons/").unwrap_or("");
            assert!(
                icons_dir.join(filename).is_file(),
                "icon file missing on disk: {actual}"
            );
        }
    }

    #[tokio::test]
    async fn overview_all_8_apis_return_not_measured_when_postgres_unreachable(
    ) -> Result<(), String> {
        let unused_port = {
            let l = TcpListener::bind("127.0.0.1:0")
                .await
                .map_err(|e| format!("bind failed: {e}"))?;
            l.local_addr()
                .map_err(|e| format!("local_addr failed: {e}"))?
                .port()
        };
        let mut st = test_state_with_url("http://127.0.0.1:9".to_string());
        let dsn = format!("postgresql://fdai:fdai@127.0.0.1:{unused_port}/fdai");
        st.db = crate::db::DbHandle::from_dsn_opt(Some(&dsn), false);
        let app = build_router(st);

        let urls = [
            "/api/v4/overview/summary",
            "/api/v4/overview/dashboard?window=1h",
            "/api/v4/overview/resources?limit=20&offset=0&search=nsg",
            "/api/v4/overview/outcomes?period=30d",
            "/api/v4/overview/control-assurance",
            "/api/v4/overview/verticals?period=30d",
            "/api/v4/overview/cost-governance?surface=overview",
            "/api/v4/overview/llm-cost?range=30d",
        ];
        for url in urls {
            let (status, body) = get_json_with_auth(&app, url, None).await?;
            assert_eq!(status, StatusCode::OK, "expected 200 on {url}");
            assert_eq!(
                body.get("measurement_state").and_then(Value::as_str),
                Some("not-measured"),
                "unreachable postgres must return not-measured on {url}: {body}"
            );
            assert_eq!(
                body.get("data"),
                Some(&Value::Null),
                "unreachable postgres must not fabricate numeric 0 on {url}"
            );
        }
        Ok(())
    }

    #[tokio::test]
    async fn overview_all_8_apis_hydrate_from_local_postgres_when_upstream_offline(
    ) -> Result<(), String> {
        let st = test_state_with_local_db("http://127.0.0.1:9".to_string());
        if !st.db.is_configured() {
            return Ok(());
        }
        if st.db.query_single_readonly("SELECT 1").await.is_err() {
            return Ok(());
        }

        let app = build_router(st);

        // 1. Summary
        let (code, summary) = get_json_with_auth(&app, "/api/v4/overview/summary", None).await?;
        assert_eq!(code, StatusCode::OK);
        assert_eq!(summary.get("source").and_then(Value::as_str), Some("postgres-direct"));
        assert_eq!(summary.get("measurement_status").and_then(Value::as_str), Some("measured"));
        assert_eq!(summary.get("measurement_state").and_then(Value::as_str), Some("measured"));
        assert!(
            summary
                .pointer("/data/observed_resources")
                .and_then(Value::as_i64)
                .unwrap_or(0)
                > 0
        );
        assert!(
            summary
                .pointer("/data/audit_events")
                .and_then(Value::as_i64)
                .unwrap_or(0)
                > 0
        );

        // 2. Dashboard
        let (code, dash) =
            get_json_with_auth(&app, "/api/v4/overview/dashboard?window=24h", None).await?;
        assert_eq!(code, StatusCode::OK);
        assert_eq!(dash.get("source").and_then(Value::as_str), Some("postgres-direct"));
        assert_eq!(dash.get("measurement_status").and_then(Value::as_str), Some("measured"));
        assert!(
            dash.pointer("/data/posture/event_count")
                .and_then(Value::as_i64)
                .unwrap_or(0)
                > 0
        );
        assert_eq!(
            dash.pointer("/data/domain_breakdown")
                .and_then(Value::as_array)
                .map(Vec::len),
            Some(4)
        );
        assert!(
            dash.pointer("/data/time_buckets")
                .and_then(Value::as_array)
                .map(Vec::len)
                .unwrap_or(0)
                > 0
        );
        let scatter = dash
            .pointer("/data/scatter_points")
            .and_then(Value::as_array)
            .ok_or_else(|| "missing /data/scatter_points array".to_string())?;
        assert!(
            !scatter.is_empty(),
            "expected measured scatter_points from local postgres audit_log"
        );
        for pt in scatter {
            let ratio = pt
                .get("offset_ratio")
                .and_then(Value::as_f64)
                .ok_or_else(|| format!("missing offset_ratio in scatter point: {pt}"))?;
            assert!(
                (0.0..=1.0).contains(&ratio),
                "measured scatter_point offset_ratio must stay within past..=NOW (<= 1.0), got {ratio}"
            );
            let href = pt
                .get("href")
                .and_then(Value::as_str)
                .ok_or_else(|| format!("missing href in scatter point: {pt}"))?;
            assert!(
                href.contains("?item="),
                "scatter_point href must include ?item= deep link, got {href}"
            );
            let sev_band = pt
                .get("severity_band")
                .and_then(Value::as_i64)
                .ok_or_else(|| format!("missing severity_band in scatter point: {pt}"))?;
            assert!(
                (0..=4).contains(&sev_band),
                "severity_band must be within 0..=4, got {sev_band}"
            );
            if pt.get("action_kind").and_then(Value::as_str) == Some("hil.requested") {
                if pt.get("severity").and_then(Value::as_str) == Some("low") {
                    assert_eq!(
                        sev_band, 1,
                        "low-severity hil.requested must map to severity_band 1 (low), got {pt}"
                    );
                    if let Some(score) = pt.get("risk_score").and_then(Value::as_i64) {
                        assert!(
                            score < 80,
                            "low-severity hil.requested must never receive a fabricated high risk_score >= 80, got {score}"
                        );
                    }
                }
                let rule_id = pt.get("rule_id").and_then(Value::as_str).unwrap_or("");
                let action_type = pt.get("action_type").and_then(Value::as_str).unwrap_or("");
                assert!(
                    !rule_id.is_empty() && !action_type.is_empty(),
                    "hil.requested scatter point must carry joined rule_id and action_type metadata: {pt}"
                );
                let target_val = pt.get("target").and_then(Value::as_str).unwrap_or("");
                assert_ne!(
                    target_val, "fdai.core.hil_resume",
                    "hil.requested must never collapse target to actor name fdai.core.hil_resume"
                );
            }
        }
        assert_eq!(
            dash.pointer("/data/forecast/measurement_status")
                .and_then(Value::as_str),
            Some("not-measured")
        );

        // 3. Resources with filter, search, limit, and offset pagination
        let (code, res_p1) = get_json_with_auth(
            &app,
            "/api/v4/overview/resources?limit=15&offset=0&lens=availability",
            None,
        )
        .await?;
        assert_eq!(code, StatusCode::OK);
        assert_eq!(res_p1.get("source").and_then(Value::as_str), Some("postgres-direct"));
        assert_eq!(res_p1.get("measurement_status").and_then(Value::as_str), Some("measured"));
        let page1_len = res_p1
            .pointer("/data/resources")
            .and_then(Value::as_array)
            .map(Vec::len)
            .unwrap_or(0);
        assert!(page1_len > 0 && page1_len <= 15);

        let (code, res_p2) = get_json_with_auth(
            &app,
            "/api/v4/overview/resources?limit=15&offset=15&search=nsg",
            None,
        )
        .await?;
        assert_eq!(code, StatusCode::OK);
        assert_eq!(res_p2.get("measurement_status").and_then(Value::as_str), Some("measured"));
        assert_eq!(
            res_p2.pointer("/data/filters/offset").and_then(Value::as_u64),
            Some(15)
        );

        // 4. Outcomes
        let (code, out) =
            get_json_with_auth(&app, "/api/v4/overview/outcomes?period=30d", None).await?;
        assert_eq!(code, StatusCode::OK);
        assert_eq!(out.get("source").and_then(Value::as_str), Some("postgres-direct"));
        assert_eq!(out.get("measurement_status").and_then(Value::as_str), Some("measured"));
        assert_eq!(
            out.pointer("/data/unmeasured_boundaries/cost_per_event/measurement_state")
                .and_then(Value::as_str),
            Some("not-measured")
        );

        // 5. Control assurance
        let (code, ctrl) =
            get_json_with_auth(&app, "/api/v4/overview/control-assurance", None).await?;
        assert_eq!(code, StatusCode::OK);
        assert_eq!(ctrl.get("source").and_then(Value::as_str), Some("postgres-direct"));
        assert_eq!(ctrl.get("measurement_status").and_then(Value::as_str), Some("measured"));
        assert_eq!(
            ctrl.pointer("/data/policy_escape_tolerance")
                .and_then(Value::as_i64),
            Some(0)
        );

        // 6. Verticals
        let (code, verts) =
            get_json_with_auth(&app, "/api/v4/overview/verticals?period=30d", None).await?;
        assert_eq!(code, StatusCode::OK);
        assert_eq!(verts.get("source").and_then(Value::as_str), Some("postgres-direct"));
        assert_eq!(verts.get("measurement_status").and_then(Value::as_str), Some("measured"));
        assert_eq!(
            verts
                .pointer("/data/unattributed_policy/separated")
                .and_then(Value::as_bool),
            Some(true)
        );

        // 7. Cost governance
        let (code, cost) = get_json_with_auth(
            &app,
            "/api/v4/overview/cost-governance?surface=overview&budget=all",
            None,
        )
        .await?;
        assert_eq!(code, StatusCode::OK);
        assert_eq!(cost.get("source").and_then(Value::as_str), Some("postgres-direct"));
        assert_eq!(cost.get("measurement_status").and_then(Value::as_str), Some("measured"));
        assert!(
            cost.pointer("/data/receipts")
                .and_then(Value::as_array)
                .map(Vec::len)
                .unwrap_or(0)
                > 0
        );
        let budget_opts = cost
            .pointer("/data/budget_options")
            .and_then(Value::as_array)
            .map(Vec::len)
            .unwrap_or(0);
        assert!(budget_opts >= 1, "expected real budget_options from postgres");
        let cost_serialized = cost.to_string();
        assert!(
            !cost_serialized.contains("prod-core-kr")
                && !cost_serialized.contains("prod-data-platform"),
            "postgres-direct cost-governance must never emit fake sample subscription names"
        );

        // 8. LLM cost
        let (code, llm) =
            get_json_with_auth(&app, "/api/v4/overview/llm-cost?range=30d", None).await?;
        assert_eq!(code, StatusCode::OK);
        assert_eq!(llm.get("source").and_then(Value::as_str), Some("postgres-direct"));
        assert_eq!(llm.get("measurement_status").and_then(Value::as_str), Some("measured"));
        assert_eq!(
            llm.pointer("/data/internal_unit_prices_disclosed")
                .and_then(Value::as_bool),
            Some(false)
        );
        assert!(
            llm.pointer("/data/models")
                .and_then(Value::as_array)
                .map(Vec::len)
                .unwrap_or(0)
                > 0
        );

        Ok(())
    }

    #[test]
    fn overview_repo_hil_low_severity_never_fabricates_high_risk_and_extracts_resource() {
        // Low-severity HIL tag remediation must stay in band 1 (low), never synthetic high/critical
        assert_eq!(overview_repo::classify_audit_series("hil.requested"), "human");
        assert_eq!(
            overview_repo::normalize_event_severity("low", "hil.requested"),
            ("low", 1)
        );
        assert_eq!(
            overview_repo::normalize_event_severity("", "hil.requested"),
            ("low", 1)
        );
        assert_eq!(
            overview_repo::normalize_event_severity("critical", "hil.requested"),
            ("critical", 4)
        );
        assert_eq!(
            overview_repo::normalize_event_severity("", "measurement.control_loop.v1"),
            ("info", 0)
        );

        let idem = "inventory-delta:b2b49845::compute.vm.environment-tag.required::scope-ddcc51/resource-group/rg-ci/providers/microsoft.compute/virtualmachines/fdai-ci-worker-01:hil_request";
        let extracted = overview_repo::extract_resource_from_idempotency_key(idem);
        assert_eq!(
            extracted,
            "scope-ddcc51/resource-group/rg-ci/providers/microsoft.compute/virtualmachines/fdai-ci-worker-01"
        );
        assert_eq!(
            overview_repo::infer_resource_type_from_ref(&extracted, "compute.vm.environment-tag.required"),
            "compute.vm"
        );
    }
}
