//! Pure-Rust Axum library root for FDAI Console v4 (`fdai-console-v4`).

pub mod assets;
pub mod db;
pub mod domains;
pub mod repos;
pub mod shell;
pub mod upstream;

use axum::{
    extract::State,
    http::{header, HeaderValue, Method, StatusCode},
    middleware::{self, Next},
    response::{
        sse::{Event, KeepAlive, Sse},
        IntoResponse, Redirect, Response,
    },
    routing::get,
    Json, Router,
};
use futures_util::stream;
use serde_json::json;
use std::convert::Infallible;
use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, OnceLock};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tokio::sync::Semaphore;
use tower_http::cors::{AllowOrigin, CorsLayer};

use crate::db::{cell_i64, cell_str, DbHandle};
use crate::upstream::UpstreamClient;

const MAX_GLOBAL_PULSE_STREAMS: usize = 128;
const MAX_PULSE_TICKS: u64 = 12;
static GLOBAL_PULSE_SEM: OnceLock<Semaphore> = OnceLock::new();
static PULSE_CACHE: OnceLock<tokio::sync::RwLock<Option<(Instant, serde_json::Value)>>> = OnceLock::new();

fn global_pulse_semaphore() -> &'static Semaphore {
    GLOBAL_PULSE_SEM.get_or_init(|| Semaphore::new(MAX_GLOBAL_PULSE_STREAMS))
}

fn pulse_cache() -> &'static tokio::sync::RwLock<Option<(Instant, serde_json::Value)>> {
    PULSE_CACHE.get_or_init(|| tokio::sync::RwLock::new(None))
}

/// RAII drop guard that tracks active SSE stream leases across all domains.
pub struct SseLeaseDropGuard {
    active: Arc<AtomicUsize>,
}

impl SseLeaseDropGuard {
    #[must_use]
    pub fn acquire(active: Arc<AtomicUsize>) -> Self {
        active.fetch_add(1, Ordering::SeqCst);
        Self { active }
    }
}

impl Drop for SseLeaseDropGuard {
    fn drop(&mut self) {
        self.active.fetch_sub(1, Ordering::SeqCst);
    }
}

#[derive(Clone)]
pub struct AppState {
    pub operator_url: String,
    pub upstream: UpstreamClient,
    pub db: DbHandle,
    pub active_sse: Arc<AtomicUsize>,
    pub brand_dir: PathBuf,
    pub azure_icons_dir: PathBuf,
    pub agent_icons_dir: PathBuf,
}

impl AppState {
    pub fn from_repo_root(repo_root: PathBuf, operator_url: String) -> Self {
        let upstream = UpstreamClient::new(operator_url.clone());
        let db = DbHandle::from_env();
        let brand_dir = {
            let rust_owned = repo_root.join("console_rs/assets/brand");
            if rust_owned.is_dir() { rust_owned } else { repo_root.join("console/public/brand") }
        };
        let agent_icons_dir = {
            let rust_owned = repo_root.join("console_rs/assets/agent-icons");
            if rust_owned.is_dir() { rust_owned } else { repo_root.join("console/public/agent-icons") }
        };
        Self {
            operator_url,
            upstream,
            db,
            active_sse: Arc::new(AtomicUsize::new(0)),
            brand_dir,
            azure_icons_dir: repo_root.join("tools/architecture-diagrams/assets/azure"),
            agent_icons_dir,
        }
    }

    pub fn from_repo_root_with_local_db(repo_root: PathBuf, operator_url: String) -> Self {
        let upstream = UpstreamClient::new(operator_url.clone());
        let db = DbHandle::from_env_or_local_runtime(&repo_root);
        let brand_dir = {
            let rust_owned = repo_root.join("console_rs/assets/brand");
            if rust_owned.is_dir() { rust_owned } else { repo_root.join("console/public/brand") }
        };
        let agent_icons_dir = {
            let rust_owned = repo_root.join("console_rs/assets/agent-icons");
            if rust_owned.is_dir() { rust_owned } else { repo_root.join("console/public/agent-icons") }
        };
        Self {
            operator_url,
            upstream,
            db,
            active_sse: Arc::new(AtomicUsize::new(0)),
            brand_dir,
            azure_icons_dir: repo_root.join("tools/architecture-diagrams/assets/azure"),
            agent_icons_dir,
        }
    }
}

