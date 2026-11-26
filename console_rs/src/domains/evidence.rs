//! Domain 5: 감사·이력 (`evidence`, 6 panels).
//! Owned by the `evidence` domain stream.
//!
//! Pure-Rust Axum handlers for:
//! - `GET /evidence`
//! - `GET /api/v4/evidence/summary`
//! - `GET /api/v4/evidence/audit`
//! - `GET /api/v4/evidence/trace`
//! - `GET /api/v4/evidence/rca`
//! - `GET /api/v4/evidence/browser-evidence`
//! - `GET /api/v4/evidence/conversations`
//! - `GET /api/v4/evidence/reports`

use axum::{
    extract::State,
    http::{header, HeaderMap, StatusCode, Uri},
    response::{IntoResponse, Response},
    routing::get,
    Json, Router,
};
use serde_json::{json, Value};

use crate::{
    shell::{finalize_v4_html, html_response},
    upstream::UpstreamOutcome,
    AppState,
};

const TEMPLATE: &str = include_str!("../../templates/evidence.html");

const PANELS: [&str; 6] = [
    "audit",
    "trace",
    "rca",
    "browser-evidence",
    "conversation-search",
    "reports",
];

const SCHEMA_VERSION: &str = "v4";
const MAX_QUERY_BYTES: usize = 2048;
const MAX_QUERY_PARAMS: usize = 32;
const MAX_SEARCH_QUERY_BYTES: usize = 256;
const MAX_AUTH_HEADER_BYTES: usize = 4096;
const MIN_LIMIT: u64 = 1;
const MAX_LIMIT: u64 = 100;

const AUDIT_QUERY_KEYS: [&str; 16] = [
    "limit",
    "cursor",
    "before_seq",
    "category",
    "action_kind",
    "correlation_id",
    "mode",
    "window",
    "q",
    "search",
    "agent",
    "outcome",
    "tier",
    "vertical",
    "from_seq",
    "through_seq",
];

const AUDIT_ALLOWED_MODES: [&str; 4] = ["shadow", "enforce", "auto", "all"];
const AUDIT_ALLOWED_CATEGORIES: [&str; 5] = ["all", "approval", "action", "observe", "shadow"];
const AUDIT_ALLOWED_WINDOWS: [&str; 5] = ["24h", "7d", "30d", "90d", "all"];
const RCA_QUERY_KEYS: [&str; 2] = ["correlation_id", "case_id"];
const BROWSER_QUERY_KEYS: [&str; 5] = ["retention", "finding", "cursor", "limit", "q"];
const BROWSER_ALLOWED_RETENTION: [&str; 5] = [
    "all",
    "retained",
    "held",
    "expiring",
    "expired_pending_purge",
];
const BROWSER_ALLOWED_FINDING: [&str; 3] = ["all", "present", "clear"];
const CONVERSATION_QUERY_KEYS: [&str; 6] = ["q", "mode", "role", "channel", "cursor", "limit"];
const CONVERSATION_ALLOWED_MODES: [&str; 3] = ["terms", "phrase", "prefix"];
const CONVERSATION_ALLOWED_ROLES: [&str; 5] = ["all", "operator", "assistant", "tool", "system"];
const REPORT_QUERY_KEYS: [&str; 3] = ["report_id", "window", "scope"];
const REPORT_ALLOWED_WINDOWS: [&str; 4] = ["24h", "7d", "30d", "90d"];

const SENSITIVE_BROWSER_KEYS: [&str; 10] = [
    "raw_html",
    "raw_body",
    "raw_dom",
    "raw_content",
    "script_source",
    "cookies",
    "set_cookie",
    "authorization",
    "session_token",
    "access_token",
];

pub fn panel_ids() -> &'static [&'static str] {
    &PANELS
}

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/evidence", get(page_evidence))
        .route("/api/v4/evidence/summary", get(api_evidence_summary))
        .route("/api/v4/evidence/audit", get(api_evidence_audit))
        .route("/api/v4/evidence/trace", get(api_evidence_trace))
        .route("/api/v4/evidence/rca", get(api_evidence_rca))
        .route(
            "/api/v4/evidence/browser-evidence",
            get(api_evidence_browser_evidence),
        )
        .route(
            "/api/v4/evidence/conversations",
            get(api_evidence_conversations),
        )
        .route("/api/v4/evidence/reports", get(api_evidence_reports))
}

async fn page_evidence(State(state): State<AppState>) -> Response {
    let html = finalize_v4_html(
        TEMPLATE,
        "evidence",
        "audit",
        &state.operator_url,
        json!({
            "panels": PANELS,
            "api_endpoints": {
                "summary": "/api/v4/evidence/summary",
                "audit": "/api/v4/evidence/audit",
                "trace": "/api/v4/evidence/trace",
                "rca": "/api/v4/evidence/rca",
                "browser_evidence": "/api/v4/evidence/browser-evidence",
                "conversations": "/api/v4/evidence/conversations",
                "reports": "/api/v4/evidence/reports"
            }
        }),
    );
    html_response(html)
}

async fn api_evidence_summary(State(state): State<AppState>, headers: HeaderMap) -> Response {
    let auth = extract_auth(&headers);
    let (audit_up, browser_up, rca_up) = tokio::join!(
        state.upstream.get_json("/audit?limit=25", auth),
        state.upstream.get_json("/browser-evidence?limit=20", auth),
        state.upstream.get_json("/rca", auth),
    );

    let audit_measured = is_measured(&audit_up);
    let browser_measured = is_measured(&browser_up);
    let rca_measured = is_measured(&rca_up);

    let audit_integrity = match (&audit_up.payload, audit_measured) {
        (Some(payload), true) => extract_audit_integrity(payload),
        _ => not_measured_integrity(&upstream_unavailable_reason(&audit_up)),
    };
    let (integrity_verified, integrity_alert) = audit_integrity_flags(&audit_integrity);

    let any_measured = audit_measured || browser_measured || rca_measured;
    if !any_measured
        && !audit_up.reachable
        && !browser_up.reachable
        && !rca_up.reachable
        && state.db.is_configured()
    {
        let db_summary = crate::repos::evidence::fetch_evidence_summary(&state.db).await;
        if is_db_measured(&db_summary) {
            let db_integrity = extract_audit_integrity(&db_summary);
            let (db_verified, db_alert) = audit_integrity_flags(&db_integrity);
            return json_api_response(
                StatusCode::OK,
                json!({
                    "schema_version": SCHEMA_VERSION,
                    "source": "postgres-direct",
                    "domain": "evidence",
                    "domain_panels_count": PANELS.len(),
                    "endpoint": "/api/v4/evidence/summary",
                    "panels": PANELS,
                    "measurement_state": "measured",
                    "measurement_status": "measured",
                    "availability": "complete",
                    "upstream_url": sanitize_upstream_url(state.upstream.base_url()),
                    "upstream_reachable": false,
                    "db_configured": true,
                    "read_only": true,
                    "append_only": true,
                    "reason": Value::Null,
                    "audit_integrity": db_integrity,
                    "integrity_verified": db_verified,
                    "integrity_alert": db_alert,
                    "sources": {
                        "audit": { "endpoint": "postgres-direct:audit_log", "measurement_state": "measured", "reachable": true, "status": 200 },
                        "browser_evidence": { "endpoint": "postgres-direct:browser_evidence_artifact", "measurement_state": "measured", "reachable": true, "status": 200 },
                        "rca": { "endpoint": "postgres-direct:operator_incident_projection", "measurement_state": "measured", "reachable": true, "status": 200 }
                    },
                    "data": db_summary
                }),
            );
        }
    }

    let measurement_state = if any_measured {
        "measured"
    } else {
        "not-measured"
    };
    let availability = if audit_measured && browser_measured && rca_measured {
        "complete"
    } else if any_measured {
        "partial"
    } else {
        "not-measured"
    };

    let reason = if any_measured {
        Value::Null
    } else {
        Value::String(upstream_unavailable_reason(&audit_up))
    };

    let audit_source = source_status_json("/audit", &audit_up);
    let browser_source = source_status_json("/browser-evidence", &browser_up);
    let rca_source = source_status_json("/rca", &rca_up);

    let sanitized_browser = if browser_measured {
        browser_up
            .payload
            .map(|p| scrub_browser_evidence_payload(p).0)
    } else {
        None
    };

    json_api_response(
        StatusCode::OK,
        json!({
            "schema_version": SCHEMA_VERSION,
            "source": if any_measured { "operator-service" } else { "console-v4-rust" },
            "domain": "evidence",
            "domain_panels_count": PANELS.len(),
            "endpoint": "/api/v4/evidence/summary",
            "panels": PANELS,
            "measurement_state": measurement_state,
            "availability": availability,
            "upstream_url": sanitize_upstream_url(state.upstream.base_url()),
            "read_only": true,
            "append_only": true,
            "reason": reason,
            "audit_integrity": audit_integrity,
            "integrity_verified": integrity_verified,
            "integrity_alert": integrity_alert,
            "sources": {
                "audit": audit_source,
                "browser_evidence": browser_source,
                "rca": rca_source
            },
            "data": if any_measured {
                json!({
                    "audit": if audit_measured { audit_up.payload } else { None },
                    "browser_evidence": sanitized_browser,
                    "rca": if rca_measured { rca_up.payload } else { None }
                })
            } else {
                Value::Null
            }
        }),
    )
}

