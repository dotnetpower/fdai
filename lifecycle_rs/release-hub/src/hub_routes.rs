//! Complete Axum 0.8 router and security/validation boundary for Release Hub.

use crate::hub_state::{
    format_unix_rfc3339, is_custom_channel, is_hex_len, is_valid_channel,
    is_valid_component_slug, is_valid_semver, now_unix_secs, parse_strict_json_object,
    sha256_hex, CapabilityRecallRecord, CatalogError, CatalogEvent, PromotionRunReceipt,
    ReleaseHubState, StoredRelease, CANDIDATE_DOCKER_TAGS, MAX_BODY_BYTES, MAX_STENCIL_BODY_BYTES,
    OCI_IMAGE_MANIFEST_MEDIA_TYPE,
};
use crate::hub_stencil_routes::{build_stencil_and_customer_routes, require_customer_grant};
use fdai_http_runtime::axum::body::{to_bytes, Body};
use fdai_http_runtime::axum::extract::{Path as AxPath, Request, State};
use fdai_http_runtime::axum::http::header::{self, HeaderName, HeaderValue};
use fdai_http_runtime::axum::http::{HeaderMap, Method, StatusCode};
use fdai_http_runtime::axum::response::Response;
use fdai_http_runtime::axum::routing::{get, post};
use fdai_http_runtime::axum::Router;
use serde_json::{json, Map, Value};
use std::collections::BTreeSet;
use std::sync::Arc;

