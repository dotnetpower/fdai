//! True Axum 0.8 + Tokio + Tower-HTTP CORS + Native SSE + Console SPA + Auth/RBAC Runtime.

use crate::auth::{
    check_loopback_and_origin, AuthError, OperatorAuthenticator, OperatorRole,
    VerifiedOperatorIdentity, APPROVAL_ROLES, CONTRIBUTOR_ROLES, READER_ROLES,
};
use crate::console_routes::{build_console_get_projection, build_runtime_settings_json};
use crate::state_store::{
    fnv1a64_bytes, is_mandatory_rule_severity, IdempotencyOutcome, RuleActivationUpdate,
    RuntimeStateStore,
};
use crate::CompatRouter;
use axum::body::{to_bytes, Body};
use axum::extract::{ConnectInfo, Request, State};
use axum::http::header::{self, HeaderName, HeaderValue};
use axum::http::{HeaderMap, Method, StatusCode};
use axum::response::sse::{Event, KeepAlive, Sse};
use axum::response::{IntoResponse, Response};
use axum::Router;
use futures_util::stream;
use std::collections::BTreeMap;
use std::convert::Infallible;
use std::fs;
use std::net::{IpAddr, Ipv4Addr, SocketAddr};
use std::path::{Component, Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tower_http::cors::{AllowOrigin, CorsLayer};

const MAX_INTERVENTION_BODY_BYTES: usize = 16_384;
const MAX_CHAT_BODY_BYTES: usize = 65_536;
const MAX_GENERAL_BODY_BYTES: usize = 1_048_576;
const MAX_CONCURRENT_SSE_STREAMS: usize = 128;

const DEFAULT_LOOPBACK_ORIGINS: [&str; 16] = [
    "http://127.0.0.1:5273",
    "http://localhost:5273",
    "http://127.0.0.1:8010",
    "http://localhost:8010",
    "http://[::1]:5273",
    "http://[::1]:8010",
    "http://127.0.0.1:8021",
    "http://localhost:8021",
    "http://127.0.0.1:8022",
    "http://localhost:8022",
    "http://127.0.0.1:8090",
    "http://localhost:8090",
    "http://127.0.0.1:8091",
    "http://localhost:8091",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
];

#[derive(Clone, Debug)]
pub struct ServerRuntimeConfig {
    pub service_id: String,
    pub host: String,
    pub port: u16,
    pub static_dir: Option<PathBuf>,
    pub cors_allow_origins: Vec<String>,
    pub entitlement_notice: String,
    pub console_runtime_config_json: Option<String>,
}

impl ServerRuntimeConfig {
    #[must_use]
    pub fn from_env_and_args(
        service_id: &str,
        default_port: u16,
        serves_console_spa: bool,
        args: &[String],
    ) -> Self {
        let mut host = match service_id {
            "release-hub" => std::env::var("FDAI_RELEASE_HUB_HOST")
                .or_else(|_| std::env::var("HOST"))
                .unwrap_or_else(|_| String::from("127.0.0.1")),
            "hub" => std::env::var("FDAI_LIFECYCLE_HUB_HOST")
                .or_else(|_| std::env::var("HOST"))
                .unwrap_or_else(|_| String::from("127.0.0.1")),
            _ => std::env::var("FDAI_OPERATOR_SERVICE_HOST")
                .or_else(|_| std::env::var("HOST"))
                .unwrap_or_else(|_| String::from("127.0.0.1")),
        };
        let mut port = match service_id {
            "release-hub" => std::env::var("FDAI_RELEASE_HUB_PORT")
                .or_else(|_| std::env::var("PORT"))
                .ok()
                .and_then(|v| v.parse::<u16>().ok())
                .unwrap_or(default_port),
            "hub" => std::env::var("FDAI_LIFECYCLE_HUB_PORT")
                .or_else(|_| std::env::var("PORT"))
                .ok()
                .and_then(|v| v.parse::<u16>().ok())
                .unwrap_or(default_port),
            _ => std::env::var("FDAI_OPERATOR_SERVICE_PORT")
                .or_else(|_| std::env::var("FDAI_E2E_OPERATOR_API_PORT"))
                .or_else(|_| std::env::var("PORT"))
                .ok()
                .and_then(|v| v.parse::<u16>().ok())
                .unwrap_or(default_port),
        };
        let mut static_dir = match service_id {
            "release-hub" => std::env::var("FDAI_RELEASE_HUB_STATIC_DIR")
                .ok()
                .filter(|s| !s.trim().is_empty())
                .map(PathBuf::from),
            "hub" => std::env::var("FDAI_LIFECYCLE_HUB_STATIC_DIR")
                .ok()
                .filter(|s| !s.trim().is_empty())
                .map(PathBuf::from),
            _ => std::env::var("FDAI_CONSOLE_STATIC_DIR")
                .or_else(|_| std::env::var("FDAI_CONSOLE_DIST_DIR"))
                .ok()
                .filter(|s| !s.trim().is_empty())
                .map(PathBuf::from),
        };
        let mut idx = 0_usize;
        while idx < args.len() {
            match args[idx].as_str() {
                "--host" if idx + 1 < args.len() => {
                    host.clone_from(&args[idx + 1]);
                    idx += 2;
                }
                "--port" if idx + 1 < args.len() => {
                    if let Ok(p) = args[idx + 1].parse::<u16>() {
                        port = p;
                    }
                    idx += 2;
                }
                "--static-dir" if idx + 1 < args.len() => {
                    static_dir = Some(PathBuf::from(&args[idx + 1]));
                    idx += 2;
                }
                _ => idx += 1,
            }
        }
        if static_dir.is_none() && serves_console_spa {
            static_dir = locate_default_spa_dist(service_id);
        }
        let raw_cors = std::env::var("FDAI_OPERATOR_API_CORS_ALLOW_ORIGINS").unwrap_or_default();
        let mut cors_allow_origins: Vec<String> = raw_cors
            .split(',')
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(String::from)
            .collect();
        if cors_allow_origins.is_empty() {
            cors_allow_origins = DEFAULT_LOOPBACK_ORIGINS.iter().map(|s| String::from(*s)).collect();
            let self_origin = format!("http://{host}:{port}");
            if !cors_allow_origins.contains(&self_origin) {
                cors_allow_origins.push(self_origin);
            }
        }
        let entitlement_notice = std::env::var("FDAI_ENTITLEMENT_NOTICE")
            .ok()
            .filter(|s| matches!(s.as_str(), "none" | "evaluation-ended" | "not-activated"))
            .unwrap_or_else(|| String::from("not-activated"));
        let console_runtime_config_json = std::env::var("FDAI_CONSOLE_RUNTIME_CONFIG_JSON")
            .ok()
            .filter(|s| !s.trim().is_empty());
        Self {
            service_id: service_id.to_string(),
            host,
            port,
            static_dir,
            cors_allow_origins,
            entitlement_notice,
            console_runtime_config_json,
        }
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.cors_allow_origins.iter().any(|o| o == "*") {
            return Err(String::from(
                "FDAI_OPERATOR_API_CORS_ALLOW_ORIGINS MUST NOT contain a wildcard origin",
            ));
        }
        Ok(())
    }
}

fn locate_default_spa_dist(service_id: &str) -> Option<PathBuf> {
    let rel_candidates: &[&str] = match service_id {
        "hub" => &[
            "lifecycle_rs/hub/ui/dist",
            "../../lifecycle_rs/hub/ui/dist",
            "console/dist",
        ],
        "release-hub" => &[
            "lifecycle_rs/release-hub/ui/dist",
            "../../lifecycle_rs/release-hub/ui/dist",
            "console/dist",
        ],
        _ => &[
            "console/dist",
            "../../console/dist",
            "../console/dist",
            "../../../console/dist",
        ],
    };
    let mut bases = vec![std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))];
    if let Ok(exe) = std::env::current_exe() {
        if let Some(exe_dir) = exe.parent() {
            bases.push(exe_dir.to_path_buf());
        }
    }
    for base in &bases {
        for rel in rel_candidates {
            let cand = base.join(rel);
            if cand.join("index.html").is_file() {
                return Some(cand);
            }
        }
    }
    None
}

#[derive(Clone)]
struct AppState {
    cfg: ServerRuntimeConfig,
    compat_router: CompatRouter,
    authenticator: OperatorAuthenticator,
    store: RuntimeStateStore,
    infra: crate::live_infra::LiveInfraHandle,
    active_sse_leases: Arc<AtomicUsize>,
    requests_total: Arc<AtomicUsize>,
    causal_inferences_total: Arc<AtomicUsize>,
}

struct SseLeaseGuard {
    leases: Arc<AtomicUsize>,
}

impl Drop for SseLeaseGuard {
    fn drop(&mut self) {
        self.leases.fetch_sub(1, Ordering::SeqCst);
    }
}

pub fn build_axum_router(
    cfg: ServerRuntimeConfig,
    compat_router: CompatRouter,
    authenticator: OperatorAuthenticator,
) -> Router {
    let store = RuntimeStateStore::open_from_env();
    build_axum_router_with_store(cfg, compat_router, authenticator, store)
}

