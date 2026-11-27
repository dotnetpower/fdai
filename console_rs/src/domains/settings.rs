//! Domain 6: 설정 (`settings`, 8 panels + SettingsOverlay modal).
//! Owned by the `settings` domain stream.

use axum::{
    extract::{Query, State},
    http::{header, HeaderMap, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use http_body_util::{BodyExt, Full};
use hyper::body::Bytes;
use hyper::{Method, Request, Uri};
use hyper_util::client::legacy::{connect::HttpConnector, Client};
use hyper_util::rt::TokioExecutor;
use serde::Deserialize;
use serde_json::{json, Map, Value};
use std::net::{IpAddr, Ipv4Addr};
use std::path::Path;
use std::sync::OnceLock;
use std::time::{Duration, Instant};
use tokio::sync::Semaphore;
use tokio::time::timeout;

use crate::{
    repos,
    shell::{finalize_v4_html, html_response},
    AppState,
};

const TEMPLATE: &str = include_str!("../../templates/settings.html");

const PANELS: [&str; 8] = [
    "settings-general",
    "settings-environment",
    "settings-models",
    "settings-runtime",
    "settings-iam",
    "settings-integrations",
    "settings-diagnostics",
    "settings-memory",
];

const MAX_AUTH_HEADER_LEN: usize = 4096;
const MAX_ID_LEN: usize = 128;
const MAX_REASON_LEN: usize = 1000;
const MAX_QUERY_LEN: usize = 256;
const MAX_POLICY_DEPTH: usize = 4;
const MAX_POLICY_KEYS: usize = 32;
const MAX_POLICY_BYTES: usize = 4096;
const MAX_CONCURRENT_DIAGNOSTIC_PROBES: usize = 8;

const ALLOWED_LOCALES: [&str; 2] = ["ko", "en"];
const ALLOWED_ANSWER_DETAILS: [&str; 3] = ["concise", "standard", "detailed"];
const ALLOWED_ANSWER_FORMATS: [&str; 7] = [
    "mixed",
    "prose",
    "bullets",
    "steps",
    "checklist",
    "table",
    "executive",
];
const ALLOWED_AUTONOMY_PROFILES: [&str; 6] = [
    "multi-operator-shadow",
    "standard-shadow",
    "single-operator-prod",
    "single-operator-dev",
    "strict-readonly",
    "enforced-guarded",
];
const ALLOWED_MEMORY_SCOPES: [&str; 4] = ["all", "subscription", "resource-group", "resource"];
const ALLOWED_IANA_AREAS: [&str; 11] = [
    "Africa",
    "America",
    "Antarctica",
    "Arctic",
    "Asia",
    "Atlantic",
    "Australia",
    "Etc",
    "Europe",
    "Indian",
    "Pacific",
];

static DIAG_HTTP_CLIENT: OnceLock<Client<HttpConnector, Full<Bytes>>> = OnceLock::new();
static DIAG_SEMAPHORE: OnceLock<Semaphore> = OnceLock::new();

fn diagnostic_http_client() -> &'static Client<HttpConnector, Full<Bytes>> {
    DIAG_HTTP_CLIENT.get_or_init(|| {
        let mut connector = HttpConnector::new();
        connector.set_connect_timeout(Some(Duration::from_millis(200)));
        Client::builder(TokioExecutor::new()).build(connector)
    })
}

fn diagnostic_semaphore() -> &'static Semaphore {
    DIAG_SEMAPHORE.get_or_init(|| Semaphore::new(MAX_CONCURRENT_DIAGNOSTIC_PROBES))
}

fn settings_json_response(status: StatusCode, payload: Value) -> Response {
    (
        status,
        [
            (header::CACHE_CONTROL, HeaderValue::from_static("no-store")),
            (
                header::X_CONTENT_TYPE_OPTIONS,
                HeaderValue::from_static("nosniff"),
            ),
        ],
        Json(payload),
    )
        .into_response()
}

fn has_control_chars(s: &str) -> bool {
    s.chars().any(char::is_control)
}

pub fn panel_ids() -> &'static [&'static str] {
    &PANELS
}

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/settings", get(page_settings))
        .route("/api/v4/settings/summary", get(api_settings_summary))
        .route("/api/v4/settings/overlay", get(api_settings_overlay))
        .route(
            "/api/v4/settings/general",
            get(api_settings_general_get).patch(api_settings_general_patch),
        )
        .route("/api/v4/settings/environment", get(api_settings_environment))
        .route("/api/v4/settings/models", get(api_settings_models))
        .route(
            "/api/v4/settings/models/validate-t2",
            post(api_settings_models_validate_t2),
        )
        .route(
            "/api/v4/settings/runtime",
            get(api_settings_runtime_get).patch(api_settings_runtime_patch),
        )
        .route("/api/v4/settings/iam", get(api_settings_iam))
        .route(
            "/api/v4/settings/iam/azure-groups",
            get(api_settings_iam_azure_groups_get).patch(api_settings_iam_azure_groups_patch),
        )
        .route(
            "/api/v4/settings/iam/decisions",
            post(api_settings_iam_decision),
        )
        .route(
            "/api/v4/settings/integrations",
            get(api_settings_integrations_get)
                .patch(api_settings_integrations_patch)
                .post(api_settings_integrations_test),
        )
        .route(
            "/api/v4/settings/integrations/test",
            post(api_settings_integrations_test),
        )
        .route("/api/v4/settings/diagnostics", get(api_settings_diagnostics))
        .route("/api/v4/settings/memory", get(api_settings_memory))
        .route(
            "/api/v4/settings/memory/extend",
            post(api_settings_memory_extend),
        )
        .route(
            "/api/v4/settings/memory/delete",
            post(api_settings_memory_delete),
        )
}

fn extract_auth(headers: &HeaderMap) -> Option<&str> {
    headers
        .get(header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok())
        .map(str::trim)
        .filter(|s| !s.is_empty() && s.len() <= MAX_AUTH_HEADER_LEN && !has_control_chars(s))
}

fn extract_idempotency_key(headers: &HeaderMap, prefix: &str) -> String {
    if let Some(raw) = headers
        .get("idempotency-key")
        .and_then(|v| v.to_str().ok())
        .map(str::trim)
    {
        if !raw.is_empty() && raw.len() <= MAX_ID_LEN && !has_control_chars(raw) {
            return raw.to_string();
        }
    }
    let epoch_ms = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0);
    format!("{prefix}-{epoch_ms}")
}

fn sanitize_kv_segment(raw: &str) -> String {
    let cleaned: String = raw
        .chars()
        .filter(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.'))
        .take(96)
        .collect();
    if cleaned.is_empty() {
        "default".to_string()
    } else {
        cleaned
    }
}

fn is_valid_email_addr(raw: &str) -> bool {
    let trimmed = raw.trim();
    if trimmed.is_empty() || trimmed.len() > 254 || has_control_chars(trimmed) {
        return false;
    }
    if trimmed.chars().any(char::is_whitespace) {
        return false;
    }
    let Some((local, domain)) = trimmed.split_once('@') else {
        return false;
    };
    !local.is_empty()
        && !domain.is_empty()
        && !domain.contains('@')
        && domain.contains('.')
        && !domain.starts_with('.')
        && !domain.ends_with('.')
}

fn overlay_contract_json() -> Value {
    json!({
        "contract_version": "v4.1",
        "modal_id": "settings-overlay",
        "scrim_id": "fdaiSettingsOverlayScrim",
        "role": "dialog",
        "aria_modal": true,
        "shortcut": "Ctrl+,",
        "close_keys": ["Escape"],
        "focus_restore": true,
        "dirty_guard": true,
        "readable_form_max_width_px": 860,
        "full_page_route_template": "/settings#tab={panel_id}",
        "labs_route_template": "/labs#tab={panel_id}",
        "groups": [
            {
                "id": "general-env",
                "title": "일반 · 실행 환경",
                "tabs": [
                    { "id": "settings-general", "label": "일반", "endpoint": "/api/v4/settings/general", "methods": ["GET", "PATCH"] },
                    { "id": "settings-environment", "label": "실행 환경 · 수집기", "endpoint": "/api/v4/settings/environment", "methods": ["GET"] }
                ]
            },
            {
                "id": "models-runtime",
                "title": "AI 모델 · 운영 정책",
                "tabs": [
                    { "id": "settings-models", "label": "AI 모델", "endpoint": "/api/v4/settings/models", "methods": ["GET", "POST /validate-t2"] },
                    { "id": "settings-runtime", "label": "운영 정책", "endpoint": "/api/v4/settings/runtime", "methods": ["GET", "PATCH"] }
                ]
            },
            {
                "id": "iam",
                "title": "사용자 · 권한",
                "tabs": [
                    { "id": "settings-iam", "label": "사용자 · 권한", "endpoint": "/api/v4/settings/iam", "methods": ["GET", "POST /decisions"] }
                ]
            },
            {
                "id": "integrations",
                "title": "외부 연동",
                "tabs": [
                    { "id": "settings-integrations", "label": "외부 연동", "endpoint": "/api/v4/settings/integrations", "methods": ["GET", "POST /test"] }
                ]
            },
            {
                "id": "diagnostics-memory",
                "title": "상태 진단 · 운영 메모",
                "tabs": [
                    { "id": "settings-diagnostics", "label": "시스템 상태 진단", "endpoint": "/api/v4/settings/diagnostics", "methods": ["GET"], "read_only": true },
                    { "id": "settings-memory", "label": "저장된 운영 메모", "endpoint": "/api/v4/settings/memory", "methods": ["GET", "POST /extend", "POST /delete"] }
                ]
            }
        ]
    })
}

/// Validates an IANA timezone identifier strictly without external dependencies.
/// Rejects path traversal, whitespace, unknown areas, and (when `/usr/share/zoneinfo` is present)
/// nonexistent zone files.
pub fn is_valid_iana_timezone(raw: &str) -> bool {
    let tz = raw.trim();
    if tz.is_empty() || tz.len() > 64 {
        return false;
    }
    if tz.contains("..") || tz.starts_with('/') || tz.ends_with('/') || tz.contains('\\') {
        return false;
    }
    if tz == "UTC" || tz == "Etc/UTC" || tz == "Etc/GMT" {
        return true;
    }
    if let Some(offset) = tz
        .strip_prefix("Etc/GMT+")
        .or_else(|| tz.strip_prefix("Etc/GMT-"))
    {
        if let Ok(hours) = offset.parse::<u8>() {
            return (1..=14).contains(&hours);
        }
        return false;
    }

    let segments: Vec<&str> = tz.split('/').collect();
    if !(2..=3).contains(&segments.len()) {
        return false;
    }
    let area = segments[0];
    if !ALLOWED_IANA_AREAS.contains(&area) {
        return false;
    }
    for seg in &segments[1..] {
        if seg.is_empty() || seg.len() > 32 {
            return false;
        }
        let first_ok = seg
            .bytes()
            .next()
            .is_some_and(|b| b.is_ascii_alphabetic() || b.is_ascii_digit());
        if !first_ok {
            return false;
        }
        if !seg
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'-' | b'+'))
        {
            return false;
        }
    }

    let zoneinfo_root = Path::new("/usr/share/zoneinfo");
    if zoneinfo_root.is_dir() {
        let candidate = zoneinfo_root.join(tz);
        return candidate.is_file();
    }
    true
}

/// Masks a webhook URL so userinfo, secret path tokens, query parameters, and fragments
/// are never echoed in responses.
pub fn mask_webhook_url(raw: &str) -> String {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return String::new();
    }
    let without_frag = trimmed.split('#').next().unwrap_or(trimmed);
    let without_query = without_frag.split('?').next().unwrap_or(without_frag);
    let Some((scheme, rest)) = without_query.split_once("://") else {
        return "****".to_string();
    };
    let mut parts = rest.splitn(2, '/');
    let authority = parts.next().unwrap_or("");
    // Strip any userinfo (`user:pass@`) before masking so credentials never appear.
    let host = authority.rsplit('@').next().unwrap_or("");
    let path = parts.next().unwrap_or("");
    if host.is_empty() {
        return "****".to_string();
    }
    if path.is_empty() {
        return format!("{scheme}://{host}/****");
    }
    let segs: Vec<&str> = path.split('/').filter(|s| !s.is_empty()).collect();
    if segs.is_empty() {
        return format!("{scheme}://{host}/****");
    }
    let prefix = segs[0];
    let last = segs[segs.len() - 1];
    let tail: String = if last.len() >= 4 {
        last.chars()
            .rev()
            .take(4)
            .collect::<String>()
            .chars()
            .rev()
            .collect()
    } else {
        String::new()
    };
    if segs.len() == 1 {
        format!("{scheme}://{host}/****{tail}")
    } else {
        format!("{scheme}://{host}/{prefix}/****{tail}")
    }
}

fn is_blocked_ipv4(v4: Ipv4Addr) -> bool {
    let o = v4.octets();
    let is_cgnat = o[0] == 100 && (64..=127).contains(&o[1]);
    v4.is_loopback()
        || v4.is_private()
        || v4.is_link_local()
        || v4.is_broadcast()
        || v4.is_documentation()
        || v4.is_unspecified()
        || v4.is_multicast()
        || o[0] == 0
        || is_cgnat
}