pub(crate) fn build_response(
    status: StatusCode,
    content_type: &'static str,
    body: Vec<u8>,
    extra: &[(&'static str, String)],
    head_only: bool,
) -> Response {
    let mut b = Response::builder()
        .status(status)
        .header(header::CONTENT_TYPE, content_type)
        .header(header::CACHE_CONTROL, "no-store")
        .header(HeaderName::from_static("x-content-type-options"), "nosniff")
        .header(HeaderName::from_static("x-frame-options"), "DENY")
        .header(HeaderName::from_static("referrer-policy"), "no-referrer")
        .header(
            HeaderName::from_static("content-security-policy"),
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
        );
    for (k, v) in extra {
        if let (Ok(hn), Ok(hv)) = (HeaderName::from_bytes(k.as_bytes()), HeaderValue::from_str(v)) {
            b = b.header(hn, hv);
        }
    }
    let payload = if head_only { Vec::new() } else { body };
    b.body(Body::from(payload))
        .unwrap_or_else(|_| Response::new(Body::empty()))
}

pub(crate) fn json_resp(status: StatusCode, val: &Value, extra: &[(&'static str, String)], head_only: bool) -> Response {
    let bytes = serde_json::to_vec(val).unwrap_or_else(|_| b"{}".to_vec());
    build_response(status, "application/json", bytes, extra, head_only)
}

pub(crate) fn err_resp(err: &CatalogError) -> Response {
    let status = StatusCode::from_u16(err.status).unwrap_or(StatusCode::BAD_REQUEST);
    json_resp(status, &json!({"error": err.message}), &[], false)
}

pub(crate) fn check_same_origin_mutation(headers: &HeaderMap) -> Result<(), CatalogError> {
    let Some(origin) = headers.get(header::ORIGIN).and_then(|v| v.to_str().ok()) else {
        return Ok(());
    };
    let host = headers.get(header::HOST).and_then(|v| v.to_str().ok()).unwrap_or("").trim();
    if host.is_empty() {
        return Err(CatalogError::new(403, "Cross-origin mutations are not allowed."));
    }
    let remote_origin = std::env::var("FDAI_RELEASE_HUB_REMOTE_ORIGIN").ok().filter(|s| !s.trim().is_empty());
    let ok = if let Some(ref ro) = remote_origin {
        origin == ro.trim()
    } else {
        origin == format!("http://{host}") || origin == format!("https://{host}")
    };
    if !ok {
        return Err(CatalogError::new(403, "Cross-origin mutations are not allowed."));
    }
    Ok(())
}

pub(crate) async fn read_strict_json_body(
    req: Request,
    max_bytes: usize,
) -> Result<(HeaderMap, Map<String, Value>), CatalogError> {
    let headers = req.headers().clone();
    check_same_origin_mutation(&headers)?;
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
        return Err(CatalogError::new(415, "Use application/json."));
    }
    let ce = headers
        .get(header::CONTENT_ENCODING)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("identity")
        .trim()
        .to_ascii_lowercase();
    if ce != "identity" {
        return Err(CatalogError::new(415, "Encoded request bodies are not supported."));
    }
    if let Some(cl_raw) = headers.get(header::CONTENT_LENGTH).and_then(|v| v.to_str().ok()) {
        let cl = cl_raw
            .trim()
            .parse::<i64>()
            .map_err(|_| CatalogError::bad_request("Content-Length must be an integer."))?;
        if cl < 0 {
            return Err(CatalogError::bad_request("Content-Length cannot be negative."));
        }
        if (cl as usize) > max_bytes {
            return Err(CatalogError::new(413, "Request body is too large."));
        }
    }
    let bytes = tokio::time::timeout(
        std::time::Duration::from_secs(10),
        to_bytes(req.into_body(), max_bytes.saturating_add(1)),
    )
    .await
    .map_err(|_| CatalogError::new(408, "Request body deadline exceeded."))?
    .map_err(|_| CatalogError::new(413, "Request body is too large."))?;
    if bytes.len() > max_bytes {
        return Err(CatalogError::new(413, "Request body is too large."));
    }
    let obj = parse_strict_json_object(&bytes)?;
    Ok((headers, obj))
}

pub(crate) fn etag_matches(headers: &HeaderMap, etag: &str) -> bool {
    let Some(inm) = headers.get(header::IF_NONE_MATCH).and_then(|v| v.to_str().ok()) else {
        return false;
    };
    inm.split(',')
        .map(|t| t.trim().trim_start_matches("W/"))
        .any(|t| t == etag || t == "*")
}

pub(crate) fn require_str<'a>(obj: &'a Map<String, Value>, key: &str) -> Result<&'a str, CatalogError> {
    obj.get(key)
        .and_then(Value::as_str)
        .ok_or_else(|| CatalogError::unprocessable(format!("Missing or invalid string field '{key}'.")))
}

fn require_u64(obj: &Map<String, Value>, key: &str) -> Result<u64, CatalogError> {
    obj.get(key)
        .and_then(Value::as_u64)
        .ok_or_else(|| CatalogError::unprocessable(format!("Missing or invalid integer field '{key}'.")))
}

async fn handle_healthz(State(st): State<Arc<ReleaseHubState>>, method: Method) -> Response {
    json_resp(StatusCode::OK, &json!({"status": "ok", "mode": st.mode}), &[], method == Method::HEAD)
}

async fn handle_readyz(State(st): State<Arc<ReleaseHubState>>, method: Method) -> Response {
    let pg_ok = if let Some(ref pg) = st.pg_ledger {
        pg.check_ready().await
    } else {
        true
    };
    let (state_ok, expired) = st
        .data
        .read()
        .map(|d| {
            let exp = now_unix_secs() >= d.last_updated_unix.saturating_add(d.ttl_seconds);
            (d.ttl_seconds > 0 && !d.created_at.is_empty(), exp)
        })
        .unwrap_or((false, true));
    let key_ok = !st.public_key_bytes.is_empty();
    let backend = if st.pg_ledger.is_some() { "postgres" } else { "file" };
    if pg_ok && state_ok && key_ok {
        json_resp(
            StatusCode::OK,
            &json!({
                "status": "ready",
                "signing_key": true,
                "storage_backend": backend,
                "storage_ok": true,
                "catalog_expired": expired,
            }),
            &[],
            method == Method::HEAD,
        )
    } else {
        json_resp(
            StatusCode::SERVICE_UNAVAILABLE,
            &json!({
                "status": "not-ready",
                "signing_key": key_ok,
                "storage_backend": backend,
                "storage_ok": pg_ok && state_ok,
                "catalog_expired": expired,
            }),
            &[],
            method == Method::HEAD,
        )
    }
}

async fn handle_auth_config(State(st): State<Arc<ReleaseHubState>>) -> Response {
    json_resp(StatusCode::OK, &st.remote_policy.auth_config_json(None), &[], false)
}

async fn handle_public_key(State(st): State<Arc<ReleaseHubState>>, method: Method) -> Response {
    json_resp(
        StatusCode::OK,
        &json!({
            "key_id": st.key_id,
            "algorithm": "Ed25519",
            "public_key_b64": st.public_key_b64,
            "public_key_pem": st.public_key_pem,
            "root_version": 1,
        }),
        &[],
        method == Method::HEAD,
    )
}

async fn handle_metrics(State(st): State<Arc<ReleaseHubState>>, headers: HeaderMap) -> Response {
    if !fdai_http_runtime::check_metrics_bearer(&headers, &st.remote_policy) {
        return json_resp(
            StatusCode::UNAUTHORIZED,
            &json!({"error": "metrics bearer token required"}),
            &[("www-authenticate", String::from("Bearer"))],
            false,
        );
    }
    let (rev, total, published, recalled, reqs, ttl_rem) = st
        .data
        .read()
        .map(|d| {
            let p = d.releases.values().filter(|r| r.published_at.is_some() && r.recalled_at.is_none()).count();
            let rec = d.releases.values().filter(|r| r.recalled_at.is_some()).count();
            let rem = d.last_updated_unix.saturating_add(d.ttl_seconds).saturating_sub(now_unix_secs());
            (d.revision, d.releases.len(), p, rec, d.deployment_requests.len(), rem)
        })
        .unwrap_or((0, 0, 0, 0, 0, 0));
    let pg_flag = u8::from(st.pg_ledger.is_some());
    let text = format!(
        "# TYPE fdai_release_hub_catalog_revision gauge\nfdai_release_hub_catalog_revision {rev}\n\
# TYPE fdai_release_hub_releases_total gauge\nfdai_release_hub_releases_total {total}\n\
# TYPE fdai_release_hub_published_releases gauge\nfdai_release_hub_published_releases {published}\n\
# TYPE fdai_release_hub_recalled_releases gauge\nfdai_release_hub_recalled_releases {recalled}\n\
# TYPE fdai_release_hub_deployment_requests_total gauge\nfdai_release_hub_deployment_requests_total {reqs}\n\
# TYPE fdai_release_hub_ttl_remaining_seconds gauge\nfdai_release_hub_ttl_remaining_seconds {ttl_rem}\n\
# TYPE fdai_release_hub_storage_pg_enabled gauge\nfdai_release_hub_storage_pg_enabled {pg_flag}\n"
    );
    build_response(StatusCode::OK, "text/plain; version=0.0.4; charset=utf-8", text.into_bytes(), &[], false)
}

async fn release_hub_guard_middleware(
    State(st): State<Arc<ReleaseHubState>>,
    req: Request,
    next: fdai_http_runtime::axum::middleware::Next,
) -> Response {
    let corr_id = fdai_http_runtime::resolve_or_generate_correlation_id(req.headers());
    let path_q = req.uri().path_and_query().map(|pq| pq.as_str()).unwrap_or("/");
    match fdai_http_runtime::check_trusted_host(req.headers(), req.method(), path_q, &st.remote_policy) {
        fdai_http_runtime::HostCheckOutcome::Allowed => {}
        fdai_http_runtime::HostCheckOutcome::RedirectPermanent(loc) => {
            return build_response(
                StatusCode::PERMANENT_REDIRECT,
                "text/plain; charset=utf-8",
                Vec::new(),
                &[("location", loc), ("x-correlation-id", corr_id)],
                true,
            );
        }
        fdai_http_runtime::HostCheckOutcome::UntrustedHost => {
            fdai_http_runtime::log_structured_hub_event("release-hub", "warn", "untrusted_host", &corr_id, path_q);
            return json_resp(
                StatusCode::FORBIDDEN,
                &json!({"error": "Untrusted Host header."}),
                &[("x-correlation-id", corr_id)],
                false,
            );
        }
    }
    let path = req.uri().path().to_string();
    if let Err((code, msg)) = fdai_http_runtime::enforce_hub_remote_auth(
        &st.authenticator,
        &st.remote_policy,
        req.headers(),
        req.method(),
        &path,
        true,
    )
    .await
    {
        fdai_http_runtime::log_structured_hub_event("release-hub", "warn", "auth_denied", &corr_id, &msg);
        let extra = if code == StatusCode::UNAUTHORIZED {
            vec![("www-authenticate", String::from("Bearer")), ("x-correlation-id", corr_id)]
        } else {
            vec![("x-correlation-id", corr_id)]
        };
        return json_resp(code, &json!({"error": msg}), &extra, false);
    }
    let mut resp = next.run(req).await;
    if let Ok(hv) = HeaderValue::from_str(&corr_id) {
        resp.headers_mut().insert(HeaderName::from_static("x-correlation-id"), hv);
    }
    resp
}

async fn handle_auth_session(State(st): State<Arc<ReleaseHubState>>) -> Response {
    json_resp(StatusCode::OK, &st.entra_status_payload(), &[], false)
}

async fn handle_entra_login(State(st): State<Arc<ReleaseHubState>>, req: Request) -> Response {
    let (_, body) = match read_strict_json_body(req, 8192).await {
        Ok(v) => v,
        Err(e) => return err_resp(&e),
    };
    match st.entra_sign_in(&body) {
        Ok(val) => json_resp(StatusCode::OK, &val, &[], false),
        Err(e) => err_resp(&e),
    }
}

async fn handle_entra_logout(State(st): State<Arc<ReleaseHubState>>, headers: HeaderMap) -> Response {
    if let Err(e) = check_same_origin_mutation(&headers) { return err_resp(&e); }
    json_resp(StatusCode::OK, &st.entra_sign_out(), &[], false)
}

async fn handle_catalog(State(st): State<Arc<ReleaseHubState>>, method: Method) -> Response {
    let guard = match st.data.read() {
        Ok(g) => g,
        Err(_) => return err_resp(&CatalogError::unavailable("Local storage is unavailable.")),
    };
    match st.build_catalog_snapshot_locked(&guard) {
        Ok(snap) => json_resp(StatusCode::OK, &snap, &[], method == Method::HEAD),
        Err(e) => err_resp(&e),
    }
}

async fn handle_export(State(st): State<Arc<ReleaseHubState>>, method: Method, headers: HeaderMap) -> Response {
    let guard = match st.data.read() {
        Ok(g) => g,
        Err(_) => return err_resp(&CatalogError::unavailable("Local storage is unavailable.")),
    };
    let (raw, digest_hex, sig) = match st.build_signed_export_locked(&guard) {
        Ok(v) => v,
        Err(e) => return err_resp(&e),
    };
    let etag = format!("\"{digest_hex}\"");
    if etag_matches(&headers, &etag) {
        return build_response(StatusCode::NOT_MODIFIED, "application/json", Vec::new(), &[("etag", etag)], true);
    }
    build_response(
        StatusCode::OK,
        "application/json",
        raw,
        &[
            ("etag", etag),
            ("x-fdai-export-signature", sig),
            ("x-fdai-export-key-id", st.key_id.clone()),
        ],
        method == Method::HEAD,
    )
}

async fn handle_metadata(State(st): State<Arc<ReleaseHubState>>, method: Method, headers: HeaderMap) -> Response {
    let guard = match st.data.read() {
        Ok(g) => g,
        Err(_) => return err_resp(&CatalogError::unavailable("Local storage is unavailable.")),
    };
    let (raw, digest_hex) = match st.build_signed_metadata_locked(&guard) {
        Ok(v) => v,
        Err(e) => return err_resp(&e),
    };
    let etag = format!("\"{digest_hex}\"");
    if etag_matches(&headers, &etag) {
        return build_response(StatusCode::NOT_MODIFIED, "application/json", Vec::new(), &[("etag", etag)], true);
    }
    build_response(StatusCode::OK, "application/json", raw, &[("etag", etag)], method == Method::HEAD)
}

async fn handle_renew(State(st): State<Arc<ReleaseHubState>>, req: Request) -> Response {
    let (_, body) = match read_strict_json_body(req, MAX_BODY_BYTES).await {
        Ok(v) => v,
        Err(e) => return err_resp(&e),
    };
    let rev = match require_u64(&body, "revision") { Ok(v) => v, Err(e) => return err_resp(&e) };
    let conf = match require_str(&body, "confirmation") { Ok(v) => v, Err(e) => return err_resp(&e) };
    let reason = match require_str(&body, "reason") { Ok(v) => v.trim(), Err(e) => return err_resp(&e) };
    if conf != format!("renew {rev}") {
        return err_resp(&CatalogError::unprocessable("Type renew and the exact catalog revision to confirm."));
    }
    if reason.len() < 3 || reason.len() > 500 {
        return err_resp(&CatalogError::unprocessable("A non-blank reason (3..=500 chars) is required."));
    }
    let actor = st.current_actor();
    let mut guard = match st.data.write() {
        Ok(g) => g,
        Err(_) => return err_resp(&CatalogError::unavailable("Local storage is unavailable.")),
    };
    if guard.revision != rev {
        return err_resp(&CatalogError::conflict("Catalog changed. Refresh and review before confirming again."));
    }
    for rel in guard.releases.values() {
        if let Some(ref sig) = rel.signature {
            if let Err(e) = st.verify_bytes_b64(rel.manifest.as_bytes(), sig) {
                return err_resp(&e);
            }
        }
    }
    let now_u = now_unix_secs().max(guard.last_updated_unix.saturating_add(1));
    let now_s = format_unix_rfc3339(now_u);
    guard.revision += 1;
    guard.last_updated_unix = now_u;
    let next_rev = guard.revision;
    guard.events.push(CatalogEvent {
        revision: next_rev,
        release_id: String::from("catalog"),
        action: String::from("renew"),
        reason: reason.to_string(),
        channel: None,
        occurred_at: now_s,
        actor,
    });
    if let Err(e) = st.persist(&guard) { return err_resp(&e); }
    match st.build_catalog_snapshot_locked(&guard) {
        Ok(snap) => json_resp(StatusCode::OK, &snap, &[], false),
        Err(e) => err_resp(&e),
    }
}

async fn handle_release_action(
    State(st): State<Arc<ReleaseHubState>>,
    AxPath((release_id, action)): AxPath<(String, String)>,
    req: Request,
) -> Response {
    if !matches!(action.as_str(), "register" | "publish" | "contribute" | "promote" | "recall") {
        return err_resp(&CatalogError::not_found("Unknown API route."));
    }
    let (_, body) = match read_strict_json_body(req, MAX_BODY_BYTES).await {
        Ok(v) => v,
        Err(e) => return err_resp(&e),
    };
    if !is_valid_semver(&release_id) {
        return err_resp(&CatalogError::unprocessable("Release id must be canonical SemVer."));
    }
    let rev = match require_u64(&body, "revision") { Ok(v) => v, Err(e) => return err_resp(&e) };
    let conf = match require_str(&body, "confirmation") { Ok(v) => v, Err(e) => return err_resp(&e) };
    let reason = match require_str(&body, "reason") { Ok(v) => v.trim(), Err(e) => return err_resp(&e) };
    if conf != release_id {
        return err_resp(&CatalogError::unprocessable("Type the exact Release id to confirm."));
    }
    if reason.len() < 3 || reason.len() > 500 {
        return err_resp(&CatalogError::unprocessable("A non-blank reason (3..=500 chars) is required."));
    }
    let actor = st.current_actor();
    let mut guard = match st.data.write() {
        Ok(g) => g,
        Err(_) => return err_resp(&CatalogError::unavailable("Local storage is unavailable.")),
    };
    if guard.revision != rev {
        return err_resp(&CatalogError::conflict("Catalog changed. Refresh and review before confirming again."));
    }
    let now_u = now_unix_secs().max(guard.last_updated_unix);
    let now_s = format_unix_rfc3339(now_u);

    match action.as_str() {
        "register" => {
            if guard.releases.contains_key(&release_id) {
                return err_resp(&CatalogError::conflict("Release ids are immutable and cannot be reused."));
            }
            let manifest_raw = match body.get("manifest").and_then(Value::as_str) {
                Some(m) if !m.trim().is_empty() => m.to_string(),
                _ => return err_resp(&CatalogError::unprocessable("A lifecycle Release manifest is required.")),
            };
            let parsed_m: Value = match serde_json::from_str::<Value>(&manifest_raw) {
                Ok(v) if v.is_object() => v,
                _ => return err_resp(&CatalogError::unprocessable("Invalid Release manifest.")),
            };
            let schema_ver = parsed_m.get("schema_version").and_then(Value::as_str).unwrap_or("");
            if !matches!(
                schema_ver,
                "fdai.application-release.v1"
                    | "fdai.application-release.v2"
                    | "fdai.lifecycle-release.v1"
                    | "fdai.release-manifest.v1"
            ) {
                return err_resp(&CatalogError::unprocessable("Only supported lifecycle Release manifests are accepted."));
            }
            if let Some(m_rel) = parsed_m.get("release_id").and_then(Value::as_str) {
                if m_rel != release_id {
                    return err_resp(&CatalogError::unprocessable("Manifest release_id does not match URL release_id."));
                }
            }
            let label = body.get("label").and_then(Value::as_str).unwrap_or("").trim().to_string();
            if label.len() > 160 {
                return err_resp(&CatalogError::unprocessable("Release label exceeds 160 characters."));
            }
            if manifest_raw.len() > 1_048_576 {
                return err_resp(&CatalogError::unprocessable("Release manifest exceeds 1 MiB limit."));
            }
            let digest = sha256_hex(manifest_raw.as_bytes());
            let stencil_id = parsed_m
                .get("stencil")
                .and_then(|s| s.get("stencil_id"))
                .and_then(Value::as_str)
                .map(String::from);
            let mut cap_ids = Vec::new();
            if let Some(caps) = parsed_m.get("capability_maximums").and_then(Value::as_object) {
                cap_ids.extend(caps.keys().cloned());
            }
            guard.releases.insert(release_id.clone(), StoredRelease {
                id: release_id.clone(),
                label,
                manifest: manifest_raw,
                digest,
                signature: None,
                published_at: None,
                recalled_at: None,
                capability_ids: cap_ids,
                stencil_id,
            });
            guard.revision += 1;
            guard.last_updated_unix = now_u;
            let next_rev = guard.revision;
            guard.events.push(CatalogEvent {
                revision: next_rev,
                release_id,
                action: String::from("register"),
                reason: reason.to_string(),
                channel: None,
                occurred_at: now_s,
                actor,
            });
        }
        "publish" => {
            let Some(rel) = guard.releases.get(&release_id).cloned() else {
                return err_resp(&CatalogError::not_found("Release not found."));
            };
            if rel.recalled_at.is_some() {
                return err_resp(&CatalogError::conflict("Recalled Releases cannot be changed or re-promoted."));
            }
            if rel.signature.is_some() {
                return err_resp(&CatalogError::conflict("Release is already published."));
            }
            if sha256_hex(rel.manifest.as_bytes()) != rel.digest {
                return err_resp(&CatalogError::conflict("Stored Release digest does not match the draft."));
            }
            let sig = st.sign_bytes_b64(rel.manifest.as_bytes());
            if let Some(slot) = guard.releases.get_mut(&release_id) {
                slot.signature = Some(sig);
                slot.published_at = Some(now_s.clone());
            }
            let dev_list = guard.channel_memberships.entry(String::from("DEV")).or_default();
            if !dev_list.contains(&release_id) {
                dev_list.push(release_id.clone());
            }
            guard.revision += 1;
            guard.last_updated_unix = now_u;
            let next_rev = guard.revision;
            guard.events.push(CatalogEvent {
                revision: next_rev,
                release_id,
                action: String::from("publish"),
                reason: reason.to_string(),
                channel: None,
                occurred_at: now_s,
                actor,
            });
        }
        "contribute" => {
            let channel = match body.get("channel").and_then(Value::as_str) {
                Some(c) if is_valid_channel(c) => c.to_string(),
                _ => return err_resp(&CatalogError::unprocessable("Choose a built-in channel or a custom- channel name.")),
            };
            let ch_conf = body.get("channel_confirmation").and_then(Value::as_str);
            if is_custom_channel(&channel) {
                if ch_conf != Some(channel.as_str()) {
                    return err_resp(&CatalogError::unprocessable("Type the exact custom channel name to confirm."));
                }
            } else if ch_conf.is_some() {
                return err_resp(&CatalogError::unprocessable("Custom channel confirmation is not valid for a built-in channel."));
            }
            let Some(rel) = guard.releases.get(&release_id).cloned() else {
                return err_resp(&CatalogError::not_found("Release not found."));
            };
            if rel.recalled_at.is_some() {
                return err_resp(&CatalogError::conflict("Recalled Releases cannot be changed or re-promoted."));
            }
            let Some(ref sig) = rel.signature else {
                return err_resp(&CatalogError::conflict("Publish the Release before adding it to a channel."));
            };
            if let Err(e) = st.verify_bytes_b64(rel.manifest.as_bytes(), sig) { return err_resp(&e); }
            let active_recalls = ReleaseHubState::active_recalled_capabilities(&guard);
            if rel.capability_ids.iter().any(|c| active_recalls.contains(c)) {
                return err_resp(&CatalogError::conflict("Releases with an active recalled capability cannot be promoted."));
            }
            let ch_list = guard.channel_memberships.entry(channel.clone()).or_default();
            if ch_list.contains(&release_id) {
                return err_resp(&CatalogError::conflict("Release already belongs to the target channel."));
            }
            ch_list.push(release_id.clone());
            guard.revision += 1;
            guard.last_updated_unix = now_u;
            let next_rev = guard.revision;
            guard.events.push(CatalogEvent {
                revision: next_rev,
                release_id,
                action: String::from("contribute"),
                reason: reason.to_string(),
                channel: Some(channel),
                occurred_at: now_s,
                actor,
            });
        }
        "promote" => {
            let src_ch = match require_str(&body, "source_channel") { Ok(v) => v.to_string(), Err(e) => return err_resp(&e) };
            let tgt_ch = match require_str(&body, "target_channel") { Ok(v) => v.to_string(), Err(e) => return err_resp(&e) };
            if !is_valid_channel(&src_ch) || !is_valid_channel(&tgt_ch) || src_ch == tgt_ch {
                return err_resp(&CatalogError::unprocessable("Invalid or identical source and target channel."));
            }
            let ch_conf = body.get("channel_confirmation").and_then(Value::as_str);
            if is_custom_channel(&tgt_ch) {
                if ch_conf != Some(tgt_ch.as_str()) {
                    return err_resp(&CatalogError::unprocessable("Type the exact custom channel name to confirm."));
                }
            } else if ch_conf.is_some() {
                return err_resp(&CatalogError::unprocessable("Custom channel confirmation is not valid for a built-in channel."));
            }
            if guard.channel_memberships.get(&tgt_ch).is_some_and(|v| v.contains(&release_id)) {
                return err_resp(&CatalogError::conflict("Release already belongs to target_channel."));
            }
            let Some(rel) = guard.releases.get(&release_id).cloned() else {
                return err_resp(&CatalogError::not_found("Release not found."));
            };
            if rel.recalled_at.is_some() {
                return err_resp(&CatalogError::conflict("Recalled Releases cannot be changed or re-promoted."));
            }
            let Some(ref sig) = rel.signature else {
                return err_resp(&CatalogError::conflict("Publish the Release before promoting it."));
            };
            if let Err(e) = st.verify_bytes_b64(rel.manifest.as_bytes(), sig) { return err_resp(&e); }
            let in_src = guard.channel_memberships.get(&src_ch).is_some_and(|v| v.contains(&release_id));
            if !in_src {
                return err_resp(&CatalogError::conflict("Release does not belong to source_channel."));
            }
            let active_recalls = ReleaseHubState::active_recalled_capabilities(&guard);
            if rel.capability_ids.iter().any(|c| active_recalls.contains(c)) {
                return err_resp(&CatalogError::conflict("Releases with an active recalled capability cannot be promoted."));
            }
            let req_labels: BTreeSet<String> = body.get("required_labels").and_then(Value::as_array)
                .map(|a| a.iter().filter_map(Value::as_str).map(String::from).collect())
                .unwrap_or_default();
            let got_labels: BTreeSet<String> = body.get("labels").and_then(Value::as_array)
                .map(|a| a.iter().filter_map(Value::as_str).map(String::from).collect())
                .unwrap_or_default();
            let min_soak = body.get("min_soak_seconds").and_then(Value::as_u64).unwrap_or(0);
            let min_canaries = body.get("min_healthy_canaries").and_then(Value::as_u64).unwrap_or(0);
            let max_timeout = body.get("max_stage_timeout_seconds").and_then(Value::as_u64).unwrap_or(3600);
            if max_timeout == 0 {
                return err_resp(&CatalogError::unprocessable("max_stage_timeout_seconds must be >= 1."));
            }
            let elapsed = body.get("elapsed_stage_seconds").and_then(Value::as_u64).unwrap_or(0);
            let obs = body.get("canary_observations").and_then(Value::as_array);
            let mut healthy_count = 0_u64;
            let mut healthy_soak_ok = 0_u64;
            let mut any_unhealthy = false;
            if let Some(arr) = obs {
                for item in arr {
                    if item.get("release_id").and_then(Value::as_str) != Some(release_id.as_str()) {
                        continue;
                    }
                    let healthy = item.get("healthy").and_then(Value::as_bool).unwrap_or(false);
                    let soak = item.get("soak_seconds").and_then(Value::as_u64).unwrap_or(0);
                    if healthy {
                        healthy_count += 1;
                        if soak >= min_soak { healthy_soak_ok += 1; }
                    } else {
                        any_unhealthy = true;
                    }
                }
            }
            let block_code = if elapsed > max_timeout {
                Some("promotion_stage_timed_out")
            } else if !req_labels.is_subset(&got_labels) {
                Some("promotion_labels_missing")
            } else if any_unhealthy || healthy_count < min_canaries {
                Some("promotion_canary_unhealthy")
            } else if min_soak > 0 && healthy_soak_ok < min_canaries.max(1) {
                Some("promotion_soak_incomplete")
            } else {
                None
            };
            let receipt_hash = sha256_hex(format!("{release_id}:{src_ch}:{tgt_ch}:{now_u}").as_bytes());
            let receipt_id = format!("pr-{}", &receipt_hash[..16]);
            if let Some(code) = block_code {
                guard.promotion_receipts.push(PromotionRunReceipt {
                    receipt_id,
                    release_id: release_id.clone(),
                    source_channel: src_ch,
                    target_channel: tgt_ch,
                    outcome: String::from("blocked"),
                    block_code: Some(String::from(code)),
                    reason: reason.to_string(),
                    actor,
                    recorded_at: now_s,
                });
                let _ = st.persist(&guard);
                return err_resp(&CatalogError::conflict(format!("Promotion stage blocked ({code}).")));
            }
            let tgt_list = guard.channel_memberships.entry(tgt_ch.clone()).or_default();
            if !tgt_list.contains(&release_id) {
                tgt_list.push(release_id.clone());
            }
            guard.promotion_receipts.push(PromotionRunReceipt {
                receipt_id,
                release_id: release_id.clone(),
                source_channel: src_ch,
                target_channel: tgt_ch.clone(),
                outcome: String::from("promoted"),
                block_code: None,
                reason: reason.to_string(),
                actor: actor.clone(),
                recorded_at: now_s.clone(),
            });
            guard.revision += 1;
            guard.last_updated_unix = now_u;
            let next_rev = guard.revision;
            guard.events.push(CatalogEvent {
                revision: next_rev,
                release_id,
                action: String::from("contribute"),
                reason: reason.to_string(),
                channel: Some(tgt_ch),
                occurred_at: now_s,
                actor,
            });
        }
        "recall" => {
            let Some(rel) = guard.releases.get(&release_id).cloned() else {
                return err_resp(&CatalogError::not_found("Release not found."));
            };
            if rel.recalled_at.is_some() {
                return err_resp(&CatalogError::conflict("Release is already recalled."));
            }
            if let Some(slot) = guard.releases.get_mut(&release_id) {
                slot.recalled_at = Some(now_s.clone());
            }
            guard.revision += 1;
            guard.last_updated_unix = now_u;
            let next_rev = guard.revision;
            guard.events.push(CatalogEvent {
                revision: next_rev,
                release_id,
                action: String::from("recall"),
                reason: reason.to_string(),
                channel: None,
                occurred_at: now_s,
                actor,
            });
        }
        _ => {}
    }

    if let Err(e) = st.persist(&guard) { return err_resp(&e); }
    match st.build_catalog_snapshot_locked(&guard) {
        Ok(snap) => json_resp(StatusCode::OK, &snap, &[], false),
        Err(e) => err_resp(&e),
    }
}

async fn handle_capability_action(
    State(st): State<Arc<ReleaseHubState>>,
    AxPath(tail): AxPath<String>,
    req: Request,
) -> Response {
    let (cap_id, action) = if let Some(c) = tail.strip_suffix("/recall") {
        (c, "recall")
    } else if let Some(c) = tail.strip_suffix("/lift") {
        (c, "lift")
    } else {
        return err_resp(&CatalogError::not_found("Unknown API route."));
    };
    if cap_id.is_empty() || cap_id.len() > 160 {
        return err_resp(&CatalogError::unprocessable("Invalid capability_id."));
    }
    let (_, body) = match read_strict_json_body(req, MAX_BODY_BYTES).await {
        Ok(v) => v,
        Err(e) => return err_resp(&e),
    };
    let rev = match require_u64(&body, "revision") { Ok(v) => v, Err(e) => return err_resp(&e) };
    let conf = match require_str(&body, "confirmation") { Ok(v) => v, Err(e) => return err_resp(&e) };
    let reason = match require_str(&body, "reason") { Ok(v) => v.trim(), Err(e) => return err_resp(&e) };
    if conf != cap_id {
        return err_resp(&CatalogError::unprocessable("Type the exact capability id to confirm."));
    }
    if reason.len() < 3 || reason.len() > 500 {
        return err_resp(&CatalogError::unprocessable("A non-blank reason is required."));
    }
    let lifting_release = body.get("lifting_release_id").and_then(Value::as_str).map(String::from);
    let actor = st.current_actor();
    let mut guard = match st.data.write() {
        Ok(g) => g,
        Err(_) => return err_resp(&CatalogError::unavailable("Local storage is unavailable.")),
    };
    if guard.revision != rev {
        return err_resp(&CatalogError::conflict("Catalog changed. Refresh and review before confirming again."));
    }
    let now_u = now_unix_secs().max(guard.last_updated_unix);
    let now_s = format_unix_rfc3339(now_u);
    let next_seq = guard.capability_recalls.len() as u64 + 1;
    guard.capability_recalls.push(CapabilityRecallRecord {
        sequence: next_seq,
        capability_id: cap_id.to_string(),
        action: action.to_string(),
        lifting_release_id: lifting_release,
        reason: reason.to_string(),
        actor: actor.clone(),
        occurred_at: now_s.clone(),
    });
    guard.revision += 1;
    guard.last_updated_unix = now_u;
    let next_rev = guard.revision;
    guard.events.push(CatalogEvent {
        revision: next_rev,
        release_id: cap_id.to_string(),
        action: format!("{action}_capability"),
        reason: reason.to_string(),
        channel: None,
        occurred_at: now_s,
        actor,
    });
    if let Err(e) = st.persist(&guard) { return err_resp(&e); }
    match st.build_catalog_snapshot_locked(&guard) {
        Ok(snap) => json_resp(StatusCode::OK, &snap, &[], false),
        Err(e) => err_resp(&e),
    }
}

async fn handle_oci_v2_base(method: Method) -> Response {
    json_resp(StatusCode::OK, &json!({}), &[("docker-distribution-api-version", String::from("registry/2.0"))], method == Method::HEAD)
}

async fn handle_oci_v2_catalog(method: Method) -> Response {
    let repos: Vec<String> = CANDIDATE_DOCKER_TAGS.iter().map(|(c, _)| format!("fdai/{c}")).collect();
    json_resp(StatusCode::OK, &json!({"repositories": repos}), &[("docker-distribution-api-version", String::from("registry/2.0"))], method == Method::HEAD)
}

async fn handle_oci_v2_manifest(
    State(st): State<Arc<ReleaseHubState>>,
    AxPath((component, reference)): AxPath<(String, String)>,
    method: Method,
    req: Request,
) -> Response {
    if !is_valid_component_slug(&component) {
        return err_resp(&CatalogError::not_found("Invalid component slug."));
    }
    if method == Method::PUT {
        let headers = req.headers().clone();
        if let Err(e) = check_same_origin_mutation(&headers) { return err_resp(&e); }
        let bytes = match to_bytes(req.into_body(), MAX_STENCIL_BODY_BYTES + 1).await {
            Ok(b) if b.len() <= MAX_STENCIL_BODY_BYTES => b,
            _ => return err_resp(&CatalogError::new(413, "Manifest too large.")),
        };
        if parse_strict_json_object(&bytes).is_err() {
            return err_resp(&CatalogError::unprocessable("Invalid OCI manifest JSON."));
        }
        let computed_digest = format!("sha256:{}", sha256_hex(&bytes));
        let digest = if let Some(hex_part) = reference.strip_prefix("sha256:") {
            if !is_hex_len(hex_part, 64) || reference != computed_digest {
                return json_resp(
                    StatusCode::BAD_REQUEST,
                    &json!({"errors": [{"code": "DIGEST_INVALID", "message": "Uploaded manifest digest does not match reference."}]}),
                    &[("docker-distribution-api-version", String::from("registry/2.0"))],
                    false,
                );
            }
            reference.clone()
        } else {
            computed_digest
        };
        let raw_str = String::from_utf8_lossy(&bytes).to_string();
        if let Ok(mut guard) = st.data.write() {
            guard.oci_manifests.insert(format!("{component}@{reference}"), raw_str.clone());
            guard.oci_manifests.insert(format!("{component}@{digest}"), raw_str);
            let _ = st.persist(&guard);
        }
        return build_response(
            StatusCode::CREATED,
            OCI_IMAGE_MANIFEST_MEDIA_TYPE,
            Vec::new(),
            &[
                ("docker-distribution-api-version", String::from("registry/2.0")),
                ("docker-content-digest", digest.clone()),
                ("location", format!("/v2/fdai/{component}/manifests/{digest}")),
            ],
            true,
        );
    }
    let headers = req.headers().clone();
    let requires_scoped = headers.contains_key("x-fdai-installation-id")
        || headers.contains_key("x-fdai-customer-principal")
        || headers.contains_key("x-fdai-distribution-grant")
        || !st.configured_grant_issuer_keys().is_empty()
        || st.data.read().is_ok_and(|g| !g.stencil_grants.is_empty());
    if requires_scoped {
        let guard = match st.data.read() {
            Ok(g) => g,
            Err(_) => {
                return json_resp(
                    StatusCode::SERVICE_UNAVAILABLE,
                    &json!({"errors": [{"code": "DENIED", "message": "Local storage is unavailable."}]}),
                    &[("docker-distribution-api-version", String::from("registry/2.0"))],
                    method == Method::HEAD,
                );
            }
        };
        if let Err(err) = require_customer_grant(&st, &headers, &guard.stencil_grants) {
            let status = StatusCode::from_u16(err.status).unwrap_or(StatusCode::FORBIDDEN);
            return json_resp(
                status,
                &json!({"errors": [{"code": "DENIED", "message": err.message}]}),
                &[("docker-distribution-api-version", String::from("registry/2.0"))],
                method == Method::HEAD,
            );
        }
    }
    let key = format!("{component}@{reference}");
    if let Ok(guard) = st.data.read() {
        if let Some(raw) = guard.oci_manifests.get(&key) {
            let bytes = raw.as_bytes().to_vec();
            let dg = format!("sha256:{}", sha256_hex(&bytes));
            return build_response(
                StatusCode::OK,
                OCI_IMAGE_MANIFEST_MEDIA_TYPE,
                bytes,
                &[
                    ("docker-distribution-api-version", String::from("registry/2.0")),
                    ("docker-content-digest", dg),
                ],
                method == Method::HEAD,
            );
        }
    }
    if let Some((bytes, dg)) = ReleaseHubState::build_default_oci_manifest(&component, &reference) {
        return build_response(
            StatusCode::OK,
            OCI_IMAGE_MANIFEST_MEDIA_TYPE,
            bytes,
            &[
                ("docker-distribution-api-version", String::from("registry/2.0")),
                ("docker-content-digest", dg),
            ],
            method == Method::HEAD,
        );
    }
    json_resp(
        StatusCode::NOT_FOUND,
        &json!({"errors": [{"code": "MANIFEST_UNKNOWN", "message": "manifest unknown"}]}),
        &[("docker-distribution-api-version", String::from("registry/2.0"))],
        method == Method::HEAD,
    )
}

async fn handle_registry_images(State(st): State<Arc<ReleaseHubState>>) -> Response {
    json_resp(StatusCode::OK, &st.registry_inventory_payload(), &[], false)
}

pub fn build_release_hub_router_with_state(state: Arc<ReleaseHubState>) -> Router {
    Router::new()
        .route("/healthz", get(handle_healthz).head(handle_healthz))
        .route("/readyz", get(handle_readyz).head(handle_readyz))
        .route("/metrics", get(handle_metrics))
        .route("/auth/config", get(handle_auth_config))
        .route("/v1/auth/session", get(handle_auth_session))
        .route("/v1/auth/entra/login", post(handle_entra_login))
        .route("/v1/auth/entra/logout", post(handle_entra_logout))
        .route("/v2", get(handle_oci_v2_base).head(handle_oci_v2_base))
        .route("/v2/", get(handle_oci_v2_base).head(handle_oci_v2_base))
        .route("/v2/_catalog", get(handle_oci_v2_catalog).head(handle_oci_v2_catalog))
        .route(
            "/v2/fdai/{component}/manifests/{reference}",
            get(handle_oci_v2_manifest).head(handle_oci_v2_manifest).put(handle_oci_v2_manifest),
        )
        .route("/v1/registry/images", get(handle_registry_images))
        .route("/v1/catalog", get(handle_catalog).head(handle_catalog))
        .route("/v1/catalog/export", get(handle_export).head(handle_export))
        .route("/v1/catalog/metadata", get(handle_metadata).head(handle_metadata))
        .route("/v1/catalog/public-key", get(handle_public_key).head(handle_public_key))
        .route("/v1/catalog/renew", post(handle_renew))
        .merge(build_stencil_and_customer_routes())
        .route("/v1/releases/{release_id}/{action}", post(handle_release_action))
        .route("/v1/capabilities/{*tail}", post(handle_capability_action))
        .layer(fdai_http_runtime::axum::middleware::from_fn_with_state(
            Arc::clone(&state),
            release_hub_guard_middleware,
        ))
        .with_state(state)
}

pub fn build_release_hub_router() -> Router {
    build_release_hub_router_with_state(ReleaseHubState::open_from_env())
}

#[cfg(test)]
mod tests {
    use super::*;
    use fdai_http_runtime::http_body_util::{BodyExt as _, Full};
    use fdai_http_runtime::hyper::body::Bytes;
    use fdai_http_runtime::hyper::Request as HyperRequest;
    use fdai_http_runtime::hyper_util::client::legacy::Client;
    use fdai_http_runtime::hyper_util::rt::TokioExecutor;

    async fn send_req(
        port: u16,
        method: &str,
        path: &str,
        body: Option<String>,
        extra_hdr: Option<(&str, &str)>,
    ) -> (StatusCode, HeaderMap, Vec<u8>) {
        let client = Client::builder(TokioExecutor::new()).build_http::<Full<Bytes>>();
        let uri = format!("http://127.0.0.1:{port}{path}");
        let mut b = HyperRequest::builder().method(method).uri(uri);
        if body.is_some() {
            b = b.header("content-type", "application/json");
        }
        if let Some((k, v)) = extra_hdr {
            b = b.header(k, v);
        }
        let payload = Full::new(Bytes::from(body.unwrap_or_default()));
        let Ok(req) = b.body(payload) else {
            return (StatusCode::INTERNAL_SERVER_ERROR, HeaderMap::new(), Vec::new());
        };
        let Ok(resp) = client.request(req).await else {
            return (StatusCode::BAD_GATEWAY, HeaderMap::new(), Vec::new());
        };
        let status = resp.status();
        let headers = resp.headers().clone();
        let bytes = resp
            .into_body()
            .collect()
            .await
            .map(|c| c.to_bytes().to_vec())
            .unwrap_or_default();
        (status, headers, bytes)
    }

    #[tokio::test]
    async fn release_lifecycle_signing_etag_and_promotion_gates_work_end_to_end() {
        let st = ReleaseHubState::open_ephemeral();
        let app = build_release_hub_router_with_state(st.clone());
        let Ok(listener) = tokio::net::TcpListener::bind("127.0.0.1:0").await else { return; };
        let Ok(addr) = listener.local_addr() else { return; };
        let srv = tokio::spawn(async move {
            let _ = fdai_http_runtime::axum::serve(listener, app).await;
        });

        let (code, hdrs, _) = send_req(
            addr.port(),
            "POST",
            "/v1/releases/1.0.0/register",
            Some(json!({
                "revision": 0,
                "confirmation": "1.0.0",
                "reason": "Initial release registration",
                "label": "v1.0.0",
                "manifest": "{\"schema_version\":\"fdai.application-release.v2\",\"release_id\":\"1.0.0\"}"
            }).to_string()),
            None,
        ).await;
        assert_eq!(code, StatusCode::OK);
        assert_eq!(hdrs.get("x-frame-options").and_then(|v| v.to_str().ok()), Some("DENY"));

        let (code, _, body) = send_req(
            addr.port(),
            "POST",
            "/v1/releases/1.0.0/publish",
            Some(json!({
                "revision": 1,
                "confirmation": "1.0.0",
                "reason": "Publish signed release"
            }).to_string()),
            None,
        ).await;
        assert_eq!(code, StatusCode::OK);
        assert!(String::from_utf8_lossy(&body).contains("development-key-verified"));

        let (code, hdrs, body) = send_req(addr.port(), "GET", "/v1/catalog/export", None, None).await;
        assert_eq!(code, StatusCode::OK);
        let sig = hdrs.get("x-fdai-export-signature").and_then(|v| v.to_str().ok()).unwrap_or("");
        assert!(st.verify_bytes_b64(&body, sig).is_ok());
        if let Some(etag) = hdrs.get("etag").and_then(|v| v.to_str().ok()) {
            let (c2, _, _) = send_req(addr.port(), "GET", "/v1/catalog/export", None, Some(("if-none-match", etag))).await;
            assert_eq!(c2, StatusCode::NOT_MODIFIED);
        }

        // Cross-origin port mismatch MUST be rejected with 403
        let (x_code, _, _) = send_req(
            addr.port(),
            "POST",
            "/v1/catalog/renew",
            Some(json!({"revision": 2, "confirmation": "renew 2", "reason": "xorigin test"}).to_string()),
            Some(("origin", "http://127.0.0.1:9999")),
        ).await;
        assert_eq!(x_code, StatusCode::FORBIDDEN);

        // Unsupported manifest schema_version MUST be rejected with 422
        let (bad_code, _, _) = send_req(
            addr.port(),
            "POST",
            "/v1/releases/2.0.0/register",
            Some(json!({
                "revision": 2,
                "confirmation": "2.0.0",
                "reason": "Bad schema test",
                "manifest": "{\"schema_version\":\"evil.v9\",\"release_id\":\"2.0.0\"}"
            }).to_string()),
            None,
        ).await;
        assert_eq!(bad_code, StatusCode::UNPROCESSABLE_ENTITY);

        // Scoped OCI manifest pull without authenticated Entra session MUST return 401 DENIED
        let (oci_code, _, oci_body) = send_req(
            addr.port(),
            "GET",
            "/v2/fdai/core-control-plane/manifests/latest",
            None,
            Some(("x-fdai-installation-id", "inst-scoped-1")),
        ).await;
        assert_eq!(oci_code, StatusCode::UNAUTHORIZED);
        assert!(String::from_utf8_lossy(&oci_body).contains("DENIED"));

        srv.abort();
    }
}