async fn api_evidence_audit(
    State(state): State<AppState>,
    headers: HeaderMap,
    uri: Uri,
) -> Response {
    let pairs = parse_query_pairs(uri.query());
    if let Err(err) = validate_limit_param(&pairs) {
        return err.into_response();
    }
    if let Err(err) = validate_enum_param(&pairs, "mode", &AUDIT_ALLOWED_MODES) {
        return err.into_response();
    }
    if let Err(err) = validate_enum_param(&pairs, "category", &AUDIT_ALLOWED_CATEGORIES) {
        return err.into_response();
    }
    if let Err(err) = validate_enum_param(&pairs, "window", &AUDIT_ALLOWED_WINDOWS) {
        return err.into_response();
    }
    if let Err(err) = validate_search_query(&pairs, "q") {
        return err.into_response();
    }
    if let Err(err) = validate_search_query(&pairs, "search") {
        return err.into_response();
    }
    if let Err(err) = validate_optional_identifier(&pairs, "correlation_id", "invalid_correlation_id") {
        return err.into_response();
    }
    for key in ["cursor", "action_kind", "agent", "outcome", "tier", "vertical"] {
        if let Err(err) = validate_optional_identifier(&pairs, key, "invalid_query_parameter") {
            return err.into_response();
        }
    }
    let from_seq = match validate_u64_param(&pairs, "from_seq") {
        Ok(v) => v,
        Err(err) => return err.into_response(),
    };
    let through_seq = match validate_u64_param(&pairs, "through_seq") {
        Ok(v) => v,
        Err(err) => return err.into_response(),
    };
    let before_seq = match validate_u64_param(&pairs, "before_seq") {
        Ok(v) => v,
        Err(err) => return err.into_response(),
    };
    if let (Some(from_v), Some(through_v)) = (from_seq, through_seq) {
        if from_v > through_v {
            return bad_request_response(
                "invalid_seq_range",
                "from_seq must be less than or equal to through_seq",
            );
        }
    }

    let auth = extract_auth(&headers);
    let path = build_forwarded_path("/audit", &pairs, &AUDIT_QUERY_KEYS);
    let up = state.upstream.get_json(&path, auth).await;

    if is_measured(&up) {
        if let Some(payload) = up.payload {
            let audit_integrity = extract_audit_integrity(&payload);
            let (integrity_verified, integrity_alert) = audit_integrity_flags(&audit_integrity);
            return json_api_response(
                StatusCode::OK,
                json!({
                    "schema_version": SCHEMA_VERSION,
                    "source": "operator-service",
                    "domain": "evidence",
                    "panel": "audit",
                    "endpoint": path,
                    "measurement_state": "measured",
                    "measurement_status": "measured",
                    "read_only": true,
                    "append_only": true,
                    "upstream_reachable": true,
                    "upstream_status": up.status,
                    "audit_integrity": audit_integrity,
                    "integrity_verified": integrity_verified,
                    "integrity_alert": integrity_alert,
                    "data": payload
                }),
            );
        }
    }

    if !up.reachable && state.db.is_configured() {
        let limit_val = find_query(&pairs, "limit").and_then(|v| v.parse::<usize>().ok());
        let search_val = find_query(&pairs, "search")
            .filter(|s| !s.trim().is_empty())
            .or_else(|| find_query(&pairs, "q").filter(|s| !s.trim().is_empty()));
        let effective_before = before_seq
            .and_then(|v| i64::try_from(v).ok())
            .or_else(|| find_query(&pairs, "cursor").and_then(|c| c.parse::<i64>().ok()));
        let filter = crate::repos::evidence::AuditChainFilter {
            correlation_id: find_query(&pairs, "correlation_id"),
            search: search_val,
            category: find_query(&pairs, "category"),
            mode: find_query(&pairs, "mode"),
            action_kind: find_query(&pairs, "action_kind"),
            agent: find_query(&pairs, "agent"),
            window: find_query(&pairs, "window"),
            from_seq: from_seq.and_then(|v| i64::try_from(v).ok()),
            through_seq: through_seq.and_then(|v| i64::try_from(v).ok()),
            before_seq: effective_before,
            limit: limit_val,
        };
        let db_payload = crate::repos::evidence::fetch_audit_chain_filtered(&state.db, &filter).await;
        if is_db_measured(&db_payload) {
            let audit_integrity = extract_audit_integrity(&db_payload);
            let (integrity_verified, integrity_alert) = audit_integrity_flags(&audit_integrity);
            return json_api_response(
                StatusCode::OK,
                json!({
                    "schema_version": SCHEMA_VERSION,
                    "source": "postgres-direct",
                    "domain": "evidence",
                    "panel": "audit",
                    "endpoint": path,
                    "measurement_state": "measured",
                    "measurement_status": "measured",
                    "progressive_disclosure": true,
                    "read_only": true,
                    "append_only": true,
                    "upstream_reachable": false,
                    "db_configured": true,
                    "audit_integrity": audit_integrity,
                    "integrity_verified": integrity_verified,
                    "integrity_alert": integrity_alert,
                    "data": db_payload
                }),
            );
        }
    }

    let reason = upstream_unavailable_reason(&up);
    let audit_integrity = not_measured_integrity(&reason);
    let (integrity_verified, integrity_alert) = audit_integrity_flags(&audit_integrity);
    json_api_response(
        StatusCode::OK,
        json!({
            "schema_version": SCHEMA_VERSION,
            "source": "console-v4-rust",
            "domain": "evidence",
            "panel": "audit",
            "endpoint": path,
            "measurement_state": "not-measured",
            "upstream_url": sanitize_upstream_url(state.upstream.base_url()),
            "upstream_reachable": up.reachable,
            "upstream_status": up.status,
            "read_only": true,
            "append_only": true,
            "reason": reason,
            "audit_integrity": audit_integrity,
            "integrity_verified": integrity_verified,
            "integrity_alert": integrity_alert,
            "data": Value::Null
        }),
    )
}

