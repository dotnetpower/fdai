//! Domain 4: 거버넌스 (`governance`, 13 panels).
//! Owned by the `governance` domain stream.
//!
//! Pure-Rust Axum handlers bridging the 13 Governance workbench panels with
//! `services_rs/operator-service` while preserving fail-closed, read-only,
//! and `not-measured` (never fabricating `0` when offline/uncollected) semantics.

use axum::{
    extract::{Path as AxumPath, RawQuery, State},
    http::{header, HeaderMap, StatusCode},
    response::{IntoResponse, Response},
    routing::{get, patch, post},
    Json, Router,
};
use serde_json::{json, Value};

const MAX_AUTH_HEADER_BYTES: usize = 4096;
const MAX_RAW_QUERY_BYTES: usize = 2048;
const MAX_QUERY_PAIRS: usize = 16;

fn is_mandatory_rule_severity(severity: &str) -> bool {
    let norm = severity.trim().to_ascii_lowercase();
    matches!(
        norm.as_str(),
        "critical" | "high" | "sev1" | "sev2" | "p0" | "p1" | "긴급" | "높음"
    )
}

fn is_safe_rule_id(rule_id: &str) -> bool {
    !rule_id.is_empty()
        && rule_id.len() <= 160
        && rule_id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.' | ':'))
}

fn json_no_store_status(status: StatusCode, payload: Value) -> Response {
    (
        status,
        [
            (header::CACHE_CONTROL, "no-store"),
            (header::X_CONTENT_TYPE_OPTIONS, "nosniff"),
            (header::REFERRER_POLICY, "no-referrer"),
            (header::VARY, "Authorization"),
        ],
        Json(payload),
    )
        .into_response()
}

fn validate_auth_header_strict(headers: &HeaderMap) -> Result<(), &'static str> {
    if let Some(val) = headers.get(header::AUTHORIZATION) {
        let bytes = val.as_bytes();
        if bytes.len() > MAX_AUTH_HEADER_BYTES {
            return Err("authorization header exceeds maximum length");
        }
        if bytes.iter().any(|&b| b < 0x20 || b == 0x7f) {
            return Err("authorization header contains forbidden control characters");
        }
    }
    Ok(())
}

fn validate_security_cves_query(raw_query: Option<&str>) -> Result<(), &'static str> {
    if let Some(raw) = raw_query {
        if raw.len() > MAX_RAW_QUERY_BYTES {
            return Err("query string exceeds maximum allowed length");
        }
        if has_forbidden_query_sequence(raw) {
            return Err("query string contains forbidden control or path traversal sequence");
        }
    }
    Ok(())
}

fn validate_security_filter_enums(params: &HashMap<String, String>) -> Result<(), &'static str> {
    if let Some(sev) = params.get("severity") {
        let s = sev.trim().to_ascii_lowercase();
        if !matches!(s.as_str(), "" | "all" | "critical" | "high" | "medium" | "low") {
            return Err("invalid severity filter value");
        }
    }
    if let Some(exp) = params.get("exploit") {
        let e = exp.trim().to_ascii_lowercase();
        if !matches!(
            e.as_str(),
            "" | "all"
                | "exploited"
                | "publicly_disclosed"
                | "exploitation_more_likely"
                | "exploitation_less_likely"
                | "exploitation_unlikely"
                | "unproven"
        ) {
            return Err("invalid exploit filter value");
        }
    }
    if let Some(pri) = params.get("priority") {
        let p = pri.trim().to_ascii_uppercase();
        if !matches!(p.as_str(), "" | "ALL" | "P0" | "P1" | "P2" | "P3") {
            return Err("invalid priority filter value");
        }
    }
    if let Some(rt) = params.get("runtime_only") {
        let r = rt.trim().to_ascii_lowercase();
        if !matches!(r.as_str(), "" | "0" | "1" | "true" | "false" | "yes" | "no") {
            return Err("invalid runtime_only filter value");
        }
    }
    if let Some(lim) = params.get("limit") {
        let parsed = lim
            .trim()
            .parse::<usize>()
            .map_err(|_| "limit must be a positive integer")?;
        if parsed == 0 || parsed > 300 {
            return Err("limit must be between 1 and 300");
        }
    }
    if let Some(off) = params.get("offset") {
        let parsed = off
            .trim()
            .parse::<usize>()
            .map_err(|_| "offset must be a non-negative integer")?;
        if parsed > 100_000 {
            return Err("offset exceeds maximum bound");
        }
    }
    if let Some(q) = params.get("search").or_else(|| params.get("q")) {
        if q.len() > 200 || q.chars().any(char::is_control) {
            return Err("search query exceeds length bound or contains control characters");
        }
    }
    Ok(())
}

use crate::{
    repos::governance as gov_repo,
    shell::{finalize_v4_html, html_response},
    upstream::UpstreamOutcome,
    AppState,
};
use std::collections::HashMap;
use std::time::{SystemTime, UNIX_EPOCH};

fn hex_val(b: u8) -> Option<u8> {
    match b {
        b'0'..=b'9' => Some(b - b'0'),
        b'a'..=b'f' => Some(b - b'a' + 10),
        b'A'..=b'F' => Some(b - b'A' + 10),
        _ => None,
    }
}

fn percent_decode_component(raw: &str) -> String {
    let bytes = raw.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0_usize;
    while i < bytes.len() {
        if bytes[i] == b'+' {
            out.push(b' ');
            i += 1;
        } else if bytes[i] == b'%' && i + 2 < bytes.len() {
            if let (Some(hi), Some(lo)) = (hex_val(bytes[i + 1]), hex_val(bytes[i + 2])) {
                let decoded = (hi << 4) | lo;
                if decoded >= 0x20 && decoded != 0x7f {
                    out.push(decoded);
                }
                i += 3;
                continue;
            }
            out.push(bytes[i]);
            i += 1;
        } else {
            out.push(bytes[i]);
            i += 1;
        }
    }
    String::from_utf8(out).unwrap_or_else(|_| raw.to_string())
}

fn parse_query_params(raw_query: Option<&str>) -> HashMap<String, String> {
    let mut map = HashMap::new();
    let Some(raw) = raw_query else {
        return map;
    };
    if raw.len() > MAX_RAW_QUERY_BYTES {
        return map;
    }
    for pair in raw.split('&').take(MAX_QUERY_PAIRS) {
        if pair.is_empty() || pair.len() > 512 {
            continue;
        }
        if let Some((k, v)) = pair.split_once('=') {
            let key = k.trim();
            if key.is_empty() || key.len() > 64 {
                continue;
            }
            let decoded = percent_decode_component(v);
            let trimmed = decoded.trim();
            if !trimmed.is_empty() && !trimmed.chars().any(char::is_control) {
                map.insert(key.to_string(), trimmed.chars().take(256).collect());
            }
        }
    }
    map
}

fn query_usize(params: &HashMap<String, String>, key: &str) -> Option<usize> {
    params.get(key).and_then(|s| s.parse::<usize>().ok())
}

fn is_repo_measured(payload: &Value) -> bool {
    payload
        .get("measurement_status")
        .and_then(Value::as_str)
        == Some("measured")
}

fn mutation_idempotency_key(headers: &HeaderMap, prefix: &str) -> String {
    if let Some(raw) = headers
        .get("x-idempotency-key")
        .and_then(|v| v.to_str().ok())
        .map(str::trim)
        .filter(|s| !s.is_empty() && s.len() <= 128 && !s.chars().any(char::is_control))
    {
        return raw.to_string();
    }
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    format!("{prefix}-{nanos}")
}

const TEMPLATE: &str = include_str!("../../templates/governance.html");

const PANELS: [&str; 13] = [
    "rules",
    "trust-routing",
    "ontology",
    "scope",
    "architecture",
    "blast-radius",
    "promotion-gates",
    "workflow-builder",
    "knowledge",
    "github",
    "gitlab",
    "azure-devops",
    "documents",
];

const API_ENDPOINTS: [&str; 16] = [
    "/api/v4/governance/summary",
    "/api/v4/governance/rules",
    "/api/v4/governance/rules/findings-summary",
    "/api/v4/governance/ontology/graph",
    "/api/v4/governance/ontology/instances",
    "/api/v4/governance/architecture",
    "/api/v4/governance/blast-radius",
    "/api/v4/governance/promotion-gates",
    "/api/v4/governance/workflows",
    "/api/v4/governance/knowledge",
    "/api/v4/governance/documents",
    "/api/v4/governance/trust-routing",
    "/api/v4/governance/scope",
    "/api/v4/governance/security/posture",
    "/api/v4/governance/security/cves",
    "/api/v4/governance/security/unknown-vulns",
];

pub fn panel_ids() -> &'static [&'static str] {
    &PANELS
}

pub fn api_endpoints() -> &'static [&'static str] {
    &API_ENDPOINTS
}

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/governance", get(page_governance))
        .route("/api/v4/governance/summary", get(api_governance_summary))
        .route("/api/v4/governance/rules", get(api_governance_rules))
        .route(
            "/api/v4/governance/rules/{rule_id}",
            get(api_governance_rule_detail),
        )
        .route(
            "/api/v4/governance/rules/{rule_id}/activation",
            patch(api_governance_rule_activation_toggle),
        )
        .route(
            "/api/v4/governance/rules/enforce-mandatory",
            post(api_governance_rules_enforce_mandatory),
        )
        .route(
            "/api/v4/governance/rules/findings-summary",
            get(api_governance_rules_findings_summary),
        )
        .route(
            "/api/v4/governance/ontology/graph",
            get(api_governance_ontology_graph),
        )
        .route(
            "/api/v4/governance/ontology/instances",
            get(api_governance_ontology_instances),
        )
        .route(
            "/api/v4/governance/ontology/instances/states",
            get(api_governance_ontology_instances_states),
        )
        .route(
            "/api/v4/governance/ontology/instances/explore",
            get(api_governance_ontology_instances_explore),
        )
        .route(
            "/api/v4/governance/ontology/lineage",
            get(api_governance_ontology_lineage),
        )
        .route(
            "/api/v4/governance/ontology/lineage/graph",
            get(api_governance_ontology_lineage_graph),
        )
        .route(
            "/api/v4/governance/architecture",
            get(api_governance_architecture),
        )
        .route(
            "/api/v4/governance/blast-radius",
            get(api_governance_blast_radius),
        )
        .route(
            "/api/v4/governance/promotion-gates",
            get(api_governance_promotion_gates),
        )
        .route(
            "/api/v4/governance/workflows",
            get(api_governance_workflows),
        )
        .route(
            "/api/v4/governance/knowledge",
            get(api_governance_knowledge),
        )
        .route(
            "/api/v4/governance/knowledge/{provider}",
            get(api_governance_knowledge_provider),
        )
        .route(
            "/api/v4/governance/documents",
            get(api_governance_documents),
        )
        .route(
            "/api/v4/governance/trust-routing",
            get(api_governance_trust_routing),
        )
        .route("/api/v4/governance/scope", get(api_governance_scope))
        .route(
            "/api/v4/governance/frameworks",
            get(api_governance_frameworks),
        )
        .route(
            "/api/v4/governance/security/posture",
            get(api_governance_security_posture),
        )
        .route(
            "/api/v4/governance/security/cves",
            get(api_governance_security_cves),
        )
        .route(
            "/api/v4/governance/security/unknown-vulns",
            get(api_governance_security_unknown_vulns),
        )
}

async fn page_governance(State(state): State<AppState>) -> Response {
    let html = finalize_v4_html(
        TEMPLATE,
        "governance",
        "rules",
        &state.operator_url,
        json!({
            "panels": PANELS,
            "endpoints": API_ENDPOINTS,
            "execution_authority": false,
            "not_measured_never_zero": true
        }),
    );
    html_response(html)
}

fn extract_auth(headers: &HeaderMap) -> Option<&str> {
    let raw = headers
        .get(header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok())
        .map(str::trim)?;
    if raw.is_empty() || raw.len() > MAX_AUTH_HEADER_BYTES || raw.chars().any(char::is_control) {
        return None;
    }
    Some(raw)
}