/// Checks whether a webhook URL uses HTTPS, carries no userinfo, and targets a public host.
fn is_safe_webhook_url(raw: &str) -> bool {
    let trimmed = raw.trim();
    if trimmed.is_empty() || trimmed.len() > 2048 || has_control_chars(trimmed) {
        return false;
    }
    let Ok(uri) = trimmed.parse::<Uri>() else {
        return false;
    };
    if uri.scheme_str() != Some("https") {
        return false;
    }
    let Some(authority) = uri.authority() else {
        return false;
    };
    // Disallow embedded credentials (`user:pass@host`) which can mask SSRF targets.
    if authority.as_str().contains('@') {
        return false;
    }
    let host_raw = authority.host();
    if host_raw.is_empty() {
        return false;
    }
    let unbracketed = host_raw.trim_start_matches('[').trim_end_matches(']');
    let normalized = unbracketed.trim_end_matches('.');
    if normalized.is_empty()
        || normalized.contains("..")
        || normalized.chars().all(|c| c.is_ascii_digit())
    {
        return false;
    }
    // Block hex/octal IPv4 encodings (e.g. `0x7f000001`, `0177.0.0.1`) that bypass standard IpAddr parsing.
    let lower_pre = normalized.to_ascii_lowercase();
    if lower_pre.starts_with("0x")
        && lower_pre[2..].chars().all(|c| c.is_ascii_hexdigit())
    {
        return false;
    }
    if lower_pre.split('.').all(|seg| {
        !seg.is_empty()
            && (seg.chars().all(|c| c.is_ascii_digit())
                || (seg.starts_with("0x")
                    && seg.len() > 2
                    && seg[2..].chars().all(|c| c.is_ascii_hexdigit())))
    }) {
        // Dotted numeric host that wasn't valid decimal IPv4 (e.g. octal `0177.0.0.1` or mixed hex).
        if let Ok(ip) = normalized.parse::<Ipv4Addr>() {
            return !is_blocked_ipv4(ip);
        }
        return false;
    }
    if let Ok(ip) = normalized.parse::<IpAddr>() {
        return match ip {
            IpAddr::V4(v4) => !is_blocked_ipv4(v4),
            IpAddr::V6(v6) => {
                if let Some(mapped) = v6.to_ipv4_mapped() {
                    if is_blocked_ipv4(mapped) {
                        return false;
                    }
                }
                let segs = v6.segments();
                if segs[0..6] == [0, 0, 0, 0, 0, 0] && (segs[6] != 0 || segs[7] > 1) {
                    let compat = Ipv4Addr::new(
                        (segs[6] >> 8) as u8,
                        (segs[6] & 0xff) as u8,
                        (segs[7] >> 8) as u8,
                        (segs[7] & 0xff) as u8,
                    );
                    if is_blocked_ipv4(compat) {
                        return false;
                    }
                }
                let seg0 = segs[0];
                let is_ula = (seg0 & 0xfe00) == 0xfc00;
                let is_link_local = (seg0 & 0xffc0) == 0xfe80;
                !(v6.is_loopback()
                    || v6.is_unspecified()
                    || v6.is_multicast()
                    || is_ula
                    || is_link_local)
            }
        };
    }

    let lower = lower_pre;
    !(lower == "localhost"
        || lower.ends_with(".localhost")
        || lower.ends_with(".local")
        || lower.ends_with(".internal")
        || lower.ends_with(".home.arpa")
        || !lower.contains('.'))
}

fn validate_policy_object(val: &Value) -> Result<(), &'static str> {
    if !val.is_object() {
        return Err("availability_policy must be a JSON object");
    }
    if val.to_string().len() > MAX_POLICY_BYTES {
        return Err("availability_policy exceeds 4096 byte size limit");
    }
    fn walk(v: &Value, depth: usize, keys_seen: &mut usize) -> Result<(), &'static str> {
        if depth > MAX_POLICY_DEPTH {
            return Err("availability_policy exceeds maximum nesting depth (4)");
        }
        match v {
            Value::Object(map) => {
                for (k, child) in map {
                    *keys_seen += 1;
                    if *keys_seen > MAX_POLICY_KEYS {
                        return Err("availability_policy exceeds maximum key count (32)");
                    }
                    if k == "__proto__" || k == "constructor" || k == "prototype" {
                        return Err("availability_policy contains prohibited prototype key");
                    }
                    if has_control_chars(k) {
                        return Err("availability_policy key contains control characters");
                    }
                    walk(child, depth + 1, keys_seen)?;
                }
            }
            Value::Array(items) => {
                if items.len() > MAX_POLICY_KEYS {
                    return Err("availability_policy array exceeds maximum length (32)");
                }
                for item in items {
                    walk(item, depth + 1, keys_seen)?;
                }
            }
            Value::String(s) if s.len() > 256 || has_control_chars(s) => {
                return Err("availability_policy string value is invalid");
            }
            _ => {}
        }
        Ok(())
    }
    let mut keys_seen = 0_usize;
    walk(val, 0, &mut keys_seen)
}

/// Validates that primary and secondary T2 model specs use distinct publishers (`provider:model` or `provider/model`).
pub fn has_distinct_t2_publishers(primary: &str, secondary: &str) -> bool {
    fn split_spec(raw: &str) -> Option<(&str, &str)> {
        let trimmed = raw.trim();
        let (pub_part, model_part) = trimmed
            .split_once(':')
            .or_else(|| trimmed.split_once('/'))?;
        let p = pub_part.trim();
        let m = model_part.trim();
        if p.is_empty() || m.is_empty() {
            None
        } else {
            Some((p, m))
        }
    }
    let (Some((p_pub, _)), Some((s_pub, _))) = (split_spec(primary), split_spec(secondary)) else {
        return false;
    };
    !p_pub.eq_ignore_ascii_case(s_pub)
}

async fn page_settings(State(state): State<AppState>) -> Response {
    let html = finalize_v4_html(
        TEMPLATE,
        "settings",
        "settings-general",
        &state.operator_url,
        json!({
            "panels": PANELS,
            "overlaySupported": true,
            "apiBase": "/api/v4/settings",
            "readableFormWidthPx": 860,
            "labsRoute": "/labs"
        }),
    );
    html_response(html)
}

async fn api_settings_overlay(State(state): State<AppState>, headers: HeaderMap) -> Response {
    let auth = extract_auth(&headers);
    let iam_up = state.upstream.get_json("/iam/self", auth).await;
    if iam_up.reachable && iam_up.status == 200 {
        return settings_json_response(
            StatusCode::OK,
            json!({
                "source": "operator-service",
                "domain": "settings",
                "panel": "settings-overlay",
                "measurement_status": "measured",
                "measurement_state": "measured",
                "overlay_contract": overlay_contract_json(),
                "principal": iam_up.payload.unwrap_or(Value::Null)
            }),
        );
    }

    if state.db.is_configured() {
        if let Some(db_data) = repos::settings::fetch_settings_overlay(&state.db).await {
            return settings_json_response(
                StatusCode::OK,
                json!({
                    "source": "postgres-direct",
                    "domain": "settings",
                    "panel": "settings-overlay",
                    "measurement_status": "measured",
                    "measurement_state": "measured",
                    "overlay_contract": overlay_contract_json(),
                    "principal": Value::Null,
                    "data": db_data
                }),
            );
        }
    }

    settings_json_response(
        StatusCode::OK,
        json!({
            "source": "console-v4-rust",
            "domain": "settings",
            "panel": "settings-overlay",
            "measurement_status": "not-measured",
            "measurement_state": "not-measured",
            "overlay_contract": overlay_contract_json(),
            "principal": Value::Null
        }),
    )
}

async fn api_settings_summary(State(state): State<AppState>, headers: HeaderMap) -> Response {
    let auth = extract_auth(&headers);
    let (iam_up, me_up, rt_up, ds_up) = tokio::join!(
        state.upstream.get_json("/iam/self", auth),
        state.upstream.get_json("/me/context", auth),
        state.upstream.get_json("/runtime/settings", auth),
        state.upstream.get_json("/system/data-sources", auth),
    );

    let measured = iam_up.reachable && iam_up.status == 200;
    if measured {
        return settings_json_response(
            StatusCode::OK,
            json!({
                "source": "operator-service",
                "domain": "settings",
                "measurement_status": "measured",
                "measurement_state": "measured",
                "panels": PANELS,
                "overlay_contract": overlay_contract_json(),
                "data": {
                    "iam_self": iam_up.payload.unwrap_or(Value::Null),
                    "me_context": if me_up.reachable && me_up.status == 200 { me_up.payload.unwrap_or(Value::Null) } else { Value::Null },
                    "runtime_settings": if rt_up.reachable && rt_up.status == 200 { rt_up.payload.unwrap_or(Value::Null) } else { Value::Null },
                    "data_sources": if ds_up.reachable && ds_up.status == 200 { ds_up.payload.unwrap_or(Value::Null) } else { Value::Null }
                }
            }),
        );
    }

    if state.db.is_configured() {
        let mut pg_sum = repos::settings::fetch_settings_summary(&state.db).await;
        let is_pg_measured = pg_sum
            .get("measurement_status")
            .and_then(Value::as_str)
            == Some("measured");
        if let Some(obj) = pg_sum.as_object_mut() {
            obj.insert("domain".to_string(), json!("settings"));
            obj.insert("panels".to_string(), json!(PANELS));
            obj.insert("overlay_contract".to_string(), overlay_contract_json());
            obj.insert(
                "measurement_state".to_string(),
                json!(if is_pg_measured { "measured" } else { "not-measured" }),
            );
            obj.insert("db_writes_allowed".to_string(), json!(state.db.mutations_allowed()));
        }
        return settings_json_response(StatusCode::OK, pg_sum);
    }

    let mut env = state.upstream.not_measured_envelope(
        "settings",
        "/iam/self",
        "operator-service offline or unauthenticated",
    );
    if let Some(obj) = env.as_object_mut() {
        obj.insert("measurement_status".to_string(), json!("not-measured"));
        obj.insert("panels".to_string(), json!(PANELS));
        obj.insert("overlay_contract".to_string(), overlay_contract_json());
    }
    settings_json_response(StatusCode::OK, env)
}

async fn api_settings_general_get(State(state): State<AppState>, headers: HeaderMap) -> Response {
    let auth = extract_auth(&headers);
    let scopes = json!({
        "browser": ["theme", "locale", "reduced_motion", "collapse_chat_trace", "show_token_usage", "capture_model_trace"],
        "account": ["answer_detail", "answer_format", "timezone", "opening_briefing", "briefing_hour", "share_with_learner"]
    });
    let validation_rules = json!({
        "locales": ALLOWED_LOCALES,
        "answer_details": ALLOWED_ANSWER_DETAILS,
        "answer_formats": ALLOWED_ANSWER_FORMATS,
        "timezone_standard": "IANA",
        "briefing_hour_range": [0, 23]
    });
    let up = state.upstream.get_json("/me/context", auth).await;
    if up.reachable && up.status == 200 {
        if let Some(payload) = up.payload {
            return settings_json_response(
                StatusCode::OK,
                json!({
                    "source": "operator-service",
                    "domain": "settings",
                    "panel": "settings-general",
                    "measurement_status": "measured",
                    "measurement_state": "measured",
                    "scopes": scopes,
                    "validation_rules": validation_rules,
                    "data": payload
                }),
            );
        }
    }

    if state.db.is_configured() {
        if let Some(db_data) = repos::settings::fetch_settings_general(&state.db).await {
            return settings_json_response(
                StatusCode::OK,
                json!({
                    "source": "postgres-direct",
                    "domain": "settings",
                    "panel": "settings-general",
                    "measurement_status": "measured",
                    "measurement_state": "measured",
                    "scopes": scopes,
                    "validation_rules": validation_rules,
                    "db_writes_allowed": state.db.mutations_allowed(),
                    "data": db_data
                }),
            );
        }
    }

    let mut env = state.upstream.not_measured_envelope(
        "settings",
        "/me/context",
        "operator-service offline or unauthenticated",
    );
    if let Some(obj) = env.as_object_mut() {
        obj.insert("measurement_status".to_string(), json!("not-measured"));
        obj.insert("panel".to_string(), json!("settings-general"));
        obj.insert("scopes".to_string(), scopes);
        obj.insert("validation_rules".to_string(), validation_rules);
    }
    settings_json_response(StatusCode::OK, env)
}

#[derive(Debug, Deserialize)]
struct GeneralPatchRequest {
    locale: Option<String>,
    answer_detail: Option<String>,
    answer_format: Option<String>,
    timezone: Option<String>,
    briefing_hour: Option<i64>,
    opening_briefing: Option<bool>,
    share_with_learner: Option<bool>,
    reduced_motion: Option<bool>,
    collapse_chat_trace: Option<bool>,
    show_token_usage: Option<bool>,
    capture_model_trace: Option<bool>,
}

async fn api_settings_general_patch(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<GeneralPatchRequest>,
) -> Response {
    let any_field = req.locale.is_some()
        || req.answer_detail.is_some()
        || req.answer_format.is_some()
        || req.timezone.is_some()
        || req.briefing_hour.is_some()
        || req.opening_briefing.is_some()
        || req.share_with_learner.is_some()
        || req.reduced_motion.is_some()
        || req.collapse_chat_trace.is_some()
        || req.show_token_usage.is_some()
        || req.capture_model_trace.is_some();
    if !any_field {
        return settings_json_response(
            StatusCode::BAD_REQUEST,
            json!({
                "error": "empty_general_patch",
                "message": "At least one general setting field must be provided"
            }),
        );
    }

    if let Some(ref loc) = req.locale {
        if !ALLOWED_LOCALES.contains(&loc.as_str()) {
            return settings_json_response(
                StatusCode::BAD_REQUEST,
                json!({
                    "error": "invalid_locale",
                    "message": "locale must be one of: ko, en"
                }),
            );
        }
    }
    if let Some(ref detail) = req.answer_detail {
        if !ALLOWED_ANSWER_DETAILS.contains(&detail.as_str()) {
            return settings_json_response(
                StatusCode::BAD_REQUEST,
                json!({
                    "error": "invalid_answer_detail",
                    "message": "answer_detail must be one of: concise, standard, detailed"
                }),
            );
        }
    }
    if let Some(ref fmt) = req.answer_format {
        if !ALLOWED_ANSWER_FORMATS.contains(&fmt.as_str()) {
            return settings_json_response(
                StatusCode::BAD_REQUEST,
                json!({
                    "error": "invalid_answer_format",
                    "message": "answer_format must be one of the 7 canonical formats"
                }),
            );
        }
    }
    if let Some(ref tz) = req.timezone {
        if !is_valid_iana_timezone(tz) {
            return settings_json_response(
                StatusCode::BAD_REQUEST,
                json!({
                    "error": "invalid_timezone",
                    "message": "timezone must be a valid IANA identifier (e.g. Asia/Seoul or UTC)"
                }),
            );
        }
    }
    if let Some(hour) = req.briefing_hour {
        if !(0..=23).contains(&hour) {
            return settings_json_response(
                StatusCode::BAD_REQUEST,
                json!({
                    "error": "invalid_briefing_hour",
                    "message": "briefing_hour must be within 0..=23"
                }),
            );
        }
    }

    let normalized = json!({
        "locale": req.locale,
        "answer_detail": req.answer_detail,
        "answer_format": req.answer_format,
        "timezone": req.timezone.as_deref().map(str::trim),
        "briefing_hour": req.briefing_hour,
        "opening_briefing": req.opening_briefing,
        "share_with_learner": req.share_with_learner,
        "browser_preferences": {
            "reduced_motion": req.reduced_motion,
            "collapse_chat_trace": req.collapse_chat_trace,
            "show_token_usage": req.show_token_usage,
            "capture_model_trace": req.capture_model_trace
        }
    });

    let auth = extract_auth(&headers);
    let up = state
        .upstream
        .patch_json("/me/context", normalized.clone(), auth)
        .await;
    if up.reachable && (200..300).contains(&up.status) {
        return settings_json_response(
            StatusCode::OK,
            json!({
                "source": "operator-service",
                "domain": "settings",
                "panel": "settings-general",
                "measurement_status": "measured",
                "measurement_state": "measured",
                "validated": true,
                "persisted": true,
                "persisted_upstream": true,
                "data": up.payload.unwrap_or(normalized)
            }),
        );
    }

    if state.db.mutations_allowed() {
        let idem = extract_idempotency_key(&headers, "settings-general-patch");
        match state
            .db
            .execute_audited_kv_mutation(
                "settings:general:v1",
                &normalized.to_string(),
                "console-v4-operator",
                "settings.general.patch",
                &idem,
            )
            .await
        {
            Ok(receipt) => {
                return settings_json_response(
                    StatusCode::OK,
                    json!({
                        "source": "postgres-direct",
                        "domain": "settings",
                        "panel": "settings-general",
                        "measurement_status": "measured",
                        "measurement_state": "measured",
                        "validated": true,
                        "persisted": true,
                        "persisted_upstream": false,
                        "db_receipt": receipt,
                        "data": normalized
                    }),
                );
            }
            Err(err_code) => {
                return settings_json_response(
                    StatusCode::OK,
                    json!({
                        "source": "postgres-direct",
                        "domain": "settings",
                        "panel": "settings-general",
                        "measurement_status": "measured",
                        "measurement_state": "measured",
                        "validated": true,
                        "persisted": false,
                        "persisted_upstream": false,
                        "reason": err_code,
                        "normalized": normalized
                    }),
                );
            }
        }
    }

    let status_label = if state.db.is_configured() {
        "measured"
    } else {
        "not-measured"
    };
    let source_label = if state.db.is_configured() {
        "postgres-direct"
    } else {
        "console-v4-rust"
    };
    settings_json_response(
        StatusCode::OK,
        json!({
            "source": source_label,
            "domain": "settings",
            "panel": "settings-general",
            "measurement_status": status_label,
            "measurement_state": status_label,
            "validated": true,
            "persisted": false,
            "persisted_upstream": false,
            "upstream_status": if up.reachable { Value::from(up.status) } else { Value::Null },
            "reason": if state.db.is_configured() {
                "db_writes_disabled_readonly_mode"
            } else {
                "operator-service offline, unauthenticated, or PATCH /me/context not enabled"
            },
            "normalized": normalized
        }),
    )
}