async fn api_evidence_trace(
    State(state): State<AppState>,
    headers: HeaderMap,
    uri: Uri,
) -> Response {
    let pairs = parse_query_pairs(uri.query());
    if let Err(err) = validate_limit_param(&pairs) {
        return err.into_response();
    }
    let corr = find_query(&pairs, "correlation_id")
        .map(str::trim)
        .filter(|v| !v.is_empty());

    if let Some(id) = corr {
        if !is_safe_correlation_id(id) {
            return bad_request_response(
                "invalid_correlation_id",
                "correlation_id must be 1..=128 ASCII [A-Za-z0-9._:-] characters without '..'",
            );
        }
    }

    let auth = extract_auth(&headers);
    let (mode, path) = match corr {
        Some(id) => ("correlation-trace", format!("/audit/{id}/trace")),
        None => {
            let mut discovery_path = build_forwarded_path("/audit", &pairs, &["limit"]);
            if discovery_path == "/audit" {
                discovery_path = "/audit?limit=25".to_string();
            }
            ("recent-discovery", discovery_path)
        }
    };

    let up = state.upstream.get_json(&path, auth).await;
    if is_measured(&up) {
        if let Some(payload) = up.payload {
            let audit_integrity = extract_audit_integrity(&payload);
            let (integrity_verified, integrity_alert) = audit_integrity_flags(&audit_integrity);
            return json_api_response(
                StatusCode::OK,
                json!({
                    "schema_version": SCHEMA_VERSION,
                    "source": "operator-service",
                    "domain": "evidence",
                    "panel": "trace",
                    "mode": mode,
                    "correlation_id": corr,
                    "endpoint": path,
                    "measurement_state": "measured",
                    "read_only": true,
                    "upstream_reachable": true,
                    "upstream_status": up.status,
                    "audit_integrity": audit_integrity,
                    "integrity_verified": integrity_verified,
                    "integrity_alert": integrity_alert,
                    "data": payload
                }),
            );
        }
    }

    if !up.reachable && state.db.is_configured() {
        let limit_val = find_query(&pairs, "limit").and_then(|v| v.parse::<usize>().ok());
        let db_payload = crate::repos::evidence::fetch_trace(&state.db, corr, limit_val).await;
        if is_db_measured(&db_payload) {
            let audit_integrity = extract_audit_integrity(&db_payload);
            let (integrity_verified, integrity_alert) = audit_integrity_flags(&audit_integrity);
            return json_api_response(
                StatusCode::OK,
                json!({
                    "schema_version": SCHEMA_VERSION,
                    "source": "postgres-direct",
                    "domain": "evidence",
                    "panel": "trace",
                    "mode": mode,
                    "correlation_id": corr.map(Value::from).unwrap_or_else(|| {
                        db_payload.get("correlation_id").cloned().unwrap_or(Value::Null)
                    }),
                    "endpoint": path,
                    "measurement_state": "measured",
                    "measurement_status": "measured",
                    "read_only": true,
                    "upstream_reachable": false,
                    "db_configured": true,
                    "audit_integrity": audit_integrity,
                    "integrity_verified": integrity_verified,
                    "integrity_alert": integrity_alert,
                    "data": db_payload
                }),
            );
        }
    }

    let reason = upstream_unavailable_reason(&up);
    let audit_integrity = not_measured_integrity(&reason);
    let (integrity_verified, integrity_alert) = audit_integrity_flags(&audit_integrity);
    json_api_response(
        StatusCode::OK,
        json!({
            "schema_version": SCHEMA_VERSION,
            "source": "console-v4-rust",
            "domain": "evidence",
            "panel": "trace",
            "mode": mode,
            "correlation_id": corr,
            "endpoint": path,
            "measurement_state": "not-measured",
            "upstream_url": sanitize_upstream_url(state.upstream.base_url()),
            "upstream_reachable": up.reachable,
            "upstream_status": up.status,
            "read_only": true,
            "reason": reason,
            "audit_integrity": audit_integrity,
            "integrity_verified": integrity_verified,
            "integrity_alert": integrity_alert,
            "data": Value::Null
        }),
    )
}

async fn api_evidence_rca(
    State(state): State<AppState>,
    headers: HeaderMap,
    uri: Uri,
) -> Response {
    let pairs = parse_query_pairs(uri.query());
    if let Err(err) = validate_optional_identifier(&pairs, "correlation_id", "invalid_correlation_id") {
        return err.into_response();
    }
    if let Err(err) = validate_optional_identifier(&pairs, "case_id", "invalid_case_id") {
        return err.into_response();
    }

    let auth = extract_auth(&headers);
    let path = build_forwarded_path("/rca", &pairs, &RCA_QUERY_KEYS);
    let up = state.upstream.get_json(&path, auth).await;

    if is_measured(&up) {
        if let Some(payload) = up.payload {
            return json_api_response(
                StatusCode::OK,
                json!({
                    "schema_version": SCHEMA_VERSION,
                    "source": "operator-service",
                    "domain": "evidence",
                    "panel": "rca",
                    "endpoint": path,
                    "measurement_state": "measured",
                    "correlation_is_not_causation": true,
                    "abstained_supported": true,
                    "read_only": true,
                    "upstream_reachable": true,
                    "upstream_status": up.status,
                    "data": payload
                }),
            );
        }
    }

    if !up.reachable && state.db.is_configured() {
        let db_payload = crate::repos::evidence::fetch_rca(
            &state.db,
            find_query(&pairs, "correlation_id"),
            find_query(&pairs, "case_id"),
        )
        .await;
        if is_db_measured(&db_payload) {
            return json_api_response(
                StatusCode::OK,
                json!({
                    "schema_version": SCHEMA_VERSION,
                    "source": "postgres-direct",
                    "domain": "evidence",
                    "panel": "rca",
                    "endpoint": path,
                    "measurement_state": "measured",
                    "measurement_status": "measured",
                    "correlation_is_not_causation": true,
                    "abstained_supported": true,
                    "read_only": true,
                    "upstream_reachable": false,
                    "db_configured": true,
                    "data": db_payload
                }),
            );
        }
    }

    let reason = upstream_unavailable_reason(&up);
    json_api_response(
        StatusCode::OK,
        json!({
            "schema_version": SCHEMA_VERSION,
            "source": "console-v4-rust",
            "domain": "evidence",
            "panel": "rca",
            "endpoint": path,
            "measurement_state": "not-measured",
            "confidence_state": "not-measured",
            "correlation_is_not_causation": true,
            "abstained_supported": true,
            "read_only": true,
            "upstream_url": sanitize_upstream_url(state.upstream.base_url()),
            "upstream_reachable": up.reachable,
            "upstream_status": up.status,
            "reason": reason,
            "data": Value::Null
        }),
    )
}

async fn api_evidence_browser_evidence(
    State(state): State<AppState>,
    headers: HeaderMap,
    uri: Uri,
) -> Response {
    let pairs = parse_query_pairs(uri.query());
    if let Err(err) = validate_limit_param(&pairs) {
        return err.into_response();
    }
    if let Err(err) = validate_enum_param(&pairs, "retention", &BROWSER_ALLOWED_RETENTION) {
        return err.into_response();
    }
    if let Err(err) = validate_enum_param(&pairs, "finding", &BROWSER_ALLOWED_FINDING) {
        return err.into_response();
    }
    if let Err(err) = validate_optional_identifier(&pairs, "cursor", "invalid_cursor") {
        return err.into_response();
    }
    if let Err(err) = validate_search_query(&pairs, "q") {
        return err.into_response();
    }

    let auth = extract_auth(&headers);
    let path = build_forwarded_path("/browser-evidence", &pairs, &BROWSER_QUERY_KEYS);
    let up = state.upstream.get_json(&path, auth).await;

    if is_measured(&up) {
        if let Some(payload) = up.payload {
            let (scrubbed, scrubbed_count) = scrub_browser_evidence_payload(payload);
            return json_api_response(
                StatusCode::OK,
                json!({
                    "schema_version": SCHEMA_VERSION,
                    "source": "operator-service",
                    "domain": "evidence",
                    "panel": "browser-evidence",
                    "endpoint": path,
                    "measurement_state": "measured",
                    "raw_content_exposed": false,
                    "scrubbed_sensitive_fields": scrubbed_count,
                    "read_only": true,
                    "upstream_reachable": true,
                    "upstream_status": up.status,
                    "data": scrubbed
                }),
            );
        }
    }

    if !up.reachable && state.db.is_configured() {
        let limit_val = find_query(&pairs, "limit").and_then(|v| v.parse::<usize>().ok());
        let db_payload = crate::repos::evidence::fetch_browser_evidence_filtered(
            &state.db,
            find_query(&pairs, "retention"),
            find_query(&pairs, "finding"),
            find_query(&pairs, "q"),
            limit_val,
        )
        .await;
        if is_db_measured(&db_payload) {
            let (scrubbed, scrubbed_count) = scrub_browser_evidence_payload(db_payload);
            return json_api_response(
                StatusCode::OK,
                json!({
                    "schema_version": SCHEMA_VERSION,
                    "source": "postgres-direct",
                    "domain": "evidence",
                    "panel": "browser-evidence",
                    "endpoint": path,
                    "measurement_state": "measured",
                    "measurement_status": "measured",
                    "raw_content_exposed": false,
                    "scrubbed_sensitive_fields": scrubbed_count,
                    "read_only": true,
                    "upstream_reachable": false,
                    "db_configured": true,
                    "data": scrubbed
                }),
            );
        }
    }

    let reason = upstream_unavailable_reason(&up);
    json_api_response(
        StatusCode::OK,
        json!({
            "schema_version": SCHEMA_VERSION,
            "source": "console-v4-rust",
            "domain": "evidence",
            "panel": "browser-evidence",
            "endpoint": path,
            "measurement_state": "not-measured",
            "raw_content_exposed": false,
            "scrubbed_sensitive_fields": 0,
            "read_only": true,
            "upstream_url": sanitize_upstream_url(state.upstream.base_url()),
            "upstream_reachable": up.reachable,
            "upstream_status": up.status,
            "reason": reason,
            "data": Value::Null
        }),
    )
}