async fn apply_security_headers(
    req: axum::http::Request<axum::body::Body>,
    next: Next,
) -> Response {
    let mut resp = next.run(req).await;
    let headers = resp.headers_mut();
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

fn build_cors_layer() -> CorsLayer {
    let mut allowed: Vec<HeaderValue> = vec![
        HeaderValue::from_static("http://127.0.0.1:5290"),
        HeaderValue::from_static("http://localhost:5290"),
        HeaderValue::from_static("http://127.0.0.1:5273"),
        HeaderValue::from_static("http://localhost:5273"),
        HeaderValue::from_static("http://127.0.0.1:8010"),
    ];
    if let Ok(extra) = std::env::var("FDAI_CONSOLE_V4_CORS_ORIGINS") {
        for raw in extra.split(',') {
            let trimmed = raw.trim();
            if !trimmed.is_empty() && trimmed != "*" {
                if let Ok(val) = HeaderValue::from_str(trimmed) {
                    allowed.push(val);
                }
            }
        }
    }
    CorsLayer::new()
        .allow_origin(AllowOrigin::list(allowed))
        .allow_methods([
            Method::GET,
            Method::POST,
            Method::PUT,
            Method::PATCH,
            Method::DELETE,
            Method::OPTIONS,
        ])
        .allow_headers([
            header::CONTENT_TYPE,
            header::AUTHORIZATION,
            header::ACCEPT,
        ])
}

pub fn build_router(state: AppState) -> Router {
    let cors = build_cors_layer();

    Router::new()
        .route("/healthz", get(healthz))
        .route("/readyz", get(readyz))
        .route("/api/v4/meta", get(api_meta))
        .route("/api/v4/live/pulse", get(api_live_pulse_stream))
        // Legacy mockup path redirects so zero links ever 404
        .route("/mockup-overview.html", get(|| async { Redirect::temporary("/overview") }))
        .route("/mockup-operations.html", get(|| async { Redirect::temporary("/operations") }))
        .route("/mockup-agents.html", get(|| async { Redirect::temporary("/agents") }))
        .route("/mockup-governance.html", get(|| async { Redirect::temporary("/governance") }))
        .route("/mockup-evidence.html", get(|| async { Redirect::temporary("/evidence") }))
        .route("/mockup-settings-labs.html", get(|| async { Redirect::temporary("/settings") }))
        .route("/mockup-chat.html", get(|| async { Redirect::temporary("/chat") }))
        .route("/overview-components.html", get(|| async { Redirect::temporary("/components") }))
        .merge(assets::router())
        .merge(domains::router())
        .layer(middleware::from_fn(apply_security_headers))
        .layer(cors)
        .with_state(state)
}

async fn healthz() -> Response {
    (
        StatusCode::OK,
        Json(json!({
            "status": "ok",
            "service": "fdai-console-v4",
            "engine": "pure-rust-axum",
            "python_free": true
        })),
    )
        .into_response()
}

async fn readyz(State(state): State<AppState>) -> Response {
    let up = state.upstream.get_json("/healthz", None).await;
    let db_snap = state.db.health_snapshot().await;
    (
        StatusCode::OK,
        Json(json!({
            "status": "ready",
            "service": "fdai-console-v4",
            "operator_service_url": state.operator_url,
            "operator_service_reachable": up.reachable,
            "operator_service_status": up.status,
            "db_configured": db_snap.configured,
            "db_reachable": db_snap.reachable,
            "active_sse_leases": state.active_sse.load(Ordering::SeqCst),
            "domains_registered": 8,
            "total_panels": domains::all_panel_ids().len()
        })),
    )
        .into_response()
}

async fn api_meta(State(state): State<AppState>) -> Response {
    Json(json!({
        "service": "fdai-console-v4",
        "engine": "pure-rust-axum",
        "python_free": true,
        "db_configured": state.db.is_configured(),
        "operator_url": state.operator_url,
        "domains": domains::domain_manifest(),
        "total_panels": domains::all_panel_ids().len()
    }))
    .into_response()
}

async fn sample_live_pulse(db: &DbHandle, tick: u64, prev_audit_seq: &mut i64, prev_watermark: &mut i64) -> serde_json::Value {
    let observed_epoch_ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0);
    if !db.is_configured() {
        return json!({
            "measurement_status": "not-measured",
            "source": "postgres-direct",
            "tick": tick,
            "observed_epoch_ms": observed_epoch_ms,
            "reason": "db_unconfigured"
        });
    }
    let t0 = Instant::now();
    let (audit_agg, audit_last, res_agg, lin_last, inc_agg) = tokio::join!(
        db.query_single_readonly(
            "SELECT count(*), COALESCE(max(seq), 0), \
             count(*) FILTER (WHERE action_kind = 'hil.requested'), \
             count(*) FILTER (WHERE action_kind = 'hil.timeout') \
             FROM audit_log"
        ),
        db.query_single_readonly(
            "SELECT seq, actor, action_kind, \
             COALESCE(entry->>'resource_type', entry->>'target', ''), \
             to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') \
             FROM audit_log ORDER BY seq DESC LIMIT 1"
        ),
        db.query_single_readonly(
            "SELECT count(*), count(*) FILTER (WHERE object_type = 'Resource') FROM ontology_resource"
        ),
        db.query_single_readonly(
            "SELECT watermark, subject_ref, mutation_kind, source_identity \
             FROM inventory_observation_journal ORDER BY watermark DESC LIMIT 1"
        ),
        db.query_single_readonly(
            "SELECT count(*) FILTER (WHERE projected_state NOT IN ('resolved', 'closed')), count(*) \
             FROM operator_incident_projection"
        ),
    );
    let db_latency_ms = t0.elapsed().as_millis() as u64;
    let Ok(aa) = audit_agg else {
        return json!({
            "measurement_status": "not-measured",
            "source": "postgres-direct",
            "tick": tick,
            "db_latency_ms": db_latency_ms,
            "observed_epoch_ms": observed_epoch_ms,
            "reason": "postgres_unreachable"
        });
    };
    let aar = aa.rows.first().map(Vec::as_slice).unwrap_or(&[]);
    let audit_total = cell_i64(aar, 0).unwrap_or(0);
    let audit_latest_seq = cell_i64(aar, 1).unwrap_or(0);
    let hil_pending = (cell_i64(aar, 2).unwrap_or(0) - cell_i64(aar, 3).unwrap_or(0)).max(0);

    let alr = audit_last
        .ok()
        .and_then(|r| r.rows.into_iter().next())
        .unwrap_or_default();
    let rr = res_agg
        .ok()
        .and_then(|r| r.rows.into_iter().next())
        .unwrap_or_default();
    let lr = lin_last
        .ok()
        .and_then(|r| r.rows.into_iter().next())
        .unwrap_or_default();
    let ir = inc_agg
        .ok()
        .and_then(|r| r.rows.into_iter().next())
        .unwrap_or_default();

    let journal_watermark = cell_i64(&lr, 0).unwrap_or(0);
    let delta_audit = if *prev_audit_seq > 0 {
        (audit_latest_seq - *prev_audit_seq).max(0)
    } else {
        0
    };
    let delta_watermark = if *prev_watermark > 0 {
        (journal_watermark - *prev_watermark).max(0)
    } else {
        0
    };
    *prev_audit_seq = audit_latest_seq;
    *prev_watermark = journal_watermark;

    json!({
        "measurement_status": "measured",
        "source": "postgres-direct",
        "tick": tick,
        "db_latency_ms": db_latency_ms,
        "observed_epoch_ms": observed_epoch_ms,
        "audit_total": audit_total,
        "audit_latest_seq": audit_latest_seq,
        "delta_audit": delta_audit,
        "latest_event": {
            "seq": cell_i64(&alr, 0).unwrap_or(audit_latest_seq),
            "actor": cell_str(&alr, 1),
            "action_kind": cell_str(&alr, 2),
            "target": cell_str(&alr, 3),
            "created_at": cell_str(&alr, 4)
        },
        "ontology_resources_total": cell_i64(&rr, 0).unwrap_or(0),
        "azure_resources_total": cell_i64(&rr, 1).unwrap_or(0),
        "journal_watermark": journal_watermark,
        "delta_watermark": delta_watermark,
        "latest_lineage": {
            "subject_ref": cell_str(&lr, 1),
            "mutation_kind": cell_str(&lr, 2),
            "source_identity": cell_str(&lr, 3)
        },
        "open_incidents": cell_i64(&ir, 0).unwrap_or(0),
        "total_incidents": cell_i64(&ir, 1).unwrap_or(0),
        "hil_pending": hil_pending
    })
}

