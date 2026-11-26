//! Domain 7: 실험실 (`labs`, 6 panels).
//! Owned by the `labs` domain stream.
//! Pure-Rust Axum handlers enforcing `lab-sandbox` isolation, strict input validation,
//! security headers, and `not-measured` fallback without fabricating zeros.

use axum::{
    extract::{Query, State},
    http::{header, HeaderMap, HeaderName, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    routing::get,
    Json, Router,
};
use serde::Deserialize;
use serde_json::{json, Map, Value};

use crate::{
    repos::labs as labs_repo,
    shell::{finalize_v4_html, html_response},
    upstream::UpstreamOutcome,
    AppState,
};

const TEMPLATE: &str = include_str!("../../templates/labs.html");

const PANELS: [&str; 6] = [
    "labs",
    "aks-commerce",
    "assurance-twin",
    "forecast-learning",
    "conversation-assurance",
    "context-selection-comparisons",
];

const SANDBOX_SCOPE: &str = "lab-sandbox";
const SCHEMA_VERSION: &str = "v4.labs.1";
const DEFAULT_AKS_SERVICE_ID: &str = "order-fulfillment";
const MAX_REVIEW_KEY_LEN: usize = 128;
const MAX_AUTH_HEADER_LEN: usize = 4096;

pub fn panel_ids() -> &'static [&'static str] {
    &PANELS
}

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/labs", get(page_labs))
        .route("/api/v4/labs/summary", get(api_labs_summary))
        .route("/api/v4/labs/aks-commerce", get(api_labs_aks_commerce))
        .route("/api/v4/labs/assurance-twin", get(api_labs_assurance_twin))
        .route(
            "/api/v4/labs/forecast-learning",
            get(api_labs_forecast_learning),
        )
        .route(
            "/api/v4/labs/conversation-assurance",
            get(api_labs_conversation_assurance),
        )
        .route(
            "/api/v4/labs/context-comparisons",
            get(api_labs_context_comparisons),
        )
}

#[derive(Debug, Default, Deserialize)]
struct AksCommerceQuery {
    service_id: Option<String>,
}

#[derive(Debug, Default, Deserialize)]
struct AssuranceTwinQuery {
    review: Option<String>,
}

fn lab_isolation_boundary() -> Value {
    json!({
        "dev_only": true,
        "sandbox_scope": SANDBOX_SCOPE,
        "production_subscription_link": "blocked",
        "mutation_authority": "none",
        "side_effects": 0
    })
}

fn lab_modules_catalog() -> Value {
    json!([
        {
            "id": "aks-commerce",
            "api": "/api/v4/labs/aks-commerce",
            "upstream": "/aks-commerce/overview",
            "sandbox_scope": SANDBOX_SCOPE
        },
        {
            "id": "assurance-twin",
            "api": "/api/v4/labs/assurance-twin",
            "upstream": "/assurance-twin/posture",
            "sandbox_scope": SANDBOX_SCOPE
        },
        {
            "id": "forecast-learning",
            "api": "/api/v4/labs/forecast-learning",
            "upstream": "/forecast-learning",
            "sandbox_scope": SANDBOX_SCOPE
        },
        {
            "id": "conversation-assurance",
            "api": "/api/v4/labs/conversation-assurance",
            "upstream": "/conversation-assurance",
            "sandbox_scope": SANDBOX_SCOPE
        },
        {
            "id": "context-selection-comparisons",
            "api": "/api/v4/labs/context-comparisons",
            "upstream": "/context-selection-comparisons",
            "sandbox_scope": SANDBOX_SCOPE
        }
    ])
}

fn extract_auth(headers: &HeaderMap) -> Option<&str> {
    let raw = headers
        .get(header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok())?
        .trim();
    if raw.is_empty() || raw.len() > MAX_AUTH_HEADER_LEN {
        return None;
    }
    if raw.bytes().any(|b| b < 0x20 || b == 0x7F) {
        return None;
    }
    Some(raw)
}

fn parse_aks_service_id(raw: Option<&str>) -> Result<&'static str, &'static str> {
    match raw.map(str::trim) {
        None | Some("") | Some("order-fulfillment") => Ok(DEFAULT_AKS_SERVICE_ID),
        Some("catalog-browse") => Ok("catalog-browse"),
        Some(_) => Err("unsupported service_id; allowed values: order-fulfillment, catalog-browse"),
    }
}