async fn api_evidence_conversations(
    State(state): State<AppState>,
    headers: HeaderMap,
    uri: Uri,
) -> Response {
    let pairs = parse_query_pairs(uri.query());
    if let Err(err) = validate_limit_param(&pairs) {
        return err.into_response();
    }
    if let Err(err) = validate_enum_param(&pairs, "mode", &CONVERSATION_ALLOWED_MODES) {
        return err.into_response();
    }
    if let Err(err) = validate_enum_param(&pairs, "role", &CONVERSATION_ALLOWED_ROLES) {
        return err.into_response();
    }
    if let Err(err) = validate_optional_identifier(&pairs, "channel", "invalid_channel") {
        return err.into_response();
    }
    if let Err(err) = validate_optional_identifier(&pairs, "cursor", "invalid_cursor") {
        return err.into_response();
    }
    if let Err(err) = validate_search_query(&pairs, "q") {
        return err.into_response();
    }

    let auth = extract_auth(&headers);
    let search_path = build_forwarded_path("/conversations/search", &pairs, &CONVERSATION_QUERY_KEYS);
    let primary = state.upstream.get_json(&search_path, auth).await;

    if is_measured(&primary) {
        if let Some(payload) = primary.payload {
            return json_api_response(
                StatusCode::OK,
                json!({
                    "schema_version": SCHEMA_VERSION,
                    "source": "operator-service",
                    "domain": "evidence",
                    "panel": "conversation-search",
                    "endpoint": search_path,
                    "measurement_state": "measured",
                    "redaction_applied": true,
                    "read_only": true,
                    "upstream_reachable": true,
                    "upstream_status": primary.status,
                    "data": payload
                }),
            );
        }
    }

    // Fallback to `/me/context` projection when dedicated `/conversations/search` is not enabled.
    let context_up = state.upstream.get_json("/me/context", auth).await;
    if is_measured(&context_up) {
        if let Some(ref payload) = context_up.payload {
            if let Some(conversations) = payload.get("conversations") {
                let page = payload
                    .get("conversation_page")
                    .cloned()
                    .unwrap_or_else(|| json!({ "has_more": false, "next_cursor": Value::Null }));
                return json_api_response(
                    StatusCode::OK,
                    json!({
                        "schema_version": SCHEMA_VERSION,
                        "source": "operator-service",
                        "domain": "evidence",
                        "panel": "conversation-search",
                        "endpoint": "/me/context",
                        "measurement_state": "measured",
                        "redaction_applied": true,
                        "read_only": true,
                        "upstream_reachable": true,
                        "upstream_status": context_up.status,
                        "data": {
                            "conversations": conversations,
                            "conversation_page": page
                        }
                    }),
                );
            }
        }
    }

    if !primary.reachable && !context_up.reachable && state.db.is_configured() {
        let limit_val = find_query(&pairs, "limit").and_then(|v| v.parse::<usize>().ok());
        let db_payload = crate::repos::evidence::fetch_conversations(
            &state.db,
            find_query(&pairs, "q"),
            find_query(&pairs, "channel"),
            limit_val,
        )
        .await;
        if is_db_measured(&db_payload) {
            return json_api_response(
                StatusCode::OK,
                json!({
                    "schema_version": SCHEMA_VERSION,
                    "source": "postgres-direct",
                    "domain": "evidence",
                    "panel": "conversation-search",
                    "endpoint": search_path,
                    "measurement_state": "measured",
                    "measurement_status": "measured",
                    "redaction_applied": true,
                    "read_only": true,
                    "upstream_reachable": false,
                    "db_configured": true,
                    "data": db_payload
                }),
            );
        }
    }

    let reason = resolve_fallback_reason(&primary, &context_up);
    json_api_response(
        StatusCode::OK,
        json!({
            "schema_version": SCHEMA_VERSION,
            "source": "console-v4-rust",
            "domain": "evidence",
            "panel": "conversation-search",
            "endpoint": search_path,
            "measurement_state": "not-measured",
            "redaction_applied": true,
            "read_only": true,
            "upstream_url": sanitize_upstream_url(state.upstream.base_url()),
            "upstream_reachable": primary.reachable || context_up.reachable,
            "upstream_status": if matches!(context_up.status, 401 | 403) {
                context_up.status
            } else if primary.status != 0 {
                primary.status
            } else {
                context_up.status
            },
            "reason": reason,
            "data": Value::Null
        }),
    )
}

async fn api_evidence_reports(
    State(state): State<AppState>,
    headers: HeaderMap,
    uri: Uri,
) -> Response {
    let pairs = parse_query_pairs(uri.query());
    if let Err(err) = validate_enum_param(&pairs, "window", &REPORT_ALLOWED_WINDOWS) {
        return err.into_response();
    }
    if let Err(err) = validate_optional_identifier(&pairs, "scope", "invalid_scope") {
        return err.into_response();
    }
    if let Err(err) = validate_optional_identifier(&pairs, "report_id", "invalid_report_id") {
        return err.into_response();
    }

    let auth = extract_auth(&headers);
    let reports_path = build_forwarded_path("/reports", &pairs, &REPORT_QUERY_KEYS);
    let (reports_up, audit_up) = tokio::join!(
        state.upstream.get_json(&reports_path, auth),
        state.upstream.get_json("/audit?limit=1", auth),
    );

    let audit_integrity = match (&audit_up.payload, is_measured(&audit_up)) {
        (Some(payload), true) => extract_audit_integrity(payload),
        _ => not_measured_integrity(&upstream_unavailable_reason(&audit_up)),
    };
    let (integrity_verified, integrity_alert) = audit_integrity_flags(&audit_integrity);

    if is_measured(&reports_up) {
        if let Some(payload) = reports_up.payload {
            return json_api_response(
                StatusCode::OK,
                json!({
                    "schema_version": SCHEMA_VERSION,
                    "source": "operator-service",
                    "domain": "evidence",
                    "panel": "reports",
                    "endpoint": reports_path,
                    "measurement_state": "measured",
                    "signature_algorithm": "SHA-256",
                    "read_only": true,
                    "execution_authority": false,
                    "upstream_reachable": true,
                    "upstream_status": reports_up.status,
                    "audit_integrity": audit_integrity,
                    "integrity_verified": integrity_verified,
                    "integrity_alert": integrity_alert,
                    "data": payload
                }),
            );
        }
    }

    if !reports_up.reachable && state.db.is_configured() {
        let db_payload = crate::repos::evidence::fetch_reports(
            &state.db,
            find_query(&pairs, "window"),
            find_query(&pairs, "scope"),
            find_query(&pairs, "report_id"),
        )
        .await;
        if is_db_measured(&db_payload) {
            let db_integrity = extract_audit_integrity(&db_payload);
            let (db_verified, db_alert) = audit_integrity_flags(&db_integrity);
            return json_api_response(
                StatusCode::OK,
                json!({
                    "schema_version": SCHEMA_VERSION,
                    "source": "postgres-direct",
                    "domain": "evidence",
                    "panel": "reports",
                    "endpoint": reports_path,
                    "measurement_state": "measured",
                    "measurement_status": "measured",
                    "signature_algorithm": "SHA-256",
                    "read_only": true,
                    "execution_authority": false,
                    "upstream_reachable": false,
                    "db_configured": true,
                    "audit_integrity": db_integrity,
                    "integrity_verified": db_verified,
                    "integrity_alert": db_alert,
                    "data": db_payload
                }),
            );
        }
    }

    let reason = upstream_unavailable_reason(&reports_up);
    json_api_response(
        StatusCode::OK,
        json!({
            "schema_version": SCHEMA_VERSION,
            "source": "console-v4-rust",
            "domain": "evidence",
            "panel": "reports",
            "endpoint": reports_path,
            "measurement_state": "not-measured",
            "report_projection": "unavailable",
            "signature_algorithm": "SHA-256",
            "read_only": true,
            "execution_authority": false,
            "upstream_url": sanitize_upstream_url(state.upstream.base_url()),
            "upstream_reachable": reports_up.reachable || audit_up.reachable,
            "upstream_status": reports_up.status,
            "reason": reason,
            "audit_integrity": audit_integrity,
            "integrity_verified": integrity_verified,
            "integrity_alert": integrity_alert,
            "data": Value::Null
        }),
    )
}