fn has_forbidden_query_sequence(value: &str) -> bool {
    if value
        .chars()
        .any(|c| c.is_control() || c == ' ' || c == '#' || c == '\\')
    {
        return true;
    }
    let lower = value.to_ascii_lowercase();
    if lower.contains("..")
        || lower.contains("%2e%2e")
        || lower.contains("%2f")
        || lower.contains("%5c")
        || lower.contains("%7f")
    {
        return true;
    }
    let bytes = lower.as_bytes();
    let mut i = 0_usize;
    while i + 2 < bytes.len() {
        if bytes[i] == b'%' {
            let hi = bytes[i + 1];
            let lo = bytes[i + 2];
            // Block percent-encoded ASCII control characters (%00-%1f) including CR/LF/NUL.
            if (hi == b'0' || hi == b'1') && lo.is_ascii_hexdigit() {
                return true;
            }
        }
        i += 1;
    }
    false
}

fn sanitize_query_string(raw_query: Option<&str>, allowed_keys: &[&str]) -> String {
    let Some(raw) = raw_query else {
        return String::new();
    };
    if raw.len() > MAX_RAW_QUERY_BYTES {
        return String::new();
    }
    let mut kept = Vec::new();
    for pair in raw.split('&') {
        if kept.len() >= MAX_QUERY_PAIRS {
            break;
        }
        if pair.is_empty() || pair.len() > 256 {
            continue;
        }
        let (key, val) = match pair.split_once('=') {
            Some((k, v)) => (k, Some(v)),
            None => (pair, None),
        };
        if !allowed_keys.contains(&key) {
            continue;
        }
        let is_safe_value = val
            .map(|v| !has_forbidden_query_sequence(v))
            .unwrap_or(true);
        if !is_safe_value {
            continue;
        }
        match val {
            Some(v) => kept.push(format!("{key}={v}")),
            None => kept.push(key.to_string()),
        }
    }
    kept.join("&")
}

fn json_no_store_response(payload: Value) -> Response {
    (
        StatusCode::OK,
        [
            (header::CACHE_CONTROL, "no-store"),
            (header::X_CONTENT_TYPE_OPTIONS, "nosniff"),
            (header::VARY, "Authorization"),
        ],
        Json(payload),
    )
        .into_response()
}

fn build_upstream_path(base_path: &str, raw_query: Option<&str>, allowed_keys: &[&str]) -> String {
    let filtered = sanitize_query_string(raw_query, allowed_keys);
    if filtered.is_empty() {
        base_path.to_string()
    } else {
        format!("{base_path}?{filtered}")
    }
}

fn reason_for_outcome(outcome: &UpstreamOutcome) -> &'static str {
    if !outcome.reachable {
        "operator-service unreachable"
    } else if outcome.status == 401 || outcome.status == 403 {
        "operator-service authentication or RBAC authorization required"
    } else if outcome.status == 404 || outcome.status == 501 {
        "upstream governance projection endpoint not enabled"
    } else if outcome.status == 503 {
        "upstream governance collector unavailable"
    } else if outcome.status == 200 {
        "upstream returned non-JSON payload"
    } else {
        "operator-service returned non-success status"
    }
}

fn measured_envelope(endpoint: &str, payload: Value, contract: Value) -> Response {
    json_no_store_response(json!({
        "source": "operator-service",
        "domain": "governance",
        "endpoint": endpoint,
        "measurement_state": "measured",
        "measurement_status": "measured",
        "execution_authority": false,
        "auth_mode_supported": ["bearer", "local-session"],
        "no_store": true,
        "contract": contract,
        "data": payload
    }))
}

fn postgres_measured_envelope(endpoint: &str, payload: Value, contract: Value) -> Response {
    json_no_store_response(json!({
        "source": "postgres-direct",
        "domain": "governance",
        "endpoint": endpoint,
        "measurement_state": "measured",
        "measurement_status": "measured",
        "execution_authority": false,
        "auth_mode_supported": ["bearer", "local-session"],
        "no_store": true,
        "contract": contract,
        "data": payload
    }))
}

fn not_measured_response(
    state: &AppState,
    endpoint: &str,
    outcome: &UpstreamOutcome,
    contract: Value,
) -> Response {
    let reason = reason_for_outcome(outcome);
    let mut base = state
        .upstream
        .not_measured_envelope("governance", endpoint, reason);
    if let Some(obj) = base.as_object_mut() {
        obj.insert(
            "measurement_status".to_string(),
            Value::String("not-measured".to_string()),
        );
        obj.insert("execution_authority".to_string(), Value::Bool(false));
        obj.insert(
            "auth_mode_supported".to_string(),
            json!(["bearer", "local-session"]),
        );
        obj.insert("no_store".to_string(), Value::Bool(true));
        obj.insert(
            "upstream_reachable".to_string(),
            Value::Bool(outcome.reachable),
        );
        obj.insert(
            "upstream_status".to_string(),
            Value::from(outcome.status),
        );
        obj.insert("contract".to_string(), contract);
    }
    json_no_store_response(base)
}

async fn proxy_governance_get_or_db<F, Fut>(
    state: &AppState,
    headers: &HeaderMap,
    upstream_path: &str,
    endpoint_label: &str,
    contract: Value,
    db_fetch: F,
) -> Response
where
    F: FnOnce() -> Fut,
    Fut: std::future::Future<Output = Value>,
{
    let auth = extract_auth(headers);
    let outcome = state.upstream.get_json(upstream_path, auth).await;
    if outcome.reachable && outcome.status == 200 {
        if let Some(payload) = outcome.payload {
            return measured_envelope(upstream_path, payload, contract);
        }
    }
    if state.db.is_configured() {
        let db_payload = db_fetch().await;
        if is_repo_measured(&db_payload) {
            return postgres_measured_envelope(endpoint_label, db_payload, contract);
        }
    }
    not_measured_response(state, upstream_path, &outcome, contract)
}

async fn proxy_governance_get_with_fallback_or_db<F, Fut>(
    state: &AppState,
    headers: &HeaderMap,
    primary_path: &str,
    fallback_path: &str,
    endpoint_label: &str,
    contract: Value,
    db_fetch: F,
) -> Response
where
    F: FnOnce() -> Fut,
    Fut: std::future::Future<Output = Value>,
{
    let auth = extract_auth(headers);
    let primary = state.upstream.get_json(primary_path, auth).await;
    if primary.reachable && primary.status == 200 {
        if let Some(payload) = primary.payload {
            return measured_envelope(primary_path, payload, contract);
        }
    }
    let fallback = state.upstream.get_json(fallback_path, auth).await;
    if fallback.reachable && fallback.status == 200 {
        if let Some(payload) = fallback.payload {
            return measured_envelope(fallback_path, payload, contract);
        }
    }
    if state.db.is_configured() {
        let db_payload = db_fetch().await;
        if is_repo_measured(&db_payload) {
            return postgres_measured_envelope(endpoint_label, db_payload, contract);
        }
    }
    not_measured_response(state, primary_path, &primary, contract)
}

async fn api_governance_summary(State(state): State<AppState>, headers: HeaderMap) -> Response {
    let auth = extract_auth(&headers);
    let (rules_up, findings_up, instances_up) = tokio::join!(
        state.upstream.get_json("/rules", auth),
        state.upstream.get_json("/rules/findings-summary", auth),
        state.upstream.get_json("/ontology/instances/states", auth),
    );

    let rules_data = if rules_up.reachable && rules_up.status == 200 {
        rules_up.payload.clone()
    } else {
        None
    };
    let findings_data = if findings_up.reachable && findings_up.status == 200 {
        findings_up.payload.clone()
    } else {
        None
    };
    let instances_data = if instances_up.reachable && instances_up.status == 200 {
        instances_up.payload.clone()
    } else {
        None
    };

    let measured_count = usize::from(rules_data.is_some())
        + usize::from(findings_data.is_some())
        + usize::from(instances_data.is_some());

    let contract = json!({
        "panels": PANELS,
        "panel_count": PANELS.len(),
        "endpoints": API_ENDPOINTS,
        "frameworks": ["MCSB", "CAF", "WARA", "MSRC", "BestPractices"],
        "ontology_meaning_only": true,
        "not_measured_never_zero": true
    });

    if measured_count == 0 {
        if state.db.is_configured() {
            let (onto, rules, findings, gates, workflows, trust) = tokio::join!(
                gov_repo::fetch_ontology_summary(&state.db),
                gov_repo::fetch_rules_filtered(&state.db, None, None, None, None, None, None, Some(20), None),
                gov_repo::fetch_rules_findings_summary(&state.db),
                gov_repo::fetch_promotion_gates(&state.db, None, None),
                gov_repo::fetch_workflows(&state.db, None, None),
                gov_repo::fetch_trust_routing(&state.db, None),
            );
            if is_repo_measured(&onto) || is_repo_measured(&rules) {
                return postgres_measured_envelope(
                    "/api/v4/governance/summary",
                    json!({
                        "measurement_status": "measured",
                        "source": "postgres-direct",
                        "ontology": onto,
                        "rules": rules,
                        "findings_summary": findings,
                        "promotion_gates": gates,
                        "workflows": workflows,
                        "trust_routing": trust,
                        "sub_sources": {
                            "ontology": if is_repo_measured(&onto) { "measured" } else { "not-measured" },
                            "rules": if is_repo_measured(&rules) { "measured" } else { "not-measured" },
                            "findings_summary": if is_repo_measured(&findings) { "measured" } else { "not-measured" },
                            "promotion_gates": if is_repo_measured(&gates) { "measured" } else { "not-measured" },
                            "workflows": if is_repo_measured(&workflows) { "measured" } else { "not-measured" },
                            "trust_routing": if is_repo_measured(&trust) { "measured" } else { "not-measured" }
                        }
                    }),
                    contract,
                );
            }
        }
        return not_measured_response(&state, "/rules", &rules_up, contract);
    }

    let measurement_state = if measured_count == 3 {
        "measured"
    } else {
        "partial"
    };

    json_no_store_response(json!({
        "source": "operator-service",
        "domain": "governance",
        "endpoint": "/api/v4/governance/summary",
        "measurement_state": measurement_state,
        "measurement_status": measurement_state,
        "execution_authority": false,
        "auth_mode_supported": ["bearer", "local-session"],
        "no_store": true,
        "contract": contract,
        "data": {
            "rules": rules_data,
            "findings_summary": findings_data,
            "ontology_instances_states": instances_data,
            "sub_sources": {
                "rules": if rules_up.reachable && rules_up.status == 200 { "measured" } else { "not-measured" },
                "findings_summary": if findings_up.reachable && findings_up.status == 200 { "measured" } else { "not-measured" },
                "ontology_instances_states": if instances_up.reachable && instances_up.status == 200 { "measured" } else { "not-measured" }
            }
        }
    }))
}

async fn api_governance_rules(
    State(state): State<AppState>,
    headers: HeaderMap,
    RawQuery(query): RawQuery,
) -> Response {
    let path = build_upstream_path(
        "/rules",
        query.as_deref(),
        &[
            "origin",
            "category",
            "severity",
            "source",
            "mode",
            "search",
            "q",
            "activation_state",
            "offset",
            "limit",
            "framework",
            "view",
        ],
    );
    let params = parse_query_params(query.as_deref());
    let db = state.db.clone();
    proxy_governance_get_or_db(
        &state,
        &headers,
        &path,
        "/api/v4/governance/rules",
        json!({
            "panel": "rules",
            "admin_toggle_supported": true,
            "mandatory_severities": ["critical", "high"],
            "critical_high_cannot_be_disabled": true,
            "frameworks": ["MCSB", "CAF", "WARA", "MSRC", "BestPractices"]
        }),
        move || async move {
            let search = params
                .get("search")
                .or_else(|| params.get("q"))
                .map(String::as_str);
            let act_state = params.get("activation_state").map(String::as_str);
            let sev = params.get("severity").map(String::as_str);
            let cat = params.get("category").map(String::as_str);
            let orig = params.get("origin").map(String::as_str);
            let fw = params
                .get("framework")
                .or_else(|| params.get("source"))
                .map(String::as_str);
            let lim = query_usize(&params, "limit");
            let off = query_usize(&params, "offset");
            let summary_only = params
                .get("view")
                .map(|v| v.eq_ignore_ascii_case("summary"))
                .unwrap_or(false);
            gov_repo::fetch_rules_filtered_view(
                &db,
                act_state,
                search,
                sev,
                cat,
                orig,
                fw,
                lim,
                off,
                summary_only,
            )
            .await
        },
    )
    .await
}