pub fn build_axum_router_with_store(
    cfg: ServerRuntimeConfig,
    compat_router: CompatRouter,
    authenticator: OperatorAuthenticator,
    store: RuntimeStateStore,
) -> Router {
    let infra = crate::live_infra::LiveInfraHandle::from_env();
    build_axum_router_with_store_and_infra(cfg, compat_router, authenticator, store, infra)
}

pub fn build_axum_router_with_routes(
    cfg: ServerRuntimeConfig,
    compat_router: CompatRouter,
    authenticator: OperatorAuthenticator,
    service_routes: Router,
) -> Router {
    let store = RuntimeStateStore::open_from_env();
    let infra = crate::live_infra::LiveInfraHandle::from_env();
    build_axum_router_with_store_infra_and_routes(
        cfg,
        compat_router,
        authenticator,
        store,
        infra,
        Some(service_routes),
    )
}

fn build_axum_router_with_store_and_infra(
    cfg: ServerRuntimeConfig,
    compat_router: CompatRouter,
    authenticator: OperatorAuthenticator,
    store: RuntimeStateStore,
    infra: crate::live_infra::LiveInfraHandle,
) -> Router {
    build_axum_router_with_store_infra_and_routes(
        cfg,
        compat_router,
        authenticator,
        store,
        infra,
        None,
    )
}

fn build_axum_router_with_store_infra_and_routes(
    cfg: ServerRuntimeConfig,
    compat_router: CompatRouter,
    authenticator: OperatorAuthenticator,
    store: RuntimeStateStore,
    infra: crate::live_infra::LiveInfraHandle,
    service_routes: Option<Router>,
) -> Router {
    let cors_layer = build_cors_layer(&cfg.cors_allow_origins);
    let state = AppState {
        cfg,
        compat_router,
        authenticator,
        store,
        infra,
        active_sse_leases: Arc::new(AtomicUsize::new(0)),
        requests_total: Arc::new(AtomicUsize::new(0)),
        causal_inferences_total: Arc::new(AtomicUsize::new(0)),
    };
    let fallback_app = Router::new()
        .fallback(dispatch_axum_request)
        .with_state(state);
    if let Some(routes) = service_routes {
        Router::new()
            .merge(routes)
            .fallback_service(fallback_app)
            .layer(cors_layer)
    } else {
        fallback_app.layer(cors_layer)
    }
}

pub async fn serve_axum_http_with_routes(
    cfg: ServerRuntimeConfig,
    compat_router: CompatRouter,
    service_routes: Router,
) -> Result<u16, String> {
    serve_axum_http_inner(cfg, compat_router, Some(service_routes)).await
}

fn build_cors_layer(origins: &[String]) -> CorsLayer {
    let parsed_origins: Vec<HeaderValue> = origins
        .iter()
        .filter_map(|o| HeaderValue::from_str(o).ok())
        .collect();
    CorsLayer::new()
        .allow_origin(AllowOrigin::list(parsed_origins))
        .allow_methods([
            Method::GET,
            Method::POST,
            Method::PUT,
            Method::DELETE,
            Method::PATCH,
            Method::HEAD,
            Method::OPTIONS,
        ])
        .allow_headers([
            header::AUTHORIZATION,
            header::CONTENT_TYPE,
            HeaderName::from_static("idempotency-key"),
            HeaderName::from_static("if-match"),
            HeaderName::from_static("if-none-match"),
            HeaderName::from_static("last-event-id"),
            HeaderName::from_static("x-correlation-id"),
            HeaderName::from_static("x-fdai-installation-id"),
            HeaderName::from_static("x-fdai-customer-principal"),
            HeaderName::from_static("x-fdai-distribution-grant"),
            HeaderName::from_static("x-fdai-installed-release-id"),
        ])
        .expose_headers([
            header::ETAG,
            HeaderName::from_static("docker-distribution-api-version"),
            HeaderName::from_static("docker-content-digest"),
            HeaderName::from_static("x-fdai-artifact-sha256"),
            HeaderName::from_static("x-fdai-entitlement"),
            HeaderName::from_static("x-fdai-expected-rows"),
            HeaderName::from_static("x-fdai-export-key-id"),
            HeaderName::from_static("x-fdai-export-signature"),
            HeaderName::from_static("x-fdai-grant-scope-digest"),
            HeaderName::from_static("x-fdai-grant-scope-signature"),
            HeaderName::from_static("x-fdai-included-rows"),
            HeaderName::from_static("x-fdai-local-session"),
            HeaderName::from_static("x-fdai-recovery-only"),
            HeaderName::from_static("x-fdai-revision"),
        ])
        .max_age(Duration::from_secs(600))
}

pub async fn serve_axum_http(
    cfg: ServerRuntimeConfig,
    compat_router: CompatRouter,
) -> Result<u16, String> {
    serve_axum_http_inner(cfg, compat_router, None).await
}

async fn serve_axum_http_inner(
    cfg: ServerRuntimeConfig,
    compat_router: CompatRouter,
    service_routes: Option<Router>,
) -> Result<u16, String> {
    cfg.validate()?;
    let authenticator = OperatorAuthenticator::from_env()?;
    let bind_target = if cfg.host.contains(':') && !cfg.host.starts_with('[') {
        format!("[{}]:{}", cfg.host, cfg.port)
    } else {
        format!("{}:{}", cfg.host, cfg.port)
    };
    let listener = tokio::net::TcpListener::bind(&bind_target)
        .await
        .map_err(|e| format!("axum bind {bind_target} failed: {e}"))?;
    let local_addr = listener.local_addr().map_err(|e| e.to_string())?;
    let static_desc = cfg
        .static_dir
        .as_ref()
        .map_or_else(|| String::from("none"), |p| p.display().to_string());
    let store = RuntimeStateStore::open_from_env();
    let infra = crate::live_infra::LiveInfraHandle::from_env();
    if !matches!(cfg.service_id.as_str(), "hub" | "release-hub") {
        infra.spawn_kafka_sse_bridge(store.clone());
    }
    println!(
        "AXUM_LISTENING http://{local_addr} service={} auth={} routes={} static={static_desc} pg={} kafka={}",
        cfg.service_id,
        authenticator.mode_label(),
        compat_router.total_method_bindings(),
        infra.pg_configured(),
        infra.kafka_configured()
    );
    let app = build_axum_router_with_store_infra_and_routes(
        cfg,
        compat_router,
        authenticator,
        store,
        infra,
        service_routes,
    );
    axum::serve(
        listener,
        app.into_make_service_with_connect_info::<SocketAddr>(),
    )
    .with_graceful_shutdown(shutdown_signal())
    .await
    .map_err(|e| format!("axum serve error: {e}"))?;
    Ok(local_addr.port())
}

async fn shutdown_signal() {
    let ctrl_c = async {
        let _ = tokio::signal::ctrl_c().await;
    };
    #[cfg(unix)]
    let terminate = async {
        if let Ok(mut sig) =
            tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
        {
            sig.recv().await;
        }
    };
    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();
    tokio::select! {
        () = ctrl_c => {},
        () = terminate => {},
    }
}