fn validate_review_key(raw: &str) -> Result<&str, &'static str> {
    let trimmed = raw.trim();
    if trimmed.len() > MAX_REVIEW_KEY_LEN {
        return Err("review key exceeds maximum length of 128 bytes");
    }
    if trimmed.bytes().any(|b| b < 0x20 || b == 0x7F) {
        return Err("review key contains disallowed control characters");
    }
    if trimmed.contains("..") || trimmed.contains('\\') {
        return Err("review key contains disallowed path traversal sequence");
    }
    Ok(trimmed)
}

fn percent_encode_query_component(input: &str) -> String {
    const HEX: &[u8; 16] = b"0123456789ABCDEF";
    let mut out = String::with_capacity(input.len());
    for byte in input.bytes() {
        let is_unreserved = byte.is_ascii_alphanumeric()
            || matches!(byte, b'-' | b'_' | b'.' | b'~');
        if is_unreserved {
            out.push(char::from(byte));
        } else {
            out.push('%');
            out.push(char::from(HEX[usize::from(byte >> 4)]));
            out.push(char::from(HEX[usize::from(byte & 0x0F)]));
        }
    }
    out
}

fn outcome_reason(up: &UpstreamOutcome) -> String {
    if !up.reachable {
        return "operator-service offline or unreachable".to_string();
    }
    match up.status {
        401 | 403 => format!("operator-service unauthenticated or forbidden (HTTP {})", up.status),
        404 | 503 => format!("operator-service projection unavailable (HTTP {})", up.status),
        200 => "operator-service returned non-JSON payload".to_string(),
        code => format!("operator-service returned HTTP {code}"),
    }
}

fn outcome_reason_code(up: &UpstreamOutcome) -> &'static str {
    if !up.reachable {
        return "upstream_unreachable";
    }
    match up.status {
        401 | 403 => "upstream_unauthenticated",
        404 | 503 => "projection_unavailable",
        200 => "invalid_upstream_json",
        _ => "upstream_http_error",
    }
}

fn json_lab_response(status: StatusCode, payload: Value) -> Response {
    let mut resp = (status, Json(payload)).into_response();
    let headers = resp.headers_mut();
    headers.insert(header::CACHE_CONTROL, HeaderValue::from_static("no-store"));
    headers.insert(
        header::X_CONTENT_TYPE_OPTIONS,
        HeaderValue::from_static("nosniff"),
    );
    headers.insert(
        HeaderName::from_static("x-fdai-sandbox-scope"),
        HeaderValue::from_static(SANDBOX_SCOPE),
    );
    headers.insert(
        HeaderName::from_static("x-fdai-mutation-authority"),
        HeaderValue::from_static("none"),
    );
    // Keep canonical casing marker in documentation and tests: X-FDAI-Sandbox-Scope
    resp
}

fn build_bad_request_response(panel: &str, endpoint: &str, message: &str) -> Response {
    json_lab_response(
        StatusCode::BAD_REQUEST,
        json!({
            "source": "console-v4-rust",
            "schema_version": SCHEMA_VERSION,
            "domain": "labs",
            "panel": panel,
            "endpoint": endpoint,
            "measurement_state": "not-measured",
            "measurement_status": "not-measured",
            "reason_code": "invalid_query_parameter",
            "reason": message,
            "isolation": lab_isolation_boundary(),
            "data": Value::Null
        }),
    )
}

fn build_measured_response_with_source(
    source: &str,
    panel: &str,
    endpoint: &str,
    data: Value,
    extra: Vec<(&str, Value)>,
) -> Response {
    let mut obj = Map::new();
    obj.insert("source".to_string(), json!(source));
    obj.insert("schema_version".to_string(), json!(SCHEMA_VERSION));
    obj.insert("domain".to_string(), json!("labs"));
    obj.insert("panel".to_string(), json!(panel));
    obj.insert("endpoint".to_string(), json!(endpoint));
    obj.insert("measurement_state".to_string(), json!("measured"));
    obj.insert("measurement_status".to_string(), json!("measured"));
    obj.insert("isolation".to_string(), lab_isolation_boundary());
    for (k, v) in extra {
        obj.insert(k.to_string(), v);
    }
    obj.insert("data".to_string(), data);
    json_lab_response(StatusCode::OK, Value::Object(obj))
}