async fn api_governance_rule_detail(
    State(state): State<AppState>,
    headers: HeaderMap,
    AxumPath(rule_id): AxumPath<String>,
) -> Response {
    if let Err(msg) = validate_auth_header_strict(&headers) {
        return json_no_store_status(StatusCode::BAD_REQUEST, json!({"error": msg}));
    }
    let trimmed = rule_id.trim();
    if !is_safe_rule_id(trimmed) {
        return json_no_store_status(
            StatusCode::BAD_REQUEST,
            json!({"error": "유효하지 않은 규칙 ID 형식입니다."}),
        );
    }
    let data = gov_repo::fetch_rule_detail(&state.db, trimmed).await;
    let mstate = data
        .get("measurement_status")
        .and_then(Value::as_str)
        .unwrap_or("not-measured");
    json_no_store_status(
        StatusCode::OK,
        json!({
            "domain": "governance",
            "endpoint": format!("/api/v4/governance/rules/{trimmed}"),
            "measurement_state": mstate,
            "data": data
        }),
    )
}

async fn api_governance_rule_activation_toggle(
    State(state): State<AppState>,
    headers: HeaderMap,
    AxumPath(rule_id): AxumPath<String>,
    Json(body): Json<Value>,
) -> Response {
    let trimmed_id = rule_id.trim();
    if !is_safe_rule_id(trimmed_id) {
        return json_no_store_status(
            StatusCode::BAD_REQUEST,
            json!({
                "source": "console-v4-rust",
                "domain": "governance",
                "error": {
                    "code": "invalid_rule_id",
                    "message": "유효하지 않은 규칙 ID 형식입니다."
                }
            }),
        );
    }
    let Some(enabled) = body.get("enabled").and_then(Value::as_bool) else {
        return json_no_store_status(
            StatusCode::BAD_REQUEST,
            json!({
                "source": "console-v4-rust",
                "domain": "governance",
                "error": {
                    "code": "missing_enabled",
                    "message": "boolean 필드 'enabled'가 필요합니다."
                }
            }),
        );
    };
    let severity = body
        .get("severity")
        .and_then(Value::as_str)
        .unwrap_or("medium");
    if (is_mandatory_rule_severity(severity) || gov_repo::is_mandatory_rule_severity(severity))
        && !enabled
    {
        return json_no_store_status(
            StatusCode::BAD_REQUEST,
            json!({
                "source": "console-v4-rust",
                "domain": "governance",
                "rule_id": trimmed_id,
                "severity": severity,
                "mandatory_active": true,
                "can_deactivate": false,
                "error": {
                    "code": "mandatory_severity_locked",
                    "message": "심각도가 Critical 또는 High인 운영 규칙은 필수 활성화 대상이므로 비활성화할 수 없습니다."
                }
            }),
        );
    }

    // Defense-in-depth: verify actual DB severity when deactivating so callers cannot spoof medium/low.
    if !enabled && state.db.is_configured() {
        if let Some(db_sev) = gov_repo::fetch_rule_severity(&state.db, trimmed_id).await {
            if gov_repo::is_mandatory_rule_severity(&db_sev) {
                return json_no_store_status(
                    StatusCode::CONFLICT,
                    json!({
                        "source": "postgres-direct",
                        "domain": "governance",
                        "rule_id": trimmed_id,
                        "severity": db_sev,
                        "mandatory_active": true,
                        "can_deactivate": false,
                        "error": {
                            "code": "mandatory_severity_locked",
                            "message": "DB 기준 심각도가 Critical 또는 High인 운영 규칙은 필수 활성화 대상이므로 비활성화할 수 없습니다."
                        }
                    }),
                );
            }
        }
    }

    let mode = body
        .get("mode")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|s| matches!(*s, "Enforce" | "Shadow" | "Advise" | "Disabled"));
    let reason: String = body
        .get("reason")
        .and_then(Value::as_str)
        .unwrap_or("")
        .trim()
        .chars()
        .take(500)
        .collect();

    let upstream_path = format!("/rules/{trimmed_id}/activation");
    let forward_payload = json!({
        "enabled": enabled,
        "mode": mode,
        "severity": severity,
        "reason": reason
    });
    let auth = extract_auth(&headers);
    let outcome = state
        .upstream
        .patch_json(&upstream_path, forward_payload, auth)
        .await;

    if outcome.reachable && outcome.status == 200 {
        if let Some(payload) = outcome.payload {
            return json_no_store_status(
                StatusCode::OK,
                json!({
                    "source": "operator-service",
                    "domain": "governance",
                    "endpoint": upstream_path,
                    "measurement_state": "measured",
                    "measurement_status": "measured",
                    "persisted": payload.get("persisted").and_then(Value::as_bool).unwrap_or(true),
                    "pg_persisted": payload.get("pg_persisted").and_then(Value::as_bool).unwrap_or(false),
                    "rule_id": trimmed_id,
                    "data": payload
                }),
            );
        }
    }

    if outcome.reachable && matches!(outcome.status, 400 | 401 | 403 | 409) {
        let mapped_status =
            StatusCode::from_u16(outcome.status).unwrap_or(StatusCode::CONFLICT);
        let fallback_reason = reason_for_outcome(&outcome);
        let upstream_status = outcome.status;
        return json_no_store_status(
            mapped_status,
            json!({
                "source": "operator-service",
                "domain": "governance",
                "endpoint": upstream_path,
                "rule_id": trimmed_id,
                "upstream_status": upstream_status,
                "error": outcome.payload.unwrap_or_else(|| json!({
                    "code": "upstream_rejected",
                    "message": fallback_reason
                }))
            }),
        );
    }

    if state.db.is_configured() {
        let idem = mutation_idempotency_key(&headers, &format!("rule-act-{trimmed_id}"));
        let actor = "console-v4-operator";
        if state.db.mutations_allowed() {
            match gov_repo::update_rule_activation(
                &state.db, trimmed_id, enabled, severity, actor, &reason, &idem,
            )
            .await
            {
                Ok(val) => {
                    return json_no_store_status(
                        StatusCode::OK,
                        json!({
                            "source": "postgres-direct",
                            "domain": "governance",
                            "endpoint": upstream_path,
                            "measurement_state": "measured",
                            "measurement_status": "measured",
                            "persisted": true,
                            "pg_persisted": true,
                            "rule_id": trimmed_id,
                            "data": val
                        }),
                    );
                }
                Err((409, val)) => {
                    return json_no_store_status(
                        StatusCode::CONFLICT,
                        json!({
                            "source": "postgres-direct",
                            "domain": "governance",
                            "endpoint": upstream_path,
                            "rule_id": trimmed_id,
                            "mandatory_active": true,
                            "can_deactivate": false,
                            "error": val
                        }),
                    );
                }
                Err((_, val)) => {
                    let guard_reason = val
                        .get("reason")
                        .and_then(Value::as_str)
                        .unwrap_or("db_write_guard");
                    return json_no_store_status(
                        StatusCode::OK,
                        json!({
                            "source": "postgres-direct",
                            "domain": "governance",
                            "endpoint": upstream_path,
                            "measurement_state": "measured",
                            "measurement_status": "measured",
                            "persisted": false,
                            "pg_persisted": false,
                            "read_only_guard": true,
                            "reason": guard_reason,
                            "rule_id": trimmed_id,
                            "data": {
                                "rule_id": trimmed_id,
                                "enabled": enabled,
                                "severity": severity,
                                "mode": mode,
                                "mandatory_active": false,
                                "can_deactivate": true,
                                "persisted": false
                            }
                        }),
                    );
                }
            }
        }
        return json_no_store_status(
            StatusCode::OK,
            json!({
                "source": "postgres-direct",
                "domain": "governance",
                "endpoint": upstream_path,
                "measurement_state": "measured",
                "measurement_status": "measured",
                "persisted": false,
                "pg_persisted": false,
                "read_only_guard": true,
                "reason": "db_writes_disabled",
                "rule_id": trimmed_id,
                "data": {
                    "rule_id": trimmed_id,
                    "enabled": enabled,
                    "severity": severity,
                    "mode": mode,
                    "mandatory_active": false,
                    "can_deactivate": true,
                    "persisted": false
                }
            }),
        );
    }

    json_no_store_status(
        StatusCode::OK,
        json!({
            "source": "console-v4-rust",
            "domain": "governance",
            "endpoint": upstream_path,
            "measurement_state": "not-measured",
            "measurement_status": "not-measured",
            "persisted": false,
            "pg_persisted": false,
            "rule_id": trimmed_id,
            "upstream_reachable": outcome.reachable,
            "upstream_status": outcome.status,
            "reason": reason_for_outcome(&outcome),
            "data": Value::Null
        }),
    )
}