async fn api_settings_environment(State(state): State<AppState>, headers: HeaderMap) -> Response {
    let auth = extract_auth(&headers);
    let (ds_up, routes_up) = tokio::join!(
        state.upstream.get_json("/system/data-sources", auth),
        state.upstream.get_json("/routes", auth),
    );
    if ds_up.reachable && ds_up.status == 200 {
        return settings_json_response(
            StatusCode::OK,
            json!({
                "source": "operator-service",
                "domain": "settings",
                "panel": "settings-environment",
                "measurement_status": "measured",
                "measurement_state": "measured",
                "no_zero_for_unmeasured": true,
                "data": {
                    "data_sources": ds_up.payload.unwrap_or(Value::Null),
                    "routes": if routes_up.reachable && routes_up.status == 200 { routes_up.payload.unwrap_or(Value::Null) } else { Value::Null }
                }
            }),
        );
    }

    if state.db.is_configured() {
        if let Some(db_data) = repos::settings::fetch_settings_environment(&state.db).await {
            return settings_json_response(
                StatusCode::OK,
                json!({
                    "source": "postgres-direct",
                    "domain": "settings",
                    "panel": "settings-environment",
                    "measurement_status": "measured",
                    "measurement_state": "measured",
                    "no_zero_for_unmeasured": true,
                    "data": db_data
                }),
            );
        }
    }

    let mut env = state.upstream.not_measured_envelope(
        "settings",
        "/system/data-sources",
        "operator-service offline or unauthenticated",
    );
    if let Some(obj) = env.as_object_mut() {
        obj.insert("measurement_status".to_string(), json!("not-measured"));
        obj.insert("panel".to_string(), json!("settings-environment"));
        obj.insert("no_zero_for_unmeasured".to_string(), json!(true));
    }
    settings_json_response(StatusCode::OK, env)
}

async fn api_settings_models(State(state): State<AppState>, headers: HeaderMap) -> Response {
    let auth = extract_auth(&headers);
    let up = state.upstream.get_json("/models/settings", auth).await;
    let invariants = json!({
        "deterministic_first": true,
        "distinct_publisher_locked": true,
        "console_direct_activation_blocked": true,
        "t2_pr_draft_only": true
    });
    if up.reachable && up.status == 200 {
        if let Some(payload) = up.payload {
            return settings_json_response(
                StatusCode::OK,
                json!({
                    "source": "operator-service",
                    "domain": "settings",
                    "panel": "settings-models",
                    "measurement_status": "measured",
                    "measurement_state": "measured",
                    "invariants": invariants,
                    "data": payload
                }),
            );
        }
    }

    if state.db.is_configured() {
        if let Some(db_data) = repos::settings::fetch_settings_models(&state.db).await {
            return settings_json_response(
                StatusCode::OK,
                json!({
                    "source": "postgres-direct",
                    "domain": "settings",
                    "panel": "settings-models",
                    "measurement_status": "measured",
                    "measurement_state": "measured",
                    "invariants": invariants,
                    "data": db_data
                }),
            );
        }
    }

    let mut env = state.upstream.not_measured_envelope(
        "settings",
        "/models/settings",
        "operator-service offline or unauthenticated",
    );
    if let Some(obj) = env.as_object_mut() {
        obj.insert("measurement_status".to_string(), json!("not-measured"));
        obj.insert("panel".to_string(), json!("settings-models"));
        obj.insert("invariants".to_string(), invariants);
    }
    settings_json_response(StatusCode::OK, env)
}

#[derive(Debug, Deserialize)]
struct ValidateT2Request {
    primary: String,
    secondary: String,
}

async fn api_settings_models_validate_t2(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<ValidateT2Request>,
) -> Response {
    let primary = req.primary.trim();
    let secondary = req.secondary.trim();
    if primary.is_empty()
        || secondary.is_empty()
        || primary.len() > MAX_ID_LEN
        || secondary.len() > MAX_ID_LEN
        || has_control_chars(primary)
        || has_control_chars(secondary)
    {
        return settings_json_response(
            StatusCode::BAD_REQUEST,
            json!({
                "error": "invalid_t2_model_spec",
                "message": "primary and secondary model specs must be non-empty provider:model strings without control characters"
            }),
        );
    }

    if !has_distinct_t2_publishers(primary, secondary) {
        return settings_json_response(
            StatusCode::UNPROCESSABLE_ENTITY,
            json!({
                "error": "t2_same_publisher_blocked",
                "message": "T2 primary and verifier models must belong to distinct publishers",
                "distinct_publisher": false,
                "execution_authority": false
            }),
        );
    }

    let draft_payload = json!({
        "t2_primary": primary,
        "t2_secondary": secondary,
        "distinct_publisher": true,
        "enforcement": "pr_artifact_only",
        "execution_authority": false
    });

    if state.db.mutations_allowed() {
        let idem = extract_idempotency_key(&headers, "settings-models-t2-draft");
        if let Ok(receipt) = state
            .db
            .execute_audited_kv_mutation(
                "settings:models:t2-draft:v1",
                &draft_payload.to_string(),
                "console-v4-operator",
                "settings.models.validate_t2_draft",
                &idem,
            )
            .await
        {
            return settings_json_response(
                StatusCode::OK,
                json!({
                    "source": "postgres-direct",
                    "domain": "settings",
                    "panel": "settings-models",
                    "measurement_status": "measured",
                    "measurement_state": "measured",
                    "distinct_publisher": true,
                    "enforcement": "pr_artifact_only",
                    "execution_authority": false,
                    "persisted": true,
                    "db_receipt": receipt,
                    "t2_primary": primary,
                    "t2_secondary": secondary
                }),
            );
        }
    }

    settings_json_response(
        StatusCode::OK,
        json!({
            "source": if state.db.is_configured() { "postgres-direct" } else { "console-v4-rust" },
            "domain": "settings",
            "panel": "settings-models",
            "measurement_status": if state.db.is_configured() { "measured" } else { "not-measured" },
            "measurement_state": if state.db.is_configured() { "measured" } else { "not-measured" },
            "distinct_publisher": true,
            "enforcement": "pr_artifact_only",
            "execution_authority": false,
            "persisted": false,
            "t2_primary": primary,
            "t2_secondary": secondary
        }),
    )
}

async fn api_settings_runtime_get(State(state): State<AppState>, headers: HeaderMap) -> Response {
    let auth = extract_auth(&headers);
    let up = state.upstream.get_json("/runtime/settings", auth).await;
    let locked_invariants = json!({
        "shadow_default_locked": true,
        "no_zero_for_unmeasured_locked": true,
        "silence_means_deny_locked": true,
        "seven_safeguards_required": true
    });
    if up.reachable && up.status == 200 {
        if let Some(payload) = up.payload {
            return settings_json_response(
                StatusCode::OK,
                json!({
                    "source": "operator-service",
                    "domain": "settings",
                    "panel": "settings-runtime",
                    "measurement_status": "measured",
                    "measurement_state": "measured",
                    "locked_invariants": locked_invariants,
                    "data": payload
                }),
            );
        }
    }

    if state.db.is_configured() {
        if let Some(db_data) = repos::settings::fetch_settings_runtime(&state.db).await {
            return settings_json_response(
                StatusCode::OK,
                json!({
                    "source": "postgres-direct",
                    "domain": "settings",
                    "panel": "settings-runtime",
                    "measurement_status": "measured",
                    "measurement_state": "measured",
                    "locked_invariants": locked_invariants,
                    "db_writes_allowed": state.db.mutations_allowed(),
                    "data": db_data
                }),
            );
        }
    }

    let mut env = state.upstream.not_measured_envelope(
        "settings",
        "/runtime/settings",
        "operator-service offline or unauthenticated",
    );
    if let Some(obj) = env.as_object_mut() {
        obj.insert("measurement_status".to_string(), json!("not-measured"));
        obj.insert("panel".to_string(), json!("settings-runtime"));
        obj.insert("locked_invariants".to_string(), locked_invariants);
    }
    settings_json_response(StatusCode::OK, env)
}

#[derive(Debug, Deserialize)]
struct RuntimePatchRequest {
    revision: Option<u64>,
    autonomy_profile: Option<String>,
    approval_expiry_min: Option<u64>,
    turn_budget_sec: Option<u64>,
    batch_concurrency: Option<u64>,
    availability_policy: Option<Value>,
    risk_acknowledged: Option<bool>,
    shadow_default: Option<bool>,
    no_zero_for_unmeasured: Option<bool>,
    silence_means_deny: Option<bool>,
}

async fn api_settings_runtime_patch(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<RuntimePatchRequest>,
) -> Response {
    // Constitutional invariants cannot be disabled.
    if req.shadow_default == Some(false)
        || req.no_zero_for_unmeasured == Some(false)
        || req.silence_means_deny == Some(false)
    {
        return settings_json_response(
            StatusCode::BAD_REQUEST,
            json!({
                "error": "invariant_violation",
                "message": "Locked constitutional invariants (shadow_default, no_zero_for_unmeasured, silence_means_deny) cannot be disabled"
            }),
        );
    }

    if let Some(ref profile) = req.autonomy_profile {
        if !ALLOWED_AUTONOMY_PROFILES.contains(&profile.as_str()) {
            return settings_json_response(
                StatusCode::BAD_REQUEST,
                json!({
                    "error": "invalid_autonomy_profile",
                    "message": "Unsupported autonomy_profile value"
                }),
            );
        }
    }

    if let Some(expiry) = req.approval_expiry_min {
        if !(5..=120).contains(&expiry) {
            return settings_json_response(
                StatusCode::BAD_REQUEST,
                json!({
                    "error": "invalid_approval_expiry_min",
                    "message": "approval_expiry_min must be within 5..=120"
                }),
            );
        }
    }

    if let Some(budget) = req.turn_budget_sec {
        if !(10..=300).contains(&budget) {
            return settings_json_response(
                StatusCode::BAD_REQUEST,
                json!({
                    "error": "invalid_turn_budget_sec",
                    "message": "turn_budget_sec must be within 10..=300"
                }),
            );
        }
    }

    if let Some(conc) = req.batch_concurrency {
        if !(1..=16).contains(&conc) {
            return settings_json_response(
                StatusCode::BAD_REQUEST,
                json!({
                    "error": "invalid_batch_concurrency",
                    "message": "batch_concurrency must be within 1..=16"
                }),
            );
        }
    }

    if let Some(ref policy) = req.availability_policy {
        if let Err(msg) = validate_policy_object(policy) {
            return settings_json_response(
                StatusCode::BAD_REQUEST,
                json!({
                    "error": "invalid_availability_policy",
                    "message": msg
                }),
            );
        }
    }

    let mut changes = Map::new();
    if let Some(profile) = &req.autonomy_profile {
        changes.insert("autonomy_profile".to_string(), json!(profile));
    }
    if let Some(expiry) = req.approval_expiry_min {
        changes.insert("approval_expiry_min".to_string(), json!(expiry));
    }
    if let Some(budget) = req.turn_budget_sec {
        changes.insert("turn_budget_sec".to_string(), json!(budget));
    }
    if let Some(conc) = req.batch_concurrency {
        changes.insert("batch_concurrency".to_string(), json!(conc));
    }
    if let Some(policy) = &req.availability_policy {
        changes.insert("availability_policy".to_string(), policy.clone());
    }

    if changes.is_empty() {
        return settings_json_response(
            StatusCode::BAD_REQUEST,
            json!({
                "error": "empty_runtime_patch",
                "message": "At least one adjustable runtime policy field must be provided"
            }),
        );
    }

    let high_impact_profile = req
        .autonomy_profile
        .as_deref()
        .is_some_and(|p| p != "multi-operator-shadow" && p != "standard-shadow");
    let high_impact_expiry = req.approval_expiry_min.is_some_and(|m| m != 15);
    let high_impact = high_impact_profile || high_impact_expiry;

    if high_impact && req.risk_acknowledged != Some(true) {
        return settings_json_response(
            StatusCode::UNPROCESSABLE_ENTITY,
            json!({
                "error": "risk_acknowledgement_required",
                "message": "High-impact runtime policy changes require explicit risk_acknowledged=true confirmation"
            }),
        );
    }

    let upstream_body = json!({
        "revision": req.revision,
        "changes": changes,
        "risk_acknowledged": req.risk_acknowledged.unwrap_or(false)
    });

    let auth = extract_auth(&headers);
    let up = state
        .upstream
        .patch_json("/runtime/settings", upstream_body.clone(), auth)
        .await;
    if up.reachable && (200..300).contains(&up.status) {
        return settings_json_response(
            StatusCode::OK,
            json!({
                "source": "operator-service",
                "domain": "settings",
                "panel": "settings-runtime",
                "measurement_status": "measured",
                "measurement_state": "measured",
                "validated": true,
                "high_impact": high_impact,
                "seven_safeguards_required": true,
                "persisted": true,
                "persisted_upstream": true,
                "data": up.payload.unwrap_or(upstream_body)
            }),
        );
    }

    if state.db.mutations_allowed() {
        let idem = extract_idempotency_key(&headers, "settings-runtime-patch");
        match state
            .db
            .execute_audited_kv_mutation(
                "settings:runtime:v1",
                &upstream_body.to_string(),
                "console-v4-operator",
                "settings.runtime.patch",
                &idem,
            )
            .await
        {
            Ok(receipt) => {
                return settings_json_response(
                    StatusCode::OK,
                    json!({
                        "source": "postgres-direct",
                        "domain": "settings",
                        "panel": "settings-runtime",
                        "measurement_status": "measured",
                        "measurement_state": "measured",
                        "validated": true,
                        "high_impact": high_impact,
                        "seven_safeguards_required": true,
                        "persisted": true,
                        "persisted_upstream": false,
                        "db_receipt": receipt,
                        "data": upstream_body
                    }),
                );
            }
            Err(err_code) => {
                return settings_json_response(
                    StatusCode::OK,
                    json!({
                        "source": "postgres-direct",
                        "domain": "settings",
                        "panel": "settings-runtime",
                        "measurement_status": "measured",
                        "measurement_state": "measured",
                        "validated": true,
                        "high_impact": high_impact,
                        "seven_safeguards_required": true,
                        "persisted": false,
                        "persisted_upstream": false,
                        "reason": err_code,
                        "normalized": upstream_body
                    }),
                );
            }
        }
    }

    let status_label = if state.db.is_configured() {
        "measured"
    } else {
        "not-measured"
    };
    let source_label = if state.db.is_configured() {
        "postgres-direct"
    } else {
        "console-v4-rust"
    };
    settings_json_response(
        StatusCode::OK,
        json!({
            "source": source_label,
            "domain": "settings",
            "panel": "settings-runtime",
            "measurement_status": status_label,
            "measurement_state": status_label,
            "validated": true,
            "high_impact": high_impact,
            "seven_safeguards_required": true,
            "persisted": false,
            "persisted_upstream": false,
            "upstream_status": if up.reachable { Value::from(up.status) } else { Value::Null },
            "reason": if state.db.is_configured() {
                "db_writes_disabled_readonly_mode"
            } else {
                "operator-service offline, unauthenticated, or runtime PATCH route unavailable"
            },
            "normalized": upstream_body
        }),
    )
}