async fn sample_live_pulse_cached(db: &DbHandle, tick: u64, prev_audit_seq: &mut i64, prev_watermark: &mut i64) -> serde_json::Value {
    if let Some((ts, cached)) = pulse_cache().read().await.as_ref() {
        if ts.elapsed() < Duration::from_secs(3) {
            let mut v = cached.clone();
            if let Some(obj) = v.as_object_mut() {
                obj.insert("tick".to_string(), json!(tick));
            }
            return v;
        }
    }
    let fresh = sample_live_pulse(db, tick, prev_audit_seq, prev_watermark).await;
    *pulse_cache().write().await = Some((Instant::now(), fresh.clone()));
    fresh
}

async fn api_live_pulse_stream(State(state): State<AppState>) -> Response {
    let Ok(permit) = global_pulse_semaphore().try_acquire() else {
        return (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(json!({ "error": "global_live_pulse_capacity_reached" })),
        )
            .into_response();
    };
    let lease = SseLeaseDropGuard::acquire(Arc::clone(&state.active_sse));
    let db = state.db.clone();
    let sse_stream = stream::unfold(
        (db, lease, permit, 0_u64, 0_i64, 0_i64),
        |(db, lease, permit, mut tick, mut prev_seq, mut prev_wm)| async move {
            if tick >= MAX_PULSE_TICKS {
                return None;
            }
            if tick > 0 {
                tokio::time::sleep(Duration::from_secs(4)).await;
            }
            tick = tick.saturating_add(1);
            let payload = sample_live_pulse_cached(&db, tick, &mut prev_seq, &mut prev_wm).await;
            let ev = Event::default().event("pulse").data(payload.to_string());
            Some((Ok::<Event, Infallible>(ev), (db, lease, permit, tick, prev_seq, prev_wm)))
        },
    );
    (
        [
            (header::CACHE_CONTROL, HeaderValue::from_static("no-store")),
            (
                header::X_CONTENT_TYPE_OPTIONS,
                HeaderValue::from_static("nosniff"),
            ),
        ],
        Sse::new(sse_stream).keep_alive(KeepAlive::new().interval(Duration::from_secs(15))),
    )
        .into_response()
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::body::Body;
    use axum::http::Request;
    use http_body_util::BodyExt;
    use tower::ServiceExt;

    fn test_state() -> AppState {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("."));
        AppState::from_repo_root(root, "http://127.0.0.1:8010".to_string())
    }

    #[tokio::test]
    async fn healthz_and_all_domain_pages_return_200() {
        let app = build_router(test_state());
        for path in [
            "/healthz",
            "/api/v4/meta",
            "/",
            "/overview",
            "/operations",
            "/agents",
            "/governance",
            "/evidence",
            "/settings",
            "/labs",
            "/chat",
            "/components",
            "/assets/fdai-console-shared.css",
            "/assets/fdai-console-shell.js",
            "/assets/fdai-console-live.js",
        ] {
            let req_res = Request::builder().uri(path).body(Body::empty());
            assert!(req_res.is_ok(), "failed to build request for {path}");
            if let Ok(req) = req_res {
                let Ok(resp) = app.clone().oneshot(req).await;
                assert_eq!(resp.status(), StatusCode::OK, "non-200 on {path}");
                let bytes_res = resp.into_body().collect().await;
                assert!(bytes_res.is_ok(), "body collect failed on {path}");
                if let Ok(collected) = bytes_res {
                    assert!(!collected.to_bytes().is_empty(), "empty body on {path}");
                }
            }
        }
    }

    #[test]
    fn all_65_panels_are_registered_without_duplicates() {
        let ids = domains::all_panel_ids();
        assert_eq!(ids.len(), 65);
        let uniq: std::collections::BTreeSet<&str> = ids.iter().copied().collect();
        assert_eq!(uniq.len(), 65);
    }

    #[tokio::test]
    async fn all_65_clean_canonical_panel_urls_return_200_without_hash() {
        let app = build_router(test_state());
        for pid in domains::all_panel_ids() {
            let path = shell::canonical_panel_path(pid);
            assert!(!path.contains('#'), "canonical path must not contain #: {path}");
            let req_res = Request::builder().uri(&path).body(Body::empty());
            assert!(req_res.is_ok(), "failed request build for {path}");
            if let Ok(req) = req_res {
                let Ok(resp) = app.clone().oneshot(req).await;
                assert_eq!(resp.status(), StatusCode::OK, "non-200 on clean URL {path}");
            }
        }
    }

    #[tokio::test]
    async fn legacy_flat_panel_urls_redirect_308_to_canonical_domain_path_preserving_query() {
        let app = build_router(test_state());
        for (legacy, expected) in [
            ("/architecture?scope=rg-fdai-dev-wus3&node=abc", "/governance/architecture?scope=rg-fdai-dev-wus3&node=abc"),
            ("/dashboard", "/overview/dashboard"),
            ("/rules?framework=mcsb", "/governance/rules?framework=mcsb"),
            ("/audit", "/evidence/audit"),
            ("/settings-general", "/settings/general"),
        ] {
            let req_res = Request::builder().uri(legacy).body(Body::empty());
            assert!(req_res.is_ok(), "failed request build for {legacy}");
            if let Ok(req) = req_res {
                let Ok(resp) = app.clone().oneshot(req).await;
                assert_eq!(resp.status(), StatusCode::PERMANENT_REDIRECT, "expected 308 on {legacy}");
                let loc = resp.headers().get(header::LOCATION).and_then(|v| v.to_str().ok()).unwrap_or("");
                assert_eq!(loc, expected, "unexpected redirect target for {legacy}");
            }
        }
    }
}