fn build_measured_response(
    panel: &str,
    endpoint: &str,
    data: Value,
    extra: Vec<(&str, Value)>,
) -> Response {
    build_measured_response_with_source("operator-service", panel, endpoint, data, extra)
}

fn build_not_measured_response(
    state: &AppState,
    panel: &str,
    endpoint: &str,
    up: &UpstreamOutcome,
    extra: Vec<(&str, Value)>,
) -> Response {
    let reason = outcome_reason(up);
    let mut envelope = state.upstream.not_measured_envelope("labs", endpoint, &reason);
    if let Value::Object(ref mut obj) = envelope {
        obj.insert("schema_version".to_string(), json!(SCHEMA_VERSION));
        obj.insert("panel".to_string(), json!(panel));
        obj.insert("measurement_status".to_string(), json!("not-measured"));
        obj.insert("reason_code".to_string(), json!(outcome_reason_code(up)));
        obj.insert("isolation".to_string(), lab_isolation_boundary());
        obj.insert("upstream_reachable".to_string(), json!(up.reachable));
        obj.insert("upstream_status".to_string(), json!(up.status));
        for (k, v) in extra {
            obj.insert(k.to_string(), v);
        }
    }
    json_lab_response(StatusCode::OK, envelope)
}

fn is_db_measured(val: &Value) -> bool {
    val.get("measurement_status")
        .and_then(Value::as_str)
        .is_some_and(|s| s == "measured")
}

async fn proxy_lab_endpoint_with_db<F, Fut>(
    state: &AppState,
    headers: &HeaderMap,
    panel: &str,
    endpoint: &str,
    extra: Vec<(&str, Value)>,
    db_fallback: F,
) -> Response
where
    F: FnOnce() -> Fut,
    Fut: std::future::Future<Output = Value>,
{
    let auth = extract_auth(headers);
    let up = state.upstream.get_json(endpoint, auth).await;
    if up.reachable && up.status == 200 {
        if let Some(payload) = up.payload {
            return build_measured_response(panel, endpoint, payload, extra);
        }
    }
    if state.db.is_configured() {
        let db_val = db_fallback().await;
        if is_db_measured(&db_val) {
            return build_measured_response_with_source(
                "postgres-direct",
                panel,
                endpoint,
                db_val,
                extra,
            );
        }
    }
    build_not_measured_response(state, panel, endpoint, &up, extra)
}

async fn page_labs(State(state): State<AppState>) -> Response {
    let html = finalize_v4_html(
        TEMPLATE,
        "labs",
        "labs",
        &state.operator_url,
        json!({
            "panels": PANELS,
            "isolatedSandbox": true,
            "sandboxScope": SANDBOX_SCOPE,
            "schemaVersion": SCHEMA_VERSION,
            "apiBase": "/api/v4/labs"
        }),
    );
    html_response(html)
}

async fn api_labs_summary(State(state): State<AppState>, headers: HeaderMap) -> Response {
    proxy_lab_endpoint_with_db(
        &state,
        &headers,
        "labs",
        "/system/data-sources",
        vec![
            ("panel_count", json!(PANELS.len())),
            ("modules", lab_modules_catalog()),
        ],
        || labs_repo::fetch_labs_summary(&state.db),
    )
    .await
}

async fn api_labs_aks_commerce(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(query): Query<AksCommerceQuery>,
) -> Response {
    let service_id = match parse_aks_service_id(query.service_id.as_deref()) {
        Ok(id) => id,
        Err(msg) => {
            return build_bad_request_response("aks-commerce", "/aks-commerce/overview", msg);
        }
    };
    let endpoint = format!("/aks-commerce/overview?service_id={service_id}");
    proxy_lab_endpoint_with_db(
        &state,
        &headers,
        "aks-commerce",
        &endpoint,
        vec![
            ("service_id", json!(service_id)),
            (
                "supported_services",
                json!(["order-fulfillment", "catalog-browse"]),
            ),
        ],
        || labs_repo::fetch_aks_commerce(&state.db, service_id),
    )
    .await
}