async fn api_governance_rules_enforce_mandatory(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Response {
    let auth = extract_auth(&headers);
    let upstream_path = "/rules/activation/enforce-mandatory";
    let outcome = state
        .upstream
        .post_json(upstream_path, json!({}), auth)
        .await;
    if outcome.reachable && outcome.status == 200 {
        if let Some(payload) = outcome.payload {
            return json_no_store_status(
                StatusCode::OK,
                json!({
                    "source": "operator-service",
                    "domain": "governance",
                    "endpoint": upstream_path,
                    "measurement_state": "measured",
                    "measurement_status": "measured",
                    "persisted": true,
                    "data": payload
                }),
            );
        }
    }

    if state.db.is_configured() {
        let idem = mutation_idempotency_key(&headers, "rule-enforce-mandatory");
        let actor = "console-v4-operator";
        if state.db.mutations_allowed() {
            if let Ok(val) = gov_repo::enforce_mandatory_rules(&state.db, actor, &idem).await {
                return json_no_store_status(
                    StatusCode::OK,
                    json!({
                        "source": "postgres-direct",
                        "domain": "governance",
                        "endpoint": upstream_path,
                        "measurement_state": "measured",
                        "measurement_status": "measured",
                        "persisted": true,
                        "pg_persisted": true,
                        "data": val
                    }),
                );
            }
        }
        if let Some((mandatory_rule_count, enforced_count)) =
            gov_repo::fetch_mandatory_rule_counts(&state.db).await
        {
            return json_no_store_status(
                StatusCode::OK,
                json!({
                    "source": "postgres-direct",
                    "domain": "governance",
                    "endpoint": upstream_path,
                    "measurement_state": "measured",
                    "measurement_status": "measured",
                    "persisted": false,
                    "pg_persisted": false,
                    "read_only_guard": true,
                    "data": {
                        "mandatory_severities": ["critical", "high"],
                        "mandatory_rule_count": mandatory_rule_count,
                        "enforced_count": enforced_count,
                        "policy_enforced_in_projection": true
                    }
                }),
            );
        }
    }

    json_no_store_status(
        StatusCode::OK,
        json!({
            "source": "console-v4-rust",
            "domain": "governance",
            "endpoint": upstream_path,
            "measurement_state": "not-measured",
            "measurement_status": "not-measured",
            "persisted": false,
            "upstream_reachable": outcome.reachable,
            "upstream_status": outcome.status,
            "reason": reason_for_outcome(&outcome),
            "data": Value::Null
        }),
    )
}

async fn api_governance_rules_findings_summary(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Response {
    let db = state.db.clone();
    proxy_governance_get_or_db(
        &state,
        &headers,
        "/rules/findings-summary",
        "/api/v4/governance/rules/findings-summary",
        json!({
            "panel": "rules",
            "distinguishes_unevaluated_from_zero": true
        }),
        move || async move { gov_repo::fetch_rules_findings_summary(&db).await },
    )
    .await
}

async fn api_governance_ontology_graph(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Response {
    let db = state.db.clone();
    proxy_governance_get_or_db(
        &state,
        &headers,
        "/ontology/graph",
        "/api/v4/governance/ontology/graph",
        json!({
            "panel": "ontology",
            "views": ["instance", "knowledge", "lineage", "schema", "semantic"],
            "mutation_authority": false,
            "meaning_validation_only": true
        }),
        move || async move { gov_repo::fetch_ontology_graph(&db).await },
    )
    .await
}

async fn api_governance_ontology_instances(
    State(state): State<AppState>,
    headers: HeaderMap,
    RawQuery(query): RawQuery,
) -> Response {
    let allowed = ["search", "resource_type", "cursor", "limit", "subscription", "offset"];
    let primary = build_upstream_path("/ontology/instances", query.as_deref(), &allowed);
    let fallback = build_upstream_path("/ontology/instances/states", query.as_deref(), &allowed);
    let params = parse_query_params(query.as_deref());
    let db = state.db.clone();
    proxy_governance_get_with_fallback_or_db(
        &state,
        &headers,
        &primary,
        &fallback,
        "/api/v4/governance/ontology/instances",
        json!({
            "panel": "ontology",
            "layout": "3-zone",
            "state_axes": ["operational", "availability", "configuration"],
            "mutation_authority": false
        }),
        move || async move {
            let search = params.get("search").map(String::as_str);
            let rtype = params.get("resource_type").map(String::as_str);
            let lim = query_usize(&params, "limit");
            let off = query_usize(&params, "offset");
            gov_repo::fetch_ontology_instances(&db, search, rtype, lim, off).await
        },
    )
    .await
}

async fn api_governance_ontology_instances_states(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Response {
    let db = state.db.clone();
    proxy_governance_get_or_db(
        &state,
        &headers,
        "/ontology/instances/states",
        "/api/v4/governance/ontology/instances/states",
        json!({
            "panel": "ontology",
            "integrity_checked": true,
            "mutation_authority": false,
            "meaning_validation_only": true
        }),
        move || async move { gov_repo::fetch_ontology_instances_states(&db).await },
    )
    .await
}

async fn api_governance_ontology_instances_explore(
    State(state): State<AppState>,
    headers: HeaderMap,
    RawQuery(query): RawQuery,
) -> Response {
    let allowed = ["root", "depth", "limit", "activity_limit"];
    let primary = build_upstream_path("/ontology/instances/explore", query.as_deref(), &allowed);
    let fallback = build_upstream_path("/ontology/instances", query.as_deref(), &["limit"]);
    let params = parse_query_params(query.as_deref());
    let db = state.db.clone();
    proxy_governance_get_with_fallback_or_db(
        &state,
        &headers,
        &primary,
        &fallback,
        "/api/v4/governance/ontology/instances/explore",
        json!({
            "panel": "ontology",
            "layout": "3-zone",
            "mode": "explore-root",
            "mutation_authority": false
        }),
        move || async move {
            let root = params.get("root").map(String::as_str);
            let depth = query_usize(&params, "depth");
            let lim = query_usize(&params, "limit");
            gov_repo::fetch_ontology_instances_explore(&db, root, depth, lim).await
        },
    )
    .await
}

async fn api_governance_ontology_lineage(
    State(state): State<AppState>,
    headers: HeaderMap,
    RawQuery(query): RawQuery,
) -> Response {
    let allowed = ["resource_id", "resource_type", "search", "limit", "include_audit"];
    let primary = build_upstream_path("/ontology/instances/lineage", query.as_deref(), &allowed);
    let fallback = build_upstream_path("/ontology/instances", query.as_deref(), &["search", "limit"]);
    let params = parse_query_params(query.as_deref());
    let db = state.db.clone();
    proxy_governance_get_with_fallback_or_db(
        &state,
        &headers,
        &primary,
        &fallback,
        "/api/v4/governance/ontology/lineage",
        json!({
            "panel": "ontology",
            "view": "lineage",
            "stages": ["source", "snapshot", "pipeline", "ontology_instance", "audit_events"],
            "mutation_authority": false
        }),
        move || async move {
            let rid = params
                .get("resource_id")
                .or_else(|| params.get("search"))
                .map(String::as_str);
            gov_repo::fetch_lineage(&db, rid).await
        },
    )
    .await
}

async fn api_governance_architecture(
    State(state): State<AppState>,
    headers: HeaderMap,
    RawQuery(query): RawQuery,
) -> Response {
    let allowed = ["scope", "subscription", "vnet", "subnet", "layer"];
    let primary = build_upstream_path("/inventory/graph", query.as_deref(), &allowed);
    let fallback = build_upstream_path("/ontology/instances", query.as_deref(), &allowed);
    let params = parse_query_params(query.as_deref());
    let db = state.db.clone();
    proxy_governance_get_with_fallback_or_db(
        &state,
        &headers,
        &primary,
        &fallback,
        "/api/v4/governance/architecture",
        json!({
            "panel": "architecture",
            "views": ["topo", "netpath"],
            "nested_boundaries": ["subscription", "vnet", "subnet", "resource_group"],
            "dynamic_svg_schema": ["views", "containers", "nodes", "edges", "summary"],
            "read_only": true
        }),
        move || async move {
            let scope = params
                .get("scope")
                .or_else(|| params.get("subscription"))
                .map(String::as_str);
            let layer = params.get("layer").map(String::as_str);
            gov_repo::fetch_architecture(&db, scope, layer).await
        },
    )
    .await
}

async fn api_governance_blast_radius(
    State(state): State<AppState>,
    headers: HeaderMap,
    RawQuery(query): RawQuery,
) -> Response {
    let allowed = ["target", "hop", "risk_class", "subscription"];
    let primary = build_upstream_path("/blast-radius", query.as_deref(), &allowed);
    let params = parse_query_params(query.as_deref());
    let db = state.db.clone();
    proxy_governance_get_or_db(
        &state,
        &headers,
        &primary,
        "/api/v4/governance/blast-radius",
        json!({
            "panel": "blast-radius",
            "simulation_only": true,
            "max_hops": 3,
            "safeguards": [
                "stop_condition",
                "tested_rollback",
                "blast_radius_limit",
                "dry_run",
                "logical_target_lock",
                "idempotency_key",
                "two_phase_audit"
            ]
        }),
        move || async move {
            let target = params.get("target").map(String::as_str);
            let hop = query_usize(&params, "hop");
            gov_repo::fetch_blast_radius(&db, target, hop).await
        },
    )
    .await
}

async fn api_governance_promotion_gates(
    State(state): State<AppState>,
    headers: HeaderMap,
    RawQuery(query): RawQuery,
) -> Response {
    let path = build_upstream_path("/promotion-gates", query.as_deref(), &["state", "action_type"]);
    let params = parse_query_params(query.as_deref());
    let db = state.db.clone();
    proxy_governance_get_or_db(
        &state,
        &headers,
        &path,
        "/api/v4/governance/promotion-gates",
        json!({
            "panel": "promotion-gates",
            "required_evidences": [
                "zero_policy_escapes",
                "dry_run_passed",
                "tested_rollback",
                "minimum_observation_window"
            ],
            "recall_overrides_exception": true
        }),
        move || async move {
            let st = params.get("state").map(String::as_str);
            let at = params.get("action_type").map(String::as_str);
            gov_repo::fetch_promotion_gates(&db, st, at).await
        },
    )
    .await
}

async fn api_governance_workflows(
    State(state): State<AppState>,
    headers: HeaderMap,
    RawQuery(query): RawQuery,
) -> Response {
    let path = build_upstream_path("/views/workflow-apps", query.as_deref(), &["mode", "template"]);
    let params = parse_query_params(query.as_deref());
    let db = state.db.clone();
    proxy_governance_get_or_db(
        &state,
        &headers,
        &path,
        "/api/v4/governance/workflows",
        json!({
            "panel": "workflow-builder",
            "default_mode": "shadow",
            "shadow_locked": true,
            "stages": [
                "Heimdall.trigger",
                "Forseti.guard",
                "Var.human_approval",
                "Thor.isolated_execute",
                "Vidar.verify_and_Saga.audit"
            ]
        }),
        move || async move {
            let mode = params.get("mode").map(String::as_str);
            let tmpl = params.get("template").map(String::as_str);
            gov_repo::fetch_workflows(&db, mode, tmpl).await
        },
    )
    .await
}

async fn api_governance_knowledge(
    State(state): State<AppState>,
    headers: HeaderMap,
    RawQuery(query): RawQuery,
) -> Response {
    let provider_filter = sanitize_query_string(query.as_deref(), &["provider"]);
    let params = parse_query_params(query.as_deref());
    let p_filter = params.get("provider").map(String::as_str);
    handle_governance_knowledge(
        &state,
        &headers,
        "/api/v4/governance/knowledge",
        &provider_filter,
        p_filter,
    )
    .await
}

async fn api_governance_knowledge_provider(
    State(state): State<AppState>,
    headers: HeaderMap,
    AxumPath(provider): AxumPath<String>,
) -> Response {
    let norm = provider.trim().to_ascii_lowercase();
    if !matches!(norm.as_str(), "github" | "gitlab" | "azure-devops") {
        return json_no_store_status(
            StatusCode::BAD_REQUEST,
            json!({
                "domain": "governance",
                "error": {
                    "code": "invalid_knowledge_provider",
                    "message": "supported providers are github, gitlab, azure-devops"
                },
                "execution_authority": false,
                "no_store": true
            }),
        );
    }
    let endpoint = format!("/api/v4/governance/knowledge/{norm}");
    let filter_str = format!("provider={norm}");
    handle_governance_knowledge(&state, &headers, &endpoint, &filter_str, Some(norm.as_str())).await
}

async fn handle_governance_knowledge(
    state: &AppState,
    headers: &HeaderMap,
    endpoint: &str,
    provider_filter: &str,
    p_filter: Option<&str>,
) -> Response {
    let auth = extract_auth(headers);
    let (cloud_up, github_up) = tokio::join!(
        state.upstream.get_json("/ingestion/cloud-knowledge", auth),
        state.upstream.get_json("/knowledge/github/sources", auth),
    );

    let cloud_data = if cloud_up.reachable && cloud_up.status == 200 {
        cloud_up.payload.clone()
    } else {
        None
    };
    let github_data = if github_up.reachable && github_up.status == 200 {
        github_up.payload.clone()
    } else {
        None
    };

    let contract = json!({
        "panel": p_filter.unwrap_or("knowledge"),
        "providers": ["documents", "github", "gitlab", "azure-devops"],
        "provider_filter": provider_filter,
        "read_only_retrieval": true,
        "unconnected_never_zero": true
    });

    if cloud_data.is_none() && github_data.is_none() {
        if state.db.is_configured() {
            let db_payload = gov_repo::fetch_knowledge(&state.db, p_filter).await;
            if is_repo_measured(&db_payload) {
                return postgres_measured_envelope(endpoint, db_payload, contract);
            }
        }
        return not_measured_response(state, "/ingestion/cloud-knowledge", &cloud_up, contract);
    }

    let measurement_state = if cloud_data.is_some() && github_data.is_some() {
        "measured"
    } else {
        "partial"
    };

    json_no_store_response(json!({
        "source": "operator-service",
        "domain": "governance",
        "endpoint": endpoint,
        "measurement_state": measurement_state,
        "measurement_status": measurement_state,
        "execution_authority": false,
        "auth_mode_supported": ["bearer", "local-session"],
        "no_store": true,
        "contract": contract,
        "data": {
            "cloud_knowledge": cloud_data,
            "github_sources": github_data,
            "provider_states": {
                "github": if github_data.is_some() { "measured" } else { "not-measured" },
                "gitlab": "not-connected",
                "azure_devops": "not-connected"
            }
        }
    }))
}

async fn api_governance_documents(
    State(state): State<AppState>,
    headers: HeaderMap,
    RawQuery(query): RawQuery,
) -> Response {
    let path = build_upstream_path(
        "/documents",
        query.as_deref(),
        &["collection", "search", "cursor", "limit"],
    );
    let params = parse_query_params(query.as_deref());
    let db = state.db.clone();
    proxy_governance_get_or_db(
        &state,
        &headers,
        &path,
        "/api/v4/governance/documents",
        json!({
            "panel": "documents",
            "malware_scan_required": "ClamAV",
            "preserves_source_digest": true
        }),
        move || async move {
            let col = params.get("collection").map(String::as_str);
            let search = params.get("search").map(String::as_str);
            let lim = query_usize(&params, "limit");
            gov_repo::fetch_catalog_documents_filtered(&db, col, search, lim).await
        },
    )
    .await
}

async fn api_governance_trust_routing(
    State(state): State<AppState>,
    headers: HeaderMap,
    RawQuery(query): RawQuery,
) -> Response {
    let path = build_upstream_path("/trust-routing", query.as_deref(), &["window", "subscription"]);
    let params = parse_query_params(query.as_deref());
    let db = state.db.clone();
    proxy_governance_get_or_db(
        &state,
        &headers,
        &path,
        "/api/v4/governance/trust-routing",
        json!({
            "panel": "trust-routing",
            "tiers": ["T0", "T1", "T2"],
            "deterministic_first": true,
            "verifier_abstain_on_insufficient_evidence": true
        }),
        move || async move {
            let win = params.get("window").map(String::as_str);
            gov_repo::fetch_trust_routing(&db, win).await
        },
    )
    .await
}

async fn api_governance_scope(
    State(state): State<AppState>,
    headers: HeaderMap,
    RawQuery(query): RawQuery,
) -> Response {
    let path = build_upstream_path("/scope", query.as_deref(), &["axis", "subscription"]);
    let params = parse_query_params(query.as_deref());
    let db = state.db.clone();
    proxy_governance_get_or_db(
        &state,
        &headers,
        &path,
        "/api/v4/governance/scope",
        json!({
            "panel": "scope",
            "axes": ["monitoring", "action"],
            "draft_mode": "proposal_only",
            "direct_mutation_forbidden": true
        }),
        move || async move {
            let axis = params.get("axis").map(String::as_str);
            gov_repo::fetch_scope(&db, axis).await
        },
    )
    .await
}

async fn api_governance_frameworks(
    State(state): State<AppState>,
    headers: HeaderMap,
    RawQuery(query): RawQuery,
) -> Response {
    let allowed = ["framework", "search", "q", "limit", "offset"];
    let path = build_upstream_path("/frameworks", query.as_deref(), &allowed);
    let params = parse_query_params(query.as_deref());
    let db = state.db.clone();
    proxy_governance_get_or_db(
        &state,
        &headers,
        &path,
        "/api/v4/governance/frameworks",
        json!({
            "panel": "rules",
            "frameworks": ["mcsb", "caf", "wara", "waf", "msrc"],
            "real_postgres_projections": true,
            "not_measured_never_zero": true
        }),
        move || async move {
            let fw = params.get("framework").map(String::as_str);
            let search = params
                .get("search")
                .or_else(|| params.get("q"))
                .map(String::as_str);
            let lim = query_usize(&params, "limit");
            let off = query_usize(&params, "offset");
            gov_repo::fetch_frameworks(&db, fw, search, lim, off).await
        },
    )
    .await
}

async fn api_governance_security_posture(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Response {
    if let Err(msg) = validate_auth_header_strict(&headers) {
        return json_no_store_status(StatusCode::BAD_REQUEST, json!({"error": msg}));
    }
    let data = gov_repo::fetch_security_governance_posture(&state.db).await;
    let mstate = data
        .get("measurement_status")
        .and_then(Value::as_str)
        .unwrap_or("measured");
    json_no_store_status(
        StatusCode::OK,
        json!({
            "domain": "governance",
            "endpoint": "/api/v4/governance/security/posture",
            "measurement_state": mstate,
            "data": data
        }),
    )
}

async fn api_governance_security_cves(
    State(state): State<AppState>,
    headers: HeaderMap,
    RawQuery(raw_query): RawQuery,
) -> Response {
    if let Err(msg) = validate_auth_header_strict(&headers) {
        return json_no_store_status(StatusCode::BAD_REQUEST, json!({"error": msg}));
    }
    if let Err(msg) = validate_security_cves_query(raw_query.as_deref()) {
        return json_no_store_status(StatusCode::BAD_REQUEST, json!({"error": msg}));
    }
    let params = parse_query_params(raw_query.as_deref());
    if let Err(msg) = validate_security_filter_enums(&params) {
        return json_no_store_status(StatusCode::BAD_REQUEST, json!({"error": msg}));
    }
    let search = params
        .get("search")
        .or_else(|| params.get("q"))
        .map(String::as_str);
    let severity = params.get("severity").map(String::as_str);
    let exploit = params.get("exploit").map(String::as_str);
    let priority = params.get("priority").map(String::as_str);
    let runtime_only = params
        .get("runtime_only")
        .map(|s| matches!(s.as_str(), "1" | "true" | "yes"))
        .unwrap_or(false);
    let lim = query_usize(&params, "limit");
    let off = query_usize(&params, "offset");

    let data = gov_repo::fetch_security_cves(
        &state.db,
        search,
        severity,
        exploit,
        priority,
        runtime_only,
        lim,
        off,
    )
    .await;
    let mstate = data
        .get("measurement_status")
        .and_then(Value::as_str)
        .unwrap_or("measured");
    json_no_store_status(
        StatusCode::OK,
        json!({
            "domain": "governance",
            "endpoint": "/api/v4/governance/security/cves",
            "measurement_state": mstate,
            "data": data
        }),
    )
}

async fn api_governance_security_unknown_vulns(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Response {
    if let Err(msg) = validate_auth_header_strict(&headers) {
        return json_no_store_status(StatusCode::BAD_REQUEST, json!({"error": msg}));
    }
    let data = gov_repo::fetch_security_unknown_vulns(&state.db).await;
    let mstate = data
        .get("measurement_status")
        .and_then(Value::as_str)
        .unwrap_or("measured");
    json_no_store_status(
        StatusCode::OK,
        json!({
            "domain": "governance",
            "endpoint": "/api/v4/governance/security/unknown-vulns",
            "measurement_state": mstate,
            "data": data
        }),
    )
}

async fn api_governance_ontology_lineage_graph(
    State(state): State<AppState>,
    headers: HeaderMap,
    RawQuery(raw_query): RawQuery,
) -> Response {
    if let Err(msg) = validate_auth_header_strict(&headers) {
        return json_no_store_status(StatusCode::BAD_REQUEST, json!({"error": msg}));
    }
    if let Err(msg) = validate_security_cves_query(raw_query.as_deref()) {
        return json_no_store_status(StatusCode::BAD_REQUEST, json!({"error": msg}));
    }
    let params = parse_query_params(raw_query.as_deref());
    let mode = params
        .get("mode")
        .map(String::as_str)
        .unwrap_or("clustered");
    if !matches!(mode, "clustered" | "full") {
        return json_no_store_status(
            StatusCode::BAD_REQUEST,
            json!({"error": "mode must be 'clustered' or 'full'"}),
        );
    }
    let data = gov_repo::fetch_lineage_graph(&state.db, mode).await;
    let mstate = data
        .get("measurement_status")
        .and_then(Value::as_str)
        .unwrap_or("not-measured");
    json_no_store_status(
        StatusCode::OK,
        json!({
            "domain": "governance",
            "endpoint": "/api/v4/governance/ontology/lineage/graph",
            "measurement_state": mstate,
            "data": data
        }),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::build_router;
    use axum::{
        body::Body,
        http::{Request, StatusCode},
    };
    use http_body_util::BodyExt;
    use std::path::PathBuf;
    use tower::ServiceExt;

    fn repo_root() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("."))
    }

    fn offline_state() -> AppState {
        // Port 9 (discard) / closed local port + explicitly unconfigured DB guarantees deterministic offline fallback.
        let mut state = AppState::from_repo_root(repo_root(), "http://127.0.0.1:1".to_string());
        state.db = crate::db::DbHandle::from_dsn_opt(None, false);
        state
    }

    async fn read_body_string(resp: Response) -> Result<String, String> {
        let bytes = resp
            .into_body()
            .collect()
            .await
            .map_err(|e| format!("failed to collect response body: {e}"))?
            .to_bytes();
        String::from_utf8(bytes.to_vec()).map_err(|e| format!("invalid utf-8 body: {e}"))
    }

    #[test]
    fn governance_panel_manifest_has_exact_13_panels() {
        let ids = panel_ids();
        assert_eq!(ids.len(), 13);
        for required in [
            "rules",
            "trust-routing",
            "ontology",
            "scope",
            "architecture",
            "blast-radius",
            "promotion-gates",
            "workflow-builder",
            "knowledge",
            "github",
            "gitlab",
            "azure-devops",
            "documents",
        ] {
            assert!(
                ids.contains(&required),
                "missing required governance panel id: {required}"
            );
        }
        assert_eq!(api_endpoints().len(), 16);
    }

    #[test]
    fn governance_query_sanitizer_keeps_only_allowed_safe_pairs() {
        let out = build_upstream_path(
            "/rules",
            Some("origin=active&severity=critical&evil=1&search=aks&bad=foo%0a"),
            &["origin", "severity", "search"],
        );
        assert_eq!(out, "/rules?origin=active&severity=critical&search=aks");

        let blocked = build_upstream_path(
            "/rules",
            Some("search=hello world&origin=a#frag&limit=50"),
            &["search", "origin", "limit"],
        );
        assert_eq!(blocked, "/rules?limit=50");
    }

    #[tokio::test]
    async fn governance_page_renders_all_13_panels_and_svg_canvas_assets() -> Result<(), String> {
        let app = build_router(offline_state());
        let req = Request::builder()
            .uri("/governance")
            .body(Body::empty())
            .map_err(|e| format!("request build error: {e}"))?;
        let Ok(resp) = app.oneshot(req).await;
        assert_eq!(resp.status(), StatusCode::OK);
        let html = read_body_string(resp).await?;

        for panel in panel_ids() {
            let marker = format!("data-panel-id=\"{panel}\"");
            assert!(html.contains(&marker), "missing panel marker: {marker}");
        }
        assert!(html.contains("id=\"fdaiOntologyKgCanvas\""));
        assert!(html.contains("/azure-icons/kubernetes-services.svg"));
        assert!(html.contains("window.__FDAI_V4_BOOTSTRAP__"));
        assert!(!html.contains("mockup-governance.html"));
        Ok(())
    }

    #[tokio::test]
    async fn governance_all_13_api_endpoints_return_200_not_measured_when_offline(
    ) -> Result<(), String> {
        let app = build_router(offline_state());
        for endpoint in api_endpoints() {
            let req = Request::builder()
                .uri(*endpoint)
                .body(Body::empty())
                .map_err(|e| format!("request build error for {endpoint}: {e}"))?;
            let Ok(resp) = app.clone().oneshot(req).await;
            assert_eq!(
                resp.status(),
                StatusCode::OK,
                "expected 200 OK for {endpoint}"
            );
            let body = read_body_string(resp).await?;
            let parsed: Value = serde_json::from_str(&body)
                .map_err(|e| format!("invalid JSON for {endpoint}: {e}"))?;
            assert_eq!(
                parsed.get("domain").and_then(Value::as_str),
                Some("governance"),
                "wrong domain for {endpoint}"
            );
            if endpoint.starts_with("/api/v4/governance/security/") {
                assert_eq!(
                    parsed.pointer("/data/db_measurement_status").and_then(Value::as_str),
                    Some("not-measured"),
                    "security endpoint must mark DB as not-measured when offline: {endpoint}"
                );
                continue;
            }
            assert_eq!(
                parsed.get("measurement_state").and_then(Value::as_str),
                Some("not-measured"),
                "expected not-measured when upstream offline for {endpoint}"
            );
            assert_eq!(
                parsed.get("execution_authority").and_then(Value::as_bool),
                Some(false),
                "execution_authority must be false for {endpoint}"
            );
            assert!(
                parsed.get("data").map(Value::is_null).unwrap_or(false),
                "data must be null when not-measured for {endpoint}"
            );
        }
        Ok(())
    }

    #[tokio::test]
    async fn governance_endpoints_proxy_measured_upstream_payloads() -> Result<(), String> {
        let mock_upstream = Router::new()
            .route(
                "/rules",
                get(|| async {
                    Json(json!({
                        "total": 2418,
                        "filtered_total": 52,
                        "rules": [{"id": "RULE-SRE-014"}]
                    }))
                }),
            )
            .route(
                "/rules/findings-summary",
                get(|| async { Json(json!({ "evaluated": true, "counts": { "RULE-SRE-014": 18 } })) }),
            )
            .route(
                "/ontology/instances/states",
                get(|| async { Json(json!({ "total_count": 2213, "resources": [] })) }),
            )
            .route(
                "/ontology/graph",
                get(|| async { Json(json!({ "node_count": 40, "edge_count": 68 })) }),
            )
            .route(
                "/ontology/instances",
                get(|| async { Json(json!({ "resources": [{"id": "prod-aks-02"}] })) }),
            )
            .route(
                "/inventory/graph",
                get(|| async { Json(json!({ "subscriptions": 2, "vnets": 2 })) }),
            )
            .route(
                "/blast-radius",
                get(|| async { Json(json!({ "target": "pg-orders-kr", "hop_1": 4 })) }),
            )
            .route(
                "/promotion-gates",
                get(|| async { Json(json!({ "ready": 1, "blocked": 1, "recall": 1 })) }),
            )
            .route(
                "/views/workflow-apps",
                get(|| async { Json(json!({ "items": [{"name": "draft-pg-pool-advisory"}] })) }),
            )
            .route(
                "/ingestion/cloud-knowledge",
                get(|| async { Json(json!({ "available": true, "sources": [] })) }),
            )
            .route(
                "/knowledge/github/sources",
                get(|| async { Json(json!({ "count": 14, "items": [] })) }),
            )
            .route(
                "/documents",
                get(|| async { Json(json!({ "total": 52, "items": [] })) }),
            )
            .route(
                "/trust-routing",
                get(|| async { Json(json!({ "t0_pct": 78.4, "t1_pct": 16.8, "t2_pct": 4.8 })) }),
            )
            .route(
                "/scope",
                get(|| async { Json(json!({ "monitoring_count": 5, "action_count": 2 })) }),
            );

        let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .map_err(|e| format!("bind mock upstream failed: {e}"))?;
        let addr = listener
            .local_addr()
            .map_err(|e| format!("local_addr failed: {e}"))?;
        let server_handle = tokio::spawn(async move {
            let _ = axum::serve(listener, mock_upstream).await;
        });

        let state = AppState::from_repo_root(repo_root(), format!("http://{addr}"));
        let app = build_router(state);

        for endpoint in api_endpoints() {
            let req = Request::builder()
                .uri(*endpoint)
                .body(Body::empty())
                .map_err(|e| format!("request build error for {endpoint}: {e}"))?;
            let Ok(resp) = app.clone().oneshot(req).await;
            assert_eq!(resp.status(), StatusCode::OK);
            let body = read_body_string(resp).await?;
            let parsed: Value = serde_json::from_str(&body)
                .map_err(|e| format!("invalid JSON for {endpoint}: {e}"))?;
            assert_eq!(
                parsed.get("measurement_state").and_then(Value::as_str),
                Some("measured"),
                "expected measured state for {endpoint}, got {parsed}"
            );
            if !endpoint.starts_with("/api/v4/governance/security/") {
                assert_eq!(
                    parsed.get("source").and_then(Value::as_str),
                    Some("operator-service"),
                    "expected operator-service source for {endpoint}"
                );
            }
            assert!(
                !parsed.get("data").map(Value::is_null).unwrap_or(true),
                "expected non-null data for {endpoint}"
            );
        }

        server_handle.abort();
        Ok(())
    }

    #[tokio::test]
    async fn governance_partial_summary_and_fallback_and_auth_errors() -> Result<(), String> {
        // 1. Query sanitizer blocks percent-encoded CRLF, NUL, path traversal, and oversize queries.
        let crlf_blocked = build_upstream_path(
            "/rules",
            Some("search=ok%0d%0aX-Inject:1&origin=..%2fetc&severity=high&mode=foo%00bar&source=WARA"),
            &["search", "origin", "severity", "mode", "source"],
        );
        assert_eq!(crlf_blocked, "/rules?severity=high&source=WARA");

        let huge_query = "origin=active&".repeat(300);
        assert_eq!(
            build_upstream_path("/rules", Some(&huge_query), &["origin"]),
            "/rules"
        );

        let too_many = (0..25)
            .map(|i| format!("search=v{i}"))
            .collect::<Vec<_>>()
            .join("&");
        let capped = sanitize_query_string(Some(&too_many), &["search"]);
        assert_eq!(capped.split('&').count(), MAX_QUERY_PAIRS);

        // 2. Authorization header validation rejects oversize values.
        let mut bad_headers = HeaderMap::new();
        let oversized = "Bearer ".to_string() + &"a".repeat(MAX_AUTH_HEADER_BYTES + 10);
        if let Ok(val) = axum::http::HeaderValue::from_str(&oversized) {
            bad_headers.insert(header::AUTHORIZATION, val);
        }
        assert!(extract_auth(&bad_headers).is_none());

        // 3. Mock upstream simulating partial availability, 2nd-stage fallbacks, 401 and 503.
        let mock_upstream = Router::new()
            .route("/rules", get(|| async { Json(json!({ "total": 52 })) }))
            .route(
                "/rules/findings-summary",
                get(|| async { StatusCode::SERVICE_UNAVAILABLE }),
            )
            .route(
                "/ontology/instances",
                get(|| async { StatusCode::NOT_FOUND }),
            )
            .route(
                "/ontology/instances/states",
                get(|| async { Json(json!({ "total_count": 12, "resources": [] })) }),
            )
            .route(
                "/inventory/graph",
                get(|| async { StatusCode::NOT_FOUND }),
            )
            .route("/scope", get(|| async { StatusCode::UNAUTHORIZED }))
            .route(
                "/ingestion/cloud-knowledge",
                get(|| async { StatusCode::SERVICE_UNAVAILABLE }),
            )
            .route(
                "/knowledge/github/sources",
                get(|| async { Json(json!({ "count": 14, "items": [] })) }),
            );

        let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .map_err(|e| format!("bind mock upstream failed: {e}"))?;
        let addr = listener
            .local_addr()
            .map_err(|e| format!("local_addr failed: {e}"))?;
        let server_handle = tokio::spawn(async move {
            let _ = axum::serve(listener, mock_upstream).await;
        });

        let state = AppState::from_repo_root(repo_root(), format!("http://{addr}"));
        let app = build_router(state);

        // 3a. Summary returns partial (rules + instances_states ok, findings 503) with security headers.
        let req = Request::builder()
            .uri("/api/v4/governance/summary")
            .body(Body::empty())
            .map_err(|e| format!("req error: {e}"))?;
        let Ok(resp) = app.clone().oneshot(req).await;
        assert_eq!(resp.status(), StatusCode::OK);
        assert_eq!(
            resp.headers()
                .get(header::CACHE_CONTROL)
                .and_then(|v| v.to_str().ok()),
            Some("no-store")
        );
        assert_eq!(
            resp.headers()
                .get(header::X_CONTENT_TYPE_OPTIONS)
                .and_then(|v| v.to_str().ok()),
            Some("nosniff")
        );
        assert_eq!(
            resp.headers()
                .get(header::VARY)
                .and_then(|v| v.to_str().ok()),
            Some("Authorization")
        );
        let summary: Value = serde_json::from_str(&read_body_string(resp).await?)
            .map_err(|e| format!("json error: {e}"))?;
        assert_eq!(
            summary.get("measurement_state").and_then(Value::as_str),
            Some("partial")
        );

        // 3b. Ontology instances falls back from /ontology/instances (404) -> /ontology/instances/states (200).
        let req_inst = Request::builder()
            .uri("/api/v4/governance/ontology/instances")
            .body(Body::empty())
            .map_err(|e| format!("req error: {e}"))?;
        let Ok(resp_inst) = app.clone().oneshot(req_inst).await;
        let inst: Value = serde_json::from_str(&read_body_string(resp_inst).await?)
            .map_err(|e| format!("json error: {e}"))?;
        assert_eq!(
            inst.get("measurement_state").and_then(Value::as_str),
            Some("measured")
        );
        assert_eq!(
            inst.get("endpoint").and_then(Value::as_str),
            Some("/ontology/instances/states")
        );

        // 3c. Scope returns not-measured with 401 auth reason.
        let req_scope = Request::builder()
            .uri("/api/v4/governance/scope")
            .body(Body::empty())
            .map_err(|e| format!("req error: {e}"))?;
        let Ok(resp_scope) = app.clone().oneshot(req_scope).await;
        let scope: Value = serde_json::from_str(&read_body_string(resp_scope).await?)
            .map_err(|e| format!("json error: {e}"))?;
        assert_eq!(
            scope.get("measurement_state").and_then(Value::as_str),
            Some("not-measured")
        );
        assert_eq!(
            scope.get("upstream_status").and_then(Value::as_u64),
            Some(401)
        );

        // 3d. Knowledge returns partial (github ok, cloud-knowledge 503).
        let req_know = Request::builder()
            .uri("/api/v4/governance/knowledge")
            .body(Body::empty())
            .map_err(|e| format!("req error: {e}"))?;
        let Ok(resp_know) = app.clone().oneshot(req_know).await;
        let know: Value = serde_json::from_str(&read_body_string(resp_know).await?)
            .map_err(|e| format!("json error: {e}"))?;
        assert_eq!(
            know.get("measurement_state").and_then(Value::as_str),
            Some("partial")
        );

        // 3e. Unregistered path returns 404.
        let req_404 = Request::builder()
            .uri("/api/v4/governance/does-not-exist")
            .body(Body::empty())
            .map_err(|e| format!("req error: {e}"))?;
        let Ok(resp_404) = app.clone().oneshot(req_404).await;
        assert_eq!(resp_404.status(), StatusCode::NOT_FOUND);

        server_handle.abort();
        Ok(())
    }

    #[tokio::test]
    async fn governance_rule_activation_enforces_mandatory_critical_high_and_toggles_medium(
    ) -> Result<(), String> {
        // 1. Offline: Critical / High deactivation MUST be blocked immediately with 400.
        let offline_app = build_router(offline_state());
        for (rule_id, sev) in [
            ("RULE-SRE-014", "critical"),
            ("RULE-SEC-041", "High"),
            ("RULE-SRE-022", "긴급"),
            ("RULE-SRE-031", "높음"),
        ] {
            let req = Request::builder()
                .method("PATCH")
                .uri(format!("/api/v4/governance/rules/{rule_id}/activation"))
                .header(header::CONTENT_TYPE, "application/json")
                .body(Body::from(
                    json!({ "enabled": false, "severity": sev }).to_string(),
                ))
                .map_err(|e| format!("req error: {e}"))?;
            let Ok(resp) = offline_app.clone().oneshot(req).await;
            assert_eq!(
                resp.status(),
                StatusCode::BAD_REQUEST,
                "expected 400 for mandatory severity {sev}"
            );
            let parsed: Value = serde_json::from_str(&read_body_string(resp).await?)
                .map_err(|e| format!("json error: {e}"))?;
            assert_eq!(
                parsed
                    .get("error")
                    .and_then(|e| e.get("code"))
                    .and_then(Value::as_str),
                Some("mandatory_severity_locked")
            );
        }

        // 2. Offline Medium toggle returns honest not-measured with persisted=false.
        let req_off = Request::builder()
            .method("PATCH")
            .uri("/api/v4/governance/rules/RULE-COST-011/activation")
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(
                json!({ "enabled": false, "severity": "medium" }).to_string(),
            ))
            .map_err(|e| format!("req error: {e}"))?;
        let Ok(resp_off) = offline_app.clone().oneshot(req_off).await;
        assert_eq!(resp_off.status(), StatusCode::OK);
        let off_json: Value = serde_json::from_str(&read_body_string(resp_off).await?)
            .map_err(|e| format!("json error: {e}"))?;
        assert_eq!(
            off_json.get("measurement_state").and_then(Value::as_str),
            Some("not-measured")
        );
        assert_eq!(
            off_json.get("persisted").and_then(Value::as_bool),
            Some(false)
        );

        // 3. Connected mock upstream proxies Medium toggle & enforce-mandatory cleanly.
        let mock_upstream = Router::new()
            .route(
                "/rules/{rule_id}/activation",
                patch(
                    |AxumPath(rid): AxumPath<String>, Json(b): Json<Value>| async move {
                        Json(json!({
                            "status": "applied",
                            "persisted": true,
                            "pg_persisted": true,
                            "activation": {
                                "rule_id": rid,
                                "enabled": b.get("enabled").and_then(Value::as_bool).unwrap_or(true),
                                "mandatory_active": false
                            }
                        }))
                    },
                ),
            )
            .route(
                "/rules/activation/enforce-mandatory",
                post(|| async {
                    Json(json!({
                        "status": "applied",
                        "mandatory_rule_count": 12,
                        "enforced_count": 3,
                        "pg_persisted": true
                    }))
                }),
            );

        let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .map_err(|e| format!("bind failed: {e}"))?;
        let addr = listener
            .local_addr()
            .map_err(|e| format!("local_addr failed: {e}"))?;
        let server_handle = tokio::spawn(async move {
            let _ = axum::serve(listener, mock_upstream).await;
        });

        let live_app = build_router(AppState::from_repo_root(
            repo_root(),
            format!("http://{addr}"),
        ));

        let req_toggle = Request::builder()
            .method("PATCH")
            .uri("/api/v4/governance/rules/RULE-COST-011/activation")
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(
                json!({ "enabled": true, "severity": "medium", "mode": "Enforce" }).to_string(),
            ))
            .map_err(|e| format!("req error: {e}"))?;
        let Ok(resp_toggle) = live_app.clone().oneshot(req_toggle).await;
        assert_eq!(resp_toggle.status(), StatusCode::OK);
        let toggle_json: Value = serde_json::from_str(&read_body_string(resp_toggle).await?)
            .map_err(|e| format!("json error: {e}"))?;
        assert_eq!(
            toggle_json.get("measurement_state").and_then(Value::as_str),
            Some("measured")
        );
        assert_eq!(
            toggle_json.get("pg_persisted").and_then(Value::as_bool),
            Some(true)
        );

        let req_enforce = Request::builder()
            .method("POST")
            .uri("/api/v4/governance/rules/enforce-mandatory")
            .body(Body::empty())
            .map_err(|e| format!("req error: {e}"))?;
        let Ok(resp_enforce) = live_app.clone().oneshot(req_enforce).await;
        assert_eq!(resp_enforce.status(), StatusCode::OK);
        let enforce_json: Value = serde_json::from_str(&read_body_string(resp_enforce).await?)
            .map_err(|e| format!("json error: {e}"))?;
        assert_eq!(
            enforce_json.get("measurement_state").and_then(Value::as_str),
            Some("measured")
        );

        server_handle.abort();
        Ok(())
    }

    #[test]
    fn governance_query_param_decoder_and_mandatory_severity_guards() {
        let params = parse_query_params(Some(
            "search=prod%2Faks%20cluster&limit=50&offset=10&bad=a%0Ab",
        ));
        assert_eq!(
            params.get("search").map(String::as_str),
            Some("prod/aks cluster")
        );
        assert_eq!(query_usize(&params, "limit"), Some(50));
        assert_eq!(query_usize(&params, "offset"), Some(10));

        // UTF-8 percent-encoded Korean search decoding ("영역 중복")
        let ko_params = parse_query_params(Some(
            "search=%EC%98%81%EC%97%AD%20%EC%A4%91%EB%B3%B5&framework=wara",
        ));
        assert_eq!(ko_params.get("search").map(String::as_str), Some("영역 중복"));
        assert_eq!(ko_params.get("framework").map(String::as_str), Some("wara"));

        for sev in ["critical", "HIGH", "sev1", "Sev2", "P0", "p1", "긴급", "높음"] {
            assert!(
                gov_repo::is_mandatory_rule_severity(sev),
                "expected mandatory severity for {sev}"
            );
        }
        for sev in ["medium", "low", "info", "보통", "낮음", ""] {
            assert!(
                !gov_repo::is_mandatory_rule_severity(sev),
                "expected non-mandatory severity for {sev}"
            );
        }
    }

    #[tokio::test]
    async fn governance_repo_update_rule_activation_blocks_mandatory_severity() {
        let db = crate::db::DbHandle::from_dsn_opt(None, false);
        let res = gov_repo::update_rule_activation(
            &db,
            "RULE-CRIT-001",
            false,
            "critical",
            "tester",
            "attempt disable",
            "idem-test-1",
        )
        .await;
        assert!(res.is_err());
        if let Err((status, body)) = res {
            assert_eq!(status, 409);
            assert_eq!(
                body.get("mandatory_active").and_then(Value::as_bool),
                Some(true)
            );
            assert_eq!(
                body.get("can_deactivate").and_then(Value::as_bool),
                Some(false)
            );
        }
    }

    #[tokio::test]
    async fn governance_frameworks_endpoint_returns_not_measured_offline_and_proxies_upstream(
    ) -> Result<(), String> {
        let offline_app = build_router(offline_state());
        let req = Request::builder()
            .uri("/api/v4/governance/frameworks?framework=mcsb&limit=50")
            .body(Body::empty())
            .map_err(|e| format!("req error: {e}"))?;
        let Ok(resp) = offline_app.oneshot(req).await;
        assert_eq!(resp.status(), StatusCode::OK);
        let parsed: Value = serde_json::from_str(&read_body_string(resp).await?)
            .map_err(|e| format!("json error: {e}"))?;
        assert_eq!(
            parsed.get("measurement_state").and_then(Value::as_str),
            Some("not-measured")
        );
        assert!(parsed.get("data").map(Value::is_null).unwrap_or(false));

        let mock_upstream = Router::new().route(
            "/frameworks",
            get(|| async {
                Json(json!({
                    "counts": { "mcsb": 86, "caf": 15, "wara": 456, "waf": 59, "msrc": 0 },
                    "controls": [{ "control_id": "AM-1", "title": "Track asset inventory" }]
                }))
            }),
        );
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .map_err(|e| format!("bind failed: {e}"))?;
        let addr = listener
            .local_addr()
            .map_err(|e| format!("local_addr failed: {e}"))?;
        let server_handle = tokio::spawn(async move {
            let _ = axum::serve(listener, mock_upstream).await;
        });

        let mut st = AppState::from_repo_root(repo_root(), format!("http://{addr}"));
        st.db = crate::db::DbHandle::from_dsn_opt(None, false);
        let live_app = build_router(st);
        let req_live = Request::builder()
            .uri("/api/v4/governance/frameworks?framework=mcsb")
            .body(Body::empty())
            .map_err(|e| format!("req error: {e}"))?;
        let Ok(resp_live) = live_app.oneshot(req_live).await;
        assert_eq!(resp_live.status(), StatusCode::OK);
        let live_json: Value = serde_json::from_str(&read_body_string(resp_live).await?)
            .map_err(|e| format!("json error: {e}"))?;
        assert_eq!(
            live_json.get("measurement_state").and_then(Value::as_str),
            Some("measured")
        );
        assert_eq!(
            live_json
                .get("data")
                .and_then(|d| d.get("counts"))
                .and_then(|c| c.get("mcsb"))
                .and_then(Value::as_u64),
            Some(86)
        );

        server_handle.abort();
        Ok(())
    }

    #[tokio::test]
    async fn governance_ontology_instances_states_and_display_name_normalization() -> Result<(), String>
    {
        // 1. Offline states endpoint returns 200 not-measured (never 404).
        let offline_app = build_router(offline_state());
        let req = Request::builder()
            .uri("/api/v4/governance/ontology/instances/states")
            .body(Body::empty())
            .map_err(|e| format!("req error: {e}"))?;
        let Ok(resp) = offline_app.oneshot(req).await;
        assert_eq!(resp.status(), StatusCode::OK);
        let parsed: Value = serde_json::from_str(&read_body_string(resp).await?)
            .map_err(|e| format!("json error: {e}"))?;
        assert_eq!(
            parsed.get("measurement_state").and_then(Value::as_str),
            Some("not-measured")
        );

        // 2. Nameless ontology_resource display_name normalization eliminates raw hash IDs.
        let bv = gov_repo::resolve_ontology_display_name(
            "benchmark-validation:0122ce51c2f286fd234c4224713c0a56",
            "BenchmarkValidation",
            &json!({ "benchmark_id": "sregym", "mechanism_id": "kubernetes_quota_revert_authority" }),
        );
        assert_eq!(bv, "sregym · kubernetes quota revert authority");

        let prop = gov_repo::resolve_ontology_display_name(
            "property.cache.zones",
            "Property",
            &json!({ "semantic_id": "resilience.availability.zones" }),
        );
        assert_eq!(prop, "cache.zones (resilience.availability.zones)");

        let rt = gov_repo::resolve_ontology_display_name(
            "action-group",
            "ResourceType",
            &json!({ "provider_type": "Microsoft.Insights/actionGroups" }),
        );
        assert_eq!(rt, "action group");

        let rc = gov_repo::resolve_ontology_display_name(
            "review-cf98713f993541d8a5e4db1b948761a9",
            "ReviewCase",
            &json!({ "status": "open" }),
        );
        assert_eq!(rc, "검토 케이스 · cf98713f (open)");
        assert_eq!(gov_repo::ontology_type_label_ko("BenchmarkValidation"), "벤치마크 검증");
        assert_eq!(gov_repo::ontology_type_label_ko("Resource"), "클라우드 리소스");
        Ok(())
    }

    #[tokio::test]
    async fn governance_architecture_forwards_scope_and_returns_dynamic_graph_schema(
    ) -> Result<(), String> {
        let mock_upstream = Router::new().route(
            "/inventory/graph",
            get(|RawQuery(q): RawQuery| async move {
                Json(json!({
                    "active_scope": q.unwrap_or_default(),
                    "views": [{ "id": "all", "label": "전체 실측 스코프", "count": 808 }],
                    "containers": [{ "id": "rg:demo", "kind": "resource_group", "name": "demo", "subtitle": "westus3", "parent_id": null, "resource_count": 2 }],
                    "nodes": [
                        { "id": "n1", "name": "vnet-1", "display_name": "vnet-1", "resource_type": "network.vnet", "container_id": "rg:demo", "status": "observed" },
                        { "id": "n2", "name": "pe-1", "display_name": "pe-1", "resource_type": "network.private-endpoint", "container_id": "rg:demo", "status": "observed" }
                    ],
                    "edges": [
                        { "id": "e1", "source": "n2", "target": "n1", "link_type": "attached_to", "category": "pe" }
                    ],
                    "summary": {
                        "vnet_count": 1,
                        "subnet_count": 0,
                        "private_endpoint_count": 1,
                        "nsg_count": 0,
                        "firewall_count": 0,
                        "peering_count": 0,
                        "route_count": 0,
                        "total_resources": 2,
                        "total_links": 1
                    }
                }))
            }),
        );
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .map_err(|e| format!("bind failed: {e}"))?;
        let addr = listener
            .local_addr()
            .map_err(|e| format!("local_addr failed: {e}"))?;
        let server_handle = tokio::spawn(async move {
            let _ = axum::serve(listener, mock_upstream).await;
        });

        let mut st = AppState::from_repo_root(repo_root(), format!("http://{addr}"));
        st.db = crate::db::DbHandle::from_dsn_opt(None, false);
        let app = build_router(st);

        let req = Request::builder()
            .uri("/api/v4/governance/architecture?scope=rg:demo")
            .body(Body::empty())
            .map_err(|e| format!("req error: {e}"))?;
        let Ok(resp) = app.oneshot(req).await;
        assert_eq!(resp.status(), StatusCode::OK);
        let parsed: Value = serde_json::from_str(&read_body_string(resp).await?)
            .map_err(|e| format!("json error: {e}"))?;
        assert_eq!(
            parsed.get("measurement_state").and_then(Value::as_str),
            Some("measured")
        );
        let data = parsed.get("data").ok_or("missing data")?;
        assert!(data.get("views").and_then(Value::as_array).is_some());
        assert!(data.get("containers").and_then(Value::as_array).is_some());
        assert_eq!(
            data.get("nodes").and_then(Value::as_array).map(Vec::len),
            Some(2)
        );
        assert_eq!(
            data.get("edges").and_then(Value::as_array).map(Vec::len),
            Some(1)
        );
        assert_eq!(
            data.get("summary")
                .and_then(|s| s.get("private_endpoint_count"))
                .and_then(Value::as_u64),
            Some(1)
        );
        server_handle.abort();
        Ok(())
    }

    #[test]
    fn governance_producer_humanizes_uuids_and_resource_types() {
        assert!(gov_repo::is_uuid_like(
            "4c5696bc-c315-164d-f627-ce5ed0aad5a0"
        ));
        assert!(!gov_repo::is_uuid_like("rg-fdai-dev-wus3"));

        let rbac_props = json!({
            "name": "4c5696bc-c315-164d-f627-ce5ed0aad5a0",
            "resource_type": "authorization.role-assignment"
        });
        let rbac_name = gov_repo::resolve_ontology_display_name(
            "scope-demo/resource-group/rg-demo/providers/microsoft.authorization/roleassignments/4c5696bc-c315-164d-f627-ce5ed0aad5a0",
            "Resource",
            &rbac_props,
        );
        assert!(
            rbac_name.contains("RBAC 역할 할당") && !rbac_name.contains("ce5ed0aad5a0"),
            "bare UUID must be humanized: got {rbac_name}"
        );

        let rg_type_props = json!({ "provider_type": "Microsoft.Resources/resourceGroups" });
        let rg_type_name =
            gov_repo::resolve_ontology_display_name("resource-group", "ResourceType", &rg_type_props);
        assert_eq!(rg_type_name, "리소스 그룹");

        assert_eq!(
            gov_repo::resource_type_label_ko("authorization.role-assignment"),
            "RBAC 역할 할당"
        );
        assert_eq!(
            gov_repo::resource_type_label_ko("anomaly-alert-rule"),
            "이상 탐지 알림 규칙"
        );
        assert_eq!(
            gov_repo::resource_type_label_ko("api-gateway"),
            "API 게이트웨이"
        );
        assert_eq!(
            gov_repo::resource_type_label_ko("compute.vm-scale-set"),
            "가상 머신 확장 집합 (VMSS)"
        );
    }

    #[tokio::test]
    async fn governance_knowledge_provider_routes_validate_and_fail_closed_offline(
    ) -> Result<(), String> {
        let app = build_router(offline_state());
        for provider in ["github", "gitlab", "azure-devops"] {
            let req = Request::builder()
                .uri(format!("/api/v4/governance/knowledge/{provider}"))
                .body(Body::empty())
                .map_err(|e| format!("req build error: {e}"))?;
            let Ok(resp) = app.clone().oneshot(req).await;
            assert_eq!(resp.status(), StatusCode::OK);
            let parsed: Value = serde_json::from_str(&read_body_string(resp).await?)
                .map_err(|e| format!("json error: {e}"))?;
            assert_eq!(
                parsed.get("measurement_state").and_then(Value::as_str),
                Some("not-measured")
            );
        }

        let bad_req = Request::builder()
            .uri("/api/v4/governance/knowledge/unsupported-provider")
            .body(Body::empty())
            .map_err(|e| format!("bad req build error: {e}"))?;
        let Ok(bad_resp) = app.oneshot(bad_req).await;
        assert_eq!(bad_resp.status(), StatusCode::BAD_REQUEST);
        Ok(())
    }

    #[tokio::test]
    async fn governance_template_enforces_humanized_title_zero_dead_links_and_deeplink_hooks(
    ) -> Result<(), String> {
        let app = build_router(offline_state());
        let req = Request::builder()
            .uri("/governance")
            .body(Body::empty())
            .map_err(|e| format!("req build error: {e}"))?;
        let Ok(resp) = app.oneshot(req).await;
        assert_eq!(resp.status(), StatusCode::OK);
        let html = read_body_string(resp).await?;

        assert!(html.contains("<title>FDAI 운영 콘솔 — 거버넌스</title>"));
        assert!(!html.contains("href=\"#\""));
        assert!(!html.contains("Shared Design System"));
        assert!(!html.contains("소속 리소스 그룹"));
        assert!(html.contains("window.fdaiV4Humanize"));
        assert!(html.contains("window.fdaiV4Selection"));
        assert!(html.contains("window.fdaiV4Shimmer"));
        assert!(html.contains("data-resource-id"));
        assert!(html.contains("node-hit-area"));
        Ok(())
    }

    #[tokio::test]
    async fn governance_security_cves_and_unknown_vulns_expose_msrc_catalog_and_10_lenses(
    ) -> Result<(), String> {
        let msrc = gov_repo::load_msrc_csaf_catalog_cached();
        assert!(
            msrc.cves.len() >= 9000,
            "expected >=9000 MSRC CSAF CVEs, got {}",
            msrc.cves.len()
        );
        assert!(msrc.exploited_count >= 100);
        assert!(msrc.publicly_disclosed_count >= 150);
        assert!(msrc.product_mapping_count >= 1800);

        let cs = gov_repo::load_code_security_governance_cached();
        assert_eq!(cs.lenses.len(), 10, "expected 10 off-path LLM lenses");
        assert!(cs.lenses.iter().any(|l| l.id == "memory-safety"));
        assert!(cs.lenses.iter().any(|l| l.id == "missing-authorization"));
        assert!(cs.lens_quorum >= 2);
        assert!(cs.analysis_components.len() >= 6);
        assert!(cs.policy_docs.len() >= 4);

        let app = build_router(offline_state());

        let req_cves = Request::builder()
            .uri("/api/v4/governance/security/cves?exploit=exploited&limit=15")
            .body(Body::empty())
            .map_err(|e| format!("req build error: {e}"))?;
        let Ok(resp_cves) = app.clone().oneshot(req_cves).await;
        assert_eq!(resp_cves.status(), StatusCode::OK);
        let parsed_cves: Value = serde_json::from_str(&read_body_string(resp_cves).await?)
            .map_err(|e| format!("json error: {e}"))?;
        assert_eq!(
            parsed_cves.get("measurement_state").and_then(Value::as_str),
            Some("measured")
        );
        let cve_arr = parsed_cves
            .pointer("/data/cves")
            .and_then(Value::as_array)
            .ok_or_else(|| "missing cves array".to_string())?;
        assert!(!cve_arr.is_empty() && cve_arr.len() <= 15);
        assert!(cve_arr
            .iter()
            .all(|c| c.get("exploit_status").and_then(Value::as_str) == Some("exploited")));
        assert!(cve_arr.iter().all(|c| {
            let t = c.get("title_ko").and_then(Value::as_str).unwrap_or("").trim();
            !t.is_empty() && !t.to_ascii_uppercase().starts_with("CVE-")
        }));

        let req_unk = Request::builder()
            .uri("/api/v4/governance/security/unknown-vulns")
            .body(Body::empty())
            .map_err(|e| format!("req build error: {e}"))?;
        let Ok(resp_unk) = app.clone().oneshot(req_unk).await;
        assert_eq!(resp_unk.status(), StatusCode::OK);
        let parsed_unk: Value = serde_json::from_str(&read_body_string(resp_unk).await?)
            .map_err(|e| format!("json error: {e}"))?;
        assert_eq!(
            parsed_unk
                .pointer("/data/constitutional_invariant/non_mixing_enforced")
                .and_then(Value::as_bool),
            Some(true)
        );
        assert_eq!(
            parsed_unk
                .pointer("/data/summary/lens_count")
                .and_then(Value::as_u64),
            Some(10)
        );

        let req_pos = Request::builder()
            .uri("/api/v4/governance/security/posture")
            .body(Body::empty())
            .map_err(|e| format!("req build error: {e}"))?;
        let Ok(resp_pos) = app.oneshot(req_pos).await;
        assert_eq!(resp_pos.status(), StatusCode::OK);
        let parsed_pos: Value = serde_json::from_str(&read_body_string(resp_pos).await?)
            .map_err(|e| format!("json error: {e}"))?;
        assert!(
            parsed_pos
                .pointer("/data/security_assurance/total_cves")
                .and_then(Value::as_u64)
                .unwrap_or(0)
                >= 9000
        );
        Ok(())
    }

    #[tokio::test]
    async fn governance_security_redteam_blocks_malicious_queries_and_reports_offline_db_honestly(
    ) -> Result<(), String> {
        let app = build_router(offline_state());

        // 1. Block CRLF / path traversal / oversized query strings
        for bad_uri in [
            "/api/v4/governance/security/cves?search=abc%0d%0aX-Injected:1",
            "/api/v4/governance/security/cves?search=../../etc/passwd",
            "/api/v4/governance/security/cves?severity=../../etc",
            "/api/v4/governance/security/cves?exploit=drop_table",
            "/api/v4/governance/security/cves?priority=P99",
            "/api/v4/governance/security/cves?limit=999999",
            "/api/v4/governance/security/cves?runtime_only=maybe",
        ] {
            let req = Request::builder()
                .uri(bad_uri)
                .body(Body::empty())
                .map_err(|e| format!("bad uri req error: {e}"))?;
            let Ok(resp) = app.clone().oneshot(req).await;
            assert_eq!(
                resp.status(),
                StatusCode::BAD_REQUEST,
                "expected 400 BAD_REQUEST for malicious URI: {bad_uri}"
            );
            assert!(
                matches!(
                    resp.headers()
                        .get(header::REFERRER_POLICY)
                        .and_then(|v| v.to_str().ok()),
                    Some("no-referrer" | "strict-origin-when-cross-origin")
                ),
                "expected strict Referrer-Policy header for {bad_uri}"
            );
        }

        // 2. Block oversized Authorization header
        let huge_auth = format!("Bearer {}", "A".repeat(MAX_AUTH_HEADER_BYTES + 16));
        let req_auth = Request::builder()
            .uri("/api/v4/governance/security/posture")
            .header(header::AUTHORIZATION, huge_auth)
            .body(Body::empty())
            .map_err(|e| format!("auth req error: {e}"))?;
        let Ok(resp_auth) = app.clone().oneshot(req_auth).await;
        assert_eq!(resp_auth.status(), StatusCode::BAD_REQUEST);

        // 3. Offline DB must NEVER fabricate 0 for runtime metrics (not-measured != 0)
        let req_unk = Request::builder()
            .uri("/api/v4/governance/security/unknown-vulns")
            .body(Body::empty())
            .map_err(|e| format!("unk req error: {e}"))?;
        let Ok(resp_unk) = app.clone().oneshot(req_unk).await;
        assert_eq!(resp_unk.status(), StatusCode::OK);
        let unk_json: Value = serde_json::from_str(&read_body_string(resp_unk).await?)
            .map_err(|e| format!("json error: {e}"))?;
        assert_eq!(
            unk_json
                .pointer("/data/db_measurement_status")
                .and_then(Value::as_str),
            Some("not-measured")
        );
        assert!(
            unk_json
                .pointer("/data/confidence_ladder/confirmed_or_scanner_total")
                .map(Value::is_null)
                .unwrap_or(false),
            "offline DB must report null instead of fabricating 0"
        );

        let req_pos = Request::builder()
            .uri("/api/v4/governance/security/posture")
            .body(Body::empty())
            .map_err(|e| format!("pos req error: {e}"))?;
        let Ok(resp_pos) = app.clone().oneshot(req_pos).await;
        let pos_json: Value = serde_json::from_str(&read_body_string(resp_pos).await?)
            .map_err(|e| format!("json error: {e}"))?;
        assert_eq!(
            pos_json
                .pointer("/data/db_measurement_status")
                .and_then(Value::as_str),
            Some("not-measured")
        );
        assert!(pos_json
            .pointer("/data/security_rules/security_rules_total")
            .map(Value::is_null)
            .unwrap_or(false));

        // 4. Lineage Graph API validates mode enum (400) and fails closed offline (not-measured)
        let bad_lin = Request::builder()
            .uri("/api/v4/governance/ontology/lineage/graph?mode=invalid")
            .body(Body::empty())
            .map_err(|e| format!("bad lin req: {e}"))?;
        let Ok(resp_bad_lin) = app.clone().oneshot(bad_lin).await;
        assert_eq!(resp_bad_lin.status(), StatusCode::BAD_REQUEST);

        let off_lin = Request::builder()
            .uri("/api/v4/governance/ontology/lineage/graph?mode=full")
            .body(Body::empty())
            .map_err(|e| format!("off lin req: {e}"))?;
        let Ok(resp_off_lin) = app.oneshot(off_lin).await;
        assert_eq!(resp_off_lin.status(), StatusCode::OK);
        let lin_json: Value = serde_json::from_str(&read_body_string(resp_off_lin).await?)
            .map_err(|e| format!("json error: {e}"))?;
        assert_eq!(
            lin_json.get("measurement_state").and_then(Value::as_str),
            Some("not-measured")
        );
        Ok(())
    }
}
