//! Domain 2: 운영 (`operations`, 18 panels).
//! Pure-Rust Axum HTML, JSON, and SSE endpoints with fail-closed `not-measured` fallback.

use axum::{
    extract::State,
    http::{header, HeaderMap, HeaderName, HeaderValue, StatusCode, Uri},
    response::{
        sse::{Event, KeepAlive, Sse},
        IntoResponse, Response,
    },
    routing::{get, post},
    Json, Router,
};
use futures_util::stream;
use serde::Deserialize;
use serde_json::{json, Map, Value};
use std::{
    convert::Infallible,
    sync::{Arc, OnceLock},
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tokio::sync::Semaphore;

use crate::{
    repos::operations as ops_repo,
    shell::{finalize_v4_html, html_response},
    upstream::UpstreamOutcome,
    AppState, SseLeaseDropGuard,
};

const TEMPLATE: &str = include_str!("../../templates/operations.html");

const PANELS: [&str; 18] = [
    "live",
    "gpu",
    "incidents",
    "code-security",
    "vulnerability-risk",
    "configuration-baselines",
    "hil-queue",
    "alert-quality",
    "detection-readiness",
    "conversation-delivery",
    "workflow-apps",
    "automation-blueprints",
    "processes",
    "scheduler-runs",
    "background-tasks",
    "scheduled-continuations",
    "provision",
    "onboarding",
];

const API_ENDPOINTS: [&str; 22] = [
    "/api/v4/operations/summary",
    "/api/v4/operations/live",
    "/api/v4/operations/live/stream",
    "/api/v4/operations/incidents",
    "/api/v4/operations/incidents/intervention",
    "/api/v4/operations/hil-queue",
    "/api/v4/operations/hil-queue/decision",
    "/api/v4/operations/alert-quality",
    "/api/v4/operations/detection-readiness",
    "/api/v4/operations/gpu",
    "/api/v4/operations/security",
    "/api/v4/operations/baselines",
    "/api/v4/operations/conversation-delivery",
    "/api/v4/operations/automation",
    "/api/v4/operations/workflow-apps",
    "/api/v4/operations/automation-blueprints",
    "/api/v4/operations/processes",
    "/api/v4/operations/scheduler-runs",
    "/api/v4/operations/background-tasks",
    "/api/v4/operations/scheduled-continuations",
    "/api/v4/operations/provision",
    "/api/v4/operations/onboarding",
];

pub fn panel_ids() -> &'static [&'static str] {
    &PANELS
}

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/operations", get(page_operations))
        .route("/api/v4/operations/summary", get(api_operations_summary))
        .route("/api/v4/operations/live", get(api_operations_live))
        .route(
            "/api/v4/operations/live/stream",
            get(api_operations_live_stream),
        )
        .route(
            "/api/v4/operations/incidents",
            get(api_operations_incidents).post(api_operations_create_incident),
        )
        .route(
            "/api/v4/operations/incidents/intervention",
            post(api_operations_incident_intervention),
        )
        .route("/api/v4/operations/hil-queue", get(api_operations_hil_queue))
        .route(
            "/api/v4/operations/hil-queue/decision",
            post(api_operations_hil_decision),
        )
        .route(
            "/api/v4/operations/alert-quality",
            get(api_operations_alert_quality),
        )
        .route(
            "/api/v4/operations/detection-readiness",
            get(api_operations_detection_readiness),
        )
        .route("/api/v4/operations/gpu", get(api_operations_gpu))
        .route("/api/v4/operations/security", get(api_operations_security))
        .route("/api/v4/operations/baselines", get(api_operations_baselines))
        .route(
            "/api/v4/operations/conversation-delivery",
            get(api_operations_conversation_delivery),
        )
        .route(
            "/api/v4/operations/automation",
            get(api_operations_automation),
        )
        .route(
            "/api/v4/operations/workflow-apps",
            get(api_operations_workflow_apps),
        )
        .route(
            "/api/v4/operations/automation-blueprints",
            get(api_operations_automation_blueprints),
        )
        .route("/api/v4/operations/processes", get(api_operations_processes))
        .route(
            "/api/v4/operations/scheduler-runs",
            get(api_operations_scheduler_runs),
        )
        .route(
            "/api/v4/operations/background-tasks",
            get(api_operations_background_tasks),
        )
        .route(
            "/api/v4/operations/scheduled-continuations",
            get(api_operations_scheduled_continuations),
        )
        .route("/api/v4/operations/provision", get(api_operations_provision))
        .route(
            "/api/v4/operations/onboarding",
            get(api_operations_onboarding),
        )
}

const MAX_LIVE_SSE_CONNECTIONS: usize = 32;
const MAX_LIVE_SSE_TICKS: u64 = 180;
const LIVE_SSE_INTERVAL_SECS: u64 = 3;
const MAX_QUERY_LEN: usize = 512;
const MAX_AUTH_HEADER_LEN: usize = 4096;

static LIVE_SSE_LIMITER: OnceLock<Arc<Semaphore>> = OnceLock::new();

fn live_sse_limiter() -> Arc<Semaphore> {
    Arc::clone(LIVE_SSE_LIMITER.get_or_init(|| Arc::new(Semaphore::new(MAX_LIVE_SSE_CONNECTIONS))))
}

fn auth_header_str(headers: &HeaderMap) -> Option<&str> {
    let raw = headers
        .get(header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok())?
        .trim();
    if raw.is_empty() || raw.len() > MAX_AUTH_HEADER_LEN {
        return None;
    }
    if !raw.bytes().all(|b| (0x20..=0x7e).contains(&b)) {
        return None;
    }
    Some(raw)
}

fn validated_bearer_actor(headers: &HeaderMap) -> Option<&'static str> {
    let raw = auth_header_str(headers)?;
    let mut parts = raw.split_whitespace();
    let scheme = parts.next()?;
    let token = parts.next()?;
    if parts.next().is_some() {
        return None;
    }
    if !scheme.eq_ignore_ascii_case("bearer") || token.len() < 8 {
        return None;
    }
    Some("authenticated-operator")
}

fn query_param_value(uri: &Uri, name: &str) -> Option<String> {
    let q = uri.query().and_then(sanitize_query_string)?;
    for pair in q.split('&') {
        if let Some((k, v)) = pair.split_once('=') {
            if k == name && !v.is_empty() && v.len() <= 128 {
                return Some(v.to_string());
            }
        }
    }
    None
}

fn is_db_measured(val: &Value) -> bool {
    val.get("measurement_status")
        .and_then(Value::as_str)
        == Some("measured")
}

fn postgres_direct_response(
    panel: &str,
    endpoint: &str,
    db_payload: Value,
    extra: Value,
    upstream_reachable: bool,
    upstream_status: u16,
) -> Response {
    json_no_store_response(
        StatusCode::OK,
        json!({
            "source": "postgres-direct",
            "domain": "operations",
            "panel": panel,
            "endpoint": endpoint,
            "measurement_state": "measured",
            "measurement_status": "measured",
            "execution_authority": false,
            "zero_substitution_forbidden": true,
            "observed_unix_ms": now_unix_ms(),
            "upstream_reachable": upstream_reachable,
            "upstream_status": upstream_status,
            "meta": extra,
            "data": db_payload
        }),
    )
}

fn sanitize_query_string(raw: &str) -> Option<String> {
    let trimmed = raw.trim();
    if trimmed.is_empty() || trimmed.len() > MAX_QUERY_LEN {
        return None;
    }
    let lowered = trimmed.to_ascii_lowercase();
    if lowered.contains("%0d")
        || lowered.contains("%0a")
        || lowered.contains("%00")
        || trimmed.contains("..")
        || trimmed.contains('#')
        || trimmed.contains('@')
        || trimmed.contains('\\')
    {
        return None;
    }
    let safe = trimmed.bytes().all(|b| {
        b.is_ascii_alphanumeric()
            || matches!(
                b,
                b'-' | b'_' | b'.' | b'=' | b'&' | b'%' | b':' | b',' | b'+' | b'/'
            )
    });
    if !safe {
        return None;
    }
    Some(trimmed.to_string())
}

fn with_optional_query(base_path: &str, uri: &Uri) -> String {
    match uri.query().and_then(sanitize_query_string) {
        Some(q) => format!("{base_path}?{q}"),
        None => base_path.to_string(),
    }
}

fn now_unix_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| u64::try_from(d.as_millis()).unwrap_or(u64::MAX))
        .unwrap_or(0)
}

fn is_safe_path_segment(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && !value.starts_with('.')
        && !value.ends_with('.')
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b'.'))
        && !value.contains("..")
}

fn has_disallowed_control_chars(value: &str) -> bool {
    value.chars().any(|c| c.is_control() && c != ' ')
}

fn json_no_store_response(status: StatusCode, body: Value) -> Response {
    (
        status,
        [
            (header::CACHE_CONTROL, "no-store"),
            (header::X_CONTENT_TYPE_OPTIONS, "nosniff"),
        ],
        Json(body),
    )
        .into_response()
}

fn is_measured(outcome: &UpstreamOutcome) -> bool {
    outcome.reachable && (200..300).contains(&outcome.status) && outcome.payload.is_some()
}

fn not_measured_reason(outcome: &UpstreamOutcome) -> &'static str {
    if !outcome.reachable {
        "operator-service offline or unreachable"
    } else if outcome.status == 401 || outcome.status == 403 {
        "operator-service authentication or authorization required"
    } else if outcome.status == 404 {
        "operator-service projection endpoint not configured"
    } else if outcome.status == 429 {
        "operator-service rate limited"
    } else if outcome.status == 502 || outcome.status == 504 {
        "operator-service gateway timeout or bad gateway"
    } else if outcome.status == 503 {
        "operator-service collector or upstream unavailable"
    } else if (200..300).contains(&outcome.status) && outcome.payload.is_none() {
        "operator-service returned malformed non-json payload"
    } else {
        "operator-service returned non-measured response"
    }
}

fn single_upstream_response(
    state: &AppState,
    panel: &str,
    endpoint: &str,
    outcome: UpstreamOutcome,
    db_fallback: Option<Value>,
    extra: Value,
) -> Response {
    if is_measured(&outcome) {
        if let Some(payload) = outcome.payload {
            return json_no_store_response(
                StatusCode::OK,
                json!({
                    "source": "operator-service",
                    "domain": "operations",
                    "panel": panel,
                    "endpoint": endpoint,
                    "measurement_state": "measured",
                    "measurement_status": "measured",
                    "execution_authority": false,
                    "zero_substitution_forbidden": true,
                    "observed_unix_ms": now_unix_ms(),
                    "upstream_reachable": true,
                    "upstream_status": outcome.status,
                    "meta": extra,
                    "data": payload
                }),
            );
        }
    }

    if let Some(db_val) = db_fallback {
        if is_db_measured(&db_val) {
            return postgres_direct_response(
                panel,
                endpoint,
                db_val,
                extra,
                outcome.reachable,
                outcome.status,
            );
        }
    }

    let reason = not_measured_reason(&outcome);
    let mut env = state
        .upstream
        .not_measured_envelope("operations", endpoint, reason);
    if let Value::Object(ref mut map) = env {
        map.insert("panel".to_string(), json!(panel));
        map.insert("measurement_status".to_string(), json!("not-measured"));
        map.insert("execution_authority".to_string(), json!(false));
        map.insert("zero_substitution_forbidden".to_string(), json!(true));
        map.insert("observed_unix_ms".to_string(), json!(now_unix_ms()));
        map.insert("upstream_reachable".to_string(), json!(outcome.reachable));
        map.insert("upstream_status".to_string(), json!(outcome.status));
        map.insert("meta".to_string(), extra);
    }
    json_no_store_response(StatusCode::OK, env)
}