async fn api_labs_assurance_twin(
    State(state): State<AppState>,
    headers: HeaderMap,
    Query(query): Query<AssuranceTwinQuery>,
) -> Response {
    let auth = extract_auth(&headers);
    let review_key = match query.review.as_deref() {
        Some(raw) if !raw.trim().is_empty() => match validate_review_key(raw) {
            Ok(valid) => Some(valid),
            Err(msg) => {
                return build_bad_request_response("assurance-twin", "/assurance-twin/review", msg);
            }
        },
        _ => None,
    };

    let (posture_up, reviews_up) = tokio::join!(
        state.upstream.get_json("/assurance-twin/posture", auth),
        state.upstream.get_json("/assurance-twin/reviews", auth),
    );

    let detail_up = match review_key {
        Some(key) => {
            let encoded = percent_encode_query_component(key);
            let path = format!("/assurance-twin/review?review={encoded}");
            Some((path.clone(), state.upstream.get_json(&path, auth).await))
        }
        None => None,
    };

    let posture_data = if posture_up.reachable && posture_up.status == 200 {
        posture_up.payload.clone()
    } else {
        None
    };
    let reviews_data = if reviews_up.reachable && reviews_up.status == 200 {
        reviews_up.payload.clone()
    } else {
        None
    };
    let detail_data = detail_up.as_ref().and_then(|(_, outcome)| {
        if outcome.reachable && outcome.status == 200 {
            outcome.payload.clone()
        } else {
            None
        }
    });

    if posture_data.is_some() || reviews_data.is_some() || detail_data.is_some() {
        let mut partial_gaps = Vec::new();
        if posture_data.is_none() {
            partial_gaps.push(json!({
                "surface": "posture",
                "endpoint": "/assurance-twin/posture",
                "status": posture_up.status,
                "reason_code": outcome_reason_code(&posture_up),
                "reason": outcome_reason(&posture_up)
            }));
        }
        if reviews_data.is_none() {
            partial_gaps.push(json!({
                "surface": "reviews",
                "endpoint": "/assurance-twin/reviews",
                "status": reviews_up.status,
                "reason_code": outcome_reason_code(&reviews_up),
                "reason": outcome_reason(&reviews_up)
            }));
        }
        if let Some((path, ref outcome)) = detail_up {
            if detail_data.is_none() {
                partial_gaps.push(json!({
                    "surface": "detail",
                    "endpoint": path,
                    "status": outcome.status,
                    "reason_code": outcome_reason_code(outcome),
                    "reason": outcome_reason(outcome)
                }));
            }
        }

        return build_measured_response(
            "assurance-twin",
            "/assurance-twin/posture",
            json!({
                "posture": posture_data,
                "reviews": reviews_data,
                "detail": detail_data
            }),
            vec![
                ("review_key", json!(review_key)),
                ("partial_gaps", Value::Array(partial_gaps)),
            ],
        );
    }

    if state.db.is_configured() {
        let db_val = labs_repo::fetch_assurance_twin(&state.db, review_key).await;
        if is_db_measured(&db_val) {
            return build_measured_response_with_source(
                "postgres-direct",
                "assurance-twin",
                "/assurance-twin/posture",
                db_val,
                vec![
                    ("review_key", json!(review_key)),
                    ("partial_gaps", json!([])),
                ],
            );
        }
    }

    build_not_measured_response(
        &state,
        "assurance-twin",
        "/assurance-twin/posture",
        &posture_up,
        vec![("review_key", json!(review_key))],
    )
}