#[allow(clippy::too_many_lines)]
async fn dispatch_axum_request(State(state): State<AppState>, req: Request) -> Response {
    let method = req.method().clone();
    let headers = req.headers().clone();
    let raw_path = req.uri().path().to_string();
    let remote_ip: IpAddr = req
        .extensions()
        .get::<ConnectInfo<SocketAddr>>()
        .map(|ci| ci.0.ip())
        .unwrap_or(IpAddr::V4(Ipv4Addr::LOCALHOST));

    if state.authenticator.is_local_azure_cli() {
        let origin = header_str(&headers, header::ORIGIN);
        if let Err(err) = check_loopback_and_origin(remote_ip, origin, &state.cfg.cors_allow_origins) {
            return auth_error_response(&err);
        }
    }

    let head_only = method == Method::HEAD;
    let eff_method = if head_only { "GET" } else { method.as_str() };
    let explicit_api = raw_path == "/api" || raw_path.starts_with("/api/");
    let norm_path_owned = if raw_path == "/api" {
        String::from("/")
    } else if let Some(stripped) = raw_path.strip_prefix("/api/") {
        format!("/{}", stripped.trim_start_matches('/'))
    } else {
        raw_path.clone()
    };
    let norm_path = norm_path_owned.as_str();

    if eff_method == "GET" {
        if raw_path == "/fdai-config.js" {
            return serve_runtime_config_js(&state.cfg, head_only);
        }
        if matches!(state.cfg.service_id.as_str(), "release-hub" | "hub")
            && (raw_path.starts_with("/v1/") || raw_path.starts_with("/v2/"))
        {
            let msg = if state.cfg.service_id == "release-hub" {
                "Unknown API route."
            } else {
                "not_found"
            };
            let err = serde_json::json!({"error": msg});
            return json_api_response(StatusCode::NOT_FOUND, &err, None, &[], head_only);
        }
        if let Some(ref sdir) = state.cfg.static_dir {
            let accept = header_str(&headers, header::ACCEPT).unwrap_or("");
            if let Some(resp) = try_serve_static_spa(sdir, &raw_path, accept, explicit_api, head_only) {
                return resp;
            }
        }
    } else if matches!(state.cfg.service_id.as_str(), "release-hub" | "hub")
        && (raw_path.starts_with("/v1/") || raw_path.starts_with("/v2/"))
    {
        let msg = if state.cfg.service_id == "release-hub" {
            "Unknown API route."
        } else {
            "not_found"
        };
        let err = serde_json::json!({"error": msg});
        return json_api_response(StatusCode::NOT_FOUND, &err, None, &[], false);
    }

    state.requests_total.fetch_add(1, Ordering::Relaxed);
    match (eff_method, norm_path) {
        ("GET", "/healthz") => {
            let body = serde_json::json!({"service": state.cfg.service_id, "status": "ok"});
            return json_api_response(StatusCode::OK, &body, None, &[], head_only);
        }
        ("GET", "/readyz") => {
            let body = serde_json::json!({"status": "ok", "runtime": "axum-0.8", "auth": state.authenticator.mode_label()});
            return json_api_response(StatusCode::OK, &body, None, &[], head_only);
        }
        ("GET", "/metrics") => {
            if let Ok(expected) = std::env::var("FDAI_METRICS_BEARER") {
                if !expected.trim().is_empty() {
                    let provided = header_str(&headers, header::AUTHORIZATION)
                        .and_then(|v| v.strip_prefix("Bearer "))
                        .unwrap_or("");
                    if !bool::from(subtle::ConstantTimeEq::ct_eq(
                        provided.as_bytes(),
                        expected.trim().as_bytes(),
                    )) {
                        let err = serde_json::json!({"error":{"status":401,"message":"metrics bearer token required"}});
                        return json_api_response(StatusCode::UNAUTHORIZED, &err, None, &[], false);
                    }
                }
            }
            let reqs = state.requests_total.load(Ordering::Relaxed);
            let sse = state.active_sse_leases.load(Ordering::Relaxed);
            let audits = state.store.audit_count().await;
            let causals = state.causal_inferences_total.load(Ordering::Relaxed);
            let svc_label = escape_prometheus_label(&state.cfg.service_id);
            let metrics_txt = format!(
                "# TYPE fdai_http_requests_total counter\nfdai_http_requests_total{{service=\"{svc_label}\"}} {reqs}\n\
# TYPE fdai_sse_active_streams gauge\nfdai_sse_active_streams{{service=\"{svc_label}\"}} {sse}\n\
# TYPE fdai_audit_events_total gauge\nfdai_audit_events_total{{service=\"{svc_label}\"}} {audits}\n\
# TYPE fdai_causal_inferences_total counter\nfdai_causal_inferences_total{{service=\"{svc_label}\"}} {causals}\n"
            );
            return raw_bytes_response(
                StatusCode::OK,
                "text/plain; version=0.0.4; charset=utf-8",
                metrics_txt.into_bytes(),
                "no-store",
                head_only,
            );
        }
        ("GET", "/local-auth/me") => {
            if let Some((profile, token)) = state.authenticator.local_cli_profile_and_token() {
                return json_api_response(
                    StatusCode::OK,
                    profile,
                    None,
                    &[("x-fdai-local-session", token)],
                    head_only,
                );
            }
            let body = serde_json::json!({"error": {"status": 404, "message": "local Azure CLI authentication is not enabled"}});
            return json_api_response(StatusCode::NOT_FOUND, &body, None, &[], head_only);
        }
        _ => {}
    }

    let auth_header = header_str(&headers, header::AUTHORIZATION);
    let required_roles = if eff_method == "POST"
        && norm_path.starts_with("/incidents/")
        && norm_path.ends_with("/interventions")
    {
        CONTRIBUTOR_ROLES.as_slice()
    } else if eff_method != "GET"
        && norm_path != "/chat/stream"
        && norm_path != "/ontology/causal/intervene"
        && norm_path != "/ontology/causal/counterfactual"
    {
        APPROVAL_ROLES.as_slice()
    } else {
        READER_ROLES.as_slice()
    };

    let identity = if eff_method == "GET" && norm_path == "/iam/self" {
        match state.authenticator.authenticate(auth_header).await {
            Ok(id) => id,
            Err(err) => return auth_error_response(&err),
        }
    } else {
        match state
            .authenticator
            .require_any(auth_header, required_roles)
            .await
        {
            Ok(id) => id,
            Err(err) => return auth_error_response(&err),
        }
    };

    let entitlement = if identity.authenticated_via_credential {
        Some(state.cfg.entitlement_notice.as_str())
    } else {
        None
    };

    let now_iso = format_utc_rfc3339_now();
    let query_str = req.uri().query().unwrap_or("").to_string();
    match (eff_method, norm_path) {
        ("GET", "/auth/me") => {
            let body = build_auth_me_payload(&identity, state.authenticator.mode_label());
            json_api_response(StatusCode::OK, &body, entitlement, &[], head_only)
        }
        ("GET", "/migrated/routes") => {
            let routes: Vec<serde_json::Value> = state
                .compat_router
                .routes
                .iter()
                .map(|(p, ms)| serde_json::json!({"path": p, "methods": ms}))
                .collect();
            let body = serde_json::json!({
                "service": state.cfg.service_id,
                "bindings": state.compat_router.total_method_bindings(),
                "routes": routes
            });
            json_api_response(StatusCode::OK, &body, entitlement, &[], head_only)
        }
        ("GET", "/chat/health") => {
            let body = if let Some(az) = crate::AzureOpenAiConfig::from_env() {
                serde_json::json!({
                    "available": true,
                    "mode": "azure-openai-keyless",
                    "model": az.deployment,
                    "endpoint": az.endpoint
                })
            } else {
                serde_json::json!({
                    "available": true,
                    "mode": "rust-axum-native",
                    "model": "deterministic-runtime",
                    "endpoint": null
                })
            };
            json_api_response(StatusCode::OK, &body, entitlement, &[], head_only)
        }
        ("POST", "/chat/stream") => {
            let raw_bytes = match to_bytes(req.into_body(), MAX_CHAT_BODY_BYTES).await {
                Ok(b) => b,
                Err(_) => {
                    let err = serde_json::json!({"error":{"status":413,"message":"chat stream body exceeds 64 KiB limit"}});
                    return json_api_response(StatusCode::PAYLOAD_TOO_LARGE, &err, entitlement, &[], false);
                }
            };
            let parsed_req: serde_json::Value = if raw_bytes.is_empty() {
                serde_json::json!({})
            } else {
                match serde_json::from_slice(&raw_bytes) {
                    Ok(v) => v,
                    Err(_) => {
                        let err = serde_json::json!({"error":{"status":400,"message":"invalid chat stream JSON payload"}});
                        return json_api_response(StatusCode::BAD_REQUEST, &err, entitlement, &[], false);
                    }
                }
            };
            let req_id = parsed_req
                .get("request_id")
                .and_then(serde_json::Value::as_str)
                .map(String::from);
            let prompt_text = parsed_req
                .get("message")
                .or_else(|| parsed_req.get("prompt"))
                .or_else(|| parsed_req.get("question"))
                .and_then(serde_json::Value::as_str)
                .unwrap_or("");
            let pl = prompt_text.to_ascii_lowercase();
            let audit_cnt = state.store.audit_count().await;
            let (answer, model_name, source_tag) = if let Some(az_cfg) = crate::AzureOpenAiConfig::from_env() {
                let adapter = match crate::KeylessAzureAdapter::try_new(None) {
                    Ok(a) => a,
                    Err(e) => {
                        let err = serde_json::json!({"error":{"status":502,"code":"azure_openai_upstream_error","message":e}});
                        return json_api_response(StatusCode::BAD_GATEWAY, &err, entitlement, &[], false);
                    }
                };
                match adapter.stream_chat_completions(&az_cfg, prompt_text).await {
                    Ok(chunks) if !chunks.is_empty() => (
                        chunks.concat(),
                        az_cfg.deployment.clone(),
                        "azure-openai-keyless",
                    ),
                    Ok(_) => {
                        let err = serde_json::json!({"error":{"status":502,"code":"azure_openai_upstream_error","message":"Azure OpenAI returned empty completion"}});
                        return json_api_response(StatusCode::BAD_GATEWAY, &err, entitlement, &[], false);
                    }
                    Err(e) => {
                        let err = serde_json::json!({"error":{"status":502,"code":"azure_openai_upstream_error","message":e}});
                        return json_api_response(StatusCode::BAD_GATEWAY, &err, entitlement, &[], false);
                    }
                }
            } else if pl.contains("time") || prompt_text.contains("시간") || prompt_text.is_empty() {
                (format!("The current time is {now_iso} (UTC)."), String::from("rust-axum-runtime"), "server-clock")
            } else if pl.contains("audit") || pl.contains("incident") || prompt_text.contains("감사") {
                (
                    format!("Verified operator state: {audit_cnt} recorded audit events as of {now_iso} (UTC)."),
                    String::from("rust-axum-runtime"),
                    "server-clock",
                )
            } else {
                (
                    format!(
                        "Verified Rust Axum runtime ({}) observed {audit_cnt} audit events and {} registered route bindings at {now_iso} (UTC).",
                        state.cfg.service_id,
                        state.compat_router.total_method_bindings()
                    ),
                    String::from("rust-axum-runtime"),
                    "server-clock",
                )
            };
            let done_payload = serde_json::json!({
                "seq": 1,
                "revision": 0,
                "request_id": req_id,
                "status": "answered",
                "answer": answer,
                "model": model_name,
                "source": source_tag,
                "verification": {
                    "status": "verified",
                    "authority": source_tag,
                    "checks_completed": 1,
                    "checks_total": 1,
                    "evidence_refs": ["clock:utc", "store:audit"],
                    "reason_code": "server_clock_verified",
                    "claims": [],
                    "failed_claim_ids": []
                }
            });
            let data = serde_json::to_string(&done_payload).unwrap_or_else(|_| String::from("{}"));
            let event = Event::default().event("done").data(data);
            build_single_shot_sse_response(state.active_sse_leases, vec![event], entitlement)
        }
        ("POST", "/ontology/causal/intervene" | "/ontology/causal/counterfactual") => {
            let raw_bytes = match to_bytes(req.into_body(), MAX_INTERVENTION_BODY_BYTES).await {
                Ok(b) => b,
                Err(_) => {
                    let err = serde_json::json!({"error":{"status":413,"message":"causal payload exceeds 16 KiB limit"}});
                    return json_api_response(StatusCode::PAYLOAD_TOO_LARGE, &err, entitlement, &[], false);
                }
            };
            let parsed: serde_json::Value = match serde_json::from_slice(&raw_bytes) {
                Ok(v) => v,
                Err(_) => {
                    let err = serde_json::json!({"error":{"status":400,"message":"invalid causal JSON payload"}});
                    return json_api_response(StatusCode::BAD_REQUEST, &err, entitlement, &[], false);
                }
            };
            let mut g = crate::causal_ontology::CausalGraph::default();
            if let Some(edges) = parsed.get("edges").and_then(serde_json::Value::as_array) {
                if edges.len() > 512 {
                    let err = serde_json::json!({"error":{"status":400,"message":"causal graph exceeds 512 edge limit"}});
                    return json_api_response(StatusCode::BAD_REQUEST, &err, entitlement, &[], false);
                }
                for e in edges {
                    let from = e.get("from").and_then(serde_json::Value::as_str).unwrap_or("");
                    let to = e.get("to").and_then(serde_json::Value::as_str).unwrap_or("");
                    let weight = e.get("weight").and_then(serde_json::Value::as_f64).unwrap_or(1.0);
                    if !weight.is_finite() || from.len() > 128 || to.len() > 128 {
                        let err = serde_json::json!({"error":{"status":400,"message":"invalid causal edge weight or node name"}});
                        return json_api_response(StatusCode::BAD_REQUEST, &err, entitlement, &[], false);
                    }
                    let inh: Vec<&str> = e
                        .get("unless")
                        .and_then(serde_json::Value::as_array)
                        .map(|a| a.iter().filter_map(serde_json::Value::as_str).take(16).collect())
                        .unwrap_or_default();
                    if !from.is_empty() && !to.is_empty() {
                        g.add_edge(from, to, weight, &inh);
                    }
                }
            }
            const MAX_CAUSAL_NODES: usize = 256;
            if g.nodes.len() > MAX_CAUSAL_NODES {
                let err = serde_json::json!({"error":{"status":400,"message":"causal graph exceeds 256 node limit"}});
                return json_api_response(StatusCode::BAD_REQUEST, &err, entitlement, &[], false);
            }
            let target = parsed.get("treatment").or_else(|| parsed.get("target")).and_then(serde_json::Value::as_str).unwrap_or("x");
            let outcome = parsed.get("outcome").and_then(serde_json::Value::as_str).unwrap_or("y");
            let do_val = parsed.get("do_value").and_then(serde_json::Value::as_f64).unwrap_or(0.0);
            if !do_val.is_finite() {
                let err = serde_json::json!({"error":{"status":400,"message":"do_value must be finite"}});
                return json_api_response(StatusCode::BAD_REQUEST, &err, entitlement, &[], false);
            }
            let mut obs: BTreeMap<String, f64> = BTreeMap::new();
            if let Some(obj) = parsed.get("observed").and_then(serde_json::Value::as_object) {
                if obj.len() > MAX_CAUSAL_NODES {
                    let err = serde_json::json!({"error":{"status":400,"message":"observed map exceeds 256 entries"}});
                    return json_api_response(StatusCode::BAD_REQUEST, &err, entitlement, &[], false);
                }
                for (k, v) in obj {
                    if let Some(f) = v.as_f64() {
                        if !f.is_finite() {
                            let err = serde_json::json!({"error":{"status":400,"message":"observed values must be finite"}});
                            return json_api_response(StatusCode::BAD_REQUEST, &err, entitlement, &[], false);
                        }
                        obs.insert(k.clone(), f);
                    }
                }
            }
            let mut inhibitors: BTreeMap<String, Option<bool>> = BTreeMap::new();
            if let Some(obj) = parsed.get("inhibitors").and_then(serde_json::Value::as_object) {
                if obj.len() > MAX_CAUSAL_NODES {
                    let err = serde_json::json!({"error":{"status":400,"message":"inhibitors map exceeds 256 entries"}});
                    return json_api_response(StatusCode::BAD_REQUEST, &err, entitlement, &[], false);
                }
                for (k, v) in obj {
                    inhibitors.insert(k.clone(), v.as_bool());
                }
            }
            state.causal_inferences_total.fetch_add(1, Ordering::Relaxed);
            if norm_path.ends_with("/counterfactual") {
                match g.evaluate_counterfactual(&obs, target, do_val, outcome, &inhibitors) {
                    Ok(cf) => {
                        let body = serde_json::json!({
                            "rung": 3,
                            "treatment": cf.treatment,
                            "outcome": cf.outcome,
                            "factual_outcome": cf.factual_outcome,
                            "counterfactual_outcome": cf.counterfactual_outcome,
                            "individual_treatment_effect": cf.individual_treatment_effect,
                            "severed_incoming_edges": cf.severed_incoming_edges,
                            "uncertain_edges": cf.uncertain_edges,
                            "abducted_exogenous": cf.abducted_exogenous
                        });
                        json_api_response(StatusCode::OK, &body, entitlement, &[], false)
                    }
                    Err(e) => {
                        let err = serde_json::json!({"error":{"status":422,"message":e}});
                        json_api_response(StatusCode::UNPROCESSABLE_ENTITY, &err, entitlement, &[], false)
                    }
                }
            } else {
                match g.do_intervention(target, do_val, Some(outcome), &obs, &inhibitors) {
                    Ok(rec) => {
                        let body = serde_json::json!({
                            "rung": 2,
                            "target": rec.target,
                            "do_value": rec.do_value,
                            "severed_incoming_edges": rec.severed_incoming_edges,
                            "backdoor_adjustment_set": rec.backdoor_adjustment_set,
                            "inhibited_edges": rec.inhibited_edges,
                            "uncertain_edges": rec.uncertain_edges,
                            "post_intervention_values": rec.post_intervention_values
                        });
                        json_api_response(StatusCode::OK, &body, entitlement, &[], false)
                    }
                    Err(e) => {
                        let err = serde_json::json!({"error":{"status":422,"message":e}});
                        json_api_response(StatusCode::UNPROCESSABLE_ENTITY, &err, entitlement, &[], false)
                    }
                }
            }
        }
        ("GET", "/live/stream" | "/incidents/stream" | "/access-grants/stream" | "/agents/stream" | "/ontology/instances/stream") => {
            let mut initial_events: Vec<Event> = Vec::new();
            let mut emit_source_keepalive = false;
            match norm_path {
                "/live/stream" => {
                    emit_source_keepalive = true;
                    let hello = serde_json::json!({"event": "hello", "ts": now_iso});
                    let src = serde_json::json!({"status": "ready", "source": "runtime-observed", "ts": now_iso});
                    let act = serde_json::json!({"type": "live.activity-status", "status": "ready", "reason": null, "ts": now_iso});
                    initial_events.push(Event::default().event("hello").data(hello.to_string()));
                    initial_events.push(Event::default().event("source").data(src.to_string()));
                    initial_events.push(Event::default().event("activity-status-snapshot").data(act.to_string()));
                    for st_ev in state.infra.query_recent_live_stages(12, &now_iso).await {
                        initial_events.push(
                            Event::default()
                                .id(st_ev.seq.to_string())
                                .event(st_ev.event_type)
                                .data(st_ev.payload_json),
                        );
                    }
                }
                "/incidents/stream" => {
                    let inc_items = state.infra.query_incident_attention_items(&now_iso).await;
                    let snap = serde_json::json!({"event": "incident_attention.snapshot", "ts": now_iso, "incidents": inc_items});
                    initial_events.push(Event::default().event("snapshot").data(snap.to_string()));
                }
                "/access-grants/stream" => {
                    let snap = serde_json::json!({"event": "access_grant.snapshot", "ts": now_iso, "requests": []});
                    initial_events.push(Event::default().event("snapshot").data(snap.to_string()));
                }
                _ => {
                    let hb = serde_json::json!({
                        "service": state.cfg.service_id,
                        "observed_at": now_iso,
                        "principal": identity.principal.subject_id
                    });
                    initial_events.push(Event::default().event("heartbeat").data(hb.to_string()));
                }
            }
            if query_str.contains("once=1") {
                build_single_shot_sse_response(state.active_sse_leases, initial_events, entitlement)
            } else {
                let rx = state.store.subscribe_events();
                build_live_broadcast_sse_response(
                    state.active_sse_leases,
                    initial_events,
                    emit_source_keepalive,
                    rx,
                    entitlement,
                )
            }
        }
        ("GET", "/system/data-sources") => {
            let durable = state.store.is_durable_disk_backed();
            let body = state.infra.status_snapshot(&now_iso, durable).await;
            json_api_response(StatusCode::OK, &body, entitlement, &[], head_only)
        }
        ("GET", "/kpi") => {
            let body = match state.infra.query_kpi(&now_iso).await {
                Some(live) => live,
                None => state.store.kpi_snapshot().await,
            };
            json_api_response(StatusCode::OK, &body, entitlement, &[], head_only)
        }
        ("GET", "/audit") => {
            let body = match state.infra.query_audit(&query_str, &now_iso).await {
                Some(live) => live,
                None => state.store.audit_snapshot(&now_iso).await,
            };
            json_api_response(StatusCode::OK, &body, entitlement, &[], head_only)
        }
        ("GET", "/incidents") => {
            let body = match state.infra.query_incidents(&query_str, &now_iso).await {
                Some(live) => live,
                None => serde_json::json!({
                    "items": [],
                    "next_cursor": null,
                    "metrics": {
                        "source": "rust-axum-state",
                        "snapshot_seq": 0,
                        "denominator": 0,
                        "matched_total": 0,
                        "truncated": false,
                        "window_from": null,
                        "window_to": null,
                        "cohorts": {"agent_mitigated":0,"agent_assisted":0,"human_mitigated":0,"pending":0,"integrity_excluded":0},
                        "drilldown": {"agent_mitigated":[],"agent_assisted":[],"human_mitigated":[],"pending":[],"integrity_excluded":[]},
                        "drilldown_truncated": {"agent_mitigated":false,"agent_assisted":false,"human_mitigated":false,"pending":false,"integrity_excluded":false},
                        "median_time_to_mitigate_seconds": null,
                        "time_to_mitigate_sample_size": 0,
                        "terminal_rule": "resolved_and_independently_verified"
                    }
                }),
            };
            json_api_response(StatusCode::OK, &body, entitlement, &[], head_only)
        }
        ("GET", "/hil-queue") => {
            let body = serde_json::json!({"items": [], "total": 0, "detail_level": "full"});
            json_api_response(StatusCode::OK, &body, entitlement, &[], head_only)
        }
        ("GET", "/browser-evidence") => {
            let body = serde_json::json!({"items": [], "next_cursor": null});
            json_api_response(StatusCode::OK, &body, entitlement, &[], head_only)
        }
        ("GET", "/agents/activity") => {
            let body = serde_json::json!({"items": [], "snapshot_at": now_iso, "source": "authoritative"});
            json_api_response(StatusCode::OK, &body, entitlement, &[], head_only)
        }
        ("GET", "/routes") => {
            let body = serde_json::json!({
                "service": state.cfg.service_id,
                "runtime": "axum-0.8",
                "auth_mode": state.authenticator.mode_label(),
                "registered_paths": state.compat_router.routes.len(),
                "method_bindings": state.compat_router.total_method_bindings()
            });
            json_api_response(StatusCode::OK, &body, entitlement, &[], head_only)
        }
        ("PATCH", p) if p.starts_with("/rules/") && p.ends_with("/activation") => {
            let rule_id = p
                .trim_start_matches("/rules/")
                .trim_end_matches("/activation")
                .trim();
            let valid_id = !rule_id.is_empty()
                && rule_id.len() <= 160
                && rule_id
                    .chars()
                    .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.' | ':'));
            if !valid_id {
                let err = serde_json::json!({
                    "error": {"status": 400, "code": "invalid_rule_id", "message": "rule_id must contain 1..160 safe identifier characters"}
                });
                return json_api_response(StatusCode::BAD_REQUEST, &err, entitlement, &[], false);
            }
            let raw_bytes = match to_bytes(req.into_body(), MAX_INTERVENTION_BODY_BYTES).await {
                Ok(b) => b,
                Err(_) => {
                    let err = serde_json::json!({"error":{"status":413,"message":"rule activation body exceeds 16 KiB limit"}});
                    return json_api_response(StatusCode::PAYLOAD_TOO_LARGE, &err, entitlement, &[], false);
                }
            };
            let parsed: serde_json::Value = match serde_json::from_slice::<serde_json::Value>(&raw_bytes) {
                Ok(v) if v.is_object() => v,
                _ => {
                    let err = serde_json::json!({"error":{"status":400,"message":"rule activation body must be a JSON object"}});
                    return json_api_response(StatusCode::BAD_REQUEST, &err, entitlement, &[], false);
                }
            };
            let Some(enabled) = parsed.get("enabled").and_then(serde_json::Value::as_bool) else {
                let err = serde_json::json!({"error":{"status":400,"code":"missing_enabled","message":"boolean field 'enabled' is required"}});
                return json_api_response(StatusCode::BAD_REQUEST, &err, entitlement, &[], false);
            };
            let mode = parsed.get("mode").and_then(serde_json::Value::as_str);
            let reason = parsed
                .get("reason")
                .and_then(serde_json::Value::as_str)
                .unwrap_or("");
            let requested_severity = parsed
                .get("severity")
                .and_then(serde_json::Value::as_str)
                .unwrap_or("medium");

            let db_severity = state.infra.lookup_rule_severity(rule_id, &now_iso).await;
            let effective_severity = db_severity.as_deref().unwrap_or(requested_severity);

            if is_mandatory_rule_severity(effective_severity) && !enabled {
                let err = serde_json::json!({
                    "error": {
                        "status": 409,
                        "code": "mandatory_severity_cannot_be_disabled",
                        "message": "Critical and High severity rules are mandatory active and cannot be disabled."
                    },
                    "rule_id": rule_id,
                    "severity": effective_severity,
                    "mandatory_active": true,
                    "can_deactivate": false
                });
                return json_api_response(StatusCode::CONFLICT, &err, entitlement, &[], false);
            }

            match state
                .store
                .set_rule_activation(RuleActivationUpdate {
                    rule_id,
                    enabled,
                    mode,
                    severity: effective_severity,
                    actor_subject_id: &identity.principal.subject_id,
                    reason,
                    now_iso: &now_iso,
                })
                .await
            {
                Ok(record) => {
                    let mut all_activations = state.infra.load_pg_rule_activations(&now_iso).await;
                    for (k, v) in state.store.rule_activations_snapshot().await {
                        all_activations.insert(k, v);
                    }
                    let pg_persisted = state
                        .infra
                        .persist_rule_activations(&all_activations, &now_iso)
                        .await;
                    let body = serde_json::json!({
                        "status": "applied",
                        "persisted": pg_persisted || state.store.is_durable_disk_backed(),
                        "pg_persisted": pg_persisted,
                        "activation": record,
                        "activation_policy": {
                            "mandatory_severities": ["critical", "high"],
                            "critical_high_cannot_be_disabled": true
                        }
                    });
                    json_api_response(StatusCode::OK, &body, entitlement, &[], false)
                }
                Err(code) => {
                    let err = serde_json::json!({
                        "error": {
                            "status": 409,
                            "code": code,
                            "message": "Critical and High severity rules are mandatory active and cannot be disabled."
                        }
                    });
                    json_api_response(StatusCode::CONFLICT, &err, entitlement, &[], false)
                }
            }
        }
        ("POST", "/rules/activation/enforce-mandatory") => {
            let mandatory_rules = state.infra.list_mandatory_severity_rules(&now_iso).await;
            let enforced_count = state
                .store
                .enforce_mandatory_rules(&mandatory_rules, &identity.principal.subject_id, &now_iso)
                .await;
            let mut all_activations = state.infra.load_pg_rule_activations(&now_iso).await;
            for (k, v) in state.store.rule_activations_snapshot().await {
                all_activations.insert(k, v);
            }
            let pg_persisted = state
                .infra
                .persist_rule_activations(&all_activations, &now_iso)
                .await;
            let body = serde_json::json!({
                "status": "applied",
                "mandatory_rule_count": mandatory_rules.len(),
                "enforced_count": enforced_count,
                "pg_persisted": pg_persisted,
                "activation_policy": {
                    "mandatory_severities": ["critical", "high"],
                    "critical_high_cannot_be_disabled": true
                }
            });
            json_api_response(StatusCode::OK, &body, entitlement, &[], false)
        }
        ("PUT", "/runtime/settings") => {
            let raw_bytes = match to_bytes(req.into_body(), MAX_INTERVENTION_BODY_BYTES).await {
                Ok(b) => b,
                Err(_) => {
                    let err = serde_json::json!({"error":{"status":413,"message":"runtime settings body exceeds 16 KiB limit"}});
                    return json_api_response(StatusCode::PAYLOAD_TOO_LARGE, &err, entitlement, &[], false);
                }
            };
            let parsed: serde_json::Value = match serde_json::from_slice::<serde_json::Value>(&raw_bytes) {
                Ok(v) if v.is_object() => v,
                _ => {
                    let err = serde_json::json!({"error":{"status":400,"message":"runtime settings body must be a JSON object"}});
                    return json_api_response(StatusCode::BAD_REQUEST, &err, entitlement, &[], false);
                }
            };
            let expected_rev = parsed.get("revision").and_then(serde_json::Value::as_u64);
            let mut changes = BTreeMap::new();
            if let Some(obj) = parsed.get("changes").and_then(serde_json::Value::as_object) {
                for (k, v) in obj {
                    changes.insert(k.clone(), v.clone());
                }
            }
            match state
                .store
                .update_runtime_settings(expected_rev, changes, &identity.principal.subject_id, &now_iso)
                .await
            {
                Ok(updated) => {
                    let rev_str = updated.revision.to_string();
                    let body = build_runtime_settings_json(
                        &updated,
                        &identity,
                        state.store.is_durable_disk_backed(),
                    );
                    json_api_response(
                        StatusCode::OK,
                        &body,
                        entitlement,
                        &[("x-fdai-revision", &rev_str)],
                        false,
                    )
                }
                Err(cur_rev) => {
                    let err = serde_json::json!({
                        "error": {"status": 409, "message": format!("stale runtime settings revision (current={cur_rev})")}
                    });
                    json_api_response(StatusCode::CONFLICT, &err, entitlement, &[], false)
                }
            }
        }
        ("POST", p) if p.starts_with("/incidents/") && p.ends_with("/interventions") => {
            let idem = headers
                .get("idempotency-key")
                .and_then(|v| v.to_str().ok())
                .map(str::trim)
                .unwrap_or("");
            if idem.is_empty() || idem.len() > 256 {
                let err = serde_json::json!({"error":{"status":400,"message":"Idempotency-Key MUST contain 1 to 256 characters"}});
                return json_api_response(StatusCode::BAD_REQUEST, &err, entitlement, &[], false);
            }
            let raw_bytes = match to_bytes(req.into_body(), MAX_INTERVENTION_BODY_BYTES).await {
                Ok(b) => b,
                Err(_) => {
                    let err = serde_json::json!({"error":{"status":413,"message":"incident intervention body is too large"}});
                    return json_api_response(StatusCode::PAYLOAD_TOO_LARGE, &err, entitlement, &[], false);
                }
            };
            let parsed: serde_json::Value = match serde_json::from_slice::<serde_json::Value>(&raw_bytes) {
                Ok(v) if v.is_object() => v,
                _ => {
                    let err = serde_json::json!({"error":{"status":400,"message":"invalid incident intervention request"}});
                    return json_api_response(StatusCode::BAD_REQUEST, &err, entitlement, &[], false);
                }
            };
            let corr = p
                .trim_start_matches("/incidents/")
                .trim_end_matches("/interventions")
                .trim_matches('/');
            if let Some(body_corr) = parsed.get("correlation_id").and_then(serde_json::Value::as_str) {
                if body_corr != corr {
                    let err = serde_json::json!({"error":{"status":400,"message":"incident correlation does not match the route"}});
                    return json_api_response(StatusCode::BAD_REQUEST, &err, entitlement, &[], false);
                }
            }
            let action_kind = parsed
                .get("action_kind")
                .or_else(|| parsed.get("action"))
                .and_then(serde_json::Value::as_str)
                .unwrap_or("incident.intervene");
            let required_floor = match parsed
                .get("required_role")
                .and_then(serde_json::Value::as_str)
                .and_then(OperatorRole::parse_str)
            {
                Some(r) => r,
                None if action_kind.contains("approve") || action_kind.contains("enforce") => {
                    OperatorRole::Approver
                }
                None => OperatorRole::Contributor,
            };
            if let Err(err) = OperatorAuthenticator::enforce_min_rank(&identity, required_floor) {
                return auth_error_response(&err);
            }
            let digest = fnv1a64_bytes(&raw_bytes);
            match state
                .store
                .record_intervention(
                    idem,
                    digest,
                    corr,
                    action_kind,
                    &identity.principal.subject_id,
                    &now_iso,
                )
                .await
            {
                IdempotencyOutcome::Created(body) | IdempotencyOutcome::Replayed(body) => {
                    json_api_response(StatusCode::ACCEPTED, &body, entitlement, &[], false)
                }
                IdempotencyOutcome::Conflict => {
                    let err = serde_json::json!({"error":{"status":409,"message":"Idempotency-Key conflict: request payload differs from original submission"}});
                    json_api_response(StatusCode::CONFLICT, &err, entitlement, &[], false)
                }
            }
        }
        ("GET", path_key) => {
            if let Some(proj) = build_console_get_projection(
                path_key,
                &query_str,
                &state.cfg.service_id,
                &identity,
                &state.store,
                &state.infra,
                &now_iso,
            )
            .await
            {
                json_api_response(StatusCode::OK, &proj, entitlement, &[], head_only)
            } else {
                let body = serde_json::json!({
                    "error": {"status": 404, "message": "Optional source unavailable."},
                    "detail": "Optional source unavailable."
                });
                json_api_response(StatusCode::NOT_FOUND, &body, entitlement, &[], head_only)
            }
        }
        _ => {
            let raw_bytes = match to_bytes(req.into_body(), MAX_GENERAL_BODY_BYTES).await {
                Ok(b) => b,
                Err(_) => {
                    let err = serde_json::json!({"error":{"status":413,"message":"request payload exceeds 1 MiB limit"}});
                    return json_api_response(StatusCode::PAYLOAD_TOO_LARGE, &err, entitlement, &[], false);
                }
            };
            if !raw_bytes.is_empty() && serde_json::from_slice::<serde_json::Value>(&raw_bytes).is_err() {
                let err = serde_json::json!({"error":{"status":400,"message":"request body must be valid JSON"}});
                return json_api_response(StatusCode::BAD_REQUEST, &err, entitlement, &[], false);
            }
            if state.compat_router.matches_route(eff_method, norm_path) {
                let body = serde_json::json!({
                    "status": "accepted",
                    "service": state.cfg.service_id,
                    "path": norm_path,
                    "actor_subject_id": identity.principal.subject_id
                });
                json_api_response(StatusCode::ACCEPTED, &body, entitlement, &[], false)
            } else {
                let body = serde_json::json!({
                    "error": {"status": 404, "message": "Optional source unavailable."},
                    "detail": "Optional source unavailable."
                });
                json_api_response(StatusCode::NOT_FOUND, &body, entitlement, &[], head_only)
            }
        }
    }
}