fn aggregate_upstream_response(
    state: &AppState,
    panel: &str,
    primary_endpoint: &str,
    parts: Vec<(&'static str, &'static str, UpstreamOutcome)>,
    db_fallback: Option<Value>,
    extra: Value,
) -> Response {
    let mut measured_count: usize = 0;
    let total_count = parts.len();
    let mut data_map = Map::new();
    let mut sources_map = Map::new();
    let mut any_reachable = false;
    let mut first_status: u16 = 0;
    let mut first_reason = "operator-service offline or unauthenticated";

    for (key, endpoint, outcome) in parts {
        if outcome.reachable {
            any_reachable = true;
        }
        if first_status == 0 && outcome.status != 0 {
            first_status = outcome.status;
        }
        if is_measured(&outcome) {
            measured_count += 1;
            if let Some(payload) = outcome.payload {
                data_map.insert(key.to_string(), payload);
            }
            sources_map.insert(
                key.to_string(),
                json!({
                    "endpoint": endpoint,
                    "measurement_state": "measured",
                    "reachable": true,
                    "status": outcome.status
                }),
            );
        } else {
            let reason = not_measured_reason(&outcome);
            first_reason = reason;
            data_map.insert(key.to_string(), Value::Null);
            sources_map.insert(
                key.to_string(),
                json!({
                    "endpoint": endpoint,
                    "measurement_state": "not-measured",
                    "reachable": outcome.reachable,
                    "status": outcome.status,
                    "reason": reason
                }),
            );
        }
    }

    if measured_count == 0 {
        if let Some(db_val) = db_fallback {
            if is_db_measured(&db_val) {
                return postgres_direct_response(
                    panel,
                    primary_endpoint,
                    db_val,
                    extra,
                    any_reachable,
                    first_status,
                );
            }
        }
        let mut env =
            state
                .upstream
                .not_measured_envelope("operations", primary_endpoint, first_reason);
        if let Value::Object(ref mut map) = env {
            map.insert("panel".to_string(), json!(panel));
            map.insert("measurement_status".to_string(), json!("not-measured"));
            map.insert("execution_authority".to_string(), json!(false));
            map.insert("zero_substitution_forbidden".to_string(), json!(true));
            map.insert("observed_unix_ms".to_string(), json!(now_unix_ms()));
            map.insert("upstream_reachable".to_string(), json!(any_reachable));
            map.insert("upstream_status".to_string(), json!(first_status));
            map.insert("sources".to_string(), Value::Object(sources_map));
            map.insert("meta".to_string(), extra);
        }
        return json_no_store_response(StatusCode::OK, env);
    }

    let state_label = if measured_count == total_count {
        "measured"
    } else {
        "partial"
    };

    json_no_store_response(
        StatusCode::OK,
        json!({
            "source": "operator-service",
            "domain": "operations",
            "panel": panel,
            "endpoint": primary_endpoint,
            "measurement_state": state_label,
            "measurement_status": state_label,
            "execution_authority": false,
            "zero_substitution_forbidden": true,
            "observed_unix_ms": now_unix_ms(),
            "measured_sources": measured_count,
            "total_sources": total_count,
            "sources": Value::Object(sources_map),
            "meta": extra,
            "data": Value::Object(data_map)
        }),
    )
}

async fn page_operations(State(state): State<AppState>) -> Response {
    let html = finalize_v4_html(
        TEMPLATE,
        "operations",
        "live",
        &state.operator_url,
        json!({
            "panels": PANELS,
            "endpoints": API_ENDPOINTS
        }),
    );
    html_response(html)
}

async fn api_operations_summary(State(state): State<AppState>, headers: HeaderMap) -> Response {
    let auth = auth_header_str(&headers);
    let (incidents, hil_queue, findings, detection) = tokio::join!(
        state.upstream.get_json("/incidents", auth),
        state.upstream.get_json("/hil-queue", auth),
        state.upstream.get_json("/findings", auth),
        state.upstream.get_json("/detection-readiness", auth),
    );
    let any_up = is_measured(&incidents)
        || is_measured(&hil_queue)
        || is_measured(&findings)
        || is_measured(&detection);
    let db_fallback = if !any_up && state.db.is_configured() {
        Some(ops_repo::fetch_summary(&state.db).await)
    } else {
        None
    };
    aggregate_upstream_response(
        &state,
        "summary",
        "/incidents",
        vec![
            ("incidents", "/incidents", incidents),
            ("hil_queue", "/hil-queue", hil_queue),
            ("findings", "/findings", findings),
            ("detection_readiness", "/detection-readiness", detection),
        ],
        db_fallback,
        json!({
            "panels": PANELS,
            "panel_count": PANELS.len()
        }),
    )
}

async fn api_operations_live(State(state): State<AppState>, headers: HeaderMap) -> Response {
    let auth = auth_header_str(&headers);
    let (data_sources, incidents, activity) = tokio::join!(
        state.upstream.get_json("/system/data-sources", auth),
        state.upstream.get_json("/incidents", auth),
        state.upstream.get_json("/agents/activity", auth),
    );
    let any_up = is_measured(&data_sources) || is_measured(&incidents) || is_measured(&activity);
    let db_fallback = if !any_up && state.db.is_configured() {
        Some(ops_repo::fetch_live_inventory(&state.db).await)
    } else {
        None
    };
    aggregate_upstream_response(
        &state,
        "live",
        "/system/data-sources",
        vec![
            ("data_sources", "/system/data-sources", data_sources),
            ("incidents", "/incidents", incidents),
            ("agents_activity", "/agents/activity", activity),
        ],
        db_fallback,
        json!({
            "stream_endpoint": "/api/v4/operations/live/stream",
            "dropped_frames": 0
        }),
    )
}

async fn build_live_stream_payload(
    state: &AppState,
    auth: Option<&str>,
    seq: u64,
    event_kind: &'static str,
) -> Value {
    let (data_sources, incidents) = tokio::join!(
        state.upstream.get_json("/system/data-sources", auth),
        state.upstream.get_json("/incidents", auth),
    );
    let ds_measured = is_measured(&data_sources);
    let inc_measured = is_measured(&incidents);
    if ds_measured || inc_measured {
        let measurement_state = if ds_measured && inc_measured {
            "measured"
        } else {
            "partial"
        };
        return json!({
            "kind": event_kind,
            "seq": seq,
            "domain": "operations",
            "panel": "live",
            "source": "operator-service",
            "measurement_state": measurement_state,
            "measurement_status": measurement_state,
            "execution_authority": false,
            "zero_substitution_forbidden": true,
            "observed_unix_ms": now_unix_ms(),
            "dropped_frames": 0,
            "upstream_url": state.upstream.base_url(),
            "upstream_reachable": true,
            "data_sources": if ds_measured { data_sources.payload } else { None },
            "incidents": if inc_measured { incidents.payload } else { None },
            "reason": Value::Null
        });
    }

    if state.db.is_configured() {
        let db_snap = ops_repo::fetch_live_stream_snapshot(&state.db).await;
        if is_db_measured(&db_snap) {
            return json!({
                "kind": event_kind,
                "seq": seq,
                "domain": "operations",
                "panel": "live",
                "source": "postgres-direct",
                "measurement_state": "measured",
                "measurement_status": "measured",
                "execution_authority": false,
                "zero_substitution_forbidden": true,
                "observed_unix_ms": now_unix_ms(),
                "observed_at": db_snap.get("observed_at").cloned().unwrap_or_else(|| json!("")),
                "db_latency_ms": db_snap.get("db_latency_ms").cloned().unwrap_or(Value::Null),
                "latest_audit_seq": db_snap.get("latest_audit_seq").cloned().unwrap_or(Value::Null),
                "latest_audit_events": db_snap.get("latest_audit_events").cloned().unwrap_or_else(|| json!([])),
                "dropped_frames": 0,
                "upstream_url": state.upstream.base_url(),
                "upstream_reachable": false,
                "counts": db_snap.get("counts").cloned().unwrap_or(Value::Null),
                "realtime_resources": db_snap.get("realtime_resources").cloned().unwrap_or(Value::Null),
                "incidents": db_snap.get("incidents").cloned().unwrap_or(Value::Null),
                "hil_queue": db_snap.get("hil_queue").cloned().unwrap_or(Value::Null),
                "reason": Value::Null
            });
        }
    }

    let reason = Some(not_measured_reason(&data_sources));
    json!({
        "kind": event_kind,
        "seq": seq,
        "domain": "operations",
        "panel": "live",
        "source": "console-v4-rust",
        "measurement_state": "not-measured",
        "measurement_status": "not-measured",
        "execution_authority": false,
        "zero_substitution_forbidden": true,
        "observed_unix_ms": now_unix_ms(),
        "dropped_frames": 0,
        "upstream_url": state.upstream.base_url(),
        "upstream_reachable": data_sources.reachable || incidents.reachable,
        "data_sources": Value::Null,
        "incidents": Value::Null,
        "reason": reason
    })
}

async fn api_operations_live_stream(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Response {
    let Ok(permit) = live_sse_limiter().try_acquire_owned() else {
        let mut resp = json_no_store_response(
            StatusCode::SERVICE_UNAVAILABLE,
            json!({
                "source": "console-v4-rust",
                "domain": "operations",
                "panel": "live",
                "measurement_state": "not-measured",
                "measurement_status": "not-measured",
                "execution_authority": false,
                "fail_closed": true,
                "error": "sse_capacity_exceeded",
                "max_connections": MAX_LIVE_SSE_CONNECTIONS,
                "observed_unix_ms": now_unix_ms(),
                "reason": "live SSE concurrent connection cap reached"
            }),
        );
        resp.headers_mut()
            .insert(header::RETRY_AFTER, HeaderValue::from_static("5"));
        return resp;
    };

    let lease_guard = SseLeaseDropGuard::acquire(Arc::clone(&state.active_sse));
    let auth_owned = auth_header_str(&headers).map(ToString::to_string);
    let mut ticker = tokio::time::interval_at(
        tokio::time::Instant::now() + Duration::from_secs(LIVE_SSE_INTERVAL_SECS),
        Duration::from_secs(LIVE_SSE_INTERVAL_SECS),
    );
    ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);

    let event_stream = stream::unfold(
        (state, auth_owned, ticker, 0_u64, permit, lease_guard),
        |(state, auth_owned, mut ticker, seq, permit, lease_guard)| async move {
            if seq >= MAX_LIVE_SSE_TICKS {
                return None;
            }
            if seq > 0 {
                ticker.tick().await;
            }
            let event_kind = if seq == 0 { "snapshot" } else { "tick" };
            let payload =
                build_live_stream_payload(&state, auth_owned.as_deref(), seq, event_kind).await;
            let event = Event::default()
                .id(format!("ops-live-{seq}"))
                .event(event_kind)
                .retry(Duration::from_secs(LIVE_SSE_INTERVAL_SECS))
                .data(payload.to_string());
            Some((
                Ok::<Event, Infallible>(event),
                (
                    state,
                    auth_owned,
                    ticker,
                    seq.saturating_add(1),
                    permit,
                    lease_guard,
                ),
            ))
        },
    );

    let mut resp = Sse::new(event_stream)
        .keep_alive(
            KeepAlive::new()
                .interval(Duration::from_secs(15))
                .text("keep-alive"),
        )
        .into_response();
    let hdrs = resp.headers_mut();
    hdrs.insert(header::CACHE_CONTROL, HeaderValue::from_static("no-store"));
    hdrs.insert(
        header::X_CONTENT_TYPE_OPTIONS,
        HeaderValue::from_static("nosniff"),
    );
    hdrs.insert(
        HeaderName::from_static("x-accel-buffering"),
        HeaderValue::from_static("no"),
    );
    resp
}