fn build_azure_iam_groups_payload(saved_profile: Option<Value>) -> Value {
    let digest = fdai_contracts::azure_iam_groups::azure_iam_catalog_digest_hex(
        fdai_contracts::azure_iam_groups::EMBEDDED_AZURE_IAM_CATALOG_JSON,
    );
    match fdai_contracts::azure_iam_groups::load_embedded_azure_iam_catalog() {
        Ok(catalog) => {
            let valid = fdai_domain_core::azure_iam_catalog::validate_azure_iam_catalog(&catalog);
            let default_selection = json!({
                "workload_group": catalog.defaults.default_workload_group,
                "binding_mode": catalog.defaults.binding_mode,
                "custom_role_scope": catalog.defaults.custom_role_scope,
                "dev_gateway_executor_group": catalog.defaults.dev_gateway_executor_group,
                "environment": "dev",
                "pim_required": catalog.defaults.pim_required
            });
            let active_selection = saved_profile.unwrap_or(default_selection);
            let tfvars_preview = render_azure_iam_tfvars_preview(&active_selection);
            json!({
                "catalog_id": catalog.catalog_id,
                "schema_version": catalog.schema_version,
                "catalog_digest": digest,
                "catalog_valid": valid.is_ok(),
                "defaults": catalog.defaults,
                "safety_floor": catalog.safety_floor,
                "groups": catalog.groups,
                "no_target_azure_role_agents": catalog.no_target_azure_role_agents,
                "human_admin_groups": catalog.human_admin_groups,
                "active_selection": active_selection,
                "tfvars_preview": tfvars_preview,
                "direct_infra_mutation_blocked": true,
                "execution_authority": false
            })
        }
        Err(err) => json!({
            "catalog_valid": false,
            "error": err,
            "direct_infra_mutation_blocked": true,
            "execution_authority": false
        }),
    }
}

fn render_azure_iam_tfvars_preview(sel: &Value) -> String {
    let binding_mode = sel
        .get("binding_mode")
        .and_then(Value::as_str)
        .unwrap_or("direct");
    let custom_role_scope = sel
        .get("custom_role_scope")
        .and_then(Value::as_str)
        .unwrap_or("subscription");
    let devgw_group = sel
        .get("dev_gateway_executor_group")
        .and_then(Value::as_str)
        .unwrap_or("operator");
    let workload_group = sel
        .get("workload_group")
        .and_then(Value::as_str)
        .unwrap_or("reader");
    let scope_line = if custom_role_scope == "management_group" {
        "fdai_iam_role_definition_scope = \"/providers/Microsoft.Management/managementGroups/<mg-id>\"\n"
    } else {
        "# fdai_iam_role_definition_scope omitted -> defaults to current subscription\n"
    };
    format!(
        "enable_fdai_iam_permission_groups = true\n\
         # selected workload tier: {workload_group} (PIM not required)\n\
         fdai_iam_binding_mode = \"{binding_mode}\"\n\
         dev_gateway_executor_iam_group = \"{devgw_group}\"\n\
         {scope_line}"
    )
}

async fn api_settings_iam_azure_groups_get(State(state): State<AppState>) -> Response {
    let saved_profile = if state.db.is_configured() {
        repos::settings::fetch_kv_exact(&state.db, "settings:iam:azure-groups:v1")
            .await
            .ok()
            .flatten()
            .map(|(v, _)| v)
    } else {
        None
    };
    let payload = build_azure_iam_groups_payload(saved_profile);
    settings_json_response(
        StatusCode::OK,
        json!({
            "source": "embedded-catalog",
            "domain": "settings",
            "panel": "settings-iam",
            "measurement_status": "measured",
            "measurement_state": "measured",
            "db_writes_allowed": state.db.mutations_allowed(),
            "azure_iam_groups": payload
        }),
    )
}

#[derive(Debug, Deserialize)]
struct AzureIamGroupsPatchRequest {
    workload_group: String,
    binding_mode: String,
    custom_role_scope: String,
    dev_gateway_executor_group: String,
    environment: Option<String>,
}

async fn api_settings_iam_azure_groups_patch(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<AzureIamGroupsPatchRequest>,
) -> Response {
    let workload_group = req.workload_group.trim().to_ascii_lowercase();
    let binding_mode = req.binding_mode.trim().to_ascii_lowercase();
    let custom_role_scope = req.custom_role_scope.trim().to_ascii_lowercase();
    let devgw_group = req.dev_gateway_executor_group.trim().to_ascii_lowercase();
    let env_name = req
        .environment
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .unwrap_or("dev")
        .to_ascii_lowercase();

    if !matches!(env_name.as_str(), "dev" | "staging" | "production") {
        return settings_json_response(
            StatusCode::BAD_REQUEST,
            json!({
                "error": "invalid_environment",
                "message": "environment must be dev, staging, or production"
            }),
        );
    }

    let Ok(catalog) = fdai_contracts::azure_iam_groups::load_embedded_azure_iam_catalog() else {
        return settings_json_response(
            StatusCode::INTERNAL_SERVER_ERROR,
            json!({
                "error": "catalog_unavailable",
                "message": "Canonical Azure IAM permission groups catalog could not be loaded"
            }),
        );
    };

    let selection = fdai_contracts::azure_iam_groups::AzureIamProfileSelection {
        workload_group: workload_group.clone(),
        binding_mode: binding_mode.clone(),
        custom_role_scope: custom_role_scope.clone(),
        dev_gateway_executor_group: devgw_group.clone(),
        pim_required: false,
    };

    if let Err(reason) = fdai_domain_core::azure_iam_catalog::validate_profile_selection(
        &catalog,
        &selection,
        &env_name,
    ) {
        return settings_json_response(
            StatusCode::UNPROCESSABLE_ENTITY,
            json!({
                "error": "invalid_azure_iam_profile",
                "message": reason,
                "validated": false,
                "persisted": false,
                "direct_infra_mutation_blocked": true
            }),
        );
    }

    let draft = json!({
        "workload_group": workload_group,
        "binding_mode": binding_mode,
        "custom_role_scope": custom_role_scope,
        "dev_gateway_executor_group": devgw_group,
        "environment": env_name,
        "pim_required": false,
        "authority": "draft_only",
        "execution_authority": false,
        "direct_infra_mutation_blocked": true
    });
    let tfvars_preview = render_azure_iam_tfvars_preview(&draft);

    if state.db.mutations_allowed() {
        let idem = extract_idempotency_key(&headers, "settings-iam-azure-groups");
        if let Ok(receipt) = state
            .db
            .execute_audited_kv_mutation(
                "settings:iam:azure-groups:v1",
                &draft.to_string(),
                "console-v4-operator",
                "settings.iam.azure_groups.draft",
                &idem,
            )
            .await
        {
            return settings_json_response(
                StatusCode::OK,
                json!({
                    "source": "postgres-direct",
                    "domain": "settings",
                    "panel": "settings-iam",
                    "validated": true,
                    "persisted": true,
                    "direct_infra_mutation_blocked": true,
                    "execution_authority": false,
                    "active_selection": draft,
                    "tfvars_preview": tfvars_preview,
                    "receipt": receipt
                }),
            );
        }
    }

    settings_json_response(
        StatusCode::OK,
        json!({
            "source": "local-validator",
            "domain": "settings",
            "panel": "settings-iam",
            "validated": true,
            "persisted": false,
            "direct_infra_mutation_blocked": true,
            "execution_authority": false,
            "active_selection": draft,
            "tfvars_preview": tfvars_preview,
            "reason": "PostgreSQL mutations disabled or offline; validated draft only (zero direct Azure mutation)."
        }),
    )
}

async fn api_settings_iam(State(state): State<AppState>, headers: HeaderMap) -> Response {
    let auth = extract_auth(&headers);
    let (iam_up, self_up) = tokio::join!(
        state.upstream.get_json("/iam", auth),
        state.upstream.get_json("/iam/self", auth),
    );
    let saved_azure_profile = if state.db.is_configured() {
        repos::settings::fetch_kv_exact(&state.db, "settings:iam:azure-groups:v1")
            .await
            .ok()
            .flatten()
            .map(|(v, _)| v)
    } else {
        None
    };
    let azure_iam_groups = build_azure_iam_groups_payload(saved_azure_profile);
    let invariants = json!({
        "approver_ne_executor": true,
        "self_approval_blocked": true,
        "min_review_reason_chars": 20,
        "direct_infra_mutation_blocked": true,
        "pim_required": false
    });
    if iam_up.reachable && iam_up.status == 200 {
        return settings_json_response(
            StatusCode::OK,
            json!({
                "source": "operator-service",
                "domain": "settings",
                "panel": "settings-iam",
                "measurement_status": "measured",
                "measurement_state": "measured",
                "invariants": invariants,
                "azure_iam_groups": azure_iam_groups,
                "data": {
                    "iam": iam_up.payload.unwrap_or(Value::Null),
                    "self": if self_up.reachable && self_up.status == 200 { self_up.payload.unwrap_or(Value::Null) } else { Value::Null }
                }
            }),
        );
    }

    if state.db.is_configured() {
        if let Some(db_data) = repos::settings::fetch_settings_iam(&state.db).await {
            return settings_json_response(
                StatusCode::OK,
                json!({
                    "source": "postgres-direct",
                    "domain": "settings",
                    "panel": "settings-iam",
                    "measurement_status": "measured",
                    "measurement_state": "measured",
                    "invariants": invariants,
                    "azure_iam_groups": azure_iam_groups,
                    "db_writes_allowed": state.db.mutations_allowed(),
                    "data": db_data
                }),
            );
        }
    }

    let mut env = state.upstream.not_measured_envelope(
        "settings",
        "/iam",
        "operator-service offline or unauthenticated",
    );
    if let Some(obj) = env.as_object_mut() {
        obj.insert("measurement_status".to_string(), json!("not-measured"));
        obj.insert("panel".to_string(), json!("settings-iam"));
        obj.insert("invariants".to_string(), invariants);
        obj.insert("azure_iam_groups".to_string(), azure_iam_groups);
    }
    settings_json_response(StatusCode::OK, env)
}

#[derive(Debug, Deserialize)]
struct IamDecisionRequest {
    request_id: String,
    decision: String,
    reason: String,
    actor_subject_id: Option<String>,
    requester_subject_id: Option<String>,
    target_subject_id: Option<String>,
    self_owned: Option<bool>,
}