fn json_api_response(status: StatusCode, body: Value) -> Response {
    (
        status,
        [
            (header::CACHE_CONTROL, "no-store, max-age=0"),
            (header::PRAGMA, "no-cache"),
            (header::X_CONTENT_TYPE_OPTIONS, "nosniff"),
        ],
        Json(body),
    )
        .into_response()
}

fn extract_auth(headers: &HeaderMap) -> Option<&str> {
    let raw = headers.get(header::AUTHORIZATION)?.to_str().ok()?.trim();
    if raw.is_empty() || raw.len() > MAX_AUTH_HEADER_BYTES {
        return None;
    }
    if raw.bytes().any(|b| b < 0x20 || b == 0x7F) {
        return None;
    }
    Some(raw)
}

fn sanitize_upstream_url(raw: &str) -> String {
    let trimmed = raw.trim();
    let Some((scheme, rest)) = trimmed.split_once("://") else {
        return "unconfigured".to_string();
    };
    let authority = rest.split(['/', '?', '#']).next().unwrap_or("");
    let host_port = authority.rsplit('@').next().unwrap_or("");
    if host_port.is_empty() {
        return "unconfigured".to_string();
    }
    format!("{scheme}://{host_port}")
}

fn is_measured(up: &UpstreamOutcome) -> bool {
    up.reachable && up.status == 200 && up.payload.is_some()
}

fn is_db_measured(val: &Value) -> bool {
    val.get("measurement_status").and_then(Value::as_str) == Some("measured")
}

fn source_status_json(endpoint: &str, up: &UpstreamOutcome) -> Value {
    let measured = is_measured(up);
    json!({
        "endpoint": endpoint,
        "measurement_state": if measured { "measured" } else { "not-measured" },
        "reachable": up.reachable,
        "status": up.status
    })
}

fn extract_audit_integrity(payload: &Value) -> Value {
    if let Some(integrity) = payload
        .get("audit_integrity")
        .filter(|v| v.is_object())
    {
        return integrity.clone();
    }
    if let Some(integrity) = payload
        .get("summary")
        .and_then(|s| s.get("integrity"))
        .filter(|v| v.is_object())
    {
        return integrity.clone();
    }
    if let Some(integrity) = payload.get("integrity").filter(|v| v.is_object()) {
        return integrity.clone();
    }
    not_measured_integrity("upstream payload omitted audit integrity block")
}

fn audit_integrity_flags(integrity: &Value) -> (Value, bool) {
    let status = integrity
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("not-measured")
        .to_ascii_lowercase();
    let gap_count = integrity
        .get("current_link_gap_count")
        .and_then(Value::as_u64);

    if matches!(gap_count, Some(n) if n > 0) {
        return (Value::Bool(false), true);
    }
    match status.as_str() {
        "verified" => (Value::Bool(true), false),
        "not-measured" => (Value::Null, false),
        "compromised" | "broken" | "tampered" | "gap_detected" | "failed" | "mismatch"
        | "invalid" => (Value::Bool(false), true),
        _ => (Value::Null, false),
    }
}

fn scrub_browser_evidence_payload(value: Value) -> (Value, usize) {
    match value {
        Value::Object(map) => {
            let mut removed = 0usize;
            let mut out = serde_json::Map::with_capacity(map.len());
            for (k, v) in map {
                let lower = k.to_ascii_lowercase();
                if SENSITIVE_BROWSER_KEYS.iter().any(|bad| *bad == lower) {
                    removed = removed.saturating_add(1);
                    continue;
                }
                let (clean_v, child_removed) = scrub_browser_evidence_payload(v);
                removed = removed.saturating_add(child_removed);
                out.insert(k, clean_v);
            }
            (Value::Object(out), removed)
        }
        Value::Array(items) => {
            let mut removed = 0usize;
            let mut out = Vec::with_capacity(items.len());
            for item in items {
                let (clean_v, child_removed) = scrub_browser_evidence_payload(item);
                removed = removed.saturating_add(child_removed);
                out.push(clean_v);
            }
            (Value::Array(out), removed)
        }
        other => (other, 0),
    }
}

fn not_measured_integrity(reason: &str) -> Value {
    json!({
        "status": "not-measured",
        "reason": reason,
        "verified_at": Value::Null,
        "current_record_count": Value::Null,
        "current_link_gap_count": Value::Null
    })
}

fn upstream_unavailable_reason(up: &UpstreamOutcome) -> String {
    if !up.reachable {
        return "operator-service offline or unreachable".to_string();
    }
    match up.status {
        401 | 403 => "operator-service authentication or role authorization required".to_string(),
        404 | 503 => "operator-service projection unavailable".to_string(),
        code => format!("operator-service returned HTTP {code}"),
    }
}

fn resolve_fallback_reason(primary: &UpstreamOutcome, secondary: &UpstreamOutcome) -> String {
    if matches!(primary.status, 401 | 403) {
        return upstream_unavailable_reason(primary);
    }
    if matches!(secondary.status, 401 | 403) {
        return upstream_unavailable_reason(secondary);
    }
    if !primary.reachable && !secondary.reachable {
        return upstream_unavailable_reason(primary);
    }
    upstream_unavailable_reason(primary)
}

fn bad_request_response(code: &str, message: &str) -> Response {
    json_api_response(
        StatusCode::BAD_REQUEST,
        json!({
            "schema_version": SCHEMA_VERSION,
            "error": {
                "code": code,
                "message": message
            }
        }),
    )
}

fn is_safe_correlation_id(value: &str) -> bool {
    if value.is_empty() || value.len() > 128 || value.contains("..") {
        return false;
    }
    value
        .bytes()
        .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b'.' | b':'))
}

struct ValidationError {
    code: &'static str,
    message: String,
}

impl ValidationError {
    fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }

    fn into_response(self) -> Response {
        bad_request_response(self.code, &self.message)
    }
}

fn validate_optional_identifier(
    pairs: &[(String, String)],
    key: &str,
    error_code: &'static str,
) -> Result<(), ValidationError> {
    if let Some(val) = find_query(pairs, key) {
        if !val.is_empty() && !is_safe_correlation_id(val) {
            return Err(ValidationError::new(
                error_code,
                format!("{key} must be 1..=128 ASCII [A-Za-z0-9._:-] characters without '..'"),
            ));
        }
    }
    Ok(())
}

fn validate_limit_param(pairs: &[(String, String)]) -> Result<(), ValidationError> {
    if let Some(raw) = find_query(pairs, "limit") {
        if raw.is_empty() {
            return Ok(());
        }
        let parsed = raw.parse::<u64>().map_err(|_| {
            ValidationError::new(
                "invalid_limit",
                "limit must be an integer between 1 and 100",
            )
        })?;
        if !(MIN_LIMIT..=MAX_LIMIT).contains(&parsed) {
            return Err(ValidationError::new(
                "invalid_limit",
                "limit must be an integer between 1 and 100",
            ));
        }
    }
    Ok(())
}

fn validate_u64_param(
    pairs: &[(String, String)],
    key: &str,
) -> Result<Option<u64>, ValidationError> {
    let Some(raw) = find_query(pairs, key) else {
        return Ok(None);
    };
    if raw.is_empty() {
        return Ok(None);
    }
    let parsed = raw.parse::<u64>().map_err(|_| {
        ValidationError::new(
            "invalid_sequence",
            format!("{key} must be a non-negative integer"),
        )
    })?;
    Ok(Some(parsed))
}