async fn api_operations_incidents(
    State(state): State<AppState>,
    headers: HeaderMap,
    uri: Uri,
) -> Response {
    let auth = auth_header_str(&headers);
    let path = with_optional_query("/incidents", &uri);
    let up = state.upstream.get_json(&path, auth).await;
    let db_fallback = if !is_measured(&up) && state.db.is_configured() {
        let limit = query_param_value(&uri, "limit").and_then(|s| s.parse::<usize>().ok());
        let search = query_param_value(&uri, "q").or_else(|| query_param_value(&uri, "search"));
        Some(ops_repo::fetch_incidents_filtered(&state.db, limit, search.as_deref()).await)
    } else {
        None
    };
    single_upstream_response(
        &state,
        "incidents",
        &path,
        up,
        db_fallback,
        json!({
            "intervention_endpoint": "/api/v4/operations/incidents/intervention",
            "lifecycle_phases": ["investigate", "approve", "respond", "verify"]
        }),
    )
}

#[derive(Debug, Deserialize)]
struct CreateIncidentRequest {
    title: String,
    severity: String,
    subscription: String,
    resource: String,
    #[serde(default = "default_incident_vertical")]
    vertical: String,
    summary: String,
    #[serde(default)]
    idempotency_key: Option<String>,
}

fn default_incident_vertical() -> String {
    "sre".to_string()
}

async fn api_operations_create_incident(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<CreateIncidentRequest>,
) -> Response {
    let title = req.title.trim();
    let title_len = title.chars().count();
    if !(5..=160).contains(&title_len) || has_disallowed_control_chars(title) {
        return json_no_store_response(
            StatusCode::BAD_REQUEST,
            json!({
                "domain": "operations",
                "panel": "incidents",
                "recorded": false,
                "fail_closed": true,
                "execution_authority": false,
                "observed_unix_ms": now_unix_ms(),
                "error": "invalid_title",
                "message": "장애 제목은 제어문자 없이 5자 이상 160자 이하로 입력해야 합니다."
            }),
        );
    }

    let severity = req.severity.trim().to_ascii_lowercase();
    if !matches!(severity.as_str(), "critical" | "high" | "medium" | "low") {
        return json_no_store_response(
            StatusCode::BAD_REQUEST,
            json!({
                "domain": "operations",
                "panel": "incidents",
                "recorded": false,
                "fail_closed": true,
                "execution_authority": false,
                "observed_unix_ms": now_unix_ms(),
                "error": "invalid_severity",
                "message": "심각도는 critical, high, medium, low 중 하나여야 합니다."
            }),
        );
    }

    let subscription = req.subscription.trim();
    if !is_safe_path_segment(subscription) {
        return json_no_store_response(
            StatusCode::BAD_REQUEST,
            json!({
                "domain": "operations",
                "panel": "incidents",
                "recorded": false,
                "fail_closed": true,
                "execution_authority": false,
                "observed_unix_ms": now_unix_ms(),
                "error": "invalid_subscription",
                "message": "유효한 대상 구독 식별자가 필요합니다."
            }),
        );
    }

    let resource = req.resource.trim();
    let resource_len = resource.chars().count();
    if !(2..=120).contains(&resource_len) || has_disallowed_control_chars(resource) {
        return json_no_store_response(
            StatusCode::BAD_REQUEST,
            json!({
                "domain": "operations",
                "panel": "incidents",
                "recorded": false,
                "fail_closed": true,
                "execution_authority": false,
                "observed_unix_ms": now_unix_ms(),
                "error": "invalid_resource",
                "message": "대상 리소스는 제어문자 없이 2자 이상 120자 이하로 입력해야 합니다."
            }),
        );
    }

    let vertical = req.vertical.trim().to_ascii_lowercase();
    if !matches!(vertical.as_str(), "sre" | "security" | "finops") {
        return json_no_store_response(
            StatusCode::BAD_REQUEST,
            json!({
                "domain": "operations",
                "panel": "incidents",
                "recorded": false,
                "fail_closed": true,
                "execution_authority": false,
                "observed_unix_ms": now_unix_ms(),
                "error": "invalid_vertical",
                "message": "영역은 sre, security, finops 중 하나여야 합니다."
            }),
        );
    }

    let summary = req.summary.trim();
    let summary_len = summary.chars().count();
    if !(10..=2000).contains(&summary_len) || has_disallowed_control_chars(summary) {
        return json_no_store_response(
            StatusCode::BAD_REQUEST,
            json!({
                "domain": "operations",
                "panel": "incidents",
                "recorded": false,
                "fail_closed": true,
                "execution_authority": false,
                "observed_unix_ms": now_unix_ms(),
                "error": "invalid_summary",
                "message": "초기 상황 및 근거는 제어문자 없이 10자 이상 2000자 이하로 입력해야 합니다."
            }),
        );
    }

    if let Some(ref key) = req.idempotency_key {
        if !is_safe_path_segment(key.trim()) {
            return json_no_store_response(
                StatusCode::BAD_REQUEST,
                json!({
                    "domain": "operations",
                    "panel": "incidents",
                    "recorded": false,
                    "fail_closed": true,
                    "execution_authority": false,
                    "observed_unix_ms": now_unix_ms(),
                    "error": "invalid_idempotency_key",
                    "message": "유효한 멱등키(idempotency_key) 형식이 필요합니다."
                }),
            );
        }
    }

    let auth = auth_header_str(&headers);
    let mut payload_body = json!({
        "title": title,
        "severity": severity,
        "subscription": subscription,
        "resource": resource,
        "vertical": vertical,
        "summary": summary,
        "origin": "human-manual"
    });
    if let (Some(key), Value::Object(ref mut map)) =
        (req.idempotency_key.as_deref(), &mut payload_body)
    {
        map.insert("idempotency_key".to_string(), json!(key.trim()));
    }

    let up = state
        .upstream
        .post_json("/incidents", payload_body, auth)
        .await;

    if up.reachable && (200..300).contains(&up.status) {
        return json_no_store_response(
            StatusCode::CREATED,
            json!({
                "source": "operator-service",
                "domain": "operations",
                "panel": "incidents",
                "endpoint": "/incidents",
                "measurement_state": "measured",
                "measurement_status": "measured",
                "recorded": true,
                "persisted": true,
                "fail_closed": false,
                "execution_authority": false,
                "origin": "human-manual",
                "observed_unix_ms": now_unix_ms(),
                "upstream_status": up.status,
                "data": up.payload
            }),
        );
    }

    if !up.reachable && state.db.mutations_allowed() {
        let Some(actor) = validated_bearer_actor(&headers) else {
            return json_no_store_response(
                StatusCode::UNAUTHORIZED,
                json!({
                    "source": "console-v4-rust",
                    "domain": "operations",
                    "panel": "incidents",
                    "endpoint": "/incidents",
                    "measurement_state": "not-measured",
                    "measurement_status": "not-measured",
                    "recorded": false,
                    "persisted": false,
                    "fail_closed": true,
                    "execution_authority": false,
                    "origin": "human-manual",
                    "observed_unix_ms": now_unix_ms(),
                    "error": "bearer_token_required",
                    "reason": "DB 직접 영속화에는 유효한 Bearer 인증 토큰이 필요합니다."
                }),
            );
        };
        let ts = now_unix_ms();
        let inc_id = format!("INC-V4-{ts}");
        let idem = req
            .idempotency_key
            .as_deref()
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(ToString::to_string)
            .unwrap_or_else(|| format!("inc-create-{ts}"));
        let kv_key = format!("console_v4:operations:incident:{inc_id}");
        let stored = json!({
            "id": inc_id,
            "title": title,
            "severity": severity,
            "subscription": subscription,
            "resource": resource,
            "vertical": vertical,
            "summary": summary,
            "actor": actor,
            "origin": "human-manual",
            "idempotency_key": idem,
            "observed_unix_ms": ts
        });
        match state
            .db
            .execute_audited_kv_mutation(
                &kv_key,
                &stored.to_string(),
                actor,
                "operations.incident.create",
                &idem,
            )
            .await
        {
            Ok(receipt) => {
                return json_no_store_response(
                    StatusCode::CREATED,
                    json!({
                        "source": "postgres-direct",
                        "domain": "operations",
                        "panel": "incidents",
                        "endpoint": "/incidents",
                        "measurement_state": "measured",
                        "measurement_status": "measured",
                        "recorded": true,
                        "persisted": true,
                        "fail_closed": false,
                        "execution_authority": false,
                        "origin": "human-manual",
                        "observed_unix_ms": ts,
                        "data": {
                            "id": inc_id,
                            "incident_id": inc_id,
                            "receipt": receipt
                        }
                    }),
                );
            }
            Err(code) => {
                return json_no_store_response(
                    StatusCode::SERVICE_UNAVAILABLE,
                    json!({
                        "source": "postgres-direct",
                        "domain": "operations",
                        "panel": "incidents",
                        "endpoint": "/incidents",
                        "measurement_state": "not-measured",
                        "measurement_status": "not-measured",
                        "recorded": false,
                        "persisted": false,
                        "fail_closed": true,
                        "execution_authority": false,
                        "origin": "human-manual",
                        "observed_unix_ms": ts,
                        "reason": code
                    }),
                );
            }
        }
    }

    let status = if up.reachable && matches!(up.status, 401 | 403 | 409 | 429) {
        StatusCode::from_u16(up.status).unwrap_or(StatusCode::SERVICE_UNAVAILABLE)
    } else {
        StatusCode::SERVICE_UNAVAILABLE
    };

    json_no_store_response(
        status,
        json!({
            "source": "console-v4-rust",
            "domain": "operations",
            "panel": "incidents",
            "endpoint": "/incidents",
            "measurement_state": "not-measured",
            "measurement_status": "not-measured",
            "recorded": false,
            "persisted": false,
            "db_writes_enabled": state.db.mutations_allowed(),
            "fail_closed": true,
            "execution_authority": false,
            "origin": "human-manual",
            "observed_unix_ms": now_unix_ms(),
            "upstream_reachable": up.reachable,
            "upstream_status": up.status,
            "reason": not_measured_reason(&up),
            "data": up.payload
        }),
    )
}

#[derive(Debug, Deserialize)]
struct IncidentInterventionRequest {
    correlation_id: String,
    action: String,
    reason: String,
    #[serde(default)]
    idempotency_key: Option<String>,
}