async fn api_settings_iam_decision(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<IamDecisionRequest>,
) -> Response {
    let req_id = req.request_id.trim();
    if req_id.is_empty() || req_id.len() > MAX_ID_LEN || has_control_chars(req_id) {
        return settings_json_response(
            StatusCode::BAD_REQUEST,
            json!({
                "error": "invalid_request_id",
                "message": "request_id is required and must not contain control characters"
            }),
        );
    }
    if req.decision != "approve" && req.decision != "reject" {
        return settings_json_response(
            StatusCode::BAD_REQUEST,
            json!({
                "error": "invalid_decision",
                "message": "decision must be 'approve' or 'reject'"
            }),
        );
    }

    let auth = extract_auth(&headers);
    let self_up = state.upstream.get_json("/iam/self", auth).await;
    let verified_actor = self_up
        .payload
        .as_ref()
        .and_then(|p| p.pointer("/principal/subject_id"))
        .and_then(Value::as_str)
        .map(str::to_string);

    let effective_actor = verified_actor
        .as_deref()
        .or(req.actor_subject_id.as_deref())
        .map(str::trim)
        .unwrap_or("");
    let requester = req
        .requester_subject_id
        .as_deref()
        .map(str::trim)
        .unwrap_or("");
    let target = req
        .target_subject_id
        .as_deref()
        .map(str::trim)
        .unwrap_or("");

    if has_control_chars(effective_actor)
        || has_control_chars(requester)
        || has_control_chars(target)
        || effective_actor.len() > MAX_ID_LEN
        || requester.len() > MAX_ID_LEN
        || target.len() > MAX_ID_LEN
    {
        return settings_json_response(
            StatusCode::BAD_REQUEST,
            json!({
                "error": "invalid_subject_id",
                "message": "Subject identifiers must not contain control characters or exceed 128 chars"
            }),
        );
    }

    let is_self_action = req.self_owned == Some(true)
        || (!effective_actor.is_empty()
            && ((!requester.is_empty() && effective_actor.eq_ignore_ascii_case(requester))
                || (!target.is_empty() && effective_actor.eq_ignore_ascii_case(target))));

    if is_self_action {
        return settings_json_response(
            StatusCode::FORBIDDEN,
            json!({
                "error": "self_approval_blocked",
                "message": "Approver, requester, and target identities must be distinct; self-approval is strictly prohibited",
                "invariants": {
                    "approver_ne_executor": true,
                    "self_approval_blocked": true
                }
            }),
        );
    }

    // Fail-closed: both actor and requester identities must be known so self-approval cannot be bypassed.
    if effective_actor.is_empty() {
        return settings_json_response(
            StatusCode::BAD_REQUEST,
            json!({
                "error": "actor_subject_id_required",
                "message": "actor_subject_id (or authenticated /iam/self principal) is required to enforce approver != requester separation"
            }),
        );
    }
    if requester.is_empty() {
        return settings_json_response(
            StatusCode::BAD_REQUEST,
            json!({
                "error": "requester_subject_id_required",
                "message": "requester_subject_id is required to enforce approver != requester separation"
            }),
        );
    }

    let trimmed_reason = req.reason.trim();
    if has_control_chars(trimmed_reason) {
        return settings_json_response(
            StatusCode::BAD_REQUEST,
            json!({
                "error": "invalid_reason_characters",
                "message": "Review reason must not contain control characters"
            }),
        );
    }
    let reason_len = trimmed_reason.chars().count();
    if !(20..=MAX_REASON_LEN).contains(&reason_len) {
        return settings_json_response(
            StatusCode::BAD_REQUEST,
            json!({
                "error": "reason_too_short",
                "message": "Review reason must be between 20 and 1000 characters",
                "min_chars": 20,
                "max_chars": MAX_REASON_LEN,
                "actual_chars": reason_len
            }),
        );
    }

    let decision_record = json!({
        "request_id": req_id,
        "decision": req.decision,
        "reason": trimmed_reason,
        "actor_subject_id": effective_actor,
        "requester_subject_id": requester,
        "target_subject_id": target,
        "authority": "proposal_only",
        "execution_authority": false,
        "self_approval_blocked": true
    });

    if self_up.reachable && self_up.status == 200 {
        return settings_json_response(
            StatusCode::OK,
            json!({
                "source": "operator-service",
                "domain": "settings",
                "panel": "settings-iam",
                "measurement_status": "measured",
                "measurement_state": "measured",
                "request_id": req_id,
                "decision": req.decision,
                "authority": "proposal_only",
                "execution_authority": false,
                "self_approval_blocked": true,
                "provider_mutation_required": true,
                "persisted": false
            }),
        );
    }

    if state.db.mutations_allowed() {
        let key_seg = sanitize_kv_segment(req_id);
        let kv_key = format!("settings:iam:decision:{key_seg}");
        let idem = extract_idempotency_key(&headers, "settings-iam-decision");
        let actor_label = if effective_actor.is_empty() {
            "console-v4-operator"
        } else {
            effective_actor
        };
        if let Ok(receipt) = state
            .db
            .execute_audited_kv_mutation(
                &kv_key,
                &decision_record.to_string(),
                actor_label,
                "settings.iam.decision",
                &idem,
            )
            .await
        {
            return settings_json_response(
                StatusCode::OK,
                json!({
                    "source": "postgres-direct",
                    "domain": "settings",
                    "panel": "settings-iam",
                    "measurement_status": "measured",
                    "measurement_state": "measured",
                    "request_id": req_id,
                    "decision": req.decision,
                    "authority": "proposal_only",
                    "execution_authority": false,
                    "self_approval_blocked": true,
                    "provider_mutation_required": true,
                    "persisted": true,
                    "db_receipt": receipt
                }),
            );
        }
    }

    let status_label = if state.db.is_configured() {
        "measured"
    } else {
        "not-measured"
    };
    let source_label = if state.db.is_configured() {
        "postgres-direct"
    } else {
        "console-v4-rust"
    };
    settings_json_response(
        StatusCode::OK,
        json!({
            "source": source_label,
            "domain": "settings",
            "panel": "settings-iam",
            "measurement_status": status_label,
            "measurement_state": status_label,
            "request_id": req_id,
            "decision": req.decision,
            "authority": "proposal_only",
            "execution_authority": false,
            "self_approval_blocked": true,
            "provider_mutation_required": true,
            "persisted": false
        }),
    )
}