async fn api_labs_forecast_learning(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Response {
    proxy_lab_endpoint_with_db(
        &state,
        &headers,
        "forecast-learning",
        "/forecast-learning",
        vec![],
        || labs_repo::fetch_forecast_learning(&state.db),
    )
    .await
}

async fn api_labs_conversation_assurance(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Response {
    proxy_lab_endpoint_with_db(
        &state,
        &headers,
        "conversation-assurance",
        "/conversation-assurance",
        vec![],
        || labs_repo::fetch_conversation_assurance(&state.db),
    )
    .await
}

async fn api_labs_context_comparisons(
    State(state): State<AppState>,
    headers: HeaderMap,
) -> Response {
    proxy_lab_endpoint_with_db(
        &state,
        &headers,
        "context-selection-comparisons",
        "/context-selection-comparisons",
        vec![],
        || labs_repo::fetch_context_comparisons(&state.db),
    )
    .await
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

    fn repo_root() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("."))
    }

    fn test_state(operator_url: &str) -> AppState {
        let mut st = AppState::from_repo_root(repo_root(), operator_url.to_string());
        st.db = crate::db::DbHandle::from_dsn_opt(None, false);
        st
    }

    fn test_state_with_dsn(operator_url: &str, dsn: &str) -> AppState {
        let mut st = AppState::from_repo_root(repo_root(), operator_url.to_string());
        st.db = crate::db::DbHandle::from_dsn_opt(Some(dsn), false);
        st
    }

    async fn get_raw(app: &Router, uri: &str) -> Option<(StatusCode, HeaderMap, String)> {
        let req = Request::builder().uri(uri).body(Body::empty()).ok()?;
        let resp = app.clone().oneshot(req).await.ok()?;
        let status = resp.status();
        let headers = resp.headers().clone();
        let bytes = resp.into_body().collect().await.ok()?.to_bytes();
        let text = String::from_utf8(bytes.to_vec()).ok()?;
        Some((status, headers, text))
    }

    async fn get_json_val(app: &Router, uri: &str) -> Option<(StatusCode, HeaderMap, Value)> {
        let (status, headers, text) = get_raw(app, uri).await?;
        let val = serde_json::from_str::<Value>(&text).ok()?;
        Some((status, headers, val))
    }

    #[test]
    fn labs_panel_ids_match_exact_six_panels() {
        assert_eq!(
            panel_ids(),
            &[
                "labs",
                "aks-commerce",
                "assurance-twin",
                "forecast-learning",
                "conversation-assurance",
                "context-selection-comparisons",
            ]
        );
    }

    #[test]
    fn labs_percent_encode_preserves_safe_chars_and_escapes_special_bytes() {
        assert_eq!(
            percent_encode_query_component("owner/infra#412?a=1&b=2"),
            "owner%2Finfra%23412%3Fa%3D1%26b%3D2"
        );
        assert_eq!(
            percent_encode_query_component("review-key_1.0~ok"),
            "review-key_1.0~ok"
        );
    }

    #[test]
    fn labs_parse_aks_service_id_and_validate_review_key_enforce_guards() {
        assert_eq!(
            parse_aks_service_id(Some("catalog-browse")),
            Ok("catalog-browse")
        );
        assert_eq!(
            parse_aks_service_id(Some("order-fulfillment")),
            Ok("order-fulfillment")
        );
        assert_eq!(parse_aks_service_id(None), Ok("order-fulfillment"));
        assert!(parse_aks_service_id(Some("../evil?x=1")).is_err());

        assert_eq!(
            validate_review_key("owner/infra#412"),
            Ok("owner/infra#412")
        );
        assert!(validate_review_key("../etc/passwd").is_err());
        assert!(validate_review_key("owner\\infra#1").is_err());
        assert!(validate_review_key("owner\n#1").is_err());
        let too_long = "a".repeat(MAX_REVIEW_KEY_LEN + 1);
        assert!(validate_review_key(&too_long).is_err());
    }

    #[tokio::test]
    async fn labs_page_renders_labs_as_default_panel_with_sandbox_bootstrap() {
        let app = build_router(test_state("http://127.0.0.1:1"));
        let res = get_raw(&app, "/labs").await;
        assert!(res.is_some(), "GET /labs failed");
        if let Some((status, _headers, html)) = res {
            assert_eq!(status, StatusCode::OK);
            assert!(
                html.contains("\"defaultPanel\":\"labs\""),
                "bootstrap defaultPanel must be labs"
            );
            assert!(
                html.contains("\"isolatedSandbox\":true"),
                "bootstrap must mark isolatedSandbox=true"
            );
            assert!(
                html.contains("lab-sandbox"),
                "HTML must declare lab-sandbox isolation boundary"
            );
            assert!(html.contains("data-panel-id=\"labs\""));
            assert!(
                html.contains("id=\"slLiveBoundaryBar\""),
                "/labs template must include #slLiveBoundaryBar for live pulse telemetry"
            );
            assert!(
                html.contains("fdai:live-pulse"),
                "/labs template must subscribe to fdai:live-pulse SSE events"
            );
            assert!(
                html.contains("fdai:data-mode-change"),
                "/labs template must subscribe to fdai:data-mode-change for Live/Sample switching"
            );
            assert!(
                html.contains("fdaiV4Humanize"),
                "/labs template must integrate shared fdaiV4Humanize adapter"
            );
            assert!(
                html.contains("fdaiV4Selection"),
                "/labs template must integrate shared fdaiV4Selection deep-link API"
            );
            assert!(
                html.contains("drawer-tech-details"),
                "/labs template must isolate technical identifiers inside collapsible drawer-tech-details"
            );
            assert!(
                !html.contains(".innerHTML"),
                "/labs template must not assign innerHTML (XSS guard)"
            );
            assert!(
                !html.contains("data-panel-id=\"settings-general\""),
                "/labs template must not mount settings-general as first panel"
            );
            assert!(
                html.contains("<title>FDAI 운영 콘솔 — 실험실</title>"),
                "/labs page title must be standardized to FDAI 운영 콘솔 — 실험실"
            );
            let ssr_markup = TEMPLATE.split("<script").next().unwrap_or("");
            for leaked in [
                "lab-run-1126-01",
                "owner/infra#412",
                "Rev #4812",
                "ECE 0.031",
                "turn_8841c",
                "eval-ctx-1125-04",
                "hybrid-vector-v2",
                "복구 19초",
                "8 / 8 (평균 19초)",
                "120문항",
                "94.2% (162 / 172)",
                "4,820 tok",
                "orders-api",
                "compute.vm-scale-set",
                "Pure-Rust",
            ] {
                assert!(
                    !ssr_markup.contains(leaked),
                    "/labs SSR markup must not leak sample literal `{leaked}` in default Live mode"
                );
            }
        }
    }

    #[tokio::test]
    async fn labs_rejects_invalid_service_id_and_unsafe_review_keys_with_400() {
        let app = build_router(test_state("http://127.0.0.1:1"));
        let long_review = "r".repeat(MAX_REVIEW_KEY_LEN + 8);
        let bad_uris = [
            "/api/v4/labs/aks-commerce?service_id=unknown-service".to_string(),
            "/api/v4/labs/assurance-twin?review=..%2Fsecret".to_string(),
            "/api/v4/labs/assurance-twin?review=owner%5Cbad".to_string(),
            format!("/api/v4/labs/assurance-twin?review={long_review}"),
        ];
        for uri in bad_uris {
            let res = get_json_val(&app, &uri).await;
            assert!(res.is_some(), "GET {uri} did not return JSON");
            if let Some((status, headers, body)) = res {
                assert_eq!(status, StatusCode::BAD_REQUEST, "expected 400 on {uri}");
                assert_eq!(body["reason_code"], "invalid_query_parameter");
                assert_eq!(body["isolation"]["sandbox_scope"], "lab-sandbox");
                assert_eq!(
                    headers
                        .get("x-fdai-sandbox-scope")
                        .and_then(|v| v.to_str().ok()),
                    Some("lab-sandbox")
                );
                assert_eq!(
                    headers
                        .get(header::CACHE_CONTROL)
                        .and_then(|v| v.to_str().ok()),
                    Some("no-store")
                );
            }
        }
    }

    #[tokio::test]
    async fn labs_all_six_apis_return_not_measured_isolation_and_security_headers_when_offline() {
        let app = build_router(test_state("http://127.0.0.1:1"));
        for (uri, expected_panel) in [
            ("/api/v4/labs/summary", "labs"),
            ("/api/v4/labs/aks-commerce", "aks-commerce"),
            (
                "/api/v4/labs/aks-commerce?service_id=catalog-browse",
                "aks-commerce",
            ),
            ("/api/v4/labs/assurance-twin", "assurance-twin"),
            (
                "/api/v4/labs/assurance-twin?review=owner/infra%23412",
                "assurance-twin",
            ),
            ("/api/v4/labs/forecast-learning", "forecast-learning"),
            (
                "/api/v4/labs/conversation-assurance",
                "conversation-assurance",
            ),
            (
                "/api/v4/labs/context-comparisons",
                "context-selection-comparisons",
            ),
        ] {
            let res = get_json_val(&app, uri).await;
            assert!(res.is_some(), "GET {uri} did not return valid JSON");
            if let Some((status, headers, body)) = res {
                assert_eq!(status, StatusCode::OK, "expected 200 on {uri}");
                assert_eq!(body["domain"], "labs", "domain mismatch on {uri}");
                assert_eq!(body["panel"], expected_panel, "panel mismatch on {uri}");
                assert_eq!(body["schema_version"], SCHEMA_VERSION);
                assert_eq!(
                    body["measurement_state"], "not-measured",
                    "offline upstream must return not-measured on {uri}"
                );
                assert_eq!(body["reason_code"], "upstream_unreachable");
                assert!(
                    body["data"].is_null(),
                    "not-measured response must keep data=null on {uri}"
                );
                assert_eq!(body["isolation"]["dev_only"], true);
                assert_eq!(body["isolation"]["sandbox_scope"], "lab-sandbox");
                assert_eq!(body["isolation"]["production_subscription_link"], "blocked");
                assert_eq!(body["isolation"]["mutation_authority"], "none");
                assert_eq!(body["isolation"]["side_effects"], 0);
                assert_eq!(
                    headers
                        .get(header::CACHE_CONTROL)
                        .and_then(|v| v.to_str().ok()),
                    Some("no-store")
                );
                assert_eq!(
                    headers
                        .get(header::X_CONTENT_TYPE_OPTIONS)
                        .and_then(|v| v.to_str().ok()),
                    Some("nosniff")
                );
                assert_eq!(
                    headers
                        .get("x-fdai-sandbox-scope")
                        .and_then(|v| v.to_str().ok()),
                    Some("lab-sandbox")
                );
                assert_eq!(
                    headers
                        .get("x-fdai-mutation-authority")
                        .and_then(|v| v.to_str().ok()),
                    Some("none")
                );
            }
        }
    }

    #[tokio::test]
    async fn labs_all_six_apis_return_measured_when_mock_upstream_responds_200() {
        let mock_upstream = Router::new()
            .route(
                "/system/data-sources",
                get(|| async { Json(json!({ "sources": ["arg", "aks"], "healthy": 2 })) }),
            )
            .route(
                "/aks-commerce/overview",
                get(|Query(q): Query<AksCommerceQuery>| async move {
                    Json(json!({
                        "service_id": q.service_id.unwrap_or_else(|| "order-fulfillment".to_string()),
                        "status": "healthy"
                    }))
                }),
            )
            .route(
                "/assurance-twin/posture",
                get(|| async { Json(json!({ "revision": "graph-rev-4812", "reports": 3 })) }),
            )
            .route(
                "/assurance-twin/reviews",
                get(|| async { Json(json!({ "reviews": [{ "key": "owner/infra#412" }] })) }),
            )
            .route(
                "/assurance-twin/review",
                get(|Query(q): Query<AssuranceTwinQuery>| async move {
                    Json(json!({ "review": q.review, "verdict": "needs_review" }))
                }),
            )
            .route(
                "/forecast-learning",
                get(|| async { Json(json!({ "ece": 0.031, "closure_completeness": 0.942 })) }),
            )
            .route(
                "/conversation-assurance",
                get(|| async { Json(json!({ "total_turns": 120, "hard_zero_fail": 0 })) }),
            )
            .route(
                "/context-selection-comparisons",
                get(|| async { Json(json!({ "evaluations": 16, "omissions": 0 })) }),
            );

        let listener_res = tokio::net::TcpListener::bind("127.0.0.1:0").await;
        assert!(listener_res.is_ok(), "failed to bind ephemeral mock upstream");
        if let Ok(listener) = listener_res {
            let addr_res = listener.local_addr();
            assert!(addr_res.is_ok(), "failed to read mock upstream addr");
            if let Ok(addr) = addr_res {
                let server_handle = tokio::spawn(async move {
                    let _ = axum::serve(listener, mock_upstream).await;
                });

                let app = build_router(test_state(&format!("http://{addr}")));

                let checks = [
                    ("/api/v4/labs/summary", "labs"),
                    (
                        "/api/v4/labs/aks-commerce?service_id=catalog-browse",
                        "aks-commerce",
                    ),
                    (
                        "/api/v4/labs/assurance-twin?review=owner/infra%23412",
                        "assurance-twin",
                    ),
                    ("/api/v4/labs/forecast-learning", "forecast-learning"),
                    (
                        "/api/v4/labs/conversation-assurance",
                        "conversation-assurance",
                    ),
                    (
                        "/api/v4/labs/context-comparisons",
                        "context-selection-comparisons",
                    ),
                ];

                for (uri, expected_panel) in checks {
                    let res = get_json_val(&app, uri).await;
                    assert!(res.is_some(), "GET {uri} failed against mock upstream");
                    if let Some((status, headers, body)) = res {
                        assert_eq!(status, StatusCode::OK, "non-200 on {uri}");
                        assert_eq!(body["source"], "operator-service");
                        assert_eq!(body["schema_version"], SCHEMA_VERSION);
                        assert_eq!(body["panel"], expected_panel);
                        assert_eq!(body["measurement_state"], "measured");
                        assert_eq!(body["isolation"]["sandbox_scope"], "lab-sandbox");
                        assert!(!body["data"].is_null(), "measured data null on {uri}");
                        assert_eq!(
                            headers
                                .get("x-fdai-sandbox-scope")
                                .and_then(|v| v.to_str().ok()),
                            Some("lab-sandbox")
                        );
                    }
                }

                if let Some((_, _, aks_body)) =
                    get_json_val(&app, "/api/v4/labs/aks-commerce?service_id=catalog-browse").await
                {
                    assert_eq!(aks_body["service_id"], "catalog-browse");
                    assert_eq!(aks_body["data"]["service_id"], "catalog-browse");
                }
                if let Some((_, _, twin_body)) =
                    get_json_val(&app, "/api/v4/labs/assurance-twin?review=owner/infra%23412").await
                {
                    assert_eq!(twin_body["data"]["posture"]["revision"], "graph-rev-4812");
                    assert_eq!(twin_body["data"]["detail"]["review"], "owner/infra#412");
                    assert_eq!(twin_body["data"]["detail"]["verdict"], "needs_review");
                }

                server_handle.abort();
            }
        }
    }

    #[tokio::test]
    async fn labs_all_six_apis_fall_back_honestly_when_db_dsn_unreachable() {
        let app = build_router(test_state_with_dsn(
            "http://127.0.0.1:1",
            "postgresql://fdai:fdai@127.0.0.1:1/fdai",
        ));
        for (uri, expected_panel) in [
            ("/api/v4/labs/summary", "labs"),
            ("/api/v4/labs/aks-commerce", "aks-commerce"),
            ("/api/v4/labs/assurance-twin", "assurance-twin"),
            ("/api/v4/labs/forecast-learning", "forecast-learning"),
            (
                "/api/v4/labs/conversation-assurance",
                "conversation-assurance",
            ),
            (
                "/api/v4/labs/context-comparisons",
                "context-selection-comparisons",
            ),
        ] {
            let res = get_json_val(&app, uri).await;
            assert!(res.is_some(), "GET {uri} did not return valid JSON");
            if let Some((status, headers, body)) = res {
                assert_eq!(status, StatusCode::OK, "expected 200 on {uri}");
                assert_eq!(body["panel"], expected_panel);
                assert_eq!(body["measurement_state"], "not-measured");
                assert_eq!(body["measurement_status"], "not-measured");
                assert!(body["data"].is_null());
                assert_eq!(body["isolation"]["sandbox_scope"], "lab-sandbox");
                assert_eq!(
                    headers
                        .get("x-fdai-sandbox-scope")
                        .and_then(|v| v.to_str().ok()),
                    Some("lab-sandbox")
                );
            }
        }
    }

    #[tokio::test]
    async fn labs_postgres_direct_envelope_preserves_sandbox_isolation_and_status_fields() {
        let resp = build_measured_response_with_source(
            "postgres-direct",
            "labs",
            "/system/data-sources",
            json!({ "measurement_status": "measured", "transition_batch_count": 885 }),
            vec![("panel_count", json!(6))],
        );
        assert_eq!(resp.status(), StatusCode::OK);
        let headers = resp.headers().clone();
        let bytes = resp
            .into_body()
            .collect()
            .await
            .map(|c| c.to_bytes())
            .unwrap_or_default();
        let parsed = serde_json::from_slice::<Value>(&bytes).ok();
        assert!(parsed.is_some());
        if let Some(body) = parsed {
            assert_eq!(body["source"], "postgres-direct");
            assert_eq!(body["measurement_state"], "measured");
            assert_eq!(body["measurement_status"], "measured");
            assert_eq!(body["isolation"]["sandbox_scope"], "lab-sandbox");
            assert_eq!(body["isolation"]["mutation_authority"], "none");
            assert_eq!(body["data"]["transition_batch_count"], 885);
            assert_eq!(
                headers
                    .get("x-fdai-sandbox-scope")
                    .and_then(|v| v.to_str().ok()),
                Some("lab-sandbox")
            );
            assert_eq!(
                headers
                    .get("x-fdai-mutation-authority")
                    .and_then(|v| v.to_str().ok()),
                Some("none")
            );
        }
    }
}