async fn api_operations_incident_intervention(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<IncidentInterventionRequest>,
) -> Response {
    let corr_id = req.correlation_id.trim();
    if !is_safe_path_segment(corr_id) {
        return json_no_store_response(
            StatusCode::BAD_REQUEST,
            json!({
                "domain": "operations",
                "panel": "incidents",
                "recorded": false,
                "fail_closed": true,
                "execution_authority": false,
                "observed_unix_ms": now_unix_ms(),
                "error": "invalid_correlation_id",
                "message": "유효한 장애 식별자(correlation_id)가 필요합니다."
            }),
        );
    }

    let action = req.action.trim();
    if !matches!(action, "guidance" | "dev_exception" | "close") {
        return json_no_store_response(
            StatusCode::BAD_REQUEST,
            json!({
                "domain": "operations",
                "panel": "incidents",
                "recorded": false,
                "fail_closed": true,
                "execution_authority": false,
                "observed_unix_ms": now_unix_ms(),
                "error": "invalid_intervention_action",
                "message": "개입 유형은 guidance, dev_exception, close 중 하나여야 합니다."
            }),
        );
    }

    let reason = req.reason.trim();
    let reason_len = reason.chars().count();
    if !(5..=2000).contains(&reason_len) || has_disallowed_control_chars(reason) {
        return json_no_store_response(
            StatusCode::BAD_REQUEST,
            json!({
                "domain": "operations",
                "panel": "incidents",
                "recorded": false,
                "fail_closed": true,
                "execution_authority": false,
                "observed_unix_ms": now_unix_ms(),
                "error": "invalid_reason",
                "message": "개입 사유는 제어문자 없이 5자 이상 2000자 이하로 입력해야 합니다."
            }),
        );
    }

    if let Some(ref key) = req.idempotency_key {
        if !is_safe_path_segment(key.trim()) {
            return json_no_store_response(
                StatusCode::BAD_REQUEST,
                json!({
                    "domain": "operations",
                    "panel": "incidents",
                    "recorded": false,
                    "fail_closed": true,
                    "execution_authority": false,
                    "observed_unix_ms": now_unix_ms(),
                    "error": "invalid_idempotency_key",
                    "message": "유효한 멱등키(idempotency_key) 형식이 필요합니다."
                }),
            );
        }
    }

    let auth = auth_header_str(&headers);
    let upstream_path = format!("/incidents/{corr_id}/interventions");
    let mut payload_body = json!({
        "action": action,
        "reason": reason
    });
    if let (Some(key), Value::Object(ref mut map)) = (req.idempotency_key.as_deref(), &mut payload_body) {
        map.insert("idempotency_key".to_string(), json!(key.trim()));
    }
    let up = state
        .upstream
        .post_json(&upstream_path, payload_body, auth)
        .await;

    if up.reachable && (200..300).contains(&up.status) {
        return json_no_store_response(
            StatusCode::OK,
            json!({
                "source": "operator-service",
                "domain": "operations",
                "panel": "incidents",
                "measurement_state": "measured",
                "measurement_status": "measured",
                "recorded": true,
                "persisted": true,
                "fail_closed": false,
                "execution_authority": false,
                "observed_unix_ms": now_unix_ms(),
                "correlation_id": corr_id,
                "action": action,
                "upstream_status": up.status,
                "data": up.payload
            }),
        );
    }

    if !up.reachable && state.db.mutations_allowed() {
        let Some(actor) = validated_bearer_actor(&headers) else {
            return json_no_store_response(
                StatusCode::UNAUTHORIZED,
                json!({
                    "source": "console-v4-rust",
                    "domain": "operations",
                    "panel": "incidents",
                    "endpoint": upstream_path,
                    "measurement_state": "not-measured",
                    "measurement_status": "not-measured",
                    "recorded": false,
                    "persisted": false,
                    "fail_closed": true,
                    "execution_authority": false,
                    "observed_unix_ms": now_unix_ms(),
                    "correlation_id": corr_id,
                    "error": "bearer_token_required",
                    "reason": "DB 직접 개입 기록에는 유효한 Bearer 인증 토큰이 필요합니다."
                }),
            );
        };
        let ts = now_unix_ms();
        let idem = req
            .idempotency_key
            .as_deref()
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(ToString::to_string)
            .unwrap_or_else(|| format!("inc-int-{corr_id}-{ts}"));
        let kv_key = format!("console_v4:operations:intervention:{corr_id}:{ts}");
        let stored = json!({
            "correlation_id": corr_id,
            "action": action,
            "reason": reason,
            "actor": actor,
            "idempotency_key": idem,
            "observed_unix_ms": ts
        });
        match state
            .db
            .execute_audited_kv_mutation(
                &kv_key,
                &stored.to_string(),
                actor,
                "operations.incident.intervention",
                &idem,
            )
            .await
        {
            Ok(receipt) => {
                return json_no_store_response(
                    StatusCode::OK,
                    json!({
                        "source": "postgres-direct",
                        "domain": "operations",
                        "panel": "incidents",
                        "endpoint": upstream_path,
                        "measurement_state": "measured",
                        "measurement_status": "measured",
                        "recorded": true,
                        "persisted": true,
                        "fail_closed": false,
                        "execution_authority": false,
                        "observed_unix_ms": ts,
                        "correlation_id": corr_id,
                        "action": action,
                        "data": receipt
                    }),
                );
            }
            Err(code) => {
                return json_no_store_response(
                    StatusCode::SERVICE_UNAVAILABLE,
                    json!({
                        "source": "postgres-direct",
                        "domain": "operations",
                        "panel": "incidents",
                        "endpoint": upstream_path,
                        "measurement_state": "not-measured",
                        "measurement_status": "not-measured",
                        "recorded": false,
                        "persisted": false,
                        "fail_closed": true,
                        "execution_authority": false,
                        "observed_unix_ms": ts,
                        "correlation_id": corr_id,
                        "reason": code
                    }),
                );
            }
        }
    }

    let status = if up.reachable && matches!(up.status, 401 | 403 | 409 | 429) {
        StatusCode::from_u16(up.status).unwrap_or(StatusCode::SERVICE_UNAVAILABLE)
    } else {
        StatusCode::SERVICE_UNAVAILABLE
    };

    json_no_store_response(
        status,
        json!({
            "source": "console-v4-rust",
            "domain": "operations",
            "panel": "incidents",
            "endpoint": upstream_path,
            "measurement_state": "not-measured",
            "measurement_status": "not-measured",
            "recorded": false,
            "persisted": false,
            "db_writes_enabled": state.db.mutations_allowed(),
            "fail_closed": true,
            "execution_authority": false,
            "observed_unix_ms": now_unix_ms(),
            "correlation_id": corr_id,
            "upstream_reachable": up.reachable,
            "upstream_status": up.status,
            "reason": not_measured_reason(&up),
            "data": up.payload
        }),
    )
}

async fn api_operations_hil_queue(
    State(state): State<AppState>,
    headers: HeaderMap,
    uri: Uri,
) -> Response {
    let auth = auth_header_str(&headers);
    let queue_path = with_optional_query("/hil-queue", &uri);
    let (queue, contacts) = tokio::join!(
        state.upstream.get_json(&queue_path, auth),
        state
            .upstream
            .get_json("/hil/report-line-contact-requests", auth),
    );
    let any_up = is_measured(&queue) || is_measured(&contacts);
    let db_fallback = if !any_up && state.db.is_configured() {
        Some(ops_repo::fetch_hil_queue(&state.db).await)
    } else {
        None
    };
    aggregate_upstream_response(
        &state,
        "hil-queue",
        "/hil-queue",
        vec![
            ("queue", "/hil-queue", queue),
            (
                "report_line_contacts",
                "/hil/report-line-contact-requests",
                contacts,
            ),
        ],
        db_fallback,
        json!({
            "decision_endpoint": "/api/v4/operations/hil-queue/decision",
            "silence_denies": true,
            "safeguards_required": 7
        }),
    )
}

#[derive(Debug, Deserialize)]
struct HilDecisionRequest {
    approval_id: String,
    decision: String,
    reason: String,
    #[serde(default)]
    idempotency_key: Option<String>,
}