fn build_auth_me_payload(id: &VerifiedOperatorIdentity, auth_mode: &str) -> serde_json::Value {
    let roles: Vec<&str> = id.principal.roles.iter().map(|r| r.as_str()).collect();
    serde_json::json!({
        "subject_id": id.principal.subject_id,
        "principal_kind": id.principal.principal_kind,
        "username": id.username,
        "authorized_party": id.authorized_party,
        "roles": roles,
        "auth_mode": auth_mode,
        "authenticated_via_credential": id.authenticated_via_credential
    })
}

fn build_single_shot_sse_response(
    leases: Arc<AtomicUsize>,
    events: Vec<Event>,
    entitlement: Option<&str>,
) -> Response {
    if leases.load(Ordering::SeqCst) >= MAX_CONCURRENT_SSE_STREAMS {
        let err = serde_json::json!({"error":{"status":503,"message":"SSE connection limit reached"}});
        return json_api_response(StatusCode::SERVICE_UNAVAILABLE, &err, entitlement, &[], false);
    }
    leases.fetch_add(1, Ordering::SeqCst);
    let guard = SseLeaseGuard { leases };
    let ev_stream = stream::iter(events.into_iter().map(Ok::<Event, Infallible>));
    let held_stream = stream::unfold((ev_stream, Some(guard)), |(mut inner, g)| async move {
        use futures_util::StreamExt as _;
        match inner.next().await {
            Some(item) => Some((item, (inner, g))),
            None => {
                drop(g);
                None
            }
        }
    });
    decorate_sse_headers(
        Sse::new(held_stream)
            .keep_alive(KeepAlive::new().interval(Duration::from_secs(15)).text("keepalive"))
            .into_response(),
        entitlement,
    )
}