fn validate_enum_param(
    pairs: &[(String, String)],
    key: &str,
    allowed: &[&str],
) -> Result<(), ValidationError> {
    if let Some(raw) = find_query(pairs, key) {
        if !raw.is_empty() && !allowed.iter().any(|item| item.eq_ignore_ascii_case(raw)) {
            return Err(ValidationError::new(
                "invalid_filter_value",
                format!("{key} must be one of: {}", allowed.join(", ")),
            ));
        }
    }
    Ok(())
}

fn validate_search_query(pairs: &[(String, String)], key: &str) -> Result<(), ValidationError> {
    if let Some(raw) = find_query(pairs, key) {
        if raw.len() > MAX_SEARCH_QUERY_BYTES {
            return Err(ValidationError::new(
                "query_too_long",
                "search query must be at most 256 bytes",
            ));
        }
        if raw.bytes().any(|b| b < 0x20 || b == 0x7F) {
            return Err(ValidationError::new(
                "invalid_query_characters",
                "search query must not contain control characters",
            ));
        }
    }
    Ok(())
}

fn parse_query_pairs(raw_query: Option<&str>) -> Vec<(String, String)> {
    let Some(raw) = raw_query else {
        return Vec::new();
    };
    let bounded = if raw.len() > MAX_QUERY_BYTES {
        let mut end = MAX_QUERY_BYTES;
        while end > 0 && !raw.is_char_boundary(end) {
            end -= 1;
        }
        &raw[..end]
    } else {
        raw
    };
    let mut out = Vec::new();
    for segment in bounded.split('&').take(MAX_QUERY_PARAMS) {
        if segment.is_empty() {
            continue;
        }
        let (raw_k, raw_v) = match segment.split_once('=') {
            Some((k, v)) => (k, v),
            None => (segment, ""),
        };
        let key = percent_decode(raw_k);
        if !key.is_empty() {
            out.push((key, percent_decode(raw_v)));
        }
    }
    out
}

fn find_query<'a>(pairs: &'a [(String, String)], key: &str) -> Option<&'a str> {
    pairs
        .iter()
        .find(|(k, _)| k == key)
        .map(|(_, v)| v.as_str())
}

fn build_forwarded_path(
    base: &str,
    pairs: &[(String, String)],
    allowed_keys: &[&str],
) -> String {
    let mut encoded = Vec::new();
    for (k, v) in pairs {
        if allowed_keys.contains(&k.as_str()) && !v.is_empty() {
            encoded.push(format!(
                "{}={}",
                encode_query_component(k),
                encode_query_component(v)
            ));
        }
    }
    if encoded.is_empty() {
        base.to_string()
    } else {
        format!("{base}?{}", encoded.join("&"))
    }
}

fn encode_query_component(input: &str) -> String {
    const HEX: &[u8; 16] = b"0123456789ABCDEF";
    let mut out = String::with_capacity(input.len());
    for &b in input.as_bytes() {
        if b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b'.' | b'~') {
            out.push(char::from(b));
        } else {
            out.push('%');
            out.push(char::from(HEX[usize::from(b >> 4)]));
            out.push(char::from(HEX[usize::from(b & 0x0F)]));
        }
    }
    out
}