async fn api_operations_hil_decision(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<HilDecisionRequest>,
) -> Response {
    let approval_id = req.approval_id.trim();
    if !is_safe_path_segment(approval_id) {
        return json_no_store_response(
            StatusCode::BAD_REQUEST,
            json!({
                "domain": "operations",
                "panel": "hil-queue",
                "recorded": false,
                "fail_closed": true,
                "execution_authority": false,
                "approver_executor_separated": true,
                "silence_denies": true,
                "observed_unix_ms": now_unix_ms(),
                "error": "invalid_approval_id",
                "message": "유효한 승인 요청 ID(approval_id)가 필요합니다."
            }),
        );
    }

    let decision = req.decision.trim().to_ascii_lowercase();
    if decision != "approve" && decision != "reject" {
        return json_no_store_response(
            StatusCode::BAD_REQUEST,
            json!({
                "domain": "operations",
                "panel": "hil-queue",
                "recorded": false,
                "fail_closed": true,
                "execution_authority": false,
                "approver_executor_separated": true,
                "silence_denies": true,
                "observed_unix_ms": now_unix_ms(),
                "error": "invalid_decision",
                "message": "결정은 approve 또는 reject만 허용됩니다."
            }),
        );
    }

    let reason = req.reason.trim();
    let reason_len = reason.chars().count();
    if !(5..=2000).contains(&reason_len) || has_disallowed_control_chars(reason) {
        return json_no_store_response(
            StatusCode::BAD_REQUEST,
            json!({
                "domain": "operations",
                "panel": "hil-queue",
                "recorded": false,
                "fail_closed": true,
                "execution_authority": false,
                "approver_executor_separated": true,
                "silence_denies": true,
                "observed_unix_ms": now_unix_ms(),
                "error": "invalid_reason",
                "message": "승인·거절 사유는 제어문자 없이 5자 이상 2000자 이하로 입력해야 합니다."
            }),
        );
    }

    if let Some(ref key) = req.idempotency_key {
        if !is_safe_path_segment(key.trim()) {
            return json_no_store_response(
                StatusCode::BAD_REQUEST,
                json!({
                    "domain": "operations",
                    "panel": "hil-queue",
                    "recorded": false,
                    "fail_closed": true,
                    "execution_authority": false,
                    "approver_executor_separated": true,
                    "silence_denies": true,
                    "observed_unix_ms": now_unix_ms(),
                    "error": "invalid_idempotency_key",
                    "message": "유효한 멱등키(idempotency_key) 형식이 필요합니다."
                }),
            );
        }
    }

    let auth = auth_header_str(&headers);
    let mut body = json!({
        "decision": decision,
        "reason": reason
    });
    if let (Some(key), Value::Object(ref mut map)) = (req.idempotency_key.as_deref(), &mut body) {
        map.insert("idempotency_key".to_string(), json!(key.trim()));
    }

    let primary_path = format!("/hil/{approval_id}/operator-decision");
    let mut up = state
        .upstream
        .post_json(&primary_path, body.clone(), auth)
        .await;
    let mut used_path = primary_path;

    if up.reachable && (up.status == 404 || up.status == 405) {
        let fallback_path = format!("/hil/{approval_id}/decision");
        up = state.upstream.post_json(&fallback_path, body, auth).await;
        used_path = fallback_path;
    }

    if up.reachable && (200..300).contains(&up.status) {
        return json_no_store_response(
            StatusCode::OK,
            json!({
                "source": "operator-service",
                "domain": "operations",
                "panel": "hil-queue",
                "endpoint": used_path,
                "measurement_state": "measured",
                "measurement_status": "measured",
                "recorded": true,
                "persisted": true,
                "fail_closed": false,
                "execution_authority": false,
                "approver_executor_separated": true,
                "silence_denies": true,
                "observed_unix_ms": now_unix_ms(),
                "approval_id": approval_id,
                "decision": decision,
                "upstream_status": up.status,
                "data": up.payload
            }),
        );
    }

    if !up.reachable && state.db.mutations_allowed() {
        let Some(actor) = validated_bearer_actor(&headers) else {
            return json_no_store_response(
                StatusCode::UNAUTHORIZED,
                json!({
                    "source": "console-v4-rust",
                    "domain": "operations",
                    "panel": "hil-queue",
                    "endpoint": used_path,
                    "measurement_state": "not-measured",
                    "measurement_status": "not-measured",
                    "recorded": false,
                    "persisted": false,
                    "fail_closed": true,
                    "execution_authority": false,
                    "approver_executor_separated": true,
                    "silence_denies": true,
                    "observed_unix_ms": now_unix_ms(),
                    "approval_id": approval_id,
                    "decision": decision,
                    "error": "bearer_token_required",
                    "reason": "DB 직접 HIL 승인·거절 기록에는 유효한 Bearer 인증 토큰이 필요합니다."
                }),
            );
        };
        let ts = now_unix_ms();
        let idem = req
            .idempotency_key
            .as_deref()
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(ToString::to_string)
            .unwrap_or_else(|| format!("hil-dec-{approval_id}-{ts}"));
        let kv_key = format!("console_v4:operations:hil_decision:{approval_id}");
        let stored = json!({
            "approval_id": approval_id,
            "decision": decision,
            "reason": reason,
            "actor": actor,
            "approver_executor_separated": true,
            "silence_denies": true,
            "idempotency_key": idem,
            "observed_unix_ms": ts
        });
        match state
            .db
            .execute_audited_kv_mutation(
                &kv_key,
                &stored.to_string(),
                actor,
                "operations.hil.decision",
                &idem,
            )
            .await
        {
            Ok(receipt) => {
                return json_no_store_response(
                    StatusCode::OK,
                    json!({
                        "source": "postgres-direct",
                        "domain": "operations",
                        "panel": "hil-queue",
                        "endpoint": used_path,
                        "measurement_state": "measured",
                        "measurement_status": "measured",
                        "recorded": true,
                        "persisted": true,
                        "fail_closed": false,
                        "execution_authority": false,
                        "approver_executor_separated": true,
                        "silence_denies": true,
                        "observed_unix_ms": ts,
                        "approval_id": approval_id,
                        "decision": decision,
                        "data": receipt
                    }),
                );
            }
            Err(code) => {
                return json_no_store_response(
                    StatusCode::SERVICE_UNAVAILABLE,
                    json!({
                        "source": "postgres-direct",
                        "domain": "operations",
                        "panel": "hil-queue",
                        "endpoint": used_path,
                        "measurement_state": "not-measured",
                        "measurement_status": "not-measured",
                        "recorded": false,
                        "persisted": false,
                        "fail_closed": true,
                        "execution_authority": false,
                        "approver_executor_separated": true,
                        "silence_denies": true,
                        "observed_unix_ms": ts,
                        "approval_id": approval_id,
                        "decision": decision,
                        "reason": code
                    }),
                );
            }
        }
    }

    let status = if up.reachable && matches!(up.status, 401 | 403 | 409 | 429) {
        StatusCode::from_u16(up.status).unwrap_or(StatusCode::SERVICE_UNAVAILABLE)
    } else {
        StatusCode::SERVICE_UNAVAILABLE
    };

    json_no_store_response(
        status,
        json!({
            "source": "console-v4-rust",
            "domain": "operations",
            "panel": "hil-queue",
            "endpoint": used_path,
            "measurement_state": "not-measured",
            "measurement_status": "not-measured",
            "recorded": false,
            "persisted": false,
            "db_writes_enabled": state.db.mutations_allowed(),
            "fail_closed": true,
            "execution_authority": false,
            "approver_executor_separated": true,
            "silence_denies": true,
            "observed_unix_ms": now_unix_ms(),
            "approval_id": approval_id,
            "decision": decision,
            "upstream_reachable": up.reachable,
            "upstream_status": up.status,
            "reason": not_measured_reason(&up),
            "data": up.payload
        }),
    )
}

async fn api_operations_alert_quality(
    State(state): State<AppState>,
    headers: HeaderMap,
    uri: Uri,
) -> Response {
    let auth = auth_header_str(&headers);
    let findings_path = with_optional_query("/findings", &uri);
    let (findings, summary) = tokio::join!(
        state.upstream.get_json(&findings_path, auth),
        state.upstream.get_json("/rules/findings-summary", auth),
    );
    let any_up = is_measured(&findings) || is_measured(&summary);
    let db_fallback = if !any_up && state.db.is_configured() {
        Some(ops_repo::fetch_alert_quality(&state.db).await)
    } else {
        None
    };
    aggregate_upstream_response(
        &state,
        "alert-quality",
        "/findings",
        vec![
            ("findings", "/findings", findings),
            ("rules_findings_summary", "/rules/findings-summary", summary),
        ],
        db_fallback,
        json!({
            "window_days": 7,
            "ack_rate_state": "not-measured",
            "proposal_mode": "shadow-draft-only"
        }),
    )
}

async fn api_operations_detection_readiness(
    State(state): State<AppState>,
    headers: HeaderMap,
    uri: Uri,
) -> Response {
    let auth = auth_header_str(&headers);
    let path = with_optional_query("/detection-readiness", &uri);
    let up = state.upstream.get_json(&path, auth).await;
    let db_fallback = if !is_measured(&up) && state.db.is_configured() {
        Some(ops_repo::fetch_detection_readiness(&state.db).await)
    } else {
        None
    };
    single_upstream_response(
        &state,
        "detection-readiness",
        &path,
        up,
        db_fallback,
        json!({
            "signal_columns": ["metrics", "activity_logs", "diagnostics", "rules", "recovery_verification"]
        }),
    )
}

async fn api_operations_gpu(State(state): State<AppState>, headers: HeaderMap) -> Response {
    let auth = auth_header_str(&headers);
    let (data_sources, instances) = tokio::join!(
        state.upstream.get_json("/system/data-sources", auth),
        state
            .upstream
            .get_json("/ontology/instances/states?resource_type=gpu", auth),
    );
    let any_up = is_measured(&data_sources) || is_measured(&instances);
    let db_fallback = if !any_up && state.db.is_configured() {
        Some(ops_repo::fetch_gpu_observations(&state.db).await)
    } else {
        None
    };
    let has_gpu_instances = instances
        .payload
        .as_ref()
        .and_then(|v| v.get("resources"))
        .and_then(Value::as_array)
        .is_some_and(|arr| !arr.is_empty());
    let db_has_gpu = db_fallback
        .as_ref()
        .and_then(|v| v.get("nodes"))
        .and_then(Value::as_array)
        .is_some_and(|arr| !arr.is_empty());
    let collector_status = if (is_measured(&instances) && has_gpu_instances) || db_has_gpu {
        "connected"
    } else {
        "not-measured"
    };
    aggregate_upstream_response(
        &state,
        "gpu",
        "/system/data-sources",
        vec![
            ("data_sources", "/system/data-sources", data_sources),
            ("gpu_instances", "/ontology/instances/states", instances),
        ],
        db_fallback,
        json!({
            "collector": "dcgm-exporter",
            "collector_status": collector_status,
            "vram_threshold_pct": 85,
            "util_threshold_pct": 90,
            "unconnected_policy": "not-measured-never-zero"
        }),
    )
}

async fn api_operations_security(
    State(state): State<AppState>,
    headers: HeaderMap,
    uri: Uri,
) -> Response {
    let auth = auth_header_str(&headers);
    let findings_path = with_optional_query("/findings", &uri);
    let (findings, summary, rules) = tokio::join!(
        state.upstream.get_json(&findings_path, auth),
        state.upstream.get_json("/rules/findings-summary", auth),
        state.upstream.get_json("/rules", auth),
    );
    let any_up = is_measured(&findings) || is_measured(&summary) || is_measured(&rules);
    let db_fallback = if !any_up && state.db.is_configured() {
        Some(ops_repo::fetch_security(&state.db).await)
    } else {
        None
    };
    aggregate_upstream_response(
        &state,
        "security",
        "/findings",
        vec![
            ("findings", "/findings", findings),
            ("rules_findings_summary", "/rules/findings-summary", summary),
            ("rules", "/rules", rules),
        ],
        db_fallback,
        json!({
            "covered_panels": [
                "code-security",
                "vulnerability-risk",
                "configuration-baselines"
            ],
            "confidence_tiers": ["confirmed", "latent", "unknown_hypothesis"]
        }),
    )
}

async fn api_operations_baselines(State(state): State<AppState>, headers: HeaderMap) -> Response {
    let auth = auth_header_str(&headers);
    let up = state.upstream.get_json("/baselines", auth).await;
    let db_fallback = if !is_measured(&up) && state.db.is_configured() {
        Some(ops_repo::fetch_baselines(&state.db).await)
    } else {
        None
    };
    single_upstream_response(
        &state,
        "configuration-baselines",
        "/baselines",
        up,
        db_fallback,
        json!({
            "read_only": true,
            "auto_overwrite_forbidden": true
        }),
    )
}