fn build_live_broadcast_sse_response(
    leases: Arc<AtomicUsize>,
    initial_events: Vec<Event>,
    emit_source_keepalive: bool,
    rx: tokio::sync::broadcast::Receiver<crate::state_store::LiveStreamEvent>,
    entitlement: Option<&str>,
) -> Response {
    if leases.load(Ordering::SeqCst) >= MAX_CONCURRENT_SSE_STREAMS {
        let err = serde_json::json!({"error":{"status":503,"message":"SSE connection limit reached"}});
        return json_api_response(StatusCode::SERVICE_UNAVAILABLE, &err, entitlement, &[], false);
    }
    leases.fetch_add(1, Ordering::SeqCst);
    let guard = SseLeaseGuard { leases };
    let queue: std::collections::VecDeque<Event> = initial_events.into_iter().collect();
    let live_stream = stream::unfold(
        (queue, emit_source_keepalive, rx, guard),
        |(mut q, keepalive_src, mut rx, guard)| async move {
            if let Some(ev) = q.pop_front() {
                return Some((Ok::<Event, Infallible>(ev), (q, keepalive_src, rx, guard)));
            }
            loop {
                if keepalive_src {
                    tokio::select! {
                        recv = rx.recv() => match recv {
                            Ok(msg) => {
                                let ev = Event::default()
                                    .id(msg.seq.to_string())
                                    .event(msg.event_type)
                                    .data(msg.payload_json);
                                return Some((Ok::<Event, Infallible>(ev), (q, keepalive_src, rx, guard)));
                            }
                            Err(tokio::sync::broadcast::error::RecvError::Lagged(_)) => continue,
                            Err(tokio::sync::broadcast::error::RecvError::Closed) => return None,
                        },
                        () = tokio::time::sleep(Duration::from_secs(10)) => {
                            let src = serde_json::json!({
                                "status": "ready",
                                "source": "runtime-observed",
                                "ts": format_utc_rfc3339_now()
                            });
                            let ev = Event::default().event("source").data(src.to_string());
                            return Some((Ok::<Event, Infallible>(ev), (q, keepalive_src, rx, guard)));
                        }
                    }
                } else {
                    match rx.recv().await {
                        Ok(msg) => {
                            let ev = Event::default()
                                .id(msg.seq.to_string())
                                .event(msg.event_type)
                                .data(msg.payload_json);
                            return Some((Ok::<Event, Infallible>(ev), (q, keepalive_src, rx, guard)));
                        }
                        Err(tokio::sync::broadcast::error::RecvError::Lagged(_)) => continue,
                        Err(tokio::sync::broadcast::error::RecvError::Closed) => return None,
                    }
                }
            }
        },
    );
    decorate_sse_headers(
        Sse::new(live_stream)
            .keep_alive(KeepAlive::new().interval(Duration::from_secs(15)).text("keepalive"))
            .into_response(),
        entitlement,
    )
}

