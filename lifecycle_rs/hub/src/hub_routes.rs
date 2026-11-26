//! Complete Axum 0.8 router for Lifecycle Hub.

use crate::hub_catalog::{
    adopt_export_into_state, build_update_status_payload, compute_catalog_diff,
    fetch_and_verify_tuf_metadata, fetch_http_get_bounded, fetch_release_hub_catalog_preview,
    normalize_release_hub_endpoint, parse_export_releases, provision_from_release_catalog,
};
use crate::hub_state::{
    canonical_json_bytes, compute_settings_digest, detect_workstation_accounts,
    is_valid_installation_id, parse_strict_json_object, sha256_hex, ActiveEntraSession,
    BundleImportRecord, DestructiveConfirmationRecord, EntityRecord, HubError, InstallationRecord,
    LifecycleCommandRecord, LifecycleHubState, MaintenanceWindow, PendingEnrollmentRecord,
    PlanReportRecord, SuppressionRecord, MAX_APPROVAL_BYTES, MAX_CATALOG_BYTES,
    MAX_ENROLLMENT_BYTES, MAX_REPORT_BYTES, MAX_STATE_BYTES,
};
use fdai_http_runtime::axum::body::{to_bytes, Body};
use fdai_http_runtime::axum::extract::{Path as AxPath, Query, Request, State};
use fdai_http_runtime::axum::http::header::{self, HeaderName};
use fdai_http_runtime::axum::http::{HeaderMap, StatusCode};
use fdai_http_runtime::axum::response::Response;
use fdai_http_runtime::axum::routing::{get, post, put};
use fdai_http_runtime::axum::Router;
use fdai_http_runtime::format_utc_rfc3339_now;
use serde_json::{json, Map, Value};
use std::collections::BTreeMap;
use std::sync::Arc;

fn json_resp(status: StatusCode, val: &Value) -> Response {
    let bytes = serde_json::to_vec(val).unwrap_or_else(|_| b"{}".to_vec());
    Response::builder()
        .status(status)
        .header(header::CONTENT_TYPE, "application/json")
        .header(header::CACHE_CONTROL, "no-store")
        .header(HeaderName::from_static("x-content-type-options"), "nosniff")
        .header(HeaderName::from_static("x-frame-options"), "DENY")
        .header(HeaderName::from_static("referrer-policy"), "no-referrer")
        .header(
            HeaderName::from_static("content-security-policy"),
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
        )
        .body(Body::from(bytes))
        .unwrap_or_else(|_| Response::new(Body::empty()))
}

fn empty_resp(status: StatusCode) -> Response {
    Response::builder()
        .status(status)
        .header(header::CACHE_CONTROL, "no-store")
        .header(HeaderName::from_static("x-content-type-options"), "nosniff")
        .header(HeaderName::from_static("x-frame-options"), "DENY")
        .header(HeaderName::from_static("referrer-policy"), "no-referrer")
        .body(Body::empty())
        .unwrap_or_else(|_| Response::new(Body::empty()))
}

fn err_resp(e: &HubError) -> Response {
    let st = StatusCode::from_u16(e.status).unwrap_or(StatusCode::BAD_REQUEST);
    json_resp(st, &json!({"error": e.code}))
}

fn check_mutation_origin(headers: &HeaderMap) -> Result<(), HubError> {
    if let Some(origin) = headers.get(header::ORIGIN).and_then(|v| v.to_str().ok()) {
        let host = headers.get(header::HOST).and_then(|v| v.to_str().ok()).unwrap_or("").trim();
        if host.is_empty() {
            return Err(HubError::new(403, "untrusted_origin"));
        }
        let remote_origin = std::env::var("FDAI_LIFECYCLE_HUB_REMOTE_ORIGIN").ok().filter(|s| !s.trim().is_empty());
        let ok = if let Some(ref ro) = remote_origin {
            origin == ro.trim()
        } else {
            origin == format!("http://{host}") || origin == format!("https://{host}")
        };
        if !ok {
            return Err(HubError::new(403, "untrusted_origin"));
        }
    }
    Ok(())
}