async fn api_operations_conversation_delivery(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Response {
    let auth = auth_header_str(&headers);
    let up = state
        .upstream
        .get_json("/notifications/deliveries", auth)
        .await;
    let db_fallback = if !is_measured(&up) && state.db.is_configured() {
        Some(ops_repo::fetch_conversation_delivery(&state.db).await)
    } else {
        None
    };
    single_upstream_response(
        &state,
        "conversation-delivery",
        "/notifications/deliveries",
        up,
        db_fallback,
        json!({
            "channels": ["web", "teams", "slack", "webhook", "email"]
        }),
    )
}

async fn api_operations_automation(State(state): State<AppState>, headers: HeaderMap) -> Response {
    let auth = auth_header_str(&headers);
    let (workflows, bg_tasks, me_context) = tokio::join!(
        state.upstream.get_json("/views/workflow-apps", auth),
        state.upstream.get_json("/background-tasks", auth),
        state.upstream.get_json("/me/context", auth),
    );
    let any_up = is_measured(&workflows) || is_measured(&bg_tasks) || is_measured(&me_context);
    let db_fallback = if !any_up && state.db.is_configured() {
        Some(ops_repo::fetch_workflows_and_processes(&state.db).await)
    } else {
        None
    };
    aggregate_upstream_response(
        &state,
        "automation",
        "/views/workflow-apps",
        vec![
            ("workflow_apps", "/views/workflow-apps", workflows),
            ("background_tasks", "/background-tasks", bg_tasks),
            ("continuations_context", "/me/context", me_context),
        ],
        db_fallback,
        json!({
            "covered_panels": [
                "workflow-apps",
                "automation-blueprints",
                "processes",
                "scheduler-runs",
                "background-tasks",
                "scheduled-continuations"
            ],
            "background_tasks_read_only": true
        }),
    )
}

async fn api_operations_workflow_apps(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Response {
    let auth = auth_header_str(&headers);
    let up = state.upstream.get_json("/views/workflow-apps", auth).await;
    let db_fallback = if !is_measured(&up) && state.db.is_configured() {
        Some(ops_repo::fetch_workflows_and_processes(&state.db).await)
    } else {
        None
    };
    single_upstream_response(
        &state,
        "workflow-apps",
        "/views/workflow-apps",
        up,
        db_fallback,
        json!({ "default_mode": "shadow" }),
    )
}

async fn api_operations_automation_blueprints(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Response {
    let auth = auth_header_str(&headers);
    let up = state
        .upstream
        .get_json("/automation/blueprints", auth)
        .await;
    let db_fallback = if !is_measured(&up) && state.db.is_configured() {
        Some(ops_repo::fetch_workflows_and_processes(&state.db).await)
    } else {
        None
    };
    single_upstream_response(
        &state,
        "automation-blueprints",
        "/automation/blueprints",
        up,
        db_fallback,
        json!({ "shadow_default": true }),
    )
}

async fn api_operations_processes(State(state): State<AppState>, headers: HeaderMap) -> Response {
    let auth = auth_header_str(&headers);
    let up = state.upstream.get_json("/processes", auth).await;
    let db_fallback = if !is_measured(&up) && state.db.is_configured() {
        Some(ops_repo::fetch_workflows_and_processes(&state.db).await)
    } else {
        None
    };
    single_upstream_response(
        &state,
        "processes",
        "/processes",
        up,
        db_fallback,
        json!({ "dag_stages": 5 }),
    )
}

async fn api_operations_scheduler_runs(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Response {
    let auth = auth_header_str(&headers);
    let up = state.upstream.get_json("/scheduler/runs", auth).await;
    let db_fallback = if !is_measured(&up) && state.db.is_configured() {
        Some(ops_repo::fetch_scheduler_runs(&state.db).await)
    } else {
        None
    };
    single_upstream_response(
        &state,
        "scheduler-runs",
        "/scheduler/runs",
        up,
        db_fallback,
        json!({ "durable_journal": true }),
    )
}

async fn api_operations_background_tasks(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Response {
    let auth = auth_header_str(&headers);
    let up = state.upstream.get_json("/background-tasks", auth).await;
    let db_fallback = if !is_measured(&up) && state.db.is_configured() {
        Some(ops_repo::fetch_background_tasks(&state.db).await)
    } else {
        None
    };
    single_upstream_response(
        &state,
        "background-tasks",
        "/background-tasks",
        up,
        db_fallback,
        json!({ "read_only": true }),
    )
}

async fn api_operations_scheduled_continuations(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Response {
    let auth = auth_header_str(&headers);
    let up = state
        .upstream
        .get_json("/scheduled-continuations", auth)
        .await;
    let db_fallback = if !is_measured(&up) && state.db.is_configured() {
        Some(ops_repo::fetch_scheduled_continuations(&state.db).await)
    } else {
        None
    };
    single_upstream_response(
        &state,
        "scheduled-continuations",
        "/scheduled-continuations",
        up,
        db_fallback,
        json!({ "expiry_auto_reclaim": true }),
    )
}

async fn api_operations_provision(State(state): State<AppState>, headers: HeaderMap) -> Response {
    let auth = auth_header_str(&headers);
    let up = state.upstream.get_json("/provision/status", auth).await;
    let db_fallback = if !is_measured(&up) && state.db.is_configured() {
        Some(ops_repo::fetch_provision(&state.db).await)
    } else {
        None
    };
    single_upstream_response(
        &state,
        "provision",
        "/provision/status",
        up,
        db_fallback,
        json!({
            "distribution_paths": ["hub-signed-image", "local-source", "signed-offline-package"],
            "silent_source_fallback_forbidden": true
        }),
    )
}

async fn api_operations_onboarding(State(state): State<AppState>, headers: HeaderMap) -> Response {
    let auth = auth_header_str(&headers);
    let (data_sources, iam_self, inbox) = tokio::join!(
        state.upstream.get_json("/system/data-sources", auth),
        state.upstream.get_json("/iam/self", auth),
        state.upstream.get_json("/notifications/inbox", auth),
    );
    let any_up = is_measured(&data_sources) || is_measured(&iam_self) || is_measured(&inbox);
    let db_fallback = if !any_up && state.db.is_configured() {
        Some(ops_repo::fetch_onboarding(&state.db).await)
    } else {
        None
    };
    aggregate_upstream_response(
        &state,
        "onboarding",
        "/system/data-sources",
        vec![
            ("data_sources", "/system/data-sources", data_sources),
            ("iam_self", "/iam/self", iam_self),
            ("notifications_inbox", "/notifications/inbox", inbox),
        ],
        db_fallback,
        json!({
            "covered_panels": [
                "provision",
                "onboarding",
                "conversation-delivery"
            ],
            "distribution_paths": ["hub-signed-image", "local-source", "signed-offline-package"],
            "silent_source_fallback_forbidden": true
        }),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::build_router;
    use axum::{body::Body, http::Request};
    use http_body_util::BodyExt;
    use std::path::PathBuf;
    use tokio::net::TcpListener;
    use tower::ServiceExt;

    fn offline_state() -> AppState {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("."));
        AppState::from_repo_root(root, "http://127.0.0.1:1".to_string())
    }

    fn state_for_url(url: String) -> AppState {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("."));
        AppState::from_repo_root(root, url)
    }

    async fn send_oneshot(app: Router, req: Request<Body>) -> Response {
        match app.oneshot(req).await {
            Ok(resp) => resp,
            Err(never) => match never {},
        }
    }

    async fn read_json(resp: Response) -> Result<Value, String> {
        let bytes = resp
            .into_body()
            .collect()
            .await
            .map_err(|e| format!("body collect failed: {e}"))?
            .to_bytes();
        serde_json::from_slice::<Value>(&bytes).map_err(|e| format!("json parse failed: {e}"))
    }

    #[test]
    fn operations_registers_all_18_panels() {
        assert_eq!(panel_ids().len(), 18);
        let mut unique = std::collections::BTreeSet::new();
        for panel in panel_ids() {
            assert!(unique.insert(*panel), "duplicate panel id: {panel}");
        }
    }

    #[tokio::test]
    async fn operations_page_renders_all_18_panels_without_legacy_links() -> Result<(), String> {
        let app = build_router(offline_state());
        let req = Request::builder()
            .uri("/operations")
            .body(Body::empty())
            .map_err(|e| e.to_string())?;
        let resp = send_oneshot(app, req).await;
        assert_eq!(resp.status(), StatusCode::OK);
        let bytes = resp
            .into_body()
            .collect()
            .await
            .map_err(|e| e.to_string())?
            .to_bytes();
        let html = String::from_utf8(bytes.to_vec()).map_err(|e| e.to_string())?;
        for panel in panel_ids() {
            let marker = format!("data-panel-id=\"{panel}\"");
            assert!(html.contains(&marker), "missing panel section {marker}");
        }
        assert!(!html.contains("mockup-evidence.html"));
        assert!(!html.contains("mockup-governance.html"));
        assert!(!html.contains("mockup-settings-labs.html"));
        assert!(html.contains("/api/v4/operations/live/stream"));
        Ok(())
    }

    #[tokio::test]
    async fn operations_get_endpoints_return_not_measured_when_offline() -> Result<(), String> {
        let endpoints = [
            "/api/v4/operations/summary",
            "/api/v4/operations/live",
            "/api/v4/operations/incidents",
            "/api/v4/operations/hil-queue",
            "/api/v4/operations/alert-quality",
            "/api/v4/operations/detection-readiness",
            "/api/v4/operations/gpu",
            "/api/v4/operations/security",
            "/api/v4/operations/baselines",
            "/api/v4/operations/conversation-delivery",
            "/api/v4/operations/automation",
            "/api/v4/operations/workflow-apps",
            "/api/v4/operations/automation-blueprints",
            "/api/v4/operations/processes",
            "/api/v4/operations/scheduler-runs",
            "/api/v4/operations/background-tasks",
            "/api/v4/operations/scheduled-continuations",
            "/api/v4/operations/provision",
            "/api/v4/operations/onboarding",
        ];

        for path in endpoints {
            let app = build_router(offline_state());
            let req = Request::builder()
                .uri(path)
                .body(Body::empty())
                .map_err(|e| e.to_string())?;
            let resp = send_oneshot(app, req).await;
            assert_eq!(resp.status(), StatusCode::OK, "path {path} failed");
            let body = read_json(resp).await?;
            assert_eq!(
                body.get("measurement_state").and_then(Value::as_str),
                Some("not-measured"),
                "path {path} should report not-measured"
            );
            assert_eq!(
                body.get("measurement_status").and_then(Value::as_str),
                Some("not-measured"),
                "path {path} should report measurement_status=not-measured"
            );
            assert_eq!(
                body.get("zero_substitution_forbidden")
                    .and_then(Value::as_bool),
                Some(true),
                "path {path} must forbid zero substitution"
            );
            assert_eq!(
                body.get("execution_authority").and_then(Value::as_bool),
                Some(false)
            );
        }
        Ok(())
    }

    fn sse_test_lock() -> &'static tokio::sync::Mutex<()> {
        static LOCK: OnceLock<tokio::sync::Mutex<()>> = OnceLock::new();
        LOCK.get_or_init(|| tokio::sync::Mutex::new(()))
    }

    #[tokio::test]
    async fn operations_live_stream_emits_sse_snapshot() -> Result<(), String> {
        let _sse_guard = sse_test_lock().lock().await;
        let app = build_router(offline_state());
        let req = Request::builder()
            .uri("/api/v4/operations/live/stream")
            .header(header::ACCEPT, "text/event-stream")
            .body(Body::empty())
            .map_err(|e| e.to_string())?;
        let resp = send_oneshot(app, req).await;
        assert_eq!(resp.status(), StatusCode::OK);
        let content_type = resp
            .headers()
            .get(header::CONTENT_TYPE)
            .and_then(|v| v.to_str().ok())
            .unwrap_or("");
        assert!(
            content_type.contains("text/event-stream"),
            "unexpected content-type: {content_type}"
        );
        let mut body = resp.into_body();
        let frame = tokio::time::timeout(Duration::from_secs(3), body.frame())
            .await
            .map_err(|_| "SSE snapshot timed out".to_string())?;
        let data_bytes = frame
            .and_then(Result::ok)
            .and_then(|f| f.into_data().ok())
            .ok_or_else(|| "expected SSE data frame".to_string())?;
        let text = String::from_utf8(data_bytes.to_vec()).map_err(|e| e.to_string())?;
        assert!(text.contains("event: snapshot"), "frame was: {text}");
        assert!(text.contains("retry: 3000"), "missing retry directive: {text}");
        assert!(LIVE_SSE_INTERVAL_SECS >= 1 && LIVE_SSE_INTERVAL_SECS <= 4);
        assert!(MAX_LIVE_SSE_TICKS >= 60);
        assert!(
            text.contains("\"measurement_state\":\"not-measured\""),
            "frame was: {text}"
        );
        Ok(())
    }

    #[tokio::test]
    async fn operations_hil_decision_validates_and_fails_closed() -> Result<(), String> {
        let app = build_router(offline_state());
        let short_reason = Request::builder()
            .method("POST")
            .uri("/api/v4/operations/hil-queue/decision")
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(
                json!({
                    "approval_id": "HIL-8841",
                    "decision": "approve",
                    "reason": "ok"
                })
                .to_string(),
            ))
            .map_err(|e| e.to_string())?;
        let resp_bad = send_oneshot(app, short_reason).await;
        assert_eq!(resp_bad.status(), StatusCode::BAD_REQUEST);
        let bad_json = read_json(resp_bad).await?;
        assert_eq!(bad_json.get("recorded").and_then(Value::as_bool), Some(false));

        let app2 = build_router(offline_state());
        let bad_decision = Request::builder()
            .method("POST")
            .uri("/api/v4/operations/hil-queue/decision")
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(
                json!({
                    "approval_id": "HIL-8841",
                    "decision": "force_apply",
                    "reason": "valid reason length"
                })
                .to_string(),
            ))
            .map_err(|e| e.to_string())?;
        let resp_bad2 = send_oneshot(app2, bad_decision).await;
        assert_eq!(resp_bad2.status(), StatusCode::BAD_REQUEST);

        let app3 = build_router(offline_state());
        let valid_offline = Request::builder()
            .method("POST")
            .uri("/api/v4/operations/hil-queue/decision")
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(
                json!({
                    "approval_id": "HIL-8841",
                    "decision": "approve",
                    "reason": "7대 안전장치 및 롤백 확인 후 승인"
                })
                .to_string(),
            ))
            .map_err(|e| e.to_string())?;
        let resp_offline = send_oneshot(app3, valid_offline).await;
        assert_eq!(resp_offline.status(), StatusCode::SERVICE_UNAVAILABLE);
        let offline_json = read_json(resp_offline).await?;
        assert_eq!(
            offline_json.get("fail_closed").and_then(Value::as_bool),
            Some(true)
        );
        assert_eq!(
            offline_json.get("recorded").and_then(Value::as_bool),
            Some(false)
        );
        Ok(())
    }

    #[tokio::test]
    async fn operations_endpoints_proxy_measured_upstream_data() -> Result<(), String> {
        let mock_upstream = Router::new()
            .route(
                "/incidents",
                get(|| async { Json(json!({ "items": [{ "id": "INC-2026-441" }] })) }),
            )
            .route(
                "/hil-queue",
                get(|| async { Json(json!({ "items": [{ "id": "HIL-8841" }] })) }),
            )
            .route(
                "/hil/report-line-contact-requests",
                get(|| async { Json(json!({ "items": [], "total": 0 })) }),
            )
            .route(
                "/hil/HIL-8841/operator-decision",
                post(|| async { Json(json!({ "approval_id": "HIL-8841", "status": "approved" })) }),
            )
            .route(
                "/detection-readiness",
                get(|| async { Json(json!({ "target_count": 4, "targets": [] })) }),
            );

        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .map_err(|e| e.to_string())?;
        let addr = listener.local_addr().map_err(|e| e.to_string())?;
        let server_handle = tokio::spawn(async move {
            let _ = axum::serve(listener, mock_upstream).await;
        });

        let base_url = format!("http://{addr}");

        let app_inc = build_router(state_for_url(base_url.clone()));
        let req_inc = Request::builder()
            .uri("/api/v4/operations/incidents")
            .body(Body::empty())
            .map_err(|e| e.to_string())?;
        let resp_inc = send_oneshot(app_inc, req_inc).await;
        assert_eq!(resp_inc.status(), StatusCode::OK);
        let json_inc = read_json(resp_inc).await?;
        assert_eq!(
            json_inc.get("measurement_state").and_then(Value::as_str),
            Some("measured")
        );

        let app_det = build_router(state_for_url(base_url.clone()));
        let req_det = Request::builder()
            .uri("/api/v4/operations/detection-readiness")
            .body(Body::empty())
            .map_err(|e| e.to_string())?;
        let resp_det = send_oneshot(app_det, req_det).await;
        let json_det = read_json(resp_det).await?;
        assert_eq!(
            json_det.get("measurement_state").and_then(Value::as_str),
            Some("measured")
        );

        let app_hil = build_router(state_for_url(base_url));
        let req_hil = Request::builder()
            .method("POST")
            .uri("/api/v4/operations/hil-queue/decision")
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(
                json!({
                    "approval_id": "HIL-8841",
                    "decision": "approve",
                    "reason": "연결 풀 증설 사전 모의 검증 확인"
                })
                .to_string(),
            ))
            .map_err(|e| e.to_string())?;
        let resp_hil = send_oneshot(app_hil, req_hil).await;
        assert_eq!(resp_hil.status(), StatusCode::OK);
        let json_hil = read_json(resp_hil).await?;
        assert_eq!(json_hil.get("recorded").and_then(Value::as_bool), Some(true));
        assert_eq!(
            json_hil.get("measurement_state").and_then(Value::as_str),
            Some("measured")
        );

        server_handle.abort();
        Ok(())
    }

    #[tokio::test]
    async fn operations_hil_decision_blocks_path_traversal_and_supports_fallback(
    ) -> Result<(), String> {
        let app = build_router(offline_state());
        let bad_id = Request::builder()
            .method("POST")
            .uri("/api/v4/operations/hil-queue/decision")
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(
                json!({
                    "approval_id": "../admin",
                    "decision": "approve",
                    "reason": "valid reason length"
                })
                .to_string(),
            ))
            .map_err(|e| e.to_string())?;
        let resp = send_oneshot(app, bad_id).await;
        assert_eq!(resp.status(), StatusCode::BAD_REQUEST);

        let mock_fallback = Router::new().route(
            "/hil/HIL-8839/decision",
            post(|| async { Json(json!({ "approval_id": "HIL-8839", "status": "rejected" })) }),
        );
        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .map_err(|e| e.to_string())?;
        let addr = listener.local_addr().map_err(|e| e.to_string())?;
        let handle = tokio::spawn(async move {
            let _ = axum::serve(listener, mock_fallback).await;
        });

        let app_fb = build_router(state_for_url(format!("http://{addr}")));
        let req_fb = Request::builder()
            .method("POST")
            .uri("/api/v4/operations/hil-queue/decision")
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(
                json!({
                    "approval_id": "HIL-8839",
                    "decision": "reject",
                    "reason": "만료 예외 회수 범위 재검토 필요"
                })
                .to_string(),
            ))
            .map_err(|e| e.to_string())?;
        let resp_fb = send_oneshot(app_fb, req_fb).await;
        assert_eq!(resp_fb.status(), StatusCode::OK);
        let body_fb = read_json(resp_fb).await?;
        assert_eq!(body_fb.get("recorded").and_then(Value::as_bool), Some(true));
        assert_eq!(
            body_fb.get("endpoint").and_then(Value::as_str),
            Some("/hil/HIL-8839/decision")
        );

        handle.abort();
        Ok(())
    }

    #[tokio::test]
    async fn operations_incident_intervention_and_partial_summary() -> Result<(), String> {
        let app = build_router(offline_state());
        let bad_action = Request::builder()
            .method("POST")
            .uri("/api/v4/operations/incidents/intervention")
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(
                json!({
                    "correlation_id": "INC-2026-441",
                    "action": "destroy",
                    "reason": "valid reason length"
                })
                .to_string(),
            ))
            .map_err(|e| e.to_string())?;
        assert_eq!(send_oneshot(app, bad_action).await.status(), StatusCode::BAD_REQUEST);

        let mock_partial = Router::new()
            .route(
                "/incidents",
                get(|| async { Json(json!({ "items": [{ "id": "INC-2026-441" }] })) }),
            )
            .route(
                "/incidents/INC-2026-441/interventions",
                post(|| async { Json(json!({ "recorded": true, "id": "int-01" })) }),
            );
        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .map_err(|e| e.to_string())?;
        let addr = listener.local_addr().map_err(|e| e.to_string())?;
        let handle = tokio::spawn(async move {
            let _ = axum::serve(listener, mock_partial).await;
        });
        let base_url = format!("http://{addr}");

        let app_sum = build_router(state_for_url(base_url.clone()));
        let req_sum = Request::builder()
            .uri("/api/v4/operations/summary")
            .body(Body::empty())
            .map_err(|e| e.to_string())?;
        let resp_sum = send_oneshot(app_sum, req_sum).await;
        assert_eq!(resp_sum.status(), StatusCode::OK);
        let sum_json = read_json(resp_sum).await?;
        assert_eq!(
            sum_json.get("measurement_state").and_then(Value::as_str),
            Some("partial")
        );
        assert_eq!(
            sum_json.get("measured_sources").and_then(Value::as_u64),
            Some(1)
        );
        assert_eq!(
            sum_json.get("total_sources").and_then(Value::as_u64),
            Some(4)
        );

        let app_int = build_router(state_for_url(base_url));
        let req_int = Request::builder()
            .method("POST")
            .uri("/api/v4/operations/incidents/intervention")
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(
                json!({
                    "correlation_id": "INC-2026-441",
                    "action": "guidance",
                    "reason": "연결 풀 포화 원인 조사 가이드 메모"
                })
                .to_string(),
            ))
            .map_err(|e| e.to_string())?;
        let resp_int = send_oneshot(app_int, req_int).await;
        assert_eq!(resp_int.status(), StatusCode::OK);
        let int_json = read_json(resp_int).await?;
        assert_eq!(int_json.get("recorded").and_then(Value::as_bool), Some(true));

        handle.abort();
        Ok(())
    }

    #[tokio::test]
    async fn operations_redteam_security_headers_and_input_guards() -> Result<(), String> {
        // 1. Query string sanitizer blocks CRLF, fragment, path traversal, and oversize payloads
        assert_eq!(
            sanitize_query_string("scope=prod-core-kr&limit=20").as_deref(),
            Some("scope=prod-core-kr&limit=20")
        );
        assert!(sanitize_query_string("a=1%0d%0aX-Injected:1").is_none());
        assert!(sanitize_query_string("a=1#frag").is_none());
        assert!(sanitize_query_string("path=../secret").is_none());
        assert!(sanitize_query_string(&"a".repeat(MAX_QUERY_LEN + 1)).is_none());

        // 2. Leading-dot path segment and control-char reason are rejected with 400
        assert!(!is_safe_path_segment(".hidden"));
        assert!(has_disallowed_control_chars("approve\r\nforged"));
        assert!(!has_disallowed_control_chars("정상 승인 사유 확인 완료"));

        let app_ctrl = build_router(offline_state());
        let req_ctrl = Request::builder()
            .method("POST")
            .uri("/api/v4/operations/hil-queue/decision")
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(
                json!({
                    "approval_id": "HIL-8841",
                    "decision": "approve",
                    "reason": "valid\nforged-log-line"
                })
                .to_string(),
            ))
            .map_err(|e| e.to_string())?;
        let resp_ctrl = send_oneshot(app_ctrl, req_ctrl).await;
        assert_eq!(resp_ctrl.status(), StatusCode::BAD_REQUEST);
        assert_eq!(
            resp_ctrl
                .headers()
                .get(header::CACHE_CONTROL)
                .and_then(|v| v.to_str().ok()),
            Some("no-store")
        );
        assert_eq!(
            resp_ctrl
                .headers()
                .get(header::X_CONTENT_TYPE_OPTIONS)
                .and_then(|v| v.to_str().ok()),
            Some("nosniff")
        );
        let ctrl_json = read_json(resp_ctrl).await?;
        assert_eq!(
            ctrl_json
                .get("approver_executor_separated")
                .and_then(Value::as_bool),
            Some(true)
        );

        // 3. SSE endpoint emits anti-buffering & no-store headers
        let _sse_guard = sse_test_lock().lock().await;
        let app_sse = build_router(offline_state());
        let req_sse = Request::builder()
            .uri("/api/v4/operations/live/stream")
            .header(header::ACCEPT, "text/event-stream")
            .body(Body::empty())
            .map_err(|e| e.to_string())?;
        let resp_sse = send_oneshot(app_sse, req_sse).await;
        assert_eq!(resp_sse.status(), StatusCode::OK);
        assert_eq!(
            resp_sse
                .headers()
                .get(header::CACHE_CONTROL)
                .and_then(|v| v.to_str().ok()),
            Some("no-store")
        );
        assert_eq!(
            resp_sse
                .headers()
                .get("x-accel-buffering")
                .and_then(|v| v.to_str().ok()),
            Some("no")
        );
        drop(resp_sse);

        // 4. Exhausting SSE limiter returns 503 with Retry-After and recovers on drop
        let limiter = live_sse_limiter();
        let mut held = Vec::new();
        while let Ok(p) = Arc::clone(&limiter).try_acquire_owned() {
            held.push(p);
        }
        let app_full = build_router(offline_state());
        let req_full = Request::builder()
            .uri("/api/v4/operations/live/stream")
            .body(Body::empty())
            .map_err(|e| e.to_string())?;
        let resp_full = send_oneshot(app_full, req_full).await;
        assert_eq!(resp_full.status(), StatusCode::SERVICE_UNAVAILABLE);
        assert_eq!(
            resp_full
                .headers()
                .get(header::RETRY_AFTER)
                .and_then(|v| v.to_str().ok()),
            Some("5")
        );
        drop(held);
        Ok(())
    }

    #[tokio::test]
    async fn operations_create_incident_validates_and_proxies() -> Result<(), String> {
        // Short summary rejected with 400
        let app_bad = build_router(offline_state());
        let req_bad = Request::builder()
            .method("POST")
            .uri("/api/v4/operations/incidents")
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(
                json!({
                    "title": "결제 API 타임아웃 급증",
                    "severity": "high",
                    "subscription": "prod-core-kr",
                    "resource": "orders-api",
                    "vertical": "sre",
                    "summary": "짧음"
                })
                .to_string(),
            ))
            .map_err(|e| e.to_string())?;
        assert_eq!(send_oneshot(app_bad, req_bad).await.status(), StatusCode::BAD_REQUEST);

        // Valid payload fails closed (503) when offline
        let app_off = build_router(offline_state());
        let req_off = Request::builder()
            .method("POST")
            .uri("/api/v4/operations/incidents")
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(
                json!({
                    "title": "결제 API 타임아웃 급증",
                    "severity": "critical",
                    "subscription": "prod-core-kr",
                    "resource": "orders-api",
                    "vertical": "sre",
                    "summary": "고객 제보 및 APM에서 결제 승인 요청 504 오류율이 5분간 8%로 급증했습니다."
                })
                .to_string(),
            ))
            .map_err(|e| e.to_string())?;
        let resp_off = send_oneshot(app_off, req_off).await;
        assert_eq!(resp_off.status(), StatusCode::SERVICE_UNAVAILABLE);
        let off_json = read_json(resp_off).await?;
        assert_eq!(off_json.get("recorded").and_then(Value::as_bool), Some(false));
        assert_eq!(off_json.get("fail_closed").and_then(Value::as_bool), Some(true));

        // Proxies to upstream when reachable
        let mock_up = Router::new().route(
            "/incidents",
            post(|| async { Json(json!({ "id": "INC-2026-501", "status": "investigating" })) }),
        );
        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .map_err(|e| e.to_string())?;
        let addr = listener.local_addr().map_err(|e| e.to_string())?;
        let handle = tokio::spawn(async move {
            let _ = axum::serve(listener, mock_up).await;
        });

        let app_ok = build_router(state_for_url(format!("http://{addr}")));
        let req_ok = Request::builder()
            .method("POST")
            .uri("/api/v4/operations/incidents")
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(
                json!({
                    "title": "결제 API 타임아웃 급증",
                    "severity": "critical",
                    "subscription": "prod-core-kr",
                    "resource": "orders-api",
                    "vertical": "sre",
                    "summary": "고객 제보 및 APM에서 결제 승인 요청 504 오류율이 5분간 8%로 급증했습니다."
                })
                .to_string(),
            ))
            .map_err(|e| e.to_string())?;
        let resp_ok = send_oneshot(app_ok, req_ok).await;
        assert_eq!(resp_ok.status(), StatusCode::CREATED);
        let ok_json = read_json(resp_ok).await?;
        assert_eq!(ok_json.get("recorded").and_then(Value::as_bool), Some(true));
        assert_eq!(
            ok_json.get("origin").and_then(Value::as_str),
            Some("human-manual")
        );

        handle.abort();
        Ok(())
    }

    #[tokio::test]
    async fn operations_sse_tracks_active_lease_drop_guard() -> Result<(), String> {
        use std::sync::atomic::Ordering;
        let _sse_guard = sse_test_lock().lock().await;

        let state = offline_state();
        let counter = Arc::clone(&state.active_sse);
        assert_eq!(counter.load(Ordering::SeqCst), 0);

        let app = build_router(state);
        let req = Request::builder()
            .uri("/api/v4/operations/live/stream")
            .header(header::ACCEPT, "text/event-stream")
            .body(Body::empty())
            .map_err(|e| e.to_string())?;
        let resp = send_oneshot(app, req).await;
        assert_eq!(resp.status(), StatusCode::OK);
        assert_eq!(counter.load(Ordering::SeqCst), 1);

        drop(resp);
        assert_eq!(counter.load(Ordering::SeqCst), 0);
        Ok(())
    }

    #[tokio::test]
    async fn operations_db_write_path_enforces_bearer_and_runtime_guard() -> Result<(), String> {
        let mut state = offline_state();
        state.db = crate::db::DbHandle::from_dsn_opt(
            Some("postgresql://fdai:fdai@127.0.0.1:5432/fdai"),
            true,
        );

        // Missing Bearer token is rejected with 401 UNAUTHORIZED
        let app_no_auth = build_router(state.clone());
        let req_no_auth = Request::builder()
            .method("POST")
            .uri("/api/v4/operations/hil-queue/decision")
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(
                json!({
                    "approval_id": "HIL-8841",
                    "decision": "approve",
                    "reason": "7대 안전장치 확인 후 승인 요청"
                })
                .to_string(),
            ))
            .map_err(|e| e.to_string())?;
        let resp_no_auth = send_oneshot(app_no_auth, req_no_auth).await;
        assert_eq!(resp_no_auth.status(), StatusCode::UNAUTHORIZED);
        let body_no_auth = read_json(resp_no_auth).await?;
        assert_eq!(
            body_no_auth.get("persisted").and_then(Value::as_bool),
            Some(false)
        );
        assert_eq!(
            body_no_auth.get("error").and_then(Value::as_str),
            Some("bearer_token_required")
        );

        // Valid Bearer against port 5432 respects runtime_5432_write_guard (never mutates runtime DB)
        let app_guard = build_router(state);
        let req_guard = Request::builder()
            .method("POST")
            .uri("/api/v4/operations/hil-queue/decision")
            .header(header::CONTENT_TYPE, "application/json")
            .header(header::AUTHORIZATION, "Bearer test-operator-token-001")
            .body(Body::from(
                json!({
                    "approval_id": "HIL-8841",
                    "decision": "approve",
                    "reason": "7대 안전장치 확인 후 승인 요청"
                })
                .to_string(),
            ))
            .map_err(|e| e.to_string())?;
        let resp_guard = send_oneshot(app_guard, req_guard).await;
        assert_eq!(resp_guard.status(), StatusCode::SERVICE_UNAVAILABLE);
        let body_guard = read_json(resp_guard).await?;
        assert_eq!(
            body_guard.get("persisted").and_then(Value::as_bool),
            Some(false)
        );
        assert_eq!(
            body_guard.get("reason").and_then(Value::as_str),
            Some("runtime_5432_write_guard")
        );
        Ok(())
    }

    #[test]
    fn operations_template_hardening_invariants() {
        assert!(
            TEMPLATE.contains("<title>FDAI 운영 콘솔 — 운영</title>"),
            "expected unified Korean page title"
        );
        assert!(
            !TEMPLATE.contains("/azure-icons/cost-management.svg"),
            "broken 404 icon cost-management.svg must not be referenced"
        );
        for raw_db_term in [
            "audit_log",
            "state_kv",
            "hil_park:",
            "operational_state_transition_coverage",
            "ProcessStepsWidget",
        ] {
            assert!(
                !TEMPLATE.contains(raw_db_term),
                "raw internal identifier leaked into template: {raw_db_term}"
            );
        }
        assert!(
            !TEMPLATE.contains("s.match(/T(\\d{2}:\\d{2}:\\d{2})/)"),
            "shortClock must convert to local timezone instead of slicing raw UTC string"
        );
        for required_hook in [
            "fdaiV4Humanize.localClock",
            "fdaiV4Humanize.ruleId",
            "fdaiV4Humanize.remediationAction",
            "fdaiV4Humanize.severity",
            "localTzLabel",
            "fdaiV4Shimmer",
            "markStreaming",
            "upsertLiveTickerEntries",
            "applyLiveStreamFrameToTiles",
            "applyDeepLinkSelection",
            "showDeepLinkNotFound",
            "clearAllPanelsForLive",
            "restoreSampleDatasets",
            "data-hm-range=\"week\"",
            "data-hm-range=\"day\"",
            "ops-hm-gh",
            "replaceInspectorBody",
            "openInlineInspectorPane",
            "normalizeCsPriority",
            "data-cs-sev=\"undetermined\"",
            "cs-source-viewer",
        ] {
            assert!(
                TEMPLATE.contains(required_hook),
                "missing required hardening hook: {required_hook}"
            );
        }
    }

    #[test]
    fn code_security_priority_and_sarif_helpers_are_consistent() {
        use crate::repos::operations as ops_repo;
        assert_eq!(ops_repo::normalize_security_priority("critical"), "P0");
        assert_eq!(ops_repo::normalize_security_priority("high"), "P1");
        assert_eq!(ops_repo::normalize_security_priority("medium"), "P2");
        assert_eq!(ops_repo::normalize_security_priority("low"), "P3");
        assert_eq!(ops_repo::normalize_security_priority("undetermined"), "TBD");
        assert_eq!(ops_repo::normalize_security_priority(""), "TBD");

        assert_eq!(ops_repo::infer_code_ecosystem("src/ai-service/requirements.txt"), "Python");
        assert_eq!(ops_repo::infer_code_ecosystem("src/store-front/package-lock.json"), "Node.js");
        assert_eq!(ops_repo::infer_code_ecosystem("src/product-service/Dockerfile"), "Dockerfile");
        assert_eq!(ops_repo::infer_code_ecosystem("aks-store-all-in-one.yaml"), "Kubernetes YAML");
        assert_eq!(ops_repo::infer_code_ecosystem("src/makeline-service/go.mod"), "Go");

        assert_eq!(
            ops_repo::extract_cvss_score("advisory CVSS base score reported by producers: Trivy=9.5"),
            Some(9.5)
        );
        assert_eq!(
            ops_repo::extract_cvss_score("advisory CVSS base score reported by producers: Trivy=7.2, osv-scanner=8.4"),
            Some(8.4)
        );
        assert_eq!(
            ops_repo::extract_cvss_score("severity rubric 1.1.0: impact=unknown; floor -4.0 (low), ceiling 10.0 (critical)"),
            None
        );
    }
}