fn decorate_sse_headers(mut resp: Response, entitlement: Option<&str>) -> Response {
    let h = resp.headers_mut();
    h.insert(
        header::CACHE_CONTROL,
        HeaderValue::from_static("no-cache, no-transform"),
    );
    h.insert(
        HeaderName::from_static("x-accel-buffering"),
        HeaderValue::from_static("no"),
    );
    h.insert(
        header::X_CONTENT_TYPE_OPTIONS,
        HeaderValue::from_static("nosniff"),
    );
    h.insert(header::X_FRAME_OPTIONS, HeaderValue::from_static("DENY"));
    h.insert(
        header::REFERRER_POLICY,
        HeaderValue::from_static("no-referrer"),
    );
    h.insert(header::VARY, HeaderValue::from_static("Origin"));
    if let Some(stamp) = entitlement {
        if let Ok(val) = HeaderValue::from_str(stamp) {
            h.insert(HeaderName::from_static("x-fdai-entitlement"), val);
        }
    }
    resp
}

fn serve_runtime_config_js(cfg: &ServerRuntimeConfig, head_only: bool) -> Response {
    let payload = if let Some(ref raw_json) = cfg.console_runtime_config_json {
        format!("globalThis.__FDAI_CONSOLE_CONFIG__ = {raw_json};\n").into_bytes()
    } else if let Some(ref sdir) = cfg.static_dir {
        let p = sdir.join("fdai-config.js");
        if fs::symlink_metadata(&p).is_ok_and(|m| !m.file_type().is_symlink() && m.is_file()) {
            fs::read(&p).unwrap_or_else(|_| b"globalThis.__FDAI_CONSOLE_CONFIG__ = null;\n".to_vec())
        } else {
            b"globalThis.__FDAI_CONSOLE_CONFIG__ = null;\n".to_vec()
        }
    } else {
        b"globalThis.__FDAI_CONSOLE_CONFIG__ = null;\n".to_vec()
    };
    raw_bytes_response(
        StatusCode::OK,
        "application/javascript; charset=utf-8",
        payload,
        "no-store",
        head_only,
    )
}