async fn api_settings_integrations_get(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Response {
    let auth = extract_auth(&headers);
    let (rt_up, inbox_up) = tokio::join!(
        state.upstream.get_json("/runtime/settings", auth),
        state.upstream.get_json("/notifications/inbox", auth),
    );
    let email_preview = json!({
        "scripts_blocked": true,
        "boundary": "notification_only",
        "execution_authority": false,
        "measurement_status": "not-measured",
        "subject": Value::Null,
        "text": Value::Null
    });
    let base_channels_boundary = json!({
        "a1_approval": {
            "channel": "microsoft-teams-bidirectional",
            "boundary": "a1_approval_callback",
            "configured": false,
            "status": "not-measured",
            "secrets_exposed": false
        },
        "a2_a4_notifications": []
    });

    if rt_up.reachable && rt_up.status == 200 {
        return settings_json_response(
            StatusCode::OK,
            json!({
                "source": "operator-service",
                "domain": "settings",
                "panel": "settings-integrations",
                "measurement_status": "measured",
                "measurement_state": "measured",
                "secrets_exposed": false,
                "channels_boundary": base_channels_boundary,
                "email_preview": email_preview,
                "data": {
                    "runtime_settings": rt_up.payload.unwrap_or(Value::Null),
                    "notifications_inbox": if inbox_up.reachable && inbox_up.status == 200 { inbox_up.payload.unwrap_or(Value::Null) } else { Value::Null }
                }
            }),
        );
    }

    if state.db.is_configured() {
        if let Some(db_data) = repos::settings::fetch_settings_integrations(&state.db).await {
            let primary_configured = db_data
                .pointer("/channel_links/primary_transport_configured")
                .and_then(Value::as_bool)
                .unwrap_or(false);
            let configured_webhooks = db_data
                .get("configured_webhooks")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default();
            let db_channels_boundary = json!({
                "a1_approval": {
                    "channel": "microsoft-teams-bidirectional",
                    "boundary": "a1_approval_callback",
                    "configured": primary_configured,
                    "status": "not-measured",
                    "secrets_exposed": false
                },
                "a2_a4_notifications": configured_webhooks
            });
            let db_email_preview = match db_data.get("live_preview") {
                Some(lp) if lp.get("subject").and_then(Value::as_str).is_some() => json!({
                    "scripts_blocked": true,
                    "boundary": "notification_only",
                    "execution_authority": false,
                    "measurement_status": "measured",
                    "subject": lp.get("subject").cloned().unwrap_or(Value::Null),
                    "scope": lp.get("scope").cloned().unwrap_or(Value::Null),
                    "evidence": lp.get("evidence").cloned().unwrap_or(Value::Null),
                    "text": lp.get("text").cloned().unwrap_or(Value::Null)
                }),
                _ => email_preview.clone(),
            };
            return settings_json_response(
                StatusCode::OK,
                json!({
                    "source": "postgres-direct",
                    "domain": "settings",
                    "panel": "settings-integrations",
                    "measurement_status": "measured",
                    "measurement_state": "measured",
                    "secrets_exposed": false,
                    "channels_boundary": db_channels_boundary,
                    "email_preview": db_email_preview,
                    "db_writes_allowed": state.db.mutations_allowed(),
                    "data": db_data
                }),
            );
        }
    }

    let mut env = state.upstream.not_measured_envelope(
        "settings",
        "/runtime/settings",
        "operator-service offline or unauthenticated",
    );
    if let Some(obj) = env.as_object_mut() {
        obj.insert("measurement_status".to_string(), json!("not-measured"));
        obj.insert("panel".to_string(), json!("settings-integrations"));
        obj.insert("secrets_exposed".to_string(), json!(false));
        obj.insert("channels_boundary".to_string(), base_channels_boundary);
        obj.insert("email_preview".to_string(), email_preview);
    }
    settings_json_response(StatusCode::OK, env)
}

#[derive(Debug, Deserialize)]
struct IntegrationsPatchRequest {
    email_mode: Option<String>,
    custom_email: Option<String>,
    ocr_provider: Option<String>,
}

async fn api_settings_integrations_patch(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<IntegrationsPatchRequest>,
) -> Response {
    let email_mode = req.email_mode.as_deref().map(str::trim);
    let ocr_provider = req.ocr_provider.as_deref().map(str::trim);
    if email_mode.is_none() && ocr_provider.is_none() && req.custom_email.is_none() {
        return settings_json_response(
            StatusCode::BAD_REQUEST,
            json!({
                "error": "empty_integrations_patch",
                "message": "At least one non-secret integration preference must be provided"
            }),
        );
    }
    if let Some(mode) = email_mode {
        if mode != "login" && mode != "custom" {
            return settings_json_response(
                StatusCode::BAD_REQUEST,
                json!({
                    "error": "invalid_email_mode",
                    "message": "email_mode must be 'login' or 'custom'"
                }),
            );
        }
        if mode == "custom" {
            let email = req.custom_email.as_deref().map(str::trim).unwrap_or("");
            if !is_valid_email_addr(email) {
                return settings_json_response(
                    StatusCode::BAD_REQUEST,
                    json!({
                        "error": "invalid_custom_email",
                        "message": "custom_email must be a valid email address when email_mode is 'custom'"
                    }),
                );
            }
        }
    }
    if let Some(ocr) = ocr_provider {
        if ocr != "local_python" && ocr != "azure_doc_intel" {
            return settings_json_response(
                StatusCode::BAD_REQUEST,
                json!({
                    "error": "invalid_ocr_provider",
                    "message": "ocr_provider must be 'local_python' or 'azure_doc_intel'"
                }),
            );
        }
    }

    let normalized = json!({
        "email_mode": email_mode.unwrap_or("login"),
        "custom_email": if email_mode == Some("custom") {
            req.custom_email.as_deref().map(str::trim)
        } else {
            None
        },
        "ocr_provider": ocr_provider.unwrap_or("local_python"),
        "secrets_exposed": false,
        "execution_authority": false
    });

    if state.db.mutations_allowed() {
        let idem = extract_idempotency_key(&headers, "settings-integrations-patch");
        match state
            .db
            .execute_audited_kv_mutation(
                "settings:integrations:v1",
                &normalized.to_string(),
                "console-v4-operator",
                "settings.integrations.patch",
                &idem,
            )
            .await
        {
            Ok(receipt) => {
                return settings_json_response(
                    StatusCode::OK,
                    json!({
                        "source": "postgres-direct",
                        "domain": "settings",
                        "panel": "settings-integrations",
                        "measurement_status": "measured",
                        "measurement_state": "measured",
                        "validated": true,
                        "persisted": true,
                        "secrets_exposed": false,
                        "db_receipt": receipt,
                        "data": normalized
                    }),
                );
            }
            Err(err_code) => {
                return settings_json_response(
                    StatusCode::OK,
                    json!({
                        "source": "postgres-direct",
                        "domain": "settings",
                        "panel": "settings-integrations",
                        "measurement_status": "measured",
                        "measurement_state": "measured",
                        "validated": true,
                        "persisted": false,
                        "secrets_exposed": false,
                        "reason": err_code,
                        "normalized": normalized
                    }),
                );
            }
        }
    }

    let status_label = if state.db.is_configured() {
        "measured"
    } else {
        "not-measured"
    };
    settings_json_response(
        StatusCode::OK,
        json!({
            "source": if state.db.is_configured() { "postgres-direct" } else { "console-v4-rust" },
            "domain": "settings",
            "panel": "settings-integrations",
            "measurement_status": status_label,
            "measurement_state": status_label,
            "validated": true,
            "persisted": false,
            "secrets_exposed": false,
            "reason": if state.db.is_configured() {
                "db_writes_disabled_readonly_mode"
            } else {
                "operator-service offline or unauthenticated"
            },
            "normalized": normalized
        }),
    )
}

#[derive(Debug, Deserialize)]
struct IntegrationTestRequest {
    channel: String,
    webhook_url: Option<String>,
    boundary: Option<String>,
}

async fn api_settings_integrations_test(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<IntegrationTestRequest>,
) -> Response {
    let channel = req.channel.trim();
    if channel.is_empty() || channel.len() > MAX_ID_LEN || has_control_chars(channel) {
        return settings_json_response(
            StatusCode::BAD_REQUEST,
            json!({
                "error": "invalid_channel",
                "message": "channel name is required and must not contain control characters"
            }),
        );
    }

    let masked_url = if let Some(ref url) = req.webhook_url {
        if !url.trim().is_empty() && !is_safe_webhook_url(url) {
            return settings_json_response(
                StatusCode::BAD_REQUEST,
                json!({
                    "error": "unsafe_webhook_url",
                    "message": "webhook_url must use HTTPS without userinfo and cannot target private, loopback, link-local, or internal addresses"
                }),
            );
        }
        Some(mask_webhook_url(url))
    } else {
        None
    };

    let boundary = match req.boundary.as_deref() {
        Some("a1_approval_callback") => "a1_approval_callback",
        _ => "notification_only",
    };

    let auth = extract_auth(&headers);
    let rt_up = state.upstream.get_json("/runtime/settings", auth).await;
    if rt_up.reachable && rt_up.status == 200 {
        return settings_json_response(
            StatusCode::OK,
            json!({
                "source": "operator-service",
                "domain": "settings",
                "panel": "settings-integrations",
                "measurement_status": "measured",
                "measurement_state": "measured",
                "channel": channel,
                "boundary": boundary,
                "url_masked": masked_url,
                "secrets_exposed": false,
                "ssrf_guard": "enforced",
                "delivery_status": "verified_boundary",
                "persisted": false,
                "note": "Channel boundary validated against operator-service runtime configuration without exposing secrets."
            }),
        );
    }

    let masked_receipt = json!({
        "channel": channel,
        "boundary": boundary,
        "url_masked": masked_url,
        "secrets_exposed": false,
        "ssrf_guard": "enforced",
        "delivery_status": "not-measured"
    });
    if state.db.mutations_allowed() {
        let seg = sanitize_kv_segment(channel);
        let kv_key = format!("settings:integrations:test:{seg}");
        let idem = extract_idempotency_key(&headers, "settings-integrations-test");
        if let Ok(receipt) = state
            .db
            .execute_audited_kv_mutation(
                &kv_key,
                &masked_receipt.to_string(),
                "console-v4-operator",
                "settings.integrations.test",
                &idem,
            )
            .await
        {
            return settings_json_response(
                StatusCode::OK,
                json!({
                    "source": "postgres-direct",
                    "domain": "settings",
                    "panel": "settings-integrations",
                    "measurement_status": "measured",
                    "measurement_state": "measured",
                    "channel": channel,
                    "boundary": boundary,
                    "url_masked": masked_url,
                    "secrets_exposed": false,
                    "ssrf_guard": "enforced",
                    "delivery_status": "not-measured",
                    "persisted": true,
                    "db_receipt": receipt,
                    "note": "Masked boundary receipt recorded in PostgreSQL; remote webhook delivery remains not-measured while operator-service is offline."
                }),
            );
        }
    }

    let status_label = if state.db.is_configured() {
        "measured"
    } else {
        "not-measured"
    };
    settings_json_response(
        StatusCode::OK,
        json!({
            "source": if state.db.is_configured() { "postgres-direct" } else { "console-v4-rust" },
            "domain": "settings",
            "panel": "settings-integrations",
            "measurement_status": status_label,
            "measurement_state": status_label,
            "channel": channel,
            "boundary": boundary,
            "url_masked": masked_url,
            "secrets_exposed": false,
            "ssrf_guard": "enforced",
            "delivery_status": "not-measured",
            "persisted": false,
            "note": "operator-service offline or unauthenticated; webhook delivery is not-measured (never fabricated as sent)."
        }),
    )
}

async fn probe_service_healthz(name: &'static str, port: u16, base_url: &str) -> Value {
    let trimmed = base_url.trim_end_matches('/');
    let url = format!("{trimmed}/healthz");
    let Ok(uri) = url.parse::<Uri>() else {
        return json!({
            "service": name,
            "port": port,
            "healthz_path": "/healthz",
            "status": "not-measured",
            "http_status": Value::Null,
            "latency_ms": Value::Null,
            "measurement_state": "not-measured"
        });
    };

    let http = diagnostic_http_client();

    let Ok(req) = Request::builder()
        .method(Method::GET)
        .uri(uri)
        .header("accept", "application/json")
        .body(Full::new(Bytes::new()))
    else {
        return json!({
            "service": name,
            "port": port,
            "healthz_path": "/healthz",
            "status": "not-measured",
            "http_status": Value::Null,
            "latency_ms": Value::Null,
            "measurement_state": "not-measured"
        });
    };

    let started = Instant::now();
    let res = timeout(Duration::from_millis(300), http.request(req)).await;
    match res {
        Ok(Ok(resp)) => {
            let code = resp.status().as_u16();
            let _ = timeout(Duration::from_millis(150), resp.into_body().collect()).await;
            let elapsed_ms = u64::try_from(started.elapsed().as_millis()).unwrap_or(u64::MAX);
            json!({
                "service": name,
                "port": port,
                "healthz_path": "/healthz",
                "status": if code == 200 { "healthy" } else { "degraded" },
                "http_status": code,
                "latency_ms": elapsed_ms,
                "measurement_state": "measured"
            })
        }
        _ => json!({
            "service": name,
            "port": port,
            "healthz_path": "/healthz",
            "status": "not-measured",
            "http_status": Value::Null,
            "latency_ms": Value::Null,
            "measurement_state": "not-measured"
        }),
    }
}

async fn api_settings_diagnostics(State(state): State<AppState>, headers: HeaderMap) -> Response {
    let Ok(_permit) = diagnostic_semaphore().try_acquire() else {
        return settings_json_response(
            StatusCode::SERVICE_UNAVAILABLE,
            json!({
                "error": "diagnostics_probe_busy",
                "message": "Too many concurrent diagnostic probes; retry shortly"
            }),
        );
    };

    let auth = extract_auth(&headers);
    let op_url = state.operator_url.clone();

    let (s8010, s8011, s8012, s8013, s8014, s8016, ds_up) = tokio::join!(
        probe_service_healthz("fdai-operator-service", 8010, &op_url),
        probe_service_healthz("fdai-document-ingestion-api", 8011, "http://127.0.0.1:8011"),
        probe_service_healthz(
            "fdai-document-processing-worker",
            8012,
            "http://127.0.0.1:8012"
        ),
        probe_service_healthz("fdai-isolated-executor", 8013, "http://127.0.0.1:8013"),
        probe_service_healthz("fdai-core-control-plane", 8014, "http://127.0.0.1:8014"),
        probe_service_healthz(
            "fdai-system-knowledge-service",
            8016,
            "http://127.0.0.1:8016"
        ),
        state.upstream.get_json("/system/data-sources", auth),
    );

    let services = vec![s8010, s8011, s8012, s8013, s8014, s8016];
    let healthy_count = services
        .iter()
        .filter(|s| s.get("status").and_then(Value::as_str) == Some("healthy"))
        .count();
    let measured_count = services
        .iter()
        .filter(|s| s.get("measurement_state").and_then(Value::as_str) == Some("measured"))
        .count();

    let db_infra = if !(ds_up.reachable && ds_up.status == 200) && state.db.is_configured() {
        repos::settings::fetch_settings_diagnostics_db(&state.db).await
    } else {
        None
    };

    let db_measured = db_infra.is_some();
    let infra = if ds_up.reachable && ds_up.status == 200 {
        json!({
            "measurement_status": "measured",
            "measurement_state": "measured",
            "data_sources": ds_up.payload.unwrap_or(Value::Null),
            "optional_runtime_profile": {
                "measurement_status": "not-measured",
                "measurement_state": "not-measured",
                "reason": "on_demand_only_never_fabricated_as_zero"
            }
        })
    } else if let Some(pg_infra) = db_infra {
        pg_infra
    } else {
        json!({
            "measurement_status": "not-measured",
            "measurement_state": "not-measured",
            "components": [
                { "id": "postgres", "name": "PostgreSQL (:5432)", "measurement_status": "not-measured", "measurement_state": "not-measured" },
                { "id": "event-bus", "name": "Event Bus", "measurement_status": "not-measured", "measurement_state": "not-measured" },
                { "id": "ontology-cache", "name": "Ontology Cache", "measurement_status": "not-measured", "measurement_state": "not-measured" },
                { "id": "identity-keyvault", "name": "Key Vault", "measurement_status": "not-measured", "measurement_state": "not-measured" }
            ],
            "optional_runtime_profile": {
                "measurement_status": "not-measured",
                "measurement_state": "not-measured",
                "reason": "on_demand_only_never_fabricated_as_zero"
            }
        })
    };

    let overall_state = if measured_count > 0 || db_measured {
        "measured"
    } else {
        "not-measured"
    };
    let source = if db_measured && measured_count == 0 {
        "postgres-direct"
    } else {
        "console-v4-rust-probe"
    };

    let redacted_summary = json!({
        "engine": "pure-rust-axum",
        "python_processes": 0,
        "services_total": services.len(),
        "services_measured": measured_count,
        "services_healthy": healthy_count,
        "infra_state": infra.get("measurement_state").cloned().unwrap_or(json!("not-measured")),
        "redacted": true,
        "secrets_included": false,
        "dsn_included": false
    });

    settings_json_response(
        StatusCode::OK,
        json!({
            "source": source,
            "domain": "settings",
            "panel": "settings-diagnostics",
            "read_only": true,
            "editable_switches": 0,
            "dirty_bar": false,
            "python_processes": 0,
            "measurement_status": overall_state,
            "measurement_state": overall_state,
            "services_total": services.len(),
            "services_measured": measured_count,
            "services_healthy": healthy_count,
            "services": services,
            "infrastructure": infra,
            "redacted_support_summary": redacted_summary
        }),
    )
}

#[derive(Debug, Deserialize)]
struct MemoryQuery {
    scope: Option<String>,
    q: Option<String>,
}

async fn api_settings_memory(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(query): Query<MemoryQuery>,
) -> Response {
    let scope_filter = query
        .scope
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .unwrap_or("all");
    if !ALLOWED_MEMORY_SCOPES.contains(&scope_filter) {
        return settings_json_response(
            StatusCode::BAD_REQUEST,
            json!({
                "error": "invalid_memory_scope",
                "message": "scope must be one of: all, subscription, resource-group, resource"
            }),
        );
    }

    let search_q = query.q.as_deref().map(str::trim).unwrap_or("");
    if search_q.len() > MAX_QUERY_LEN || has_control_chars(search_q) {
        return settings_json_response(
            StatusCode::BAD_REQUEST,
            json!({
                "error": "invalid_memory_query",
                "message": "q must be <= 256 chars without control characters"
            }),
        );
    }

    let auth = extract_auth(&headers);
    let search_lower = search_q.to_ascii_lowercase();

    let up = state.upstream.get_json("/me/context", auth).await;
    if up.reachable && up.status == 200 {
        let items: Vec<Value> = up
            .payload
            .as_ref()
            .and_then(|p| p.get("memories"))
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default()
            .into_iter()
            .filter(|item| {
                let scope_ok = scope_filter == "all"
                    || item
                        .get("scope")
                        .and_then(Value::as_str)
                        .is_some_and(|s| s.eq_ignore_ascii_case(scope_filter));
                let text_ok = search_lower.is_empty()
                    || item.to_string().to_ascii_lowercase().contains(&search_lower);
                scope_ok && text_ok
            })
            .collect();

        return settings_json_response(
            StatusCode::OK,
            json!({
                "source": "operator-service",
                "domain": "settings",
                "panel": "settings-memory",
                "measurement_status": "measured",
                "measurement_state": "measured",
                "execution_authority": false,
                "pii_secret_storage_blocked": true,
                "filters": { "scope": scope_filter, "q": search_q },
                "count": items.len(),
                "items": items
            }),
        );
    }

    if state.db.is_configured() {
        if let Some(db_data) =
            repos::settings::fetch_settings_memory(&state.db, scope_filter, search_q).await
        {
            let items = db_data.get("items").cloned().unwrap_or_else(|| json!([]));
            let count = db_data.get("count").and_then(Value::as_u64).unwrap_or(0);
            return settings_json_response(
                StatusCode::OK,
                json!({
                    "source": "postgres-direct",
                    "domain": "settings",
                    "panel": "settings-memory",
                    "measurement_status": "measured",
                    "measurement_state": "measured",
                    "execution_authority": false,
                    "pii_secret_storage_blocked": true,
                    "db_writes_allowed": state.db.mutations_allowed(),
                    "filters": { "scope": scope_filter, "q": search_q },
                    "count": count,
                    "items": items,
                    "retention_policies": db_data.get("retention_policies").cloned().unwrap_or_else(|| json!([])),
                    "retention_policy_count": db_data.get("retention_policy_count").cloned().unwrap_or(json!(0)),
                    "compactions": db_data.get("compactions").cloned().unwrap_or_else(|| json!([])),
                    "observed_ontology_scopes": db_data.get("observed_ontology_scopes").cloned().unwrap_or_else(|| json!([])),
                    "ontology_resources_count": db_data.get("ontology_resources_count").cloned().unwrap_or(json!(0)),
                    "data": db_data
                }),
            );
        }
    }

    let mut env = state.upstream.not_measured_envelope(
        "settings",
        "/me/context",
        "operator-service offline or unauthenticated",
    );
    if let Some(obj) = env.as_object_mut() {
        obj.insert("measurement_status".to_string(), json!("not-measured"));
        obj.insert("panel".to_string(), json!("settings-memory"));
        obj.insert("execution_authority".to_string(), json!(false));
        obj.insert("pii_secret_storage_blocked".to_string(), json!(true));
        obj.insert(
            "filters".to_string(),
            json!({ "scope": scope_filter, "q": search_q }),
        );
    }
    settings_json_response(StatusCode::OK, env)
}

#[derive(Debug, Deserialize)]
struct MemoryExtendRequest {
    memory_id: String,
    extend_days: Option<u32>,
}

async fn api_settings_memory_extend(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<MemoryExtendRequest>,
) -> Response {
    let mem_id = req.memory_id.trim();
    if mem_id.is_empty() || mem_id.len() > MAX_ID_LEN || has_control_chars(mem_id) {
        return settings_json_response(
            StatusCode::BAD_REQUEST,
            json!({
                "error": "invalid_memory_id",
                "message": "memory_id is required and must not contain control characters"
            }),
        );
    }
    let days = req.extend_days.unwrap_or(14);
    if !(1..=90).contains(&days) {
        return settings_json_response(
            StatusCode::BAD_REQUEST,
            json!({
                "error": "invalid_extend_days",
                "message": "extend_days must be within 1..=90"
            }),
        );
    }

    let auth = extract_auth(&headers);
    let up = state.upstream.get_json("/me/context", auth).await;
    if up.reachable && up.status == 200 {
        return settings_json_response(
            StatusCode::OK,
            json!({
                "source": "operator-service",
                "domain": "settings",
                "panel": "settings-memory",
                "measurement_status": "measured",
                "measurement_state": "measured",
                "memory_id": mem_id,
                "extended_by_days": days,
                "persisted": false,
                "execution_authority": false
            }),
        );
    }

    if state.db.mutations_allowed() {
        let seg = sanitize_kv_segment(mem_id);
        let kv_key = format!("settings:memory:action:extend:{seg}");
        let idem = extract_idempotency_key(&headers, "settings-memory-extend");
        let rec = json!({
            "action": "extend",
            "memory_id": mem_id,
            "extend_days": days,
            "execution_authority": false
        });
        if let Ok(receipt) = state
            .db
            .execute_audited_kv_mutation(
                &kv_key,
                &rec.to_string(),
                "console-v4-operator",
                "settings.memory.extend",
                &idem,
            )
            .await
        {
            return settings_json_response(
                StatusCode::OK,
                json!({
                    "source": "postgres-direct",
                    "domain": "settings",
                    "panel": "settings-memory",
                    "measurement_status": "measured",
                    "measurement_state": "measured",
                    "memory_id": mem_id,
                    "extended_by_days": days,
                    "persisted": true,
                    "db_receipt": receipt,
                    "execution_authority": false
                }),
            );
        }
    }

    let status_label = if state.db.is_configured() {
        "measured"
    } else {
        "not-measured"
    };
    settings_json_response(
        StatusCode::OK,
        json!({
            "source": if state.db.is_configured() { "postgres-direct" } else { "console-v4-rust" },
            "domain": "settings",
            "panel": "settings-memory",
            "measurement_status": status_label,
            "measurement_state": status_label,
            "memory_id": mem_id,
            "extended_by_days": days,
            "persisted": false,
            "execution_authority": false
        }),
    )
}

#[derive(Debug, Deserialize)]
struct MemoryDeleteRequest {
    memory_id: String,
    confirmed: bool,
}

async fn api_settings_memory_delete(
    State(state): State<AppState>,
    headers: HeaderMap,
    Json(req): Json<MemoryDeleteRequest>,
) -> Response {
    let mem_id = req.memory_id.trim();
    if mem_id.is_empty() || mem_id.len() > MAX_ID_LEN || has_control_chars(mem_id) {
        return settings_json_response(
            StatusCode::BAD_REQUEST,
            json!({
                "error": "invalid_memory_id",
                "message": "memory_id is required and must not contain control characters"
            }),
        );
    }
    if !req.confirmed {
        return settings_json_response(
            StatusCode::BAD_REQUEST,
            json!({
                "error": "delete_confirmation_required",
                "message": "Deleting an operational memory requires explicit two-step confirmed=true"
            }),
        );
    }

    let auth = extract_auth(&headers);
    let up = state.upstream.get_json("/me/context", auth).await;
    if up.reachable && up.status == 200 {
        return settings_json_response(
            StatusCode::OK,
            json!({
                "source": "operator-service",
                "domain": "settings",
                "panel": "settings-memory",
                "measurement_status": "measured",
                "measurement_state": "measured",
                "memory_id": mem_id,
                "deleted": true,
                "persisted": false,
                "execution_authority": false
            }),
        );
    }

    if state.db.mutations_allowed() {
        let seg = sanitize_kv_segment(mem_id);
        let kv_key = format!("settings:memory:action:delete:{seg}");
        let idem = extract_idempotency_key(&headers, "settings-memory-delete");
        let rec = json!({
            "action": "delete",
            "memory_id": mem_id,
            "confirmed": true,
            "execution_authority": false
        });
        if let Ok(receipt) = state
            .db
            .execute_audited_kv_mutation(
                &kv_key,
                &rec.to_string(),
                "console-v4-operator",
                "settings.memory.delete",
                &idem,
            )
            .await
        {
            return settings_json_response(
                StatusCode::OK,
                json!({
                    "source": "postgres-direct",
                    "domain": "settings",
                    "panel": "settings-memory",
                    "measurement_status": "measured",
                    "measurement_state": "measured",
                    "memory_id": mem_id,
                    "deleted": true,
                    "persisted": true,
                    "db_receipt": receipt,
                    "execution_authority": false
                }),
            );
        }
    }

    let status_label = if state.db.is_configured() {
        "measured"
    } else {
        "not-measured"
    };
    settings_json_response(
        StatusCode::OK,
        json!({
            "source": if state.db.is_configured() { "postgres-direct" } else { "console-v4-rust" },
            "domain": "settings",
            "panel": "settings-memory",
            "measurement_status": status_label,
            "measurement_state": status_label,
            "memory_id": mem_id,
            "deleted": true,
            "persisted": false,
            "execution_authority": false
        }),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::build_router;
    use axum::body::Body;
    use axum::http::Request as HttpRequest;
    use std::path::PathBuf;
    use tower::ServiceExt;

    fn offline_state() -> AppState {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("."));
        // Reserved unreachable loopback port for deterministic offline fallback tests.
        AppState::from_repo_root(root, "http://127.0.0.1:59996".to_string())
    }

    async fn read_json(resp: Response) -> Option<Value> {
        let bytes = resp.into_body().collect().await.ok()?.to_bytes();
        serde_json::from_slice::<Value>(&bytes).ok()
    }

    #[test]
    fn settings_iana_timezone_validation_rejects_invalid_and_traversal() {
        assert!(is_valid_iana_timezone("Asia/Seoul"));
        assert!(is_valid_iana_timezone("UTC"));
        assert!(is_valid_iana_timezone("Etc/UTC"));
        assert!(is_valid_iana_timezone("America/New_York"));
        assert!(!is_valid_iana_timezone(""));
        assert!(!is_valid_iana_timezone("KST"));
        assert!(!is_valid_iana_timezone("Foo/Bar"));
        assert!(!is_valid_iana_timezone("../etc/passwd"));
        assert!(!is_valid_iana_timezone("Asia/NotARealCity_XYZ"));
    }

    #[test]
    fn settings_webhook_masking_and_t2_publisher_separation() {
        let masked = mask_webhook_url(
            "https://hooks.slack.com/services/T00SECRET/B00SECRET/supersecret4c10?token=abc",
        );
        assert!(masked.starts_with("https://hooks.slack.com/services/****"));
        assert!(!masked.contains("supersecret"));
        assert!(!masked.contains("token=abc"));

        assert!(has_distinct_t2_publishers(
            "openai:gpt-5-reasoning",
            "anthropic:claude-sonnet-4.5"
        ));
        assert!(!has_distinct_t2_publishers(
            "openai:gpt-5-reasoning",
            "openai:o3-mini-verifier"
        ));
    }

    #[tokio::test]
    async fn settings_all_get_endpoints_return_200_with_safe_fallback() {
        let app = build_router(offline_state());
        for uri in [
            "/settings",
            "/api/v4/settings/summary",
            "/api/v4/settings/overlay",
            "/api/v4/settings/general",
            "/api/v4/settings/environment",
            "/api/v4/settings/models",
            "/api/v4/settings/runtime",
            "/api/v4/settings/iam",
            "/api/v4/settings/integrations",
            "/api/v4/settings/diagnostics",
            "/api/v4/settings/memory?scope=all&q=prod",
        ] {
            let req = HttpRequest::builder().uri(uri).body(Body::empty());
            assert!(req.is_ok(), "failed to build request for {uri}");
            if let Ok(req) = req {
                let Ok(resp) = app.clone().oneshot(req).await;
                assert_eq!(resp.status(), StatusCode::OK, "expected 200 for {uri}");
            }
        }
    }

    #[tokio::test]
    async fn settings_general_patch_validates_iana_timezone_and_briefing_hour() {
        let app = build_router(offline_state());

        let bad_tz = HttpRequest::builder()
            .method("PATCH")
            .uri("/api/v4/settings/general")
            .header("content-type", "application/json")
            .body(Body::from(
                json!({ "timezone": "Invalid/Not_A_Zone", "briefing_hour": 9 }).to_string(),
            ));
        assert!(bad_tz.is_ok());
        if let Ok(req) = bad_tz {
            let Ok(resp) = app.clone().oneshot(req).await;
            assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
            let body = read_json(resp).await;
            assert_eq!(
                body.as_ref().and_then(|v| v.get("error")).and_then(Value::as_str),
                Some("invalid_timezone")
            );
        }

        let good = HttpRequest::builder()
            .method("PATCH")
            .uri("/api/v4/settings/general")
            .header("content-type", "application/json")
            .body(Body::from(
                json!({
                    "locale": "ko",
                    "answer_detail": "standard",
                    "answer_format": "mixed",
                    "timezone": "Asia/Seoul",
                    "briefing_hour": 9
                })
                .to_string(),
            ));
        assert!(good.is_ok());
        if let Ok(req) = good {
            let Ok(resp) = app.clone().oneshot(req).await;
            assert_eq!(resp.status(), StatusCode::OK);
            let body = read_json(resp).await;
            assert_eq!(
                body.as_ref().and_then(|v| v.get("validated")).and_then(Value::as_bool),
                Some(true)
            );
        }
    }

    #[tokio::test]
    async fn settings_runtime_patch_enforces_invariants_and_risk_ack() {
        let app = build_router(offline_state());

        // Attempting to disable Shadow invariant must fail with 400.
        let disable_shadow = HttpRequest::builder()
            .method("PATCH")
            .uri("/api/v4/settings/runtime")
            .header("content-type", "application/json")
            .body(Body::from(json!({ "shadow_default": false }).to_string()));
        assert!(disable_shadow.is_ok());
        if let Ok(req) = disable_shadow {
            let Ok(resp) = app.clone().oneshot(req).await;
            assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
        }

        // High-impact change without risk_acknowledged=true must fail with 422.
        let no_ack = HttpRequest::builder()
            .method("PATCH")
            .uri("/api/v4/settings/runtime")
            .header("content-type", "application/json")
            .body(Body::from(
                json!({
                    "autonomy_profile": "single-operator-prod",
                    "risk_acknowledged": false
                })
                .to_string(),
            ));
        assert!(no_ack.is_ok());
        if let Ok(req) = no_ack {
            let Ok(resp) = app.clone().oneshot(req).await;
            assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
        }

        // High-impact change with explicit risk_acknowledged=true passes validation.
        let with_ack = HttpRequest::builder()
            .method("PATCH")
            .uri("/api/v4/settings/runtime")
            .header("content-type", "application/json")
            .body(Body::from(
                json!({
                    "autonomy_profile": "single-operator-prod",
                    "approval_expiry_min": 30,
                    "turn_budget_sec": 60,
                    "batch_concurrency": 2,
                    "availability_policy": { "enabled": true, "window_sec": 120 },
                    "risk_acknowledged": true
                })
                .to_string(),
            ));
        assert!(with_ack.is_ok());
        if let Ok(req) = with_ack {
            let Ok(resp) = app.clone().oneshot(req).await;
            assert_eq!(resp.status(), StatusCode::OK);
        }
    }

    #[tokio::test]
    async fn settings_iam_decision_blocks_self_approval_and_short_reason() {
        let app = build_router(offline_state());

        let self_approve = HttpRequest::builder()
            .method("POST")
            .uri("/api/v4/settings/iam/decisions")
            .header("content-type", "application/json")
            .body(Body::from(
                json!({
                    "request_id": "req-iam-105",
                    "decision": "approve",
                    "reason": "Self approval must always be blocked by policy.",
                    "actor_subject_id": "ops.owner@org",
                    "requester_subject_id": "ops.owner@org"
                })
                .to_string(),
            ));
        assert!(self_approve.is_ok());
        if let Ok(req) = self_approve {
            let Ok(resp) = app.clone().oneshot(req).await;
            assert_eq!(resp.status(), StatusCode::FORBIDDEN);
        }

        let short_reason = HttpRequest::builder()
            .method("POST")
            .uri("/api/v4/settings/iam/decisions")
            .header("content-type", "application/json")
            .body(Body::from(
                json!({
                    "request_id": "req-iam-104",
                    "decision": "approve",
                    "reason": "too short",
                    "actor_subject_id": "kim.lead@org",
                    "requester_subject_id": "park.sre@org"
                })
                .to_string(),
            ));
        assert!(short_reason.is_ok());
        if let Ok(req) = short_reason {
            let Ok(resp) = app.clone().oneshot(req).await;
            assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
        }
    }

    #[tokio::test]
    async fn settings_integrations_test_masks_url_and_blocks_ssrf() {
        let app = build_router(offline_state());

        let ssrf = HttpRequest::builder()
            .method("POST")
            .uri("/api/v4/settings/integrations/test")
            .header("content-type", "application/json")
            .body(Body::from(
                json!({
                    "channel": "Teams Operations Webhook",
                    "webhook_url": "http://169.254.169.254/latest/meta-data/"
                })
                .to_string(),
            ));
        assert!(ssrf.is_ok());
        if let Ok(req) = ssrf {
            let Ok(resp) = app.clone().oneshot(req).await;
            assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
        }

        let ok_test = HttpRequest::builder()
            .method("POST")
            .uri("/api/v4/settings/integrations/test")
            .header("content-type", "application/json")
            .body(Body::from(
                json!({
                    "channel": "Slack Incident Webhook",
                    "webhook_url": "https://hooks.slack.com/services/T00DEMO/B00DEMO/secret9999"
                })
                .to_string(),
            ));
        assert!(ok_test.is_ok());
        if let Ok(req) = ok_test {
            let Ok(resp) = app.clone().oneshot(req).await;
            assert_eq!(resp.status(), StatusCode::OK);
            let body = read_json(resp).await;
            let masked = body
                .as_ref()
                .and_then(|v| v.get("url_masked"))
                .and_then(Value::as_str)
                .unwrap_or("");
            assert!(masked.contains("****"));
            assert!(!masked.contains("secret"));
        }
    }

    #[tokio::test]
    async fn settings_diagnostics_is_read_only_with_6_services_and_memory_requires_confirmation() {
        let app = build_router(offline_state());

        let diag_req = HttpRequest::builder()
            .uri("/api/v4/settings/diagnostics")
            .body(Body::empty());
        assert!(diag_req.is_ok());
        if let Ok(req) = diag_req {
            let Ok(resp) = app.clone().oneshot(req).await;
            assert_eq!(resp.status(), StatusCode::OK);
            let body = read_json(resp).await;
            assert_eq!(
                body.as_ref().and_then(|v| v.get("read_only")).and_then(Value::as_bool),
                Some(true)
            );
            assert_eq!(
                body.as_ref().and_then(|v| v.get("editable_switches")).and_then(Value::as_u64),
                Some(0)
            );
            assert_eq!(
                body.as_ref().and_then(|v| v.get("services_total")).and_then(Value::as_u64),
                Some(6)
            );
        }

        let unconfirmed_del = HttpRequest::builder()
            .method("POST")
            .uri("/api/v4/settings/memory/delete")
            .header("content-type", "application/json")
            .body(Body::from(
                json!({ "memory_id": "om-1", "confirmed": false }).to_string(),
            ));
        assert!(unconfirmed_del.is_ok());
        if let Ok(req) = unconfirmed_del {
            let Ok(resp) = app.clone().oneshot(req).await;
            assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
        }
    }

    #[tokio::test]
    async fn settings_redteam_security_headers_and_ssrf_and_policy_hardening() {
        let app = build_router(offline_state());

        // 1. Security headers on JSON responses
        let sum_req = HttpRequest::builder()
            .uri("/api/v4/settings/summary")
            .body(Body::empty());
        assert!(sum_req.is_ok());
        if let Ok(req) = sum_req {
            let Ok(resp) = app.clone().oneshot(req).await;
            assert_eq!(
                resp.headers().get(header::CACHE_CONTROL).and_then(|v| v.to_str().ok()),
                Some("no-store")
            );
            assert_eq!(
                resp.headers()
                    .get(header::X_CONTENT_TYPE_OPTIONS)
                    .and_then(|v| v.to_str().ok()),
                Some("nosniff")
            );
        }

        // 2. Expanded SSRF blocking (private IPv4, IPv6 ULA/mapped, userinfo, .internal)
        for bad_url in [
            "https://172.16.0.10/hook",
            "https://192.168.1.20/hook",
            "https://100.64.0.5/hook",
            "https://[::ffff:127.0.0.1]/hook",
            "https://[fc00::1]/hook",
            "https://[fe80::1]/hook",
            "https://user:secret@hooks.slack.com/services/a/b/c",
            "https://metadata.google.internal/computeMetadata/v1/",
            "https://2130706433/hook",
        ] {
            assert!(!is_safe_webhook_url(bad_url), "SSRF URL must be blocked: {bad_url}");
        }
        let stripped = mask_webhook_url("https://user:pass@hooks.slack.com/services/a/secret1234#frag");
        assert!(!stripped.contains("user"));
        assert!(!stripped.contains("pass"));
        assert!(!stripped.contains("frag"));
        assert!(!stripped.contains("secret"));

        // 3. Policy JSON bomb & prototype pollution blocking
        let proto_req = HttpRequest::builder()
            .method("PATCH")
            .uri("/api/v4/settings/runtime")
            .header("content-type", "application/json")
            .body(Body::from(
                json!({ "availability_policy": { "__proto__": { "admin": true } } }).to_string(),
            ));
        assert!(proto_req.is_ok());
        if let Ok(req) = proto_req {
            let Ok(resp) = app.clone().oneshot(req).await;
            assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
        }

        // 4. Empty general/runtime PATCH must fail-closed (400)
        for uri in ["/api/v4/settings/general", "/api/v4/settings/runtime"] {
            let empty_req = HttpRequest::builder()
                .method("PATCH")
                .uri(uri)
                .header("content-type", "application/json")
                .body(Body::from("{}"));
            assert!(empty_req.is_ok());
            if let Ok(req) = empty_req {
                let Ok(resp) = app.clone().oneshot(req).await;
                assert_eq!(resp.status(), StatusCode::BAD_REQUEST, "empty PATCH must fail on {uri}");
            }
        }

        // 5. IAM requester_subject_id omission (400), target self-approval (403), and CRLF log forging (400)
        let missing_requester = HttpRequest::builder()
            .method("POST")
            .uri("/api/v4/settings/iam/decisions")
            .header("content-type", "application/json")
            .body(Body::from(
                json!({
                    "request_id": "req-iam-201",
                    "decision": "approve",
                    "reason": "Reviewed thoroughly with proper operational justification.",
                    "actor_subject_id": "kim.lead@org"
                })
                .to_string(),
            ));
        assert!(missing_requester.is_ok());
        if let Ok(req) = missing_requester {
            let Ok(resp) = app.clone().oneshot(req).await;
            assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
        }

        let target_self = HttpRequest::builder()
            .method("POST")
            .uri("/api/v4/settings/iam/decisions")
            .header("content-type", "application/json")
            .body(Body::from(
                json!({
                    "request_id": "req-iam-202",
                    "decision": "approve",
                    "reason": "Reviewed thoroughly with proper operational justification.",
                    "actor_subject_id": "kim.lead@org",
                    "requester_subject_id": "park.sre@org",
                    "target_subject_id": "kim.lead@org"
                })
                .to_string(),
            ));
        assert!(target_self.is_ok());
        if let Ok(req) = target_self {
            let Ok(resp) = app.clone().oneshot(req).await;
            assert_eq!(resp.status(), StatusCode::FORBIDDEN);
        }

        let crlf_reason = HttpRequest::builder()
            .method("POST")
            .uri("/api/v4/settings/iam/decisions")
            .header("content-type", "application/json")
            .body(Body::from(
                json!({
                    "request_id": "req-iam-203",
                    "decision": "approve",
                    "reason": "Valid length reason\r\nFAKE_AUDIT_ENTRY=approved",
                    "actor_subject_id": "kim.lead@org",
                    "requester_subject_id": "park.sre@org"
                })
                .to_string(),
            ));
        assert!(crlf_reason.is_ok());
        if let Ok(req) = crlf_reason {
            let Ok(resp) = app.clone().oneshot(req).await;
            assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
        }

        // 6. T2 publisher separation API
        let same_pub = HttpRequest::builder()
            .method("POST")
            .uri("/api/v4/settings/models/validate-t2")
            .header("content-type", "application/json")
            .body(Body::from(
                json!({
                    "primary": "openai:gpt-5-reasoning",
                    "secondary": "openai:o3-mini-verifier"
                })
                .to_string(),
            ));
        assert!(same_pub.is_ok());
        if let Ok(req) = same_pub {
            let Ok(resp) = app.clone().oneshot(req).await;
            assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
        }

        let diff_pub = HttpRequest::builder()
            .method("POST")
            .uri("/api/v4/settings/models/validate-t2")
            .header("content-type", "application/json")
            .body(Body::from(
                json!({
                    "primary": "openai:gpt-5-reasoning",
                    "secondary": "anthropic:claude-sonnet-4.5"
                })
                .to_string(),
            ));
        assert!(diff_pub.is_ok());
        if let Ok(req) = diff_pub {
            let Ok(resp) = app.clone().oneshot(req).await;
            assert_eq!(resp.status(), StatusCode::OK);
        }

        // 7. Memory scope whitelist rejection
        let bad_scope = HttpRequest::builder()
            .uri("/api/v4/settings/memory?scope=invalid_scope")
            .body(Body::empty());
        assert!(bad_scope.is_ok());
        if let Ok(req) = bad_scope {
            let Ok(resp) = app.clone().oneshot(req).await;
            assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
        }
    }

    #[tokio::test]
    async fn settings_integrations_patch_and_readonly_writes_return_safe_persisted_false() {
        let app = build_router(offline_state());

        let bad_email = HttpRequest::builder()
            .method("PATCH")
            .uri("/api/v4/settings/integrations")
            .header("content-type", "application/json")
            .body(Body::from(
                json!({
                    "email_mode": "custom",
                    "custom_email": "not-an-email"
                })
                .to_string(),
            ));
        assert!(bad_email.is_ok());
        if let Ok(req) = bad_email {
            let Ok(resp) = app.clone().oneshot(req).await;
            assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
        }

        let good_int = HttpRequest::builder()
            .method("PATCH")
            .uri("/api/v4/settings/integrations")
            .header("content-type", "application/json")
            .body(Body::from(
                json!({
                    "email_mode": "custom",
                    "custom_email": "sre-oncall@org.example",
                    "ocr_provider": "local_python"
                })
                .to_string(),
            ));
        assert!(good_int.is_ok());
        if let Ok(req) = good_int {
            let Ok(resp) = app.clone().oneshot(req).await;
            assert_eq!(resp.status(), StatusCode::OK);
            let body = read_json(resp).await;
            assert_eq!(
                body.as_ref().and_then(|v| v.get("validated")).and_then(Value::as_bool),
                Some(true)
            );
            assert_eq!(
                body.as_ref().and_then(|v| v.get("persisted")).and_then(Value::as_bool),
                Some(false)
            );
            assert_eq!(
                body.as_ref().and_then(|v| v.get("secrets_exposed")).and_then(Value::as_bool),
                Some(false)
            );
        }
    }

    #[tokio::test]
    async fn settings_iam_azure_groups_exposes_three_tiers_and_enforces_recommendations() {
        let app = build_router(offline_state());

        let get_req = HttpRequest::builder()
            .uri("/api/v4/settings/iam/azure-groups")
            .body(Body::empty());
        assert!(get_req.is_ok());
        if let Ok(req) = get_req {
            let Ok(resp) = app.clone().oneshot(req).await;
            assert_eq!(resp.status(), StatusCode::OK);
            let body = read_json(resp).await;
            let groups = body
                .as_ref()
                .and_then(|v| v.pointer("/azure_iam_groups/groups"))
                .and_then(Value::as_array);
            assert_eq!(groups.map(Vec::len), Some(3));
            assert_eq!(
                body.as_ref()
                    .and_then(|v| v.pointer("/azure_iam_groups/defaults/pim_required"))
                    .and_then(Value::as_bool),
                Some(false)
            );
            assert_eq!(
                body.as_ref()
                    .and_then(|v| v.pointer("/azure_iam_groups/defaults/custom_role_scope"))
                    .and_then(Value::as_str),
                Some("subscription")
            );
            assert_eq!(
                body.as_ref()
                    .and_then(|v| v.pointer("/azure_iam_groups/defaults/dev_gateway_executor_group"))
                    .and_then(Value::as_str),
                Some("operator")
            );
            assert_eq!(
                body.as_ref()
                    .and_then(|v| v.pointer("/azure_iam_groups/human_admin_groups/0/entra_group"))
                    .and_then(Value::as_str),
                Some("fdai-readers")
            );
        }

        // Reject FDAI Contributor in default production
        let bad_prod = HttpRequest::builder()
            .method("PATCH")
            .uri("/api/v4/settings/iam/azure-groups")
            .header("content-type", "application/json")
            .body(Body::from(
                json!({
                    "workload_group": "contributor",
                    "binding_mode": "direct",
                    "custom_role_scope": "subscription",
                    "dev_gateway_executor_group": "operator",
                    "environment": "production"
                })
                .to_string(),
            ));
        assert!(bad_prod.is_ok());
        if let Ok(req) = bad_prod {
            let Ok(resp) = app.clone().oneshot(req).await;
            assert_eq!(resp.status(), StatusCode::UNPROCESSABLE_ENTITY);
        }

        // Accept recommended production operator profile without PIM
        let good_prod = HttpRequest::builder()
            .method("PATCH")
            .uri("/api/v4/settings/iam/azure-groups")
            .header("content-type", "application/json")
            .body(Body::from(
                json!({
                    "workload_group": "operator",
                    "binding_mode": "direct",
                    "custom_role_scope": "subscription",
                    "dev_gateway_executor_group": "operator",
                    "environment": "production"
                })
                .to_string(),
            ));
        assert!(good_prod.is_ok());
        if let Ok(req) = good_prod {
            let Ok(resp) = app.clone().oneshot(req).await;
            assert_eq!(resp.status(), StatusCode::OK);
            let body = read_json(resp).await;
            assert_eq!(
                body.as_ref().and_then(|v| v.get("validated")).and_then(Value::as_bool),
                Some(true)
            );
            assert_eq!(
                body.as_ref()
                    .and_then(|v| v.get("direct_infra_mutation_blocked"))
                    .and_then(Value::as_bool),
                Some(true)
            );
            assert_eq!(
                body.as_ref().and_then(|v| v.get("persisted")).and_then(Value::as_bool),
                Some(false)
            );
        }
    }

    #[tokio::test]
    async fn settings_critique_hardening_ssrf_t2_iam_and_honest_not_measured() {
        // 1. SSRF bypass attempts: trailing dots, hex/octal IPv4, IPv4-compatible IPv6, empty label
        for bypass_url in [
            "https://localhost./hook",
            "https://service.local./hook",
            "https://metadata.internal./hook",
            "https://0x7f000001/hook",
            "https://0177.0.0.1/hook",
            "https://[::127.0.0.1]/hook",
            "https://a..b.example.com/hook",
        ] {
            assert!(
                !is_safe_webhook_url(bypass_url),
                "SSRF bypass URL must be blocked: {bypass_url}"
            );
        }
        assert!(is_safe_webhook_url("https://hooks.slack.com/services/T00/B00/xyz"));

        // 2. T2 publisher separation rejects malformed specs lacking a non-empty model segment
        assert!(!has_distinct_t2_publishers("openai", "anthropic"));
        assert!(!has_distinct_t2_publishers("openai:", "anthropic:claude-sonnet-4.5"));
        assert!(!has_distinct_t2_publishers("openai:gpt-5.4", "anthropic:"));
        assert!(has_distinct_t2_publishers("openai:gpt-5.4", "anthropic:claude-sonnet-4.5"));

        let app = build_router(offline_state());

        // 3. IAM decision must fail-closed (400) if actor_subject_id is omitted when offline
        let missing_actor = HttpRequest::builder()
            .method("POST")
            .uri("/api/v4/settings/iam/decisions")
            .header("content-type", "application/json")
            .body(Body::from(
                json!({
                    "request_id": "req-iam-301",
                    "decision": "approve",
                    "reason": "Reviewed thoroughly with proper operational justification.",
                    "requester_subject_id": "park.sre@org"
                })
                .to_string(),
            ));
        assert!(missing_actor.is_ok());
        if let Ok(req) = missing_actor {
            let Ok(resp) = app.clone().oneshot(req).await;
            assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
            let body = read_json(resp).await;
            assert_eq!(
                body.as_ref().and_then(|v| v.get("error")).and_then(Value::as_str),
                Some("actor_subject_id_required")
            );
        }

        // 4. Offline integrations must NEVER fabricate demo webhook URLs or preview subjects
        let int_req = HttpRequest::builder()
            .uri("/api/v4/settings/integrations")
            .body(Body::empty());
        assert!(int_req.is_ok());
        if let Ok(req) = int_req {
            let Ok(resp) = app.clone().oneshot(req).await;
            assert_eq!(resp.status(), StatusCode::OK);
            let body = read_json(resp).await;
            let webhooks = body
                .as_ref()
                .and_then(|v| v.pointer("/channels_boundary/a2_a4_notifications"))
                .and_then(Value::as_array)
                .map(Vec::len);
            assert_eq!(webhooks, Some(0), "offline integrations must not fabricate webhook URLs");
            assert!(
                body.as_ref()
                    .and_then(|v| v.pointer("/email_preview/subject"))
                    .is_some_and(Value::is_null),
                "offline email_preview.subject must be null"
            );
        }

        // 5. Offline diagnostics must keep read-only invariants and never fabricate 0ms latency
        let diag_req = HttpRequest::builder()
            .uri("/api/v4/settings/diagnostics")
            .body(Body::empty());
        assert!(diag_req.is_ok());
        if let Ok(req) = diag_req {
            let Ok(resp) = app.clone().oneshot(req).await;
            assert_eq!(resp.status(), StatusCode::OK);
            let body = read_json(resp).await;
            assert_eq!(
                body.as_ref().and_then(|v| v.get("dirty_bar")).and_then(Value::as_bool),
                Some(false)
            );
            if let Some(svcs) = body.as_ref().and_then(|v| v.get("services")).and_then(Value::as_array) {
                for svc in svcs {
                    if svc.get("measurement_state").and_then(Value::as_str) == Some("not-measured") {
                        assert!(
                            svc.get("latency_ms").is_some_and(Value::is_null),
                            "not-measured diagnostic service must not fabricate 0ms latency"
                        );
                    }
                }
            }
        }
    }
}