fn percent_decode(input: &str) -> String {
    let bytes = input.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'+' {
            out.push(b' ');
            i += 1;
        } else if bytes[i] == b'%' && i + 2 < bytes.len() {
            if let (Some(hi), Some(lo)) = (hex_val(bytes[i + 1]), hex_val(bytes[i + 2])) {
                out.push((hi << 4) | lo);
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
    String::from_utf8_lossy(&out).into_owned()
}

fn hex_val(byte: u8) -> Option<u8> {
    match byte {
        b'0'..=b'9' => Some(byte - b'0'),
        b'a'..=b'f' => Some(byte - b'a' + 10),
        b'A'..=b'F' => Some(byte - b'A' + 10),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::build_router;
    use axum::body::Body;
    use axum::http::Request;
    use http_body_util::BodyExt;
    use std::path::PathBuf;
    use tokio::net::TcpListener;
    use tower::ServiceExt;

    type TestResult = Result<(), Box<dyn std::error::Error>>;

    fn test_state(operator_url: String) -> AppState {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("."));
        AppState::from_repo_root(root, operator_url)
    }

    async fn fetch_body(app: &Router, uri: &str) -> Result<(StatusCode, Vec<u8>), Box<dyn std::error::Error>> {
        let req = Request::builder().uri(uri).body(Body::empty())?;
        let resp = app.clone().oneshot(req).await?;
        let status = resp.status();
        let bytes = resp.into_body().collect().await?.to_bytes().to_vec();
        Ok((status, bytes))
    }

    #[test]
    fn evidence_panel_ids_and_correlation_validator() {
        assert_eq!(panel_ids().len(), 6);
        assert!(is_safe_correlation_id("corr-8a91f"));
        assert!(is_safe_correlation_id("RCA_2026:441.v1"));
        assert!(!is_safe_correlation_id(""));
        assert!(!is_safe_correlation_id("../secret"));
        assert!(!is_safe_correlation_id("corr/8a91f"));
        assert!(!is_safe_correlation_id("corr?x=1"));
        assert!(!is_safe_correlation_id(&"a".repeat(129)));
    }

    #[tokio::test]
    async fn evidence_page_has_all_six_panels_normalized_links_and_tooltips() -> TestResult {
        let app = build_router(test_state("http://127.0.0.1:1".to_string()));
        let (status, bytes) = fetch_body(&app, "/evidence").await?;
        assert_eq!(status, StatusCode::OK);
        let html = String::from_utf8(bytes)?;

        for panel in PANELS {
            let needle = format!("data-panel-id=\"{panel}\"");
            assert!(html.contains(&needle), "missing panel {panel}");
        }
        assert!(!html.contains("mockup-governance.html"));
        assert!(!html.contains("mockup-operations.html"));
        assert!(html.contains("\"/ontology\""));
        assert!(html.contains("\"/hil-queue\""));
        assert!(html.contains("\"/incidents\""));
        assert!(html.contains("data-ut-title"));
        assert!(html.contains("/api/v4/evidence/audit"));
        Ok(())
    }

    #[tokio::test]
    async fn evidence_apis_preserve_not_measured_and_integrity_when_upstream_offline() -> TestResult {
        let app = build_router(test_state("http://127.0.0.1:1".to_string()));

        for uri in [
            "/api/v4/evidence/summary",
            "/api/v4/evidence/audit?limit=10&mode=enforce",
            "/api/v4/evidence/trace",
            "/api/v4/evidence/trace?correlation_id=corr-8a91f",
            "/api/v4/evidence/rca?correlation_id=corr-8a91f",
            "/api/v4/evidence/browser-evidence?retention=held",
            "/api/v4/evidence/conversations?q=pool&mode=terms",
            "/api/v4/evidence/reports?window=7d&scope=all",
        ] {
            let (status, bytes) = fetch_body(&app, uri).await?;
            assert_eq!(status, StatusCode::OK, "expected 200 for {uri}");
            let json: Value = serde_json::from_slice(&bytes)?;
            assert_eq!(json.get("domain"), Some(&json!("evidence")));
            assert_eq!(json.get("measurement_state"), Some(&json!("not-measured")));
            assert_eq!(json.get("data"), Some(&Value::Null));
        }

        let (_, audit_bytes) = fetch_body(&app, "/api/v4/evidence/audit").await?;
        let audit_json: Value = serde_json::from_slice(&audit_bytes)?;
        let integrity = audit_json
            .get("audit_integrity")
            .ok_or("missing audit_integrity")?;
        assert_eq!(integrity.get("status"), Some(&json!("not-measured")));
        assert_eq!(integrity.get("current_link_gap_count"), Some(&Value::Null));

        let (bad_status, bad_bytes) =
            fetch_body(&app, "/api/v4/evidence/trace?correlation_id=..%2Fetc%2Fpasswd").await?;
        assert_eq!(bad_status, StatusCode::BAD_REQUEST);
        let bad_json: Value = serde_json::from_slice(&bad_bytes)?;
        assert_eq!(
            bad_json.pointer("/error/code"),
            Some(&json!("invalid_correlation_id"))
        );
        Ok(())
    }

    #[tokio::test]
    async fn evidence_apis_proxy_measured_upstream_and_preserve_verified_integrity() -> TestResult {
        let mock_upstream = Router::new()
            .route(
                "/audit",
                get(|| async {
                    Json(json!({
                        "items": [
                            { "seq": 86641, "action_kind": "risk_gate.unified", "correlation_id": "corr-8a91f" }
                        ],
                        "next_cursor": null,
                        "summary": {
                            "matching_record_count": 1,
                            "integrity": {
                                "status": "verified",
                                "reason": null,
                                "verified_at": "2026-11-26T00:00:00Z",
                                "current_record_count": 1,
                                "current_link_gap_count": 0
                            }
                        }
                    }))
                }),
            )
            .route(
                "/audit/{correlation_id}/trace",
                get(|| async {
                    Json(json!({
                        "correlation_id": "corr-8a91f",
                        "spans": [{ "seq": 86641, "actor": "Var" }],
                        "integrity": {
                            "status": "verified",
                            "current_link_gap_count": 0
                        }
                    }))
                }),
            )
            .route(
                "/rca",
                get(|| async {
                    Json(json!({
                        "case_id": "RCA-2026-441",
                        "status": "grounded",
                        "confidence": 0.91
                    }))
                }),
            )
            .route(
                "/browser-evidence",
                get(|| async {
                    Json(json!({
                        "items": [{ "id": "art-2026-901", "injection_count": 1 }],
                        "next_cursor": null
                    }))
                }),
            )
            .route(
                "/me/context",
                get(|| async {
                    Json(json!({
                        "conversations": [{ "id": "conv-9102", "channel": "web" }],
                        "conversation_page": { "has_more": false, "next_cursor": null }
                    }))
                }),
            )
            .route(
                "/reports",
                get(|| async {
                    Json(json!({
                        "items": [{ "id": "weekly-operations-2026-w48", "status": "partial" }]
                    }))
                }),
            );

        let listener = TcpListener::bind("127.0.0.1:0").await?;
        let addr = listener.local_addr()?;
        let server_handle = tokio::spawn(async move {
            let _ = axum::serve(listener, mock_upstream).await;
        });

        let app = build_router(test_state(format!("http://{addr}")));

        let (sum_status, sum_bytes) = fetch_body(&app, "/api/v4/evidence/summary").await?;
        assert_eq!(sum_status, StatusCode::OK);
        let sum_json: Value = serde_json::from_slice(&sum_bytes)?;
        assert_eq!(sum_json.get("measurement_state"), Some(&json!("measured")));
        assert_eq!(sum_json.get("availability"), Some(&json!("complete")));
        assert_eq!(
            sum_json.pointer("/audit_integrity/status"),
            Some(&json!("verified"))
        );
        assert_eq!(
            sum_json.pointer("/audit_integrity/current_link_gap_count"),
            Some(&json!(0))
        );

        let (tr_status, tr_bytes) =
            fetch_body(&app, "/api/v4/evidence/trace?correlation_id=corr-8a91f").await?;
        assert_eq!(tr_status, StatusCode::OK);
        let tr_json: Value = serde_json::from_slice(&tr_bytes)?;
        assert_eq!(tr_json.get("measurement_state"), Some(&json!("measured")));
        assert_eq!(tr_json.get("mode"), Some(&json!("correlation-trace")));
        assert_eq!(
            tr_json.pointer("/audit_integrity/status"),
            Some(&json!("verified"))
        );

        let (conv_status, conv_bytes) =
            fetch_body(&app, "/api/v4/evidence/conversations?q=pg").await?;
        assert_eq!(conv_status, StatusCode::OK);
        let conv_json: Value = serde_json::from_slice(&conv_bytes)?;
        assert_eq!(conv_json.get("measurement_state"), Some(&json!("measured")));
        assert_eq!(conv_json.get("endpoint"), Some(&json!("/me/context")));

        let (rep_status, rep_bytes) =
            fetch_body(&app, "/api/v4/evidence/reports?window=7d").await?;
        assert_eq!(rep_status, StatusCode::OK);
        let rep_json: Value = serde_json::from_slice(&rep_bytes)?;
        assert_eq!(rep_json.get("measurement_state"), Some(&json!("measured")));
        assert_eq!(rep_json.get("execution_authority"), Some(&json!(false)));
        assert_eq!(rep_json.get("signature_algorithm"), Some(&json!("SHA-256")));
        assert_eq!(
            rep_json.pointer("/audit_integrity/status"),
            Some(&json!("verified"))
        );
        assert_eq!(rep_json.get("integrity_verified"), Some(&json!(true)));
        assert_eq!(rep_json.get("integrity_alert"), Some(&json!(false)));

        server_handle.abort();
        Ok(())
    }

    #[tokio::test]
    async fn evidence_redteam_security_headers_and_input_validation() -> TestResult {
        assert_eq!(
            sanitize_upstream_url("http://user:secret@127.0.0.1:8010/api?token=abc"),
            "http://127.0.0.1:8010"
        );

        let app = build_router(test_state("http://127.0.0.1:1".to_string()));
        let req = Request::builder()
            .uri("/api/v4/evidence/audit")
            .body(Body::empty())?;
        let resp = app.clone().oneshot(req).await?;
        assert_eq!(resp.status(), StatusCode::OK);
        assert_eq!(
            resp.headers()
                .get(header::CACHE_CONTROL)
                .and_then(|v| v.to_str().ok()),
            Some("no-store, max-age=0")
        );
        assert_eq!(
            resp.headers()
                .get(header::X_CONTENT_TYPE_OPTIONS)
                .and_then(|v| v.to_str().ok()),
            Some("nosniff")
        );

        for bad_uri in [
            "/api/v4/evidence/audit?limit=999",
            "/api/v4/evidence/audit?limit=0",
            "/api/v4/evidence/audit?from_seq=200&through_seq=100",
            "/api/v4/evidence/audit?mode=evil",
            "/api/v4/evidence/audit?q=bad%0Aline",
            "/api/v4/evidence/browser-evidence?retention=invalid",
            "/api/v4/evidence/conversations?role=root",
            "/api/v4/evidence/reports?window=999d",
        ] {
            let (st, _bytes) = fetch_body(&app, bad_uri).await?;
            assert_eq!(st, StatusCode::BAD_REQUEST, "expected 400 for {bad_uri}");
        }
        Ok(())
    }

    #[tokio::test]
    async fn evidence_redteam_tamper_alert_browser_scrub_and_auth_reason() -> TestResult {
        let mock_upstream = Router::new()
            .route(
                "/audit",
                get(|| async {
                    Json(json!({
                        "items": [],
                        "summary": {
                            "integrity": {
                                "status": "tampered",
                                "current_link_gap_count": 2
                            }
                        }
                    }))
                }),
            )
            .route(
                "/browser-evidence",
                get(|| async {
                    Json(json!({
                        "items": [{
                            "id": "art-1",
                            "raw_html": "<script>alert(1)</script>",
                            "cookies": "sid=secret",
                            "nested": { "authorization": "Bearer secret", "safe": "ok" }
                        }]
                    }))
                }),
            )
            .route(
                "/me/context",
                get(|| async { (StatusCode::UNAUTHORIZED, Json(json!({ "error": "unauthorized" }))) }),
            );

        let listener = TcpListener::bind("127.0.0.1:0").await?;
        let addr = listener.local_addr()?;
        let server_handle = tokio::spawn(async move {
            let _ = axum::serve(listener, mock_upstream).await;
        });

        let app = build_router(test_state(format!("http://{addr}")));

        let (audit_st, audit_bytes) = fetch_body(&app, "/api/v4/evidence/audit").await?;
        assert_eq!(audit_st, StatusCode::OK);
        let audit_json: Value = serde_json::from_slice(&audit_bytes)?;
        assert_eq!(audit_json.get("integrity_verified"), Some(&json!(false)));
        assert_eq!(audit_json.get("integrity_alert"), Some(&json!(true)));

        let (be_st, be_bytes) = fetch_body(&app, "/api/v4/evidence/browser-evidence").await?;
        assert_eq!(be_st, StatusCode::OK);
        let be_json: Value = serde_json::from_slice(&be_bytes)?;
        assert_eq!(be_json.get("scrubbed_sensitive_fields"), Some(&json!(3)));
        let serialized = be_json.to_string();
        assert!(!serialized.contains("raw_html"));
        assert!(!serialized.contains("sid=secret"));
        assert!(!serialized.contains("Bearer secret"));
        assert!(serialized.contains("\"safe\":\"ok\""));

        let (conv_st, conv_bytes) = fetch_body(&app, "/api/v4/evidence/conversations?q=test").await?;
        assert_eq!(conv_st, StatusCode::OK);
        let conv_json: Value = serde_json::from_slice(&conv_bytes)?;
        assert_eq!(conv_json.get("upstream_status"), Some(&json!(401)));
        let reason = conv_json
            .get("reason")
            .and_then(Value::as_str)
            .unwrap_or("");
        assert!(reason.contains("authentication"), "unexpected reason: {reason}");

        server_handle.abort();
        Ok(())
    }

    #[tokio::test]
    async fn evidence_mode_labels_and_before_seq_validation() -> TestResult {
        assert_eq!(crate::repos::evidence::mode_label_ko("enforce"), "승인 후 조치");
        assert_eq!(crate::repos::evidence::mode_label_ko("auto"), "자동 조치");
        assert_eq!(crate::repos::evidence::mode_label_ko("shadow"), "감시 전용");

        let app = build_router(test_state("http://127.0.0.1:1".to_string()));
        let (bad_st, _) = fetch_body(&app, "/api/v4/evidence/audit?before_seq=not-a-num").await?;
        assert_eq!(bad_st, StatusCode::BAD_REQUEST);
        let (ok_st, _) = fetch_body(&app, "/api/v4/evidence/audit?before_seq=86600&search=Saga").await?;
        assert_eq!(ok_st, StatusCode::OK);
        Ok(())
    }

    #[tokio::test]
    async fn evidence_postgres_direct_fallback_covers_all_six_panels() -> TestResult {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("."));
        let state = AppState::from_repo_root_with_local_db(root, "http://127.0.0.1:1".to_string());
        if !state.db.is_configured() {
            return Ok(());
        }
        let app = build_router(state);

        // 1. Summary
        let (st, bytes) = fetch_body(&app, "/api/v4/evidence/summary").await?;
        assert_eq!(st, StatusCode::OK);
        let sum: Value = serde_json::from_slice(&bytes)?;
        if sum.get("source") != Some(&json!("postgres-direct")) {
            return Ok(());
        }
        assert_eq!(sum.get("measurement_state"), Some(&json!("measured")));
        assert_eq!(sum.get("measurement_status"), Some(&json!("measured")));
        assert_eq!(sum.pointer("/audit_integrity/status"), Some(&json!("verified")));

        // 2. Audit with progressive disclosure + cursor + search
        let (st, bytes) = fetch_body(&app, "/api/v4/evidence/audit?limit=20").await?;
        assert_eq!(st, StatusCode::OK);
        let aud: Value = serde_json::from_slice(&bytes)?;
        assert_eq!(aud.get("source"), Some(&json!("postgres-direct")));
        assert_eq!(aud.get("measurement_status"), Some(&json!("measured")));
        assert_eq!(aud.get("integrity_verified"), Some(&json!(true)));
        let items = aud
            .pointer("/data/items")
            .and_then(Value::as_array)
            .ok_or("missing audit items")?;
        assert!(!items.is_empty());
        assert_eq!(
            items[0].pointer("/forensic_crypto/disclosure_default_collapsed"),
            Some(&json!(true))
        );
        let next_before = aud.pointer("/data/next_before_seq").and_then(Value::as_i64);
        if let Some(seq) = next_before {
            let (st2, b2) = fetch_body(
                &app,
                &format!("/api/v4/evidence/audit?limit=10&before_seq={seq}"),
            )
            .await?;
            assert_eq!(st2, StatusCode::OK);
            let aud2: Value = serde_json::from_slice(&b2)?;
            assert_eq!(aud2.get("measurement_status"), Some(&json!("measured")));
        }

        // 2b. Audit server-side category filter & Korean search
        let (st_cat, b_cat) = fetch_body(&app, "/api/v4/evidence/audit?limit=10&category=approval").await?;
        assert_eq!(st_cat, StatusCode::OK);
        let aud_cat: Value = serde_json::from_slice(&b_cat)?;
        assert_eq!(aud_cat.get("measurement_status"), Some(&json!("measured")));
        let cat_items = aud_cat
            .pointer("/data/items")
            .and_then(Value::as_array)
            .ok_or("missing category=approval items")?;
        assert!(!cat_items.is_empty(), "expected real approval/policy rows from PostgreSQL");

        let (st_ko, b_ko) = fetch_body(&app, "/api/v4/evidence/audit?limit=10&q=%EC%8A%B9%EC%9D%B8").await?;
        assert_eq!(st_ko, StatusCode::OK);
        let aud_ko: Value = serde_json::from_slice(&b_ko)?;
        let ko_items = aud_ko
            .pointer("/data/items")
            .and_then(Value::as_array)
            .ok_or("missing Korean search items")?;
        assert!(!ko_items.is_empty(), "expected Korean search '승인' to match real PostgreSQL rows");

        // 3. Trace
        let (st, bytes) = fetch_body(&app, "/api/v4/evidence/trace").await?;
        assert_eq!(st, StatusCode::OK);
        let tr: Value = serde_json::from_slice(&bytes)?;
        assert_eq!(tr.get("source"), Some(&json!("postgres-direct")));
        assert_eq!(tr.get("measurement_status"), Some(&json!("measured")));
        assert!(tr.pointer("/data/spans").and_then(Value::as_array).is_some());

        // 4. RCA
        let (st, bytes) = fetch_body(&app, "/api/v4/evidence/rca").await?;
        assert_eq!(st, StatusCode::OK);
        let rca: Value = serde_json::from_slice(&bytes)?;
        assert_eq!(rca.get("source"), Some(&json!("postgres-direct")));
        assert_eq!(rca.get("correlation_is_not_causation"), Some(&json!(true)));
        assert!(rca.pointer("/data/cases").and_then(Value::as_array).is_some());

        // 5. Browser evidence (honest empty measured when table has 0 rows)
        let (st, bytes) = fetch_body(&app, "/api/v4/evidence/browser-evidence").await?;
        assert_eq!(st, StatusCode::OK);
        let be: Value = serde_json::from_slice(&bytes)?;
        assert_eq!(be.get("source"), Some(&json!("postgres-direct")));
        assert_eq!(be.get("measurement_status"), Some(&json!("measured")));
        assert!(be.pointer("/data/items").and_then(Value::as_array).is_some());

        // 6. Conversations
        let (st, bytes) = fetch_body(&app, "/api/v4/evidence/conversations").await?;
        assert_eq!(st, StatusCode::OK);
        let conv: Value = serde_json::from_slice(&bytes)?;
        assert_eq!(conv.get("source"), Some(&json!("postgres-direct")));
        assert_eq!(conv.get("measurement_status"), Some(&json!("measured")));
        assert!(conv.pointer("/data/items").and_then(Value::as_array).is_some());

        // 7. Reports (real PostgreSQL scopes from ontology_resource, zero mock subscriptions)
        let (st, bytes) = fetch_body(&app, "/api/v4/evidence/reports?window=7d").await?;
        assert_eq!(st, StatusCode::OK);
        let rep: Value = serde_json::from_slice(&bytes)?;
        assert_eq!(rep.get("source"), Some(&json!("postgres-direct")));
        assert_eq!(rep.get("measurement_status"), Some(&json!("measured")));
        assert_eq!(rep.get("execution_authority"), Some(&json!(false)));
        assert!(rep.pointer("/data/items").and_then(Value::as_array).is_some());
        let scopes = rep
            .pointer("/data/available_scopes")
            .and_then(Value::as_array)
            .ok_or("missing available_scopes")?;
        assert!(!scopes.is_empty(), "expected connected scopes from ontology_resource");
        let rep_serialized = rep.to_string();
        assert!(!rep_serialized.contains("prod-core-kr"));
        assert!(!rep_serialized.contains("prod-data-platform"));
        assert!(!rep_serialized.contains("sec-shared-hub"));

        Ok(())
    }
}