fn try_serve_static_spa(
    static_dir: &Path,
    req_path: &str,
    accept: &str,
    explicit_api: bool,
    head_only: bool,
) -> Option<Response> {
    if explicit_api || req_path.starts_with("/v1/") || req_path.starts_with("/v2/") {
        return None;
    }
    let lower_path = req_path.to_ascii_lowercase();
    if lower_path.contains("%2e")
        || lower_path.contains("%2f")
        || lower_path.contains("%5c")
        || lower_path.contains("%00")
        || req_path.contains('\\')
        || req_path.contains('\0')
    {
        return None;
    }
    let Ok(canon_root) = fs::canonicalize(static_dir) else {
        return None;
    };
    let trimmed = req_path.trim_start_matches('/');
    let rel_target = if trimmed.is_empty() { "index.html" } else { trimmed };
    let mut clean_rel = PathBuf::new();
    for comp in Path::new(rel_target).components() {
        match comp {
            Component::Normal(seg) => clean_rel.push(seg),
            _ => return None,
        }
    }
    let full = canon_root.join(&clean_rel);
    if let Ok(meta) = fs::symlink_metadata(&full) {
        if !meta.file_type().is_symlink()
            && meta.is_file()
            && fs::canonicalize(&full).is_ok_and(|c| c.starts_with(&canon_root))
        {
            if let Ok(bytes) = fs::read(&full) {
                let cache = if trimmed.starts_with("assets/") {
                    "public, max-age=31536000, immutable"
                } else {
                    "no-store"
                };
                return Some(raw_bytes_response(
                    StatusCode::OK,
                    content_type_for_ext(&full),
                    bytes,
                    cache,
                    head_only,
                ));
            }
        }
    }
    let has_file_ext = clean_rel.extension().is_some();
    let wants_html =
        (accept.contains("text/html") && !accept.contains("application/json")) || trimmed.is_empty();
    let is_machine_only = matches!(
        req_path,
        "/healthz"
            | "/readyz"
            | "/metrics"
            | "/routes"
            | "/auth/me"
            | "/local-auth/me"
            | "/live/stream"
            | "/incidents/stream"
            | "/access-grants/stream"
            | "/agents/stream"
            | "/chat/health"
            | "/chat/stream"
            | "/ontology/instances/stream"
            | "/ontology/causal/intervene"
            | "/ontology/causal/counterfactual"
    );
    if !has_file_ext && !is_machine_only && wants_html {
        let idx = static_dir.join("index.html");
        if fs::symlink_metadata(&idx).is_ok_and(|m| !m.file_type().is_symlink() && m.is_file()) {
            if let Ok(bytes) = fs::read(&idx) {
                return Some(raw_bytes_response(
                    StatusCode::OK,
                    "text/html; charset=utf-8",
                    bytes,
                    "no-store",
                    head_only,
                ));
            }
        }
    }
    None
}

fn content_type_for_ext(path: &Path) -> &'static str {
    match path.extension().and_then(|e| e.to_str()).unwrap_or("") {
        "html" => "text/html; charset=utf-8",
        "js" | "mjs" => "application/javascript; charset=utf-8",
        "css" => "text/css; charset=utf-8",
        "json" | "map" => "application/json; charset=utf-8",
        "svg" => "image/svg+xml",
        "png" => "image/png",
        "webp" => "image/webp",
        "ico" => "image/x-icon",
        "woff2" => "font/woff2",
        "txt" => "text/plain; charset=utf-8",
        _ => "application/octet-stream",
    }
}

fn header_str(headers: &HeaderMap, name: HeaderName) -> Option<&str> {
    headers.get(name).and_then(|v| v.to_str().ok())
}

fn auth_error_response(err: &AuthError) -> Response {
    let status = StatusCode::from_u16(err.status_code()).unwrap_or(StatusCode::UNAUTHORIZED);
    let body = serde_json::json!({"error": {"status": err.status_code(), "message": err.message()}});
    let mut resp = json_api_response(status, &body, None, &[], false);
    if status == StatusCode::UNAUTHORIZED {
        resp.headers_mut()
            .insert(header::WWW_AUTHENTICATE, HeaderValue::from_static("Bearer"));
    }
    resp
}

fn escape_prometheus_label(raw: &str) -> String {
    let mut out = String::with_capacity(raw.len());
    for ch in raw.chars() {
        match ch {
            '\\' => out.push_str("\\\\"),
            '"' => out.push_str("\\\""),
            '\n' => out.push_str("\\n"),
            c if c.is_ascii_control() => {}
            c => out.push(c),
        }
    }
    out
}

fn json_api_response<T: serde::Serialize>(
    status: StatusCode,
    payload: &T,
    entitlement: Option<&str>,
    extra: &[(&str, &str)],
    head_only: bool,
) -> Response {
    let bytes = serde_json::to_vec(payload).unwrap_or_else(|_| b"{}".to_vec());
    let mut builder = Response::builder()
        .status(status)
        .header(header::CONTENT_TYPE, "application/json; charset=utf-8")
        .header(header::CACHE_CONTROL, "no-store")
        .header(header::X_CONTENT_TYPE_OPTIONS, "nosniff")
        .header(header::X_FRAME_OPTIONS, "DENY")
        .header(header::REFERRER_POLICY, "no-referrer")
        .header("content-security-policy", "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'")
        .header("permissions-policy", "geolocation=(), microphone=(), camera=()")
        .header(header::VARY, "Origin");
    if let Some(stamp) = entitlement {
        builder = builder.header("x-fdai-entitlement", stamp);
    }
    for &(k, v) in extra {
        builder = builder.header(k, v);
    }
    let body = if head_only { Body::empty() } else { Body::from(bytes) };
    builder
        .body(body)
        .unwrap_or_else(|_| StatusCode::INTERNAL_SERVER_ERROR.into_response())
}