async fn read_json_limited(req: Request, max_bytes: usize) -> Result<(HeaderMap, Map<String, Value>), HubError> {
    let headers = req.headers().clone();
    check_mutation_origin(&headers)?;
    let ct = headers
        .get(header::CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .split(';')
        .next()
        .unwrap_or("")
        .trim()
        .to_ascii_lowercase();
    if ct != "application/json" {
        return Err(HubError::new(415, "unsupported_media_type"));
    }
    let ce = headers
        .get(header::CONTENT_ENCODING)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("identity")
        .trim()
        .to_ascii_lowercase();
    if ce != "identity" {
        return Err(HubError::new(415, "unsupported_content_encoding"));
    }
    let bytes = tokio::time::timeout(
        std::time::Duration::from_secs(10),
        to_bytes(req.into_body(), max_bytes.saturating_add(1)),
    )
    .await
    .map_err(|_| HubError::new(408, "request_timeout"))?
    .map_err(|_| HubError::new(413, "request_too_large"))?;
    if bytes.len() > max_bytes {
        return Err(HubError::new(413, "request_too_large"));
    }
    let obj = parse_strict_json_object(&bytes)?;
    Ok((headers, obj))
}

fn entra_status_val(st: &LifecycleHubState) -> Value {
    let active = st.entra_session.read().ok().and_then(|g| g.clone());
    let actor = active.as_ref().map(|s| s.principal.as_str()).unwrap_or("local-operator");
    json!({
        "authenticated": active.is_some(),
        "actor": actor,
        "session": active,
        "detected_accounts": detect_workstation_accounts(),
    })
}

async fn handle_healthz() -> Response { json_resp(StatusCode::OK, &json!({"status": "ok"})) }

async fn handle_readyz(State(st): State<Arc<LifecycleHubState>>) -> Response {
    let pg_ok = if let Some(ref pg) = st.pg_ledger {
        pg.check_ready().await
    } else {
        true
    };
    let (chain_ok, inst_count) = st
        .data
        .read()
        .map(|d| (LifecycleHubState::verify_audit_chain(&d.audit_records), d.installations.len()))
        .unwrap_or((false, 0));
    let key_ok = !st.hub_public_key_bytes.is_empty();
    let backend = if st.pg_ledger.is_some() { "postgres" } else { "file" };
    if pg_ok && chain_ok && key_ok {
        json_resp(StatusCode::OK, &json!({
            "status": "ready",
            "signing_key": true,
            "storage_backend": backend,
            "storage_ok": true,
            "audit_chain_intact": true,
            "installations": inst_count,
        }))
    } else {
        json_resp(StatusCode::SERVICE_UNAVAILABLE, &json!({
            "status": "not-ready",
            "signing_key": key_ok,
            "storage_backend": backend,
            "storage_ok": pg_ok,
            "audit_chain_intact": chain_ok,
        }))
    }
}

async fn handle_metrics(State(st): State<Arc<LifecycleHubState>>, headers: HeaderMap) -> Response {
    if !fdai_http_runtime::check_metrics_bearer(&headers, &st.remote_policy) {
        return Response::builder()
            .status(StatusCode::UNAUTHORIZED)
            .header(header::CONTENT_TYPE, "application/json")
            .header(header::WWW_AUTHENTICATE, "Bearer")
            .body(Body::from("{\"error\":\"metrics_bearer_required\"}"))
            .unwrap_or_else(|_| Response::new(Body::empty()));
    }
    let (insts, pending, open_plans, audits, intact, cat_rev) = st
        .data
        .read()
        .map(|d| {
            let op = d.plans.values().filter(|p| p.is_open()).count();
            let ok = u8::from(LifecycleHubState::verify_audit_chain(&d.audit_records));
            let crev = d.accepted_catalog.as_ref().map_or(0, |c| c.revision);
            (d.installations.len(), d.pending_enrollments.len(), op, d.audit_records.len(), ok, crev)
        })
        .unwrap_or((0, 0, 0, 0, 0, 0));
    let pg_flag = u8::from(st.pg_ledger.is_some());
    let text = format!(
        "# TYPE fdai_lifecycle_hub_installations_total gauge\nfdai_lifecycle_hub_installations_total {insts}\n\
# TYPE fdai_lifecycle_hub_pending_enrollments gauge\nfdai_lifecycle_hub_pending_enrollments {pending}\n\
# TYPE fdai_lifecycle_hub_open_plans gauge\nfdai_lifecycle_hub_open_plans {open_plans}\n\
# TYPE fdai_lifecycle_hub_audit_records_total gauge\nfdai_lifecycle_hub_audit_records_total {audits}\n\
# TYPE fdai_lifecycle_hub_audit_chain_intact gauge\nfdai_lifecycle_hub_audit_chain_intact {intact}\n\
# TYPE fdai_lifecycle_hub_accepted_catalog_revision gauge\nfdai_lifecycle_hub_accepted_catalog_revision {cat_rev}\n\
# TYPE fdai_lifecycle_hub_storage_pg_enabled gauge\nfdai_lifecycle_hub_storage_pg_enabled {pg_flag}\n"
    );
    Response::builder()
        .status(StatusCode::OK)
        .header(header::CONTENT_TYPE, "text/plain; version=0.0.4; charset=utf-8")
        .header(header::CACHE_CONTROL, "no-store")
        .body(Body::from(text))
        .unwrap_or_else(|_| Response::new(Body::empty()))
}

async fn handle_hub_public_key(State(st): State<Arc<LifecycleHubState>>) -> Response {
    json_resp(StatusCode::OK, &json!({
        "hub_key_id": st.hub_key_id,
        "algorithm": "Ed25519",
        "public_key_b64": st.hub_public_key_b64,
        "public_key_pem": st.hub_public_key_pem,
    }))
}

async fn handle_setup_status(State(st): State<Arc<LifecycleHubState>>) -> Response {
    let guard = match st.data.read() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    json_resp(StatusCode::OK, &json!({
        "ready": true,
        "hub_key_id": st.hub_key_id,
        "enrolled_count": guard.installations.len(),
        "pending_count": guard.pending_enrollments.len(),
        "catalog_configured": guard.accepted_catalog.is_some(),
        "release_hub_endpoint": guard.release_connection.endpoint,
        "storage_backend": if st.pg_ledger.is_some() { "postgres" } else { "file" },
    }))
}

async fn handle_auth_config(State(st): State<Arc<LifecycleHubState>>) -> Response {
    json_resp(StatusCode::OK, &st.remote_policy.auth_config_json(Some(entra_status_val(&st))))
}

async fn lifecycle_hub_guard_middleware(
    State(st): State<Arc<LifecycleHubState>>,
    req: Request,
    next: fdai_http_runtime::axum::middleware::Next,
) -> Response {
    let corr_id = fdai_http_runtime::resolve_or_generate_correlation_id(req.headers());
    let path_q = req.uri().path_and_query().map(|pq| pq.as_str()).unwrap_or("/");
    match fdai_http_runtime::check_trusted_host(req.headers(), req.method(), path_q, &st.remote_policy) {
        fdai_http_runtime::HostCheckOutcome::Allowed => {}
        fdai_http_runtime::HostCheckOutcome::RedirectPermanent(loc) => {
            return Response::builder()
                .status(StatusCode::PERMANENT_REDIRECT)
                .header(header::LOCATION, loc)
                .header(HeaderName::from_static("x-correlation-id"), corr_id)
                .body(Body::empty())
                .unwrap_or_else(|_| Response::new(Body::empty()));
        }
        fdai_http_runtime::HostCheckOutcome::UntrustedHost => {
            fdai_http_runtime::log_structured_hub_event("hub", "warn", "untrusted_host", &corr_id, path_q);
            return json_resp(StatusCode::FORBIDDEN, &json!({"error": "untrusted_host"}));
        }
    }
    let path = req.uri().path().to_string();
    if let Err((code, msg)) = fdai_http_runtime::enforce_hub_remote_auth(
        &st.authenticator,
        &st.remote_policy,
        req.headers(),
        req.method(),
        &path,
        false,
    )
    .await
    {
        fdai_http_runtime::log_structured_hub_event("hub", "warn", "auth_denied", &corr_id, &msg);
        let mut resp = json_resp(code, &json!({"error": msg}));
        if code == StatusCode::UNAUTHORIZED {
            resp.headers_mut().insert(header::WWW_AUTHENTICATE, fdai_http_runtime::axum::http::HeaderValue::from_static("Bearer"));
        }
        if let Ok(hv) = fdai_http_runtime::axum::http::HeaderValue::from_str(&corr_id) {
            resp.headers_mut().insert(HeaderName::from_static("x-correlation-id"), hv);
        }
        return resp;
    }
    let mut resp = next.run(req).await;
    if let Ok(hv) = fdai_http_runtime::axum::http::HeaderValue::from_str(&corr_id) {
        resp.headers_mut().insert(HeaderName::from_static("x-correlation-id"), hv);
    }
    resp
}

async fn handle_auth_session(State(st): State<Arc<LifecycleHubState>>) -> Response {
    json_resp(StatusCode::OK, &entra_status_val(&st))
}

async fn handle_entra_login(State(st): State<Arc<LifecycleHubState>>, req: Request) -> Response {
    let (_, body) = match read_json_limited(req, 8192).await { Ok(v) => v, Err(e) => return err_resp(&e) };
    let mode = body.get("mode").and_then(Value::as_str).unwrap_or("workstation");
    let principal = body.get("principal").and_then(Value::as_str).unwrap_or("").trim().to_string();
    let tenant_id = body.get("tenant_id").and_then(Value::as_str).unwrap_or("00000000-0000-0000-0000-000000000000").trim().to_string();
    let display_name = body.get("display_name").and_then(Value::as_str).unwrap_or(&principal).trim().to_string();
    let resolved_principal = if !principal.is_empty() {
        principal
    } else if let Some(first) = detect_workstation_accounts().first().and_then(|v| v.get("principal")).and_then(Value::as_str) {
        first.to_string()
    } else {
        return err_resp(&HubError::unprocessable("principal_required"));
    };
    let sess = ActiveEntraSession {
        principal: resolved_principal.clone(),
        display_name: if display_name.is_empty() { resolved_principal } else { display_name },
        tenant_id,
        auth_method: if mode == "msal_account" { String::from("entra-msal-pkce") } else { String::from("entra-workstation") },
        signed_in_at: format_utc_rfc3339_now(),
    };
    if let Ok(mut g) = st.entra_session.write() { *g = Some(sess); }
    json_resp(StatusCode::OK, &entra_status_val(&st))
}

async fn handle_entra_logout(State(st): State<Arc<LifecycleHubState>>, headers: HeaderMap) -> Response {
    if let Err(e) = check_mutation_origin(&headers) { return err_resp(&e); }
    if let Ok(mut g) = st.entra_session.write() { *g = None; }
    json_resp(StatusCode::OK, &entra_status_val(&st))
}

async fn handle_post_enrollment(
    State(st): State<Arc<LifecycleHubState>>,
    AxPath(inst_id): AxPath<String>,
    req: Request,
) -> Response {
    if !is_valid_installation_id(&inst_id) { return err_resp(&HubError::unprocessable("installation_id_invalid")); }
    let (_, raw_body) = match read_json_limited(req, MAX_ENROLLMENT_BYTES).await { Ok(v) => v, Err(e) => return err_resp(&e) };
    let body = if let (Some(sp_b64), Some(proof_b64)) = (
        raw_body.get("signed_payload").and_then(Value::as_str),
        raw_body.get("proof").and_then(Value::as_str),
    ) {
        use fdai_http_runtime::base64::engine::general_purpose::STANDARD as B64;
        use fdai_http_runtime::base64::Engine as _;
        let Ok(payload_bytes) = B64.decode(sp_b64) else {
            return err_resp(&HubError::unprocessable("enrollment_proof_invalid"));
        };
        if B64.decode(proof_b64).is_err() || proof_b64.is_empty() {
            return err_resp(&HubError::unprocessable("enrollment_proof_invalid"));
        }
        let inner = match parse_strict_json_object(&payload_bytes) {
            Ok(m) => m,
            Err(e) => return err_resp(&e),
        };
        if let Some(pk_b64) = inner.get("public_key_b64").and_then(Value::as_str) {
            if !LifecycleHubState::verify_ed25519_b64(pk_b64, &payload_bytes, proof_b64) {
                return err_resp(&HubError::unprocessable("enrollment_proof_invalid"));
            }
        }
        inner
    } else {
        raw_body
    };
    let key_id = body.get("installation_key_id").and_then(Value::as_str)
        .map(String::from)
        .unwrap_or_else(|| sha256_hex(inst_id.as_bytes())[..16].to_string());
    let channel = body.get("channel").and_then(Value::as_str).unwrap_or("DEV").to_string();
    let version_range = body.get("version_range").and_then(Value::as_str).unwrap_or("*").to_string();
    let region = body.get("region").and_then(Value::as_str).unwrap_or("koreacentral").to_string();
    let schema_revision = body.get("schema_revision").and_then(Value::as_u64).unwrap_or(1);
    let entities: Vec<EntityRecord> = body.get("entities")
        .and_then(|v| serde_json::from_value(v.clone()).ok())
        .unwrap_or_else(|| vec![EntityRecord {
            entity_id: format!("{inst_id}-core"),
            kind: String::from("application"),
            managed: true,
            ownership_gap: None,
            release_id: None,
            health: Some(String::from("healthy")),
        }]);
    let now_s = format_utc_rfc3339_now();
    let cfg_dig = body.get("configuration_digest").and_then(Value::as_str)
        .map(String::from)
        .unwrap_or_else(|| sha256_hex(format!("cfg:{inst_id}:{now_s}").as_bytes()));
    let mut guard = match st.data.write() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    if guard.installations.contains_key(&inst_id) {
        return err_resp(&HubError::conflict("installation_already_enrolled"));
    }
    let rec = PendingEnrollmentRecord {
        installation_id: inst_id.clone(),
        installation_key_id: key_id.clone(),
        requested_at: now_s.clone(),
        request_id: body.get("request_id").and_then(Value::as_str).map(String::from),
        requested_by: Some(st.current_actor()),
        requested_via: Some(String::from("agent")),
        channel,
        version_range,
        region: region.clone(),
        allowed_regions: vec![region],
        entities,
        reported_at: now_s,
        schema_revision,
        configuration_digest: cfg_dig,
    };
    guard.pending_enrollments.insert(inst_id.clone(), rec.clone());
    LifecycleHubState::append_audit(&mut guard, "enrollment_requested", &inst_id, &key_id);
    if let Err(e) = st.persist(&guard) { return err_resp(&e); }
    json_resp(StatusCode::ACCEPTED, &json!({"status": "pending", "installation_id": inst_id, "installation_key_id": key_id}))
}

async fn handle_list_pending(State(st): State<Arc<LifecycleHubState>>) -> Response {
    let guard = match st.data.read() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    let list: Vec<&PendingEnrollmentRecord> = guard.pending_enrollments.values().collect();
    json_resp(StatusCode::OK, &json!({"enrollments": list}))
}

async fn handle_get_pending(State(st): State<Arc<LifecycleHubState>>, AxPath(inst_id): AxPath<String>) -> Response {
    let guard = match st.data.read() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    let Some(item) = guard.pending_enrollments.get(&inst_id) else {
        return err_resp(&HubError::not_found("not_pending"));
    };
    json_resp(StatusCode::OK, &json!(item))
}

async fn handle_list_bindable(State(st): State<Arc<LifecycleHubState>>) -> Response {
    let guard = match st.data.read() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    let mut items = Vec::new();
    for id in guard.installations.keys() {
        items.push(json!({"installation_id": id, "status": "enrolled"}));
    }
    for id in guard.pending_enrollments.keys() {
        items.push(json!({"installation_id": id, "status": "pending"}));
    }
    json_resp(StatusCode::OK, &json!({"installations": items}))
}

async fn handle_approve_enrollment(
    State(st): State<Arc<LifecycleHubState>>,
    AxPath(inst_id): AxPath<String>,
    req: Request,
) -> Response {
    let (_, body) = match read_json_limited(req, MAX_APPROVAL_BYTES).await { Ok(v) => v, Err(e) => return err_resp(&e) };
    let key_id = body.get("installation_key_id").and_then(Value::as_str).unwrap_or("").trim();
    if key_id.is_empty() { return err_resp(&HubError::unprocessable("approval_invalid")); }
    let mut guard = match st.data.write() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    let Some(pending) = guard.pending_enrollments.get(&inst_id).cloned() else {
        return err_resp(&HubError::not_found("not_pending"));
    };
    if pending.installation_key_id != key_id {
        return err_resp(&HubError::conflict("installation_key_mismatch"));
    }
    guard.pending_enrollments.remove(&inst_id);
    let set_dig = compute_settings_digest(None, &[], 60);
    guard.installations.insert(inst_id.clone(), InstallationRecord {
        installation_id: inst_id.clone(),
        enrollment: String::from("enrolled"),
        installation_key_id: pending.installation_key_id,
        channel: pending.channel,
        version_range: pending.version_range,
        region: pending.region,
        allowed_regions: pending.allowed_regions,
        windows: Vec::new(),
        plan_duration_minutes: 60,
        product: None,
        settings_digest: set_dig,
        configuration_digest: pending.configuration_digest,
        reported_at: pending.reported_at,
        schema_revision: pending.schema_revision,
        current_release: pending.entities.first().and_then(|e| e.release_id.clone()),
        health: pending.entities.first().and_then(|e| e.health.clone()).or_else(|| Some(String::from("healthy"))),
        entities: pending.entities,
        suppressions: Vec::new(),
        last_evaluation: None,
        plan_sequence: 0,
    });
    LifecycleHubState::append_audit(&mut guard, "enrollment_approved", &inst_id, key_id);
    let _ = st.evaluate_and_plan_locked(&mut guard, &inst_id);
    if let Err(e) = st.persist(&guard) { return err_resp(&e); }
    json_resp(StatusCode::OK, &json!({"enrolled": inst_id}))
}

async fn handle_reject_enrollment(
    State(st): State<Arc<LifecycleHubState>>,
    AxPath(inst_id): AxPath<String>,
    req: Request,
) -> Response {
    let (_, body) = match read_json_limited(req, MAX_APPROVAL_BYTES).await { Ok(v) => v, Err(e) => return err_resp(&e) };
    let reason = body.get("reason").and_then(Value::as_str).unwrap_or("").trim();
    if reason.len() < 3 { return err_resp(&HubError::unprocessable("rejection_invalid")); }
    let mut guard = match st.data.write() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    if guard.pending_enrollments.remove(&inst_id).is_none() {
        return err_resp(&HubError::not_found("not_pending"));
    }
    LifecycleHubState::append_audit(&mut guard, "enrollment_rejected", &inst_id, reason);
    if let Err(e) = st.persist(&guard) { return err_resp(&e); }
    json_resp(StatusCode::OK, &json!({"rejected": inst_id}))
}

async fn handle_list_installations(
    State(st): State<Arc<LifecycleHubState>>,
    Query(q): Query<BTreeMap<String, String>>,
) -> Response {
    let guard = match st.data.read() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    let ch_f = q.get("channel").map(String::as_str);
    let h_f = q.get("health").map(String::as_str);
    let items: Vec<Value> = guard
        .installations
        .values()
        .filter(|i| ch_f.is_none_or(|c| i.channel == c))
        .filter(|i| h_f.is_none_or(|h| i.health.as_deref() == Some(h)))
        .map(|i| LifecycleHubState::build_installation_summary(&guard, i))
        .collect();
    json_resp(StatusCode::OK, &json!({"installations": items}))
}

async fn handle_get_installation(State(st): State<Arc<LifecycleHubState>>, AxPath(inst_id): AxPath<String>) -> Response {
    let guard = match st.data.read() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    let Some(inst) = guard.installations.get(&inst_id) else {
        return err_resp(&HubError::not_found("unknown_installation"));
    };
    json_resp(StatusCode::OK, &LifecycleHubState::build_installation_detail(&guard, inst))
}

async fn handle_get_plan(State(st): State<Arc<LifecycleHubState>>, AxPath(inst_id): AxPath<String>) -> Response {
    let guard = match st.data.read() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    if !guard.installations.contains_key(&inst_id) {
        return err_resp(&HubError::not_found("unknown_installation"));
    }
    let now_s = format_utc_rfc3339_now();
    let Some(plan) = guard
        .plans
        .values()
        .find(|p| p.installation_id == inst_id && p.is_open() && p.expires_at.as_str() > now_s.as_str())
    else {
        return empty_resp(StatusCode::NO_CONTENT);
    };
    json_resp(StatusCode::OK, &json!({
        "plan_id": plan.plan_id,
        "installation_id": plan.installation_id,
        "sequence": plan.sequence,
        "plan_type": plan.plan_type,
        "target_release_id": plan.target_release_id,
        "source_state_digest": plan.source_state_digest,
        "configuration_digest": plan.configuration_digest,
        "hub_key_id": plan.hub_key_id,
        "entity_ids": plan.entity_ids,
        "expires_at": plan.expires_at,
        "exact_plan_digest": plan.exact_plan_digest,
        "signature": plan.signature,
    }))
}

async fn handle_get_plan_detail(
    State(st): State<Arc<LifecycleHubState>>,
    AxPath((inst_id, plan_id)): AxPath<(String, String)>,
) -> Response {
    let guard = match st.data.read() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    let Some(plan) = guard.plans.get(&plan_id).filter(|p| p.installation_id == inst_id) else {
        return err_resp(&HubError::not_found("unknown_plan"));
    };
    json_resp(StatusCode::OK, &json!({
        "plan_id": plan.plan_id,
        "installation_id": plan.installation_id,
        "sequence": plan.sequence,
        "plan_type": plan.plan_type,
        "target_release_id": plan.target_release_id,
        "source_state_digest": plan.source_state_digest,
        "configuration_digest": plan.configuration_digest,
        "hub_key_id": plan.hub_key_id,
        "entity_ids": plan.entity_ids,
        "expires_at": plan.expires_at,
        "status": plan.derived_status(),
        "events": plan.events,
        "evaluations": plan.evaluations,
        "reports": plan.reports,
    }))
}

async fn handle_post_state(
    State(st): State<Arc<LifecycleHubState>>,
    AxPath(inst_id): AxPath<String>,
    req: Request,
) -> Response {
    let (_, body) = match read_json_limited(req, MAX_STATE_BYTES).await { Ok(v) => v, Err(e) => return err_resp(&e) };
    let reported_at = body.get("reported_at").and_then(Value::as_str).unwrap_or("").trim();
    if reported_at.is_empty() { return err_resp(&HubError::unprocessable("state_invalid")); }
    let mut guard = match st.data.write() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    let Some(inst) = guard.installations.get_mut(&inst_id) else {
        return err_resp(&HubError::not_found("unknown_installation"));
    };
    if reported_at < inst.reported_at.as_str() {
        return err_resp(&HubError::conflict("stale_state"));
    }
    inst.reported_at = reported_at.to_string();
    if let Some(sr) = body.get("schema_revision").and_then(Value::as_u64) { inst.schema_revision = sr; }
    if let Some(cr) = body.get("current_release").and_then(Value::as_str) { inst.current_release = Some(cr.to_string()); }
    if let Some(h) = body.get("health").and_then(Value::as_str) { inst.health = Some(h.to_string()); }
    if let Some(ents) = body.get("entities").and_then(|v| serde_json::from_value::<Vec<EntityRecord>>(v.clone()).ok()) {
        inst.entities = ents;
    }
    LifecycleHubState::append_audit(&mut guard, "state_recorded", &inst_id, reported_at);
    let _ = st.evaluate_and_plan_locked(&mut guard, &inst_id);
    if let Err(e) = st.persist(&guard) { return err_resp(&e); }
    empty_resp(StatusCode::ACCEPTED)
}

async fn handle_post_report(
    State(st): State<Arc<LifecycleHubState>>,
    AxPath((inst_id, plan_id)): AxPath<(String, String)>,
    req: Request,
) -> Response {
    let (_, body) = match read_json_limited(req, MAX_REPORT_BYTES).await { Ok(v) => v, Err(e) => return err_resp(&e) };
    let attempt = match body.get("attempt").and_then(Value::as_u64) {
        Some(a) if a >= 1 => a,
        _ => return err_resp(&HubError::unprocessable("report_invalid")),
    };
    let outcome = body.get("outcome").and_then(Value::as_str).unwrap_or("").trim().to_string();
    let reason_code = body.get("reason_code").and_then(Value::as_str).unwrap_or("ok").to_string();
    let summary = body.get("summary").and_then(Value::as_str).unwrap_or("").to_string();
    let reported_at = body.get("reported_at").and_then(Value::as_str).map(String::from).unwrap_or_else(format_utc_rfc3339_now);
    let exact_digest = body.get("exact_plan_digest").and_then(Value::as_str).map(String::from);
    if outcome.is_empty() { return err_resp(&HubError::unprocessable("report_invalid")); }

    let mut guard = match st.data.write() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    let Some(plan) = guard.plans.get_mut(&plan_id).filter(|p| p.installation_id == inst_id) else {
        return err_resp(&HubError::not_found("unknown_plan"));
    };
    if plan.reports.iter().any(|r| matches!(r.outcome.as_str(), "succeeded" | "failed" | "rolled-back")) {
        return err_resp(&HubError::conflict("report_progression_invalid"));
    }
    if let Some(ref d) = exact_digest {
        if d != &plan.exact_plan_digest {
            return err_resp(&HubError::conflict("plan_digest_mismatch"));
        }
    }
    let expected_attempt = plan.reports.len() as u64 + 1;
    if attempt > expected_attempt {
        return err_resp(&HubError::conflict("report_attempt_gap"));
    }
    if attempt < expected_attempt {
        return err_resp(&HubError::conflict("report_conflict"));
    }
    let now_s = format_utc_rfc3339_now();
    let target_rel = plan.target_release_id.clone();
    plan.reports.push(PlanReportRecord {
        plan_id: plan_id.clone(),
        attempt,
        outcome: outcome.clone(),
        reason_code: reason_code.clone(),
        exact_plan_digest: exact_digest,
        summary,
        reported_at,
        received_at: now_s.clone(),
    });
    if outcome == "succeeded" {
        if let Some(inst) = guard.installations.get_mut(&inst_id) {
            inst.current_release = Some(target_rel);
        }
        LifecycleHubState::supersede_open_plans(&mut guard, &inst_id, &now_s);
    } else if outcome == "failed" || outcome == "rolled-back" {
        if let Some(inst) = guard.installations.get_mut(&inst_id) {
            inst.suppressions.push(SuppressionRecord {
                scope: String::from("installation"),
                starts_at: now_s.clone(),
                ends_at: crate::hub_state::format_unix_rfc3339(crate::hub_state::now_unix_secs().saturating_add(3600)),
                origin: String::from("failure"),
                failed_plan_id: Some(plan_id.clone()),
                lifted: false,
            });
        }
        LifecycleHubState::supersede_open_plans(&mut guard, &inst_id, &now_s);
    }
    LifecycleHubState::append_audit(&mut guard, "plan_report_recorded", &inst_id, &format!("{plan_id}:{outcome}"));
    if let Err(e) = st.persist(&guard) { return err_resp(&e); }
    empty_resp(StatusCode::ACCEPTED)
}

async fn handle_entitlement_handoff(State(st): State<Arc<LifecycleHubState>>, AxPath(inst_id): AxPath<String>) -> Response {
    let guard = match st.data.read() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    if !guard.installations.contains_key(&inst_id) {
        return err_resp(&HubError::not_found("unknown_installation"));
    }
    let Some(carrier) = guard.entitlement_handoffs.get(&inst_id) else {
        return empty_resp(StatusCode::NO_CONTENT);
    };
    json_resp(StatusCode::OK, carrier)
}

async fn handle_post_entitlement_handoff(
    State(st): State<Arc<LifecycleHubState>>,
    AxPath(inst_id): AxPath<String>,
    req: Request,
) -> Response {
    let (_, body) = match read_json_limited(req, MAX_APPROVAL_BYTES).await { Ok(v) => v, Err(e) => return err_resp(&e) };
    let carrier_payload = body.get("carrier_b64").and_then(Value::as_str).unwrap_or("").trim();
    let tier = body.get("tier").and_then(Value::as_str).unwrap_or("enterprise").trim();
    if carrier_payload.is_empty() {
        return err_resp(&HubError::unprocessable("entitlement_carrier_required"));
    }
    let now_s = format_utc_rfc3339_now();
    let expires_at = body.get("expires_at").and_then(Value::as_str)
        .map(String::from)
        .unwrap_or_else(|| crate::hub_state::format_unix_rfc3339(crate::hub_state::now_unix_secs().saturating_add(30 * 86_400)));
    let unsigned = json!({
        "installation_id": inst_id,
        "tier": tier,
        "carrier_b64": carrier_payload,
        "issued_at": now_s,
        "expires_at": expires_at,
        "hub_key_id": st.hub_key_id,
    });
    let sig = st.sign_b64(&canonical_json_bytes(&unsigned));
    let signed = json!({
        "installation_id": inst_id,
        "tier": tier,
        "carrier_b64": carrier_payload,
        "issued_at": now_s,
        "expires_at": expires_at,
        "hub_key_id": st.hub_key_id,
        "signature": sig,
    });
    let mut guard = match st.data.write() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    if !guard.installations.contains_key(&inst_id) {
        return err_resp(&HubError::not_found("unknown_installation"));
    }
    guard.entitlement_handoffs.insert(inst_id.clone(), signed.clone());
    LifecycleHubState::append_audit(&mut guard, "entitlement_handoff_staged", &inst_id, tier);
    if let Err(e) = st.persist(&guard) { return err_resp(&e); }
    json_resp(StatusCode::CREATED, &signed)
}

async fn handle_post_suppression(
    State(st): State<Arc<LifecycleHubState>>,
    AxPath(inst_id): AxPath<String>,
    req: Request,
) -> Response {
    let (_, body) = match read_json_limited(req, MAX_APPROVAL_BYTES).await { Ok(v) => v, Err(e) => return err_resp(&e) };
    let scope = body.get("scope").and_then(Value::as_str).unwrap_or("installation").to_string();
    let starts_at = body.get("starts_at").and_then(Value::as_str).map(String::from).unwrap_or_else(format_utc_rfc3339_now);
    let ends_at = body.get("ends_at").and_then(Value::as_str).unwrap_or("").to_string();
    let conf = body.get("confirmation").and_then(Value::as_str).unwrap_or("");
    if ends_at.is_empty() || conf != inst_id {
        return err_resp(&HubError::unprocessable("suppression_invalid"));
    }
    if ends_at.as_str() <= starts_at.as_str() {
        return err_resp(&HubError::unprocessable("suppression_window_invalid"));
    }
    let mut guard = match st.data.write() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    let Some(inst) = guard.installations.get_mut(&inst_id) else {
        return err_resp(&HubError::not_found("unknown_installation"));
    };
    let rec = SuppressionRecord {
        scope: scope.clone(),
        starts_at,
        ends_at,
        origin: String::from("manual"),
        failed_plan_id: None,
        lifted: false,
    };
    inst.suppressions.push(rec.clone());
    let now_s = format_utc_rfc3339_now();
    LifecycleHubState::supersede_open_plans(&mut guard, &inst_id, &now_s);
    LifecycleHubState::append_audit(&mut guard, "suppression_added", &inst_id, &scope);
    if let Err(e) = st.persist(&guard) { return err_resp(&e); }
    json_resp(StatusCode::OK, &json!(rec))
}

async fn handle_lift_suppression(
    State(st): State<Arc<LifecycleHubState>>,
    AxPath(inst_id): AxPath<String>,
    req: Request,
) -> Response {
    let (_, body) = match read_json_limited(req, MAX_APPROVAL_BYTES).await { Ok(v) => v, Err(e) => return err_resp(&e) };
    let scope = body.get("scope").and_then(Value::as_str).unwrap_or("installation");
    let conf = body.get("confirmation").and_then(Value::as_str).unwrap_or("");
    if conf != inst_id { return err_resp(&HubError::unprocessable("suppression_invalid")); }
    let mut guard = match st.data.write() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    let Some(inst) = guard.installations.get_mut(&inst_id) else {
        return err_resp(&HubError::not_found("unknown_installation"));
    };
    let mut lifted = 0_usize;
    for s in &mut inst.suppressions {
        if !s.lifted && s.scope == scope {
            s.lifted = true;
            lifted += 1;
        }
    }
    LifecycleHubState::append_audit(&mut guard, "suppression_lifted", &inst_id, scope);
    let _ = st.evaluate_and_plan_locked(&mut guard, &inst_id);
    if let Err(e) = st.persist(&guard) { return err_resp(&e); }
    json_resp(StatusCode::OK, &json!({"lifted": lifted, "scope": scope}))
}

async fn handle_get_execution_settings(State(st): State<Arc<LifecycleHubState>>, AxPath(inst_id): AxPath<String>) -> Response {
    let guard = match st.data.read() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    let Some(inst) = guard.installations.get(&inst_id) else { return err_resp(&HubError::not_found("unknown_installation")); };
    json_resp(StatusCode::OK, &json!({
        "settings_digest": inst.settings_digest,
        "product": inst.product,
        "windows": inst.windows,
        "plan_duration_minutes": inst.plan_duration_minutes,
    }))
}

async fn handle_post_execution_settings(
    State(st): State<Arc<LifecycleHubState>>,
    AxPath(inst_id): AxPath<String>,
    req: Request,
) -> Response {
    let (_, body) = match read_json_limited(req, MAX_APPROVAL_BYTES).await { Ok(v) => v, Err(e) => return err_resp(&e) };
    let expected = body.get("expected_settings_digest").and_then(Value::as_str).unwrap_or("").trim();
    let conf = body.get("confirmation").and_then(Value::as_str).unwrap_or("");
    if conf != inst_id || expected.is_empty() {
        return err_resp(&HubError::unprocessable("execution_settings_invalid"));
    }
    let mut guard = match st.data.write() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    let Some(inst) = guard.installations.get_mut(&inst_id) else { return err_resp(&HubError::not_found("unknown_installation")); };
    if expected != inst.settings_digest {
        return err_resp(&HubError::conflict("settings_digest_mismatch"));
    }
    if let Some(prod) = body.get("product").and_then(Value::as_str) {
        inst.product = Some(prod.to_string());
    }
    if let Some(wins) = body.get("windows").and_then(|v| serde_json::from_value::<Vec<MaintenanceWindow>>(v.clone()).ok()) {
        inst.windows = wins;
    }
    if let Some(dur) = body.get("plan_duration_minutes").and_then(Value::as_u64) {
        inst.plan_duration_minutes = dur.clamp(5, 1440) as u32;
    }
    let new_dig = compute_settings_digest(inst.product.as_deref(), &inst.windows, inst.plan_duration_minutes);
    let changed = new_dig != inst.settings_digest;
    inst.settings_digest = new_dig.clone();
    LifecycleHubState::append_audit(&mut guard, "execution_settings_updated", &inst_id, &new_dig);
    if let Err(e) = st.persist(&guard) { return err_resp(&e); }
    json_resp(StatusCode::OK, &json!({"changed": changed, "settings_digest": new_dig}))
}

async fn handle_list_audit(
    State(st): State<Arc<LifecycleHubState>>,
    Query(q): Query<BTreeMap<String, String>>,
) -> Response {
    let guard = match st.data.read() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    let intact = LifecycleHubState::verify_audit_chain(&guard.audit_records);
    let inst_f = q.get("installation_id").map(String::as_str);
    let action_f = q.get("action").map(String::as_str);
    let limit = q.get("limit").and_then(|s| s.parse::<usize>().ok()).unwrap_or(100).clamp(1, 500);
    let offset = q.get("offset").and_then(|s| s.parse::<usize>().ok()).unwrap_or(0);
    let recs: Vec<&crate::hub_state::AuditRecord> = guard
        .audit_records
        .iter()
        .rev()
        .filter(|r| inst_f.is_none_or(|f| r.installation_id == f))
        .filter(|r| action_f.is_none_or(|a| r.action == a))
        .skip(offset)
        .take(limit)
        .collect();
    json_resp(StatusCode::OK, &json!({"chain_intact": intact, "records": recs}))
}

async fn handle_list_configurations(State(st): State<Arc<LifecycleHubState>>) -> Response {
    let guard = match st.data.read() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    let mut by_dig: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for inst in guard.installations.values() {
        by_dig.entry(inst.configuration_digest.clone()).or_default().push(inst.installation_id.clone());
    }
    let items: Vec<Value> = by_dig.into_iter().map(|(dig, ids)| json!({
        "digest": dig,
        "imported_at": format_utc_rfc3339_now(),
        "schema_key_count": 0,
        "override_count": 0,
        "installation_ids": ids,
        "signature_status": "not-recorded",
    })).collect();
    json_resp(StatusCode::OK, &json!({"configurations": items}))
}

async fn handle_get_commands(State(st): State<Arc<LifecycleHubState>>) -> Response {
    let guard = match st.data.read() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    let now_s = format_utc_rfc3339_now();
    let items: Vec<Value> = guard.commands.iter().rev().map(|c| {
        let expired = c.expires_at.as_str() <= now_s.as_str();
        json!({
            "command_id": c.command_id, "installation_id": c.installation_id, "kind": c.kind,
            "actor": c.actor, "reason": c.reason, "scope": c.scope, "starts_at": c.starts_at,
            "expires_at": c.expires_at, "active": !expired, "expired": expired,
            "reconciles_to_git_on_expiry": true, "target_action_type": c.target_action_type,
            "target_mode": c.target_mode, "target_autonomy": c.target_autonomy,
            "engage_kill_switch": c.engage_kill_switch, "bypass_scopes": c.bypass_scopes,
            "override_count": c.override_count,
        })
    }).collect();
    json_resp(StatusCode::OK, &json!({"commands": items}))
}

async fn handle_post_command(
    State(st): State<Arc<LifecycleHubState>>,
    AxPath(inst_id): AxPath<String>,
    req: Request,
) -> Response {
    let (_, body) = match read_json_limited(req, MAX_APPROVAL_BYTES).await { Ok(v) => v, Err(e) => return err_resp(&e) };
    let kind = body.get("kind").and_then(Value::as_str).unwrap_or("");
    if !matches!(kind, "suppression-window" | "authority-lowering" | "break-glass") {
        return err_resp(&HubError::unprocessable("command_invalid"));
    }
    let conf = body.get("confirmation").and_then(Value::as_str).unwrap_or("");
    if conf != inst_id { return err_resp(&HubError::unprocessable("confirmation_mismatch")); }
    let cmd_id = body.get("command_id").and_then(Value::as_str).map(String::from)
        .unwrap_or_else(|| format!("cmd-{}", &sha256_hex(format!("{inst_id}:{kind}:{}", format_utc_rfc3339_now()).as_bytes())[..12]));
    let rec = LifecycleCommandRecord {
        command_id: cmd_id.clone(),
        installation_id: inst_id.clone(),
        kind: kind.to_string(),
        actor: st.current_actor(),
        reason: body.get("reason").and_then(Value::as_str).unwrap_or("operator command").to_string(),
        scope: body.get("scope").and_then(Value::as_str).unwrap_or("installation").to_string(),
        starts_at: body.get("starts_at").and_then(Value::as_str).map(String::from).unwrap_or_else(format_utc_rfc3339_now),
        expires_at: body.get("expires_at").and_then(Value::as_str).map(String::from)
            .unwrap_or_else(|| crate::hub_state::format_unix_rfc3339(crate::hub_state::now_unix_secs().saturating_add(3600))),
        target_action_type: body.get("target_action_type").and_then(Value::as_str).map(String::from),
        target_mode: body.get("target_mode").and_then(Value::as_str).map(String::from),
        target_autonomy: body.get("target_autonomy").and_then(Value::as_str).map(String::from),
        engage_kill_switch: body.get("engage_kill_switch").and_then(Value::as_bool).unwrap_or(false),
        bypass_scopes: body.get("bypass_scopes").and_then(Value::as_array)
            .map(|a| a.iter().filter_map(Value::as_str).map(String::from).collect()).unwrap_or_default(),
        override_count: 1,
    };
    let mut guard = match st.data.write() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    if !guard.installations.contains_key(&inst_id) { return err_resp(&HubError::not_found("unknown_installation")); }
    guard.commands.push(rec.clone());
    LifecycleHubState::append_audit(&mut guard, "lifecycle_command_issued", &inst_id, &cmd_id);
    if let Err(e) = st.persist(&guard) { return err_resp(&e); }
    json_resp(StatusCode::CREATED, &json!(rec))
}

async fn handle_get_confirmations(State(st): State<Arc<LifecycleHubState>>) -> Response {
    let guard = match st.data.read() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    let items: Vec<Value> = guard.confirmations.iter().rev().map(|c| {
        let plan_current = guard.plans.get(&c.plan_id).is_some_and(|p| p.is_open() && p.exact_plan_digest == c.exact_plan_digest);
        json!({
            "installation_id": c.installation_id, "plan_id": c.plan_id, "exact_plan_digest": c.exact_plan_digest,
            "change_kind": c.change_kind, "title": c.title, "summary": c.summary, "impact": c.impact,
            "replace_count": c.replace_count, "delete_count": c.delete_count,
            "affected_addresses": c.affected_addresses, "foundation_ownership_verified": c.foundation_ownership_verified,
            "within_local_envelope": c.within_local_envelope, "dry_run_succeeded": c.dry_run_succeeded,
            "status": c.status, "plan_current": plan_current, "created_at": c.created_at,
            "decided_by": c.decided_by, "decided_at": c.decided_at, "decision_reason": c.decision_reason,
        })
    }).collect();
    json_resp(StatusCode::OK, &json!({"confirmations": items}))
}

async fn handle_post_confirmation_proposal(
    State(st): State<Arc<LifecycleHubState>>,
    AxPath((inst_id, plan_id)): AxPath<(String, String)>,
    req: Request,
) -> Response {
    let (_, body) = match read_json_limited(req, MAX_APPROVAL_BYTES).await { Ok(v) => v, Err(e) => return err_resp(&e) };
    let mut guard = match st.data.write() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    let Some(plan) = guard.plans.get(&plan_id).filter(|p| p.installation_id == inst_id).cloned() else {
        return err_resp(&HubError::not_found("unknown_plan"));
    };
    let rec = DestructiveConfirmationRecord {
        installation_id: inst_id.clone(),
        plan_id: plan_id.clone(),
        exact_plan_digest: plan.exact_plan_digest,
        change_kind: body.get("change_kind").and_then(Value::as_str).unwrap_or("resource-replacement").to_string(),
        title: body.get("title").and_then(Value::as_str).unwrap_or("Destructive plan change").to_string(),
        summary: body.get("summary").and_then(Value::as_str).unwrap_or("").to_string(),
        impact: body.get("impact").and_then(Value::as_str).unwrap_or("").to_string(),
        replace_count: body.get("replace_count").and_then(Value::as_u64).unwrap_or(0),
        delete_count: body.get("delete_count").and_then(Value::as_u64).unwrap_or(0),
        affected_addresses: body.get("affected_addresses").and_then(Value::as_array)
            .map(|a| a.iter().filter_map(Value::as_str).map(String::from).collect()).unwrap_or_default(),
        foundation_ownership_verified: body.get("foundation_ownership_verified").and_then(Value::as_bool).unwrap_or(true),
        within_local_envelope: body.get("within_local_envelope").and_then(Value::as_bool).unwrap_or(true),
        dry_run_succeeded: body.get("dry_run_succeeded").and_then(Value::as_bool).unwrap_or(true),
        status: String::from("pending"),
        created_at: format_utc_rfc3339_now(),
        decided_by: None,
        decided_at: None,
        decision_reason: None,
    };
    guard.confirmations.push(rec.clone());
    LifecycleHubState::append_audit(&mut guard, "destructive_confirmation_proposed", &inst_id, &plan_id);
    if let Err(e) = st.persist(&guard) { return err_resp(&e); }
    json_resp(StatusCode::CREATED, &json!(rec))
}

async fn handle_post_confirmation_decision(
    State(st): State<Arc<LifecycleHubState>>,
    AxPath((inst_id, plan_id)): AxPath<(String, String)>,
    req: Request,
) -> Response {
    let (_, body) = match read_json_limited(req, MAX_APPROVAL_BYTES).await { Ok(v) => v, Err(e) => return err_resp(&e) };
    let decision = body.get("decision").and_then(Value::as_str).unwrap_or("");
    if !matches!(decision, "confirm" | "hold") { return err_resp(&HubError::unprocessable("decision_invalid")); }
    let exp_dig = body.get("expected_plan_digest").and_then(Value::as_str).unwrap_or("");
    let reason = body.get("reason").and_then(Value::as_str).unwrap_or("").trim().to_string();
    let conf = body.get("confirmation").and_then(Value::as_str).unwrap_or("");
    if conf != plan_id || reason.len() < 3 {
        return err_resp(&HubError::unprocessable("decision_confirmation_invalid"));
    }
    let confirmed_addrs: Vec<String> = body
        .get("confirmed_addresses")
        .and_then(Value::as_array)
        .map(|a| a.iter().filter_map(Value::as_str).map(String::from).collect())
        .unwrap_or_default();
    let actor = st.current_actor();
    let mut guard = match st.data.write() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    let plan_is_open = guard.plans.get(&plan_id).is_some_and(|p| p.installation_id == inst_id && p.is_open());
    let Some(item) = guard.confirmations.iter_mut().rev().find(|c| c.installation_id == inst_id && c.plan_id == plan_id) else {
        return err_resp(&HubError::not_found("confirmation_not_found"));
    };
    if !plan_is_open {
        item.status = String::from("invalidated");
        return err_resp(&HubError::conflict("confirmation_invalidated"));
    }
    if item.status != "pending" {
        return err_resp(&HubError::conflict("confirmation_already_decided"));
    }
    if exp_dig != item.exact_plan_digest {
        return err_resp(&HubError::conflict("plan_digest_mismatch"));
    }
    if decision == "confirm" && item.affected_addresses.iter().any(|addr| !confirmed_addrs.contains(addr)) {
        return err_resp(&HubError::unprocessable("confirmed_addresses_mismatch"));
    }
    item.status = if decision == "confirm" { String::from("confirmed") } else { String::from("held") };
    item.decided_by = Some(actor);
    item.decided_at = Some(format_utc_rfc3339_now());
    item.decision_reason = Some(reason);
    let updated = item.clone();
    LifecycleHubState::append_audit(&mut guard, "destructive_confirmation_decided", &inst_id, &format!("{plan_id}:{decision}"));
    if let Err(e) = st.persist(&guard) { return err_resp(&e); }
    json_resp(StatusCode::OK, &json!(updated))
}

async fn handle_get_bundle_imports(State(st): State<Arc<LifecycleHubState>>) -> Response {
    let guard = match st.data.read() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    let last = guard.bundle_imports.last();
    json_resp(StatusCode::OK, &json!({
        "last_bundle_id": last.map(|b| b.bundle_id.as_str()),
        "last_imported_at": last.map(|b| b.imported_at.as_str()),
        "metadata_expiry_days": last.map(|b| b.metadata_expiry_days).unwrap_or(30),
        "imports": guard.bundle_imports,
    }))
}

async fn handle_post_bundle_import(State(st): State<Arc<LifecycleHubState>>, req: Request) -> Response {
    let (_, body) = match read_json_limited(req, MAX_ENROLLMENT_BYTES).await { Ok(v) => v, Err(e) => return err_resp(&e) };
    let bundle_id = body.get("bundle_id").and_then(Value::as_str).unwrap_or("").trim().to_string();
    let conf = body.get("confirmation").and_then(Value::as_str).unwrap_or("");
    if bundle_id.is_empty() || conf != bundle_id {
        return err_resp(&HubError::unprocessable("bundle_confirmation_invalid"));
    }
    let sig_ok = body.get("signature_verified").and_then(Value::as_bool).unwrap_or(false);
    let cksum_ok = body.get("checksums_verified").and_then(Value::as_bool).unwrap_or(false);
    if !sig_ok || !cksum_ok {
        return err_resp(&HubError::unprocessable("bundle_verification_failed"));
    }
    let mut guard = match st.data.write() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    let extends = body.get("extends_bundle_id").and_then(Value::as_str).map(String::from);
    let lineage_ok = match (&extends, guard.bundle_imports.last()) {
        (Some(ext), Some(prev)) => prev.bundle_id == *ext,
        (None, _) => true,
        (Some(_), None) => false,
    };
    if !lineage_ok { return err_resp(&HubError::unprocessable("bundle_lineage_broken")); }
    let r_start = body.get("recall_sequence_start").and_then(Value::as_u64).unwrap_or(0);
    let r_end = body.get("recall_sequence_end").and_then(Value::as_u64).unwrap_or(r_start);
    let prev_end = guard.bundle_imports.last().map(|b| b.recall_sequence_end).unwrap_or(0);
    let recall_cont = r_start <= prev_end + 1 && r_end >= r_start;
    if !recall_cont { return err_resp(&HubError::unprocessable("recall_sequence_gap")); }
    let exp_days = body.get("metadata_expiry_days").and_then(Value::as_u64).unwrap_or(30);
    let rec = BundleImportRecord {
        bundle_id: bundle_id.clone(),
        extends_bundle_id: extends,
        catalog_export_sha256: body.get("catalog_export_sha256").and_then(Value::as_str).unwrap_or("").to_string(),
        imported_at: format_utc_rfc3339_now(),
        operator: st.current_actor(),
        verification: json!({
            "vendor_signature_verified": sig_ok,
            "checksums_matched": cksum_ok,
            "checksum_count": body.get("checksum_count").and_then(Value::as_u64).unwrap_or(0),
            "lineage_verified": lineage_ok,
            "recall_sequence_continuous": recall_cont,
            "configuration_signature_verified": body.get("configuration_signature_verified").and_then(Value::as_bool).unwrap_or(true),
        }),
        contents: json!({
            "releases": body.get("releases").cloned().unwrap_or_else(|| json!([])),
            "channels": body.get("channels").cloned().unwrap_or_else(|| json!({})),
            "recall_notices": body.get("recall_notices").cloned().unwrap_or_else(|| json!([])),
            "image_layer_count": body.get("image_layer_count").and_then(Value::as_u64).unwrap_or(0),
            "configuration_package_count": body.get("configuration_package_count").and_then(Value::as_u64).unwrap_or(0),
            "metadata_expiry_days": exp_days,
        }),
        recall_sequence_end: r_end,
        metadata_expiry_days: exp_days,
    };
    guard.bundle_imports.push(rec.clone());
    LifecycleHubState::append_audit(&mut guard, "bundle_imported", "hub", &bundle_id);
    if let Err(e) = st.persist(&guard) { return err_resp(&e); }
    json_resp(StatusCode::CREATED, &json!(rec))
}

async fn handle_get_release_hub_connection(State(st): State<Arc<LifecycleHubState>>) -> Response {
    let guard = match st.data.read() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    json_resp(StatusCode::OK, &json!(guard.release_connection))
}

async fn handle_post_release_hub_connection(State(st): State<Arc<LifecycleHubState>>, req: Request) -> Response {
    let (_, body) = match read_json_limited(req, MAX_APPROVAL_BYTES).await { Ok(v) => v, Err(e) => return err_resp(&e) };
    let rev = body.get("revision").and_then(Value::as_u64).unwrap_or(u64::MAX);
    let reason = body.get("reason").and_then(Value::as_str).unwrap_or("").trim();
    let conf = body.get("confirmation").and_then(Value::as_str).unwrap_or("").trim();
    if reason.len() < 3 || conf.is_empty() { return err_resp(&HubError::unprocessable("release_hub_endpoint_invalid")); }
    let ep_raw = body.get("endpoint").and_then(Value::as_str);
    let norm_ep = match ep_raw {
        Some(s) => {
            let n = match normalize_release_hub_endpoint(s) { Ok(n) => n, Err(e) => return err_resp(&e) };
            if conf != n && conf != s.trim() {
                return err_resp(&HubError::unprocessable("release_hub_endpoint_confirmation_mismatch"));
            }
            Some(n)
        }
        None => {
            if conf != "reset" {
                return err_resp(&HubError::unprocessable("release_hub_endpoint_confirmation_mismatch"));
            }
            None
        }
    };
    let mut guard = match st.data.write() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    if guard.release_connection.revision != rev {
        return err_resp(&HubError::conflict("release_hub_endpoint_revision_conflict"));
    }
    guard.release_connection.revision += 1;
    if let Some(n) = norm_ep {
        guard.release_connection.endpoint = n.clone();
        guard.release_connection.configured_endpoint = Some(n);
        guard.release_connection.source = String::from("saved");
    } else {
        guard.release_connection.configured_endpoint = None;
        guard.release_connection.endpoint = String::from(crate::hub_state::DEFAULT_RELEASE_HUB_ENDPOINT);
        guard.release_connection.source = String::from("local-default");
    }
    let updated = guard.release_connection.clone();
    LifecycleHubState::append_audit(&mut guard, "release_hub_endpoint_changed", "hub", &updated.endpoint);
    if let Err(e) = st.persist(&guard) { return err_resp(&e); }
    json_resp(StatusCode::OK, &json!(updated))
}

async fn handle_release_hub_catalog_preview(State(st): State<Arc<LifecycleHubState>>) -> Response {
    let (endpoint, enrolled) = match st.data.read() {
        Ok(g) => (g.release_connection.endpoint.clone(), g.installations.keys().cloned().collect::<Vec<_>>()),
        Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")),
    };
    let preview = fetch_release_hub_catalog_preview(&endpoint, &enrolled).await;
    json_resp(StatusCode::OK, &preview)
}

async fn handle_release_hub_provision(State(st): State<Arc<LifecycleHubState>>, req: Request) -> Response {
    let (_, body) = match read_json_limited(req, MAX_APPROVAL_BYTES).await { Ok(v) => v, Err(e) => return err_resp(&e) };
    let endpoint = match st.data.read() {
        Ok(g) => g.release_connection.endpoint.clone(),
        Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")),
    };
    let (status, _, bytes) = match fetch_http_get_bounded(&format!("{endpoint}/v1/catalog"), MAX_CATALOG_BYTES).await {
        Ok(v) => v,
        Err(e) => return err_resp(&e),
    };
    if status != 200 { return err_resp(&HubError::unavailable("release_hub_unavailable")); }
    let cat_doc: Value = match serde_json::from_slice(&bytes) {
        Ok(v) => v,
        Err(_) => return err_resp(&HubError::unavailable("release_hub_invalid_catalog")),
    };
    let mut guard = match st.data.write() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    match provision_from_release_catalog(&st, &mut guard, &endpoint, &cat_doc, &body) {
        Ok(receipt) => {
            if let Err(e) = st.persist(&guard) { return err_resp(&e); }
            json_resp(StatusCode::OK, &receipt)
        }
        Err(e) => err_resp(&e),
    }
}

async fn handle_catalog_trust_get(State(st): State<Arc<LifecycleHubState>>) -> Response {
    let guard = match st.data.read() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    json_resp(StatusCode::OK, &json!({
        "configured": guard.catalog_trust.trusted_key_id.is_some(),
        "trust": guard.catalog_trust,
        "endpoint": guard.release_connection.endpoint,
    }))
}

async fn handle_catalog_trust_approve(State(st): State<Arc<LifecycleHubState>>, req: Request) -> Response {
    let (_, body) = match read_json_limited(req, MAX_APPROVAL_BYTES).await { Ok(v) => v, Err(e) => return err_resp(&e) };
    let key_id = body.get("key_id").and_then(Value::as_str).unwrap_or("").trim().to_string();
    let pub_b64 = body.get("public_key_b64").and_then(Value::as_str).unwrap_or("").trim().to_string();
    if key_id.is_empty() || pub_b64.is_empty() {
        return err_resp(&HubError::unprocessable("trust_key_invalid"));
    }
    let actor = st.current_actor();
    let mut guard = match st.data.write() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    guard.catalog_trust.trusted_key_id = Some(key_id.clone());
    guard.catalog_trust.trusted_public_key_b64 = Some(pub_b64);
    guard.catalog_trust.approved_by = Some(actor);
    guard.catalog_trust.approved_at = Some(format_utc_rfc3339_now());
    guard.catalog_trust.root_version = guard.catalog_trust.root_version.max(1);
    let snap = guard.catalog_trust.clone();
    LifecycleHubState::append_audit(&mut guard, "catalog_trust_approved", "hub", &key_id);
    if let Err(e) = st.persist(&guard) { return err_resp(&e); }
    json_resp(StatusCode::OK, &json!({"configured": true, "trust": snap}))
}

async fn handle_catalog_import(State(st): State<Arc<LifecycleHubState>>, req: Request) -> Response {
    let (_, body) = match read_json_limited(req, MAX_CATALOG_BYTES).await { Ok(v) => v, Err(e) => return err_resp(&e) };
    let raw_str = body.get("export_raw").and_then(Value::as_str).unwrap_or("");
    let sig = body.get("signature").and_then(Value::as_str).unwrap_or("");
    let kid = body.get("key_id").and_then(Value::as_str);
    let actor = st.current_actor();
    let mut guard = match st.data.write() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    match adopt_export_into_state(&st, &mut guard, raw_str.as_bytes(), sig, kid, &actor, "manual-import") {
        Ok((accepted, plans)) => {
            if let Err(e) = st.persist(&guard) { return err_resp(&e); }
            json_resp(StatusCode::OK, &json!({"accepted": accepted, "plans": plans}))
        }
        Err(e) => err_resp(&e),
    }
}

async fn handle_catalog_updates_get(State(st): State<Arc<LifecycleHubState>>) -> Response {
    let guard = match st.data.read() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    json_resp(StatusCode::OK, &build_update_status_payload(&guard))
}

pub async fn execute_live_update_check(st: &Arc<LifecycleHubState>) -> Result<Value, HubError> {
    let (endpoint, pinned_pk, cur_accepted, trust_snap) = match st.data.read() {
        Ok(g) => (
            g.release_connection.endpoint.clone(),
            g.catalog_trust.trusted_public_key_b64.clone(),
            g.accepted_catalog.clone(),
            g.catalog_trust.clone(),
        ),
        Err(_) => return Err(HubError::unavailable("storage_unavailable")),
    };
    let (status, hdrs, raw_bytes) = fetch_http_get_bounded(&format!("{endpoint}/v1/catalog/export"), MAX_CATALOG_BYTES).await?;
    if status != 200 { return Err(HubError::unavailable("release_hub_export_unavailable")); }
    let sig = hdrs.get("x-fdai-export-signature").and_then(|v| v.to_str().ok()).unwrap_or("").to_string();
    let key_id = hdrs.get("x-fdai-export-key-id").and_then(|v| v.to_str().ok()).map(String::from);
    let doc: Value = serde_json::from_slice(&raw_bytes).map_err(|_| HubError::unavailable("invalid_catalog_export"))?;
    let sha = sha256_hex(&raw_bytes);
    let rev = doc.get("revision").and_then(Value::as_u64).unwrap_or(0);
    let expires_at = doc.get("expires_at").and_then(Value::as_str).unwrap_or("").to_string();
    let effective_pk = pinned_pk.as_deref().or_else(|| doc.get("public_key_b64").and_then(Value::as_str));
    let sig_verified = effective_pk.is_some_and(|pk| LifecycleHubState::verify_ed25519_b64(pk, &raw_bytes, &sig));
    let tuf_integrity = fetch_and_verify_tuf_metadata(&endpoint, effective_pk, &trust_snap).await;
    let tuf_ok = tuf_integrity
        .as_ref()
        .is_none_or(|ti| ti.get("verified").and_then(Value::as_bool).unwrap_or(false));
    let all_verified = sig_verified && tuf_ok;
    let next_rels = parse_export_releases(&doc);
    let mut next_chs = BTreeMap::new();
    if let Some(co) = doc.get("channels").and_then(Value::as_object) {
        for (c, v) in co {
            if let Some(a) = v.as_array() {
                next_chs.insert(c.clone(), a.iter().filter_map(Value::as_str).map(String::from).collect());
            }
        }
    }
    let change = compute_catalog_diff(cur_accepted.as_ref(), &next_rels, &next_chs);
    let unchanged = cur_accepted.as_ref().is_some_and(|c| c.sha256 == sha && c.revision == rev);
    let outcome = if !all_verified { "failed" } else if unchanged { "unchanged" } else { "review_required" };
    let candidate = json!({
        "revision": rev,
        "sha256": sha,
        "expires_at": expires_at,
        "signature_verified": sig_verified,
        "key_id": key_id,
        "accepted_revision": cur_accepted.as_ref().map(|c| c.revision),
        "decision": {"allow": all_verified, "reasons": if all_verified { json!([]) } else if !sig_verified { json!(["signature_invalid"]) } else { json!(["tuf_integrity_failed"]) }},
        "change": change,
        "integrity": tuf_integrity,
    });
    let check_rec = json!({
        "checked_at": format_utc_rfc3339_now(),
        "outcome": outcome,
        "detail": if all_verified { "Catalog export and TUF roles verified." } else { "Catalog signature or TUF verification failed." },
        "candidate": candidate,
        "plans": [],
        "integrity": tuf_integrity,
    });
    if let Ok(mut guard) = st.data.write() {
        guard.last_update_check = Some(check_rec.clone());
        if all_verified {
            guard.pending_candidate_export = Some(json!({
                "revision": rev,
                "sha256": sha,
                "raw": String::from_utf8_lossy(&raw_bytes).to_string(),
                "signature": sig,
                "key_id": key_id,
            }));
        }
        let _ = st.persist(&guard);
    }
    Ok(check_rec)
}

async fn handle_catalog_updates_check(
    State(st): State<Arc<LifecycleHubState>>,
    headers: HeaderMap,
) -> Response {
    if let Err(e) = check_mutation_origin(&headers) { return err_resp(&e); }
    let Ok(_permit) = st.op_semaphore.try_acquire() else {
        return err_resp(&HubError::new(429, "too_many_requests"));
    };
    match execute_live_update_check(&st).await {
        Ok(rec) => json_resp(StatusCode::OK, &rec),
        Err(e) => err_resp(&e),
    }
}

async fn handle_catalog_updates_apply(State(st): State<Arc<LifecycleHubState>>, req: Request) -> Response {
    let (_, body) = match read_json_limited(req, MAX_APPROVAL_BYTES).await { Ok(v) => v, Err(e) => return err_resp(&e) };
    let req_rev = body.get("revision").and_then(Value::as_u64).unwrap_or(u64::MAX);
    let req_sha = body.get("sha256").and_then(Value::as_str).unwrap_or("");
    let actor = st.current_actor();
    let mut guard = match st.data.write() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    let Some(cand) = guard.pending_candidate_export.clone() else {
        return err_resp(&HubError::conflict("no_pending_candidate"));
    };
    let c_rev = cand.get("revision").and_then(Value::as_u64).unwrap_or(0);
    let c_sha = cand.get("sha256").and_then(Value::as_str).unwrap_or("");
    if c_rev != req_rev || c_sha != req_sha {
        return err_resp(&HubError::conflict("candidate_mismatch"));
    }
    let raw = cand.get("raw").and_then(Value::as_str).unwrap_or("");
    let sig = cand.get("signature").and_then(Value::as_str).unwrap_or("");
    let kid = cand.get("key_id").and_then(Value::as_str);
    match adopt_export_into_state(&st, &mut guard, raw.as_bytes(), sig, kid, &actor, "operator-apply") {
        Ok((_accepted, plans)) => {
            let rec = json!({
                "checked_at": format_utc_rfc3339_now(),
                "outcome": "adopted",
                "detail": format!("Adopted catalog revision {c_rev}."),
                "candidate": Value::Null,
                "plans": plans,
            });
            guard.last_update_check = Some(rec.clone());
            guard.pending_candidate_export = None;
            if let Err(e) = st.persist(&guard) { return err_resp(&e); }
            json_resp(StatusCode::OK, &rec)
        }
        Err(e) => err_resp(&e),
    }
}

async fn handle_catalog_releases(State(st): State<Arc<LifecycleHubState>>) -> Response {
    let guard = match st.data.read() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    let rels = guard.accepted_catalog.as_ref().map(|c| c.releases.clone()).unwrap_or_default();
    json_resp(StatusCode::OK, &json!({"releases": rels}))
}

async fn handle_local_channels_get(State(st): State<Arc<LifecycleHubState>>) -> Response {
    let guard = match st.data.read() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    json_resp(StatusCode::OK, &json!({"channels": guard.local_channels}))
}

async fn handle_local_channels_post(State(st): State<Arc<LifecycleHubState>>, req: Request) -> Response {
    let (_, body) = match read_json_limited(req, MAX_APPROVAL_BYTES).await { Ok(v) => v, Err(e) => return err_resp(&e) };
    let ch = body.get("channel").and_then(Value::as_str).unwrap_or("").trim().to_string();
    let rel_id = body.get("release_id").and_then(Value::as_str).unwrap_or("").trim().to_string();
    let conf = body.get("confirmation").and_then(Value::as_str).unwrap_or("");
    if ch.is_empty() || rel_id.is_empty() || conf != ch {
        return err_resp(&HubError::unprocessable("local_channel_invalid"));
    }
    let mut guard = match st.data.write() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    let Some(ref cat) = guard.accepted_catalog else {
        return err_resp(&HubError::unavailable("catalog_not_configured"));
    };
    let eligible = cat.releases.iter().any(|r| r.release_id == rel_id && !r.recalled);
    if !eligible {
        return err_resp(&HubError::conflict("release_not_eligible"));
    }
    let list = guard.local_channels.entry(ch.clone()).or_default();
    if !list.contains(&rel_id) { list.push(rel_id.clone()); }
    LifecycleHubState::append_audit(&mut guard, "local_channel_updated", "hub", &format!("{ch}:{rel_id}"));
    if let Err(e) = st.persist(&guard) { return err_resp(&e); }
    json_resp(StatusCode::OK, &json!({"channels": guard.local_channels}))
}

async fn handle_recompute(
    State(st): State<Arc<LifecycleHubState>>,
    AxPath(inst_id): AxPath<String>,
    headers: HeaderMap,
) -> Response {
    if let Err(e) = check_mutation_origin(&headers) { return err_resp(&e); }
    let mut guard = match st.data.write() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    match st.evaluate_and_plan_locked(&mut guard, &inst_id) {
        Ok(eval) => {
            if let Err(e) = st.persist(&guard) { return err_resp(&e); }
            json_resp(StatusCode::OK, &json!(eval))
        }
        Err(e) => err_resp(&e),
    }
}

async fn handle_config_keys_status(State(st): State<Arc<LifecycleHubState>>, AxPath(inst_id): AxPath<String>) -> Response {
    let guard = match st.data.read() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    let val = guard.configuration_keys.get(&inst_id).cloned().unwrap_or_else(|| json!({"installation_id": inst_id, "keys": [], "pending": []}));
    json_resp(StatusCode::OK, &val)
}

async fn handle_config_keys_op(
    State(st): State<Arc<LifecycleHubState>>,
    AxPath((inst_id, op)): AxPath<(String, String)>,
    req: Request,
) -> Response {
    let (_, body) = match read_json_limited(req, MAX_APPROVAL_BYTES).await { Ok(v) => v, Err(e) => return err_resp(&e) };
    let dig = sha256_hex(&canonical_json_bytes(&Value::Object(body.clone())));
    let mut guard = match st.data.write() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    guard.configuration_keys.insert(inst_id.clone(), json!({"installation_id": inst_id, "last_operation": op, "request_digest": dig, "updated_at": format_utc_rfc3339_now()}));
    LifecycleHubState::append_audit(&mut guard, "configuration_key_op", &inst_id, &op);
    if let Err(e) = st.persist(&guard) { return err_resp(&e); }
    json_resp(StatusCode::ACCEPTED, &json!({"request_digest": dig}))
}

async fn handle_config_read(State(st): State<Arc<LifecycleHubState>>, AxPath(inst_id): AxPath<String>) -> Response {
    let guard = match st.data.read() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    let val = guard.configurations.get(&inst_id).cloned().unwrap_or_else(|| json!({"installation_id": inst_id, "revisions": []}));
    json_resp(StatusCode::OK, &val)
}

async fn handle_config_op(
    State(st): State<Arc<LifecycleHubState>>,
    AxPath((inst_id, op)): AxPath<(String, String)>,
    req: Request,
) -> Response {
    let (_, body) = match read_json_limited(req, MAX_STATE_BYTES).await { Ok(v) => v, Err(e) => return err_resp(&e) };
    let dig = sha256_hex(&canonical_json_bytes(&Value::Object(body)));
    let mut guard = match st.data.write() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    guard.configurations.insert(inst_id.clone(), json!({"installation_id": inst_id, "operation": op, "digest": dig, "updated_at": format_utc_rfc3339_now()}));
    LifecycleHubState::append_audit(&mut guard, "configuration_import_op", &inst_id, &op);
    if let Err(e) = st.persist(&guard) { return err_resp(&e); }
    json_resp(StatusCode::ACCEPTED, &json!({"digest": dig, "operation": op}))
}

async fn handle_native_op(
    State(st): State<Arc<LifecycleHubState>>,
    AxPath((inst_id, op)): AxPath<(String, String)>,
    req: Request,
) -> Response {
    if !matches!(
        op.as_str(),
        "native-proofs"
            | "native-ownership"
            | "native-transition-approval"
            | "native-transition-completion"
            | "native-transition-state-reconciliation-approval"
            | "native-transition-state-reconciliation"
    ) {
        return err_resp(&HubError::not_found("not_found"));
    }
    let (_, body) = match read_json_limited(req, 192 * 1024).await { Ok(v) => v, Err(e) => return err_resp(&e) };
    let dig = sha256_hex(&canonical_json_bytes(&Value::Object(body)));
    let sig = st.sign_b64(dig.as_bytes());
    let mut guard = match st.data.write() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    let rec = json!({"installation_id": inst_id, "operation": op, "digest": dig, "signature": sig, "recorded_at": format_utc_rfc3339_now()});
    guard.native_ownership.insert(format!("{inst_id}:{op}"), rec.clone());
    LifecycleHubState::append_audit(&mut guard, "native_ownership_op", &inst_id, &op);
    if let Err(e) = st.persist(&guard) { return err_resp(&e); }
    json_resp(StatusCode::OK, &rec)
}

async fn handle_stencil_state_put(
    State(st): State<Arc<LifecycleHubState>>,
    AxPath(inst_id): AxPath<String>,
    req: Request,
) -> Response {
    let (_, body) = match read_json_limited(req, MAX_ENROLLMENT_BYTES).await { Ok(v) => v, Err(e) => return err_resp(&e) };
    if body.contains_key("pinned_grant_id") || body.contains_key("pinned_grant_revision") || body.contains_key("pinned_grant_scope_digest") {
        return err_resp(&HubError::unprocessable("server_pinned_grant_fields_forbidden"));
    }
    let mut guard = match st.data.write() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    let rec = json!({"installation_id": inst_id, "state": Value::Object(body), "updated_at": format_utc_rfc3339_now()});
    guard.stencil_states.insert(inst_id.clone(), rec.clone());
    LifecycleHubState::append_audit(&mut guard, "stencil_state_saved", &inst_id, "put");
    if let Err(e) = st.persist(&guard) { return err_resp(&e); }
    json_resp(StatusCode::OK, &rec)
}

async fn handle_stencil_readiness_get(State(st): State<Arc<LifecycleHubState>>, AxPath(inst_id): AxPath<String>) -> Response {
    let guard = match st.data.read() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    let Some(val) = guard.stencil_states.get(&inst_id) else {
        return err_resp(&HubError::not_found("stencil_state_not_found"));
    };
    json_resp(StatusCode::OK, &json!({"installation_id": inst_id, "ready": true, "state": val}))
}

async fn handle_stencil_reconcile_post(
    State(st): State<Arc<LifecycleHubState>>,
    AxPath(inst_id): AxPath<String>,
    req: Request,
) -> Response {
    let (_, body) = match read_json_limited(req, MAX_ENROLLMENT_BYTES).await { Ok(v) => v, Err(e) => return err_resp(&e) };
    let mut guard = match st.data.write() { Ok(g) => g, Err(_) => return err_resp(&HubError::unavailable("storage_unavailable")) };
    if !guard.stencil_states.contains_key(&inst_id) {
        return err_resp(&HubError::not_found("stencil_state_not_found"));
    }
    let rec = json!({"installation_id": inst_id, "reconciled": true, "input_digest": sha256_hex(&canonical_json_bytes(&Value::Object(body))), "reconciled_at": format_utc_rfc3339_now()});
    LifecycleHubState::append_audit(&mut guard, "stencil_reconciled", &inst_id, "reconcile");
    if let Err(e) = st.persist(&guard) { return err_resp(&e); }
    json_resp(StatusCode::OK, &rec)
}

pub fn build_lifecycle_hub_router_with_state(state: Arc<LifecycleHubState>) -> Router {
    Router::new()
        .route("/healthz", get(handle_healthz).head(handle_healthz))
        .route("/readyz", get(handle_readyz).head(handle_readyz))
        .route("/metrics", get(handle_metrics))
        .route("/v1/hub/public-key", get(handle_hub_public_key))
        .route("/v1/setup/status", get(handle_setup_status))
        .route("/auth/config", get(handle_auth_config))
        .route("/auth/session", get(handle_auth_session))
        .route("/auth/entra/login", post(handle_entra_login))
        .route("/auth/entra/logout", post(handle_entra_logout))
        .route("/v1/auth/session", get(handle_auth_session))
        .route("/v1/auth/entra/login", post(handle_entra_login))
        .route("/v1/auth/entra/logout", post(handle_entra_logout))
        .route("/v1/installations", get(handle_list_installations).head(handle_list_installations))
        .route("/v1/installations/{installation_id}", get(handle_get_installation))
        .route("/v1/installations/{installation_id}/enrollment", post(handle_post_enrollment))
        .route("/v1/installations/{installation_id}/enrollment-request", post(handle_post_enrollment))
        .route("/v1/enrollments/{installation_id}/requests", post(handle_post_enrollment))
        .route("/v1/enrollments/pending", get(handle_list_pending))
        .route("/v1/enrollments/pending/{installation_id}", get(handle_get_pending))
        .route("/v1/enrollments/bindable", get(handle_list_bindable))
        .route("/v1/installations/{installation_id}/enrollment/approve", post(handle_approve_enrollment))
        .route("/v1/installations/{installation_id}/enrollment/reject", post(handle_reject_enrollment))
        .route("/v1/installations/{installation_id}/plan", get(handle_get_plan))
        .route("/v1/installations/{installation_id}/plans/{plan_id}", get(handle_get_plan_detail))
        .route("/v1/installations/{installation_id}/plans/{plan_id}/reports", post(handle_post_report))
        .route("/v1/installations/{installation_id}/state", post(handle_post_state))
        .route("/v1/installations/{installation_id}/entitlement-handoff", get(handle_entitlement_handoff).post(handle_post_entitlement_handoff))
        .route("/v1/installations/{installation_id}/suppressions", post(handle_post_suppression))
        .route("/v1/installations/{installation_id}/suppressions/lift", post(handle_lift_suppression))
        .route("/v1/installations/{installation_id}/execution-settings", get(handle_get_execution_settings).post(handle_post_execution_settings))
        .route("/v1/installations/{installation_id}/application-binding", get(handle_get_execution_settings).post(handle_post_execution_settings))
        .route("/v1/installations/{installation_id}/recompute", post(handle_recompute))
        .route("/v1/installations/{installation_id}/commands", post(handle_post_command))
        .route("/v1/installations/{installation_id}/plans/{plan_id}/confirmations", post(handle_post_confirmation_proposal))
        .route("/v1/installations/{installation_id}/plans/{plan_id}/confirmations/decision", post(handle_post_confirmation_decision))
        .route("/v1/installations/{installation_id}/configuration-keys", get(handle_config_keys_status))
        .route("/v1/installations/{installation_id}/configuration-keys/requests/{digest}", get(handle_config_keys_status))
        .route("/v1/installations/{installation_id}/configuration-keys/{operation}", post(handle_config_keys_op))
        .route("/v1/installations/{installation_id}/configuration", get(handle_config_read))
        .route("/v1/installations/{installation_id}/configuration/revisions/{digest}", get(handle_config_read))
        .route("/v1/installations/{installation_id}/configuration-scope/requests/{digest}", get(handle_config_read))
        .route("/v1/installations/{installation_id}/configuration/{operation}", post(handle_config_op))
        .route("/v1/installations/{installation_id}/configuration-scope/{operation}", post(handle_config_op))
        .route("/v1/installations/{installation_id}/stencil-state", put(handle_stencil_state_put))
        .route("/v1/installations/{installation_id}/stencil-readiness", get(handle_stencil_readiness_get))
        .route("/v1/installations/{installation_id}/stencil-reconcile", post(handle_stencil_reconcile_post))
        .route("/v1/installations/{installation_id}/{op}", post(handle_native_op))
        .route("/v1/commands", get(handle_get_commands))
        .route("/v1/confirmations", get(handle_get_confirmations))
        .route("/v1/bundle-imports", get(handle_get_bundle_imports).post(handle_post_bundle_import))
        .route("/v1/configurations", get(handle_list_configurations))
        .route("/v1/audit", get(handle_list_audit).head(handle_list_audit))
        .route("/v1/release-hub/connection", get(handle_get_release_hub_connection).post(handle_post_release_hub_connection))
        .route("/v1/release-hub/catalog", get(handle_release_hub_catalog_preview))
        .route("/v1/release-hub/provision", post(handle_release_hub_provision))
        .route("/v1/catalog/trust", get(handle_catalog_trust_get))
        .route("/v1/catalog/trust/approve", post(handle_catalog_trust_approve))
        .route("/v1/catalog/import", post(handle_catalog_import))
        .route("/v1/catalog/updates", get(handle_catalog_updates_get))
        .route("/v1/catalog/updates/check", post(handle_catalog_updates_check))
        .route("/v1/catalog/updates/apply", post(handle_catalog_updates_apply))
        .route("/v1/catalog/releases", get(handle_catalog_releases))
        .route("/v1/catalog/local-channels", get(handle_local_channels_get).post(handle_local_channels_post))
        .layer(fdai_http_runtime::axum::middleware::from_fn_with_state(
            Arc::clone(&state),
            lifecycle_hub_guard_middleware,
        ))
        .with_state(state)
}

pub fn build_lifecycle_hub_router() -> Router {
    build_lifecycle_hub_router_with_state(LifecycleHubState::open_from_env())
}

#[cfg(test)]
mod tests {
    use super::*;
    use fdai_http_runtime::http_body_util::{BodyExt as _, Full};
    use fdai_http_runtime::hyper::body::Bytes;
    use fdai_http_runtime::hyper::Request as HyperRequest;
    use fdai_http_runtime::hyper_util::client::legacy::Client;
    use fdai_http_runtime::hyper_util::rt::TokioExecutor;

    async fn send_req(port: u16, method: &str, path: &str, body: Option<String>) -> (StatusCode, Vec<u8>) {
        let client = Client::builder(TokioExecutor::new()).build_http::<Full<Bytes>>();
        let uri = format!("http://127.0.0.1:{port}{path}");
        let mut b = HyperRequest::builder().method(method).uri(uri);
        if body.is_some() { b = b.header("content-type", "application/json"); }
        let Ok(req) = b.body(Full::new(Bytes::from(body.unwrap_or_default()))) else {
            return (StatusCode::INTERNAL_SERVER_ERROR, Vec::new());
        };
        let Ok(resp) = client.request(req).await else { return (StatusCode::BAD_GATEWAY, Vec::new()); };
        let status = resp.status();
        let bytes = resp.into_body().collect().await.map(|c| c.to_bytes().to_vec()).unwrap_or_default();
        (status, bytes)
    }

    #[tokio::test]
    async fn enrollment_plan_superseded_withdrawal_and_audit_chain_work() {
        let st = LifecycleHubState::open_ephemeral("http://127.0.0.1:8022");
        let app = build_lifecycle_hub_router_with_state(st.clone());
        let Ok(listener) = tokio::net::TcpListener::bind("127.0.0.1:0").await else { return; };
        let Ok(addr) = listener.local_addr() else { return; };
        let srv = tokio::spawn(async move { let _ = fdai_http_runtime::axum::serve(listener, app).await; });

        let (c1, b1) = send_req(addr.port(), "POST", "/v1/installations/inst-alpha/enrollment", Some(json!({"installation_key_id": "key-alpha-001", "channel": "DEV"}).to_string())).await;
        assert_eq!(c1, StatusCode::ACCEPTED);
        assert!(String::from_utf8_lossy(&b1).contains("key-alpha-001"));

        let (c2, _) = send_req(addr.port(), "POST", "/v1/installations/inst-alpha/enrollment/approve", Some(json!({"installation_key_id": "key-alpha-001"}).to_string())).await;
        assert_eq!(c2, StatusCode::OK);

        let (c3, b3) = send_req(addr.port(), "GET", "/v1/audit", None).await;
        assert_eq!(c3, StatusCode::OK);
        assert!(String::from_utf8_lossy(&b3).contains("\"chain_intact\":true"));

        // SemVer numeric ordering & range check (1.10.0 > 1.9.0)
        assert_eq!(
            crate::hub_state::compare_semver("1.10.0", "1.9.0"),
            std::cmp::Ordering::Greater
        );
        assert!(crate::hub_state::semver_matches_range("1.10.0", ">=1.9.0,<2.0.0"));
        assert!(!crate::hub_state::semver_matches_range("2.0.0", ">=1.9.0,<2.0.0"));

        // Duplicate JSON key smuggling MUST be rejected with 422
        let (dup_code, _) = send_req(
            addr.port(),
            "POST",
            "/v1/installations/inst-alpha/suppressions",
            Some(String::from("{\"scope\":\"installation\",\"scope\":\"other\",\"ends_at\":\"2099-01-01T00:00:00Z\",\"confirmation\":\"inst-alpha\"}")),
        ).await;
        assert_eq!(dup_code, StatusCode::UNPROCESSABLE_ENTITY);

        // Connection change without matching confirmation MUST fail with 422
        let (conn_code, _) = send_req(
            addr.port(),
            "POST",
            "/v1/release-hub/connection",
            Some(json!({"revision": 0, "endpoint": "http://127.0.0.1:8091", "reason": "change", "confirmation": "wrong"}).to_string()),
        ).await;
        assert_eq!(conn_code, StatusCode::UNPROCESSABLE_ENTITY);

        srv.abort();
    }
}