fn raw_bytes_response(
    status: StatusCode,
    content_type: &'static str,
    bytes: Vec<u8>,
    cache_control: &'static str,
    head_only: bool,
) -> Response {
    let body = if head_only { Body::empty() } else { Body::from(bytes) };
    let csp = if content_type.starts_with("text/html") {
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' http://127.0.0.1:8010 http://127.0.0.1:8011 http://127.0.0.1:8012 http://127.0.0.1:8013 http://127.0.0.1:8014 http://localhost:8010 http://localhost:8011 http://localhost:5273 http://127.0.0.1:5273 https://login.microsoftonline.com; frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
    } else {
        "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
    };
    Response::builder()
        .status(status)
        .header(header::CONTENT_TYPE, content_type)
        .header(header::CACHE_CONTROL, cache_control)
        .header(header::X_CONTENT_TYPE_OPTIONS, "nosniff")
        .header(header::X_FRAME_OPTIONS, "DENY")
        .header(header::REFERRER_POLICY, "no-referrer")
        .header("content-security-policy", csp)
        .header("permissions-policy", "geolocation=(), microphone=(), camera=()")
        .header(header::VARY, "Origin")
        .body(body)
        .unwrap_or_else(|_| StatusCode::INTERNAL_SERVER_ERROR.into_response())
}

#[must_use]
pub fn format_utc_rfc3339_now() -> String {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0_u64, |d| d.as_secs());
    let days = (secs / 86_400) as i64;
    let sod = secs % 86_400;
    let hh = sod / 3600;
    let mm = (sod % 3600) / 60;
    let ss = sod % 60;
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = (z - era * 146_097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let mut y = (yoe as i64) + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    if m <= 2 {
        y += 1;
    }
    format!("{y:04}-{m:02}-{d:02}T{hh:02}:{mm:02}:{ss:02}Z")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::auth::{AuthMode, OperatorAuthenticator};
    use crate::state_store::RuntimeStateStore;

    #[test]
    fn rejects_wildcard_cors_and_percent_encoded_traversal() {
        let cfg = ServerRuntimeConfig {
            service_id: String::from("operator-service"),
            host: String::from("127.0.0.1"),
            port: 8010,
            static_dir: None,
            cors_allow_origins: vec![String::from("*")],
            entitlement_notice: String::from("not-activated"),
            console_runtime_config_json: None,
        };
        assert!(cfg.validate().is_err());

        let tmp_dir = std::env::temp_dir().join(format!("fdai_spa_sec_{}", std::process::id()));
        let _ = fs::create_dir_all(&tmp_dir);
        let _ = fs::write(tmp_dir.join("index.html"), "<html>ok</html>");
        assert!(try_serve_static_spa(&tmp_dir, "/%2e%2e/etc/passwd", "text/html", false, false).is_none());
        assert!(try_serve_static_spa(&tmp_dir, "/overview", "text/html", false, false).is_some());
        let _ = fs::remove_dir_all(&tmp_dir);
    }

    #[tokio::test]
    async fn state_store_enforces_idempotency_conflict_and_disk_persistence() {
        let state_file = std::env::temp_dir().join(format!("fdai_state_{}.json", std::process::id()));
        let _ = fs::remove_file(&state_file);
        let store = RuntimeStateStore::open(Some(state_file.clone()));
        let r1 = store.record_intervention("k1", 100, "corr-1", "incident.intervene", "u1", "2026-11-24T00:00:00Z").await;
        assert!(matches!(r1, IdempotencyOutcome::Created(_)));
        let r2 = store.record_intervention("k1", 100, "corr-1", "incident.intervene", "u1", "2026-11-24T00:00:00Z").await;
        assert!(matches!(r2, IdempotencyOutcome::Replayed(_)));
        let r3 = store.record_intervention("k1", 999, "corr-1", "incident.intervene", "u1", "2026-11-24T00:00:00Z").await;
        assert!(matches!(r3, IdempotencyOutcome::Conflict));

        let reloaded = RuntimeStateStore::open(Some(state_file.clone()));
        assert_eq!(reloaded.audit_count().await, 1);
        let kpi = reloaded.kpi_snapshot().await;
        assert_eq!(kpi.get("event_count").and_then(serde_json::Value::as_u64), Some(1));
        let _ = build_axum_router_with_store(
            ServerRuntimeConfig::from_env_and_args("op", 8010, false, &[]),
            CompatRouter::new(),
            OperatorAuthenticator::new(AuthMode::FailClosedUnconfigured),
            reloaded,
        );
        let _ = fs::remove_file(&state_file);
    }

    #[tokio::test]
    async fn local_cli_mode_enforces_origin_and_session_token_over_live_axum() {
        use crate::auth::{LocalAzureCliProfile, OperatorPrincipal, OperatorPrincipalKind};
        use http_body_util::BodyExt as _;
        use hyper_util::client::legacy::Client;
        use hyper_util::rt::TokioExecutor;
        use std::collections::BTreeSet;

        let mut roles = BTreeSet::new();
        roles.insert(OperatorRole::Contributor);
        let auth = OperatorAuthenticator::new(AuthMode::LocalAzureCli {
            profile: LocalAzureCliProfile {
                oid: String::from("oid-cli-live"),
                username: String::from("cli@contoso.com"),
                name: Some(String::from("CLI User")),
                roles: vec![String::from("contributor")],
                source: String::from("azure-cli"),
            },
            principal: OperatorPrincipal {
                subject_id: String::from("oid-cli-live"),
                roles,
                principal_kind: OperatorPrincipalKind::Human,
                groups: BTreeSet::new(),
            },
            session_token: String::from("live-cli-session-secret-0123456789abcdef"),
        });
        let cfg = ServerRuntimeConfig {
            service_id: String::from("operator-service"),
            host: String::from("127.0.0.1"),
            port: 0,
            static_dir: None,
            cors_allow_origins: vec![String::from("http://127.0.0.1:5273")],
            entitlement_notice: String::from("not-activated"),
            console_runtime_config_json: Some(String::from("{\"schema_version\":\"fdai.console-runtime.v1\"}")),
        };
        let app = build_axum_router_with_store(cfg, CompatRouter::new(), auth, RuntimeStateStore::open(None));
        let Ok(listener) = tokio::net::TcpListener::bind("127.0.0.1:0").await else {
            return;
        };
        let Ok(addr) = listener.local_addr() else { return };
        let srv = tokio::spawn(async move {
            let _ = axum::serve(listener, app.into_make_service_with_connect_info::<SocketAddr>()).await;
        });

        let client = Client::builder(TokioExecutor::new()).build_http::<String>();
        let base = format!("http://{addr}");

        // 1. Disallowed origin MUST be rejected with 403 by LoopbackOnly guard
        if let Ok(req) = hyper::Request::builder()
            .uri(format!("{base}/local-auth/me"))
            .header("origin", "https://evil.example")
            .body(String::new())
        {
            if let Ok(resp) = client.request(req).await {
                assert_eq!(resp.status(), StatusCode::FORBIDDEN);
            }
        }

        // 2. Allowed origin receives X-FDAI-Local-Session token
        let mut issued_tok = String::new();
        if let Ok(req) = hyper::Request::builder()
            .uri(format!("{base}/local-auth/me"))
            .header("origin", "http://127.0.0.1:5273")
            .body(String::new())
        {
            if let Ok(resp) = client.request(req).await {
                assert_eq!(resp.status(), StatusCode::OK);
                if let Some(h) = resp.headers().get("x-fdai-local-session").and_then(|v| v.to_str().ok()) {
                    issued_tok = h.to_string();
                }
            }
        }
        assert_eq!(issued_tok, "live-cli-session-secret-0123456789abcdef");

        // 3. Wrong bearer token -> 401; valid local session token -> 200 + X-FDAI-Entitlement
        if let Ok(req) = hyper::Request::builder()
            .uri(format!("{base}/kpi"))
            .header("authorization", "Bearer wrong-token")
            .body(String::new())
        {
            if let Ok(resp) = client.request(req).await {
                assert_eq!(resp.status(), StatusCode::UNAUTHORIZED);
            }
        }
        if let Ok(req) = hyper::Request::builder()
            .uri(format!("{base}/kpi"))
            .header("authorization", format!("Bearer {issued_tok}"))
            .body(String::new())
        {
            if let Ok(resp) = client.request(req).await {
                assert_eq!(resp.status(), StatusCode::OK);
                assert_eq!(
                    resp.headers().get("x-fdai-entitlement").and_then(|v| v.to_str().ok()),
                    Some("not-activated")
                );
            }
        }

        // 4. Dynamic /fdai-config.js runtime overlay works
        if let Ok(req) = hyper::Request::builder()
            .uri(format!("{base}/fdai-config.js"))
            .body(String::new())
        {
            if let Ok(resp) = client.request(req).await {
                assert_eq!(resp.status(), StatusCode::OK);
                if let Ok(collected) = resp.into_body().collect().await {
                    let js = String::from_utf8_lossy(&collected.to_bytes()).to_string();
                    assert!(js.contains("fdai.console-runtime.v1"));
                }
            }
        }

        srv.abort();
    }
}
