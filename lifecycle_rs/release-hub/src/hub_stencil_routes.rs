//! Release Hub deployment requests, Stencil composition/grants, customer-scoped APIs, and workflow jobs.

use crate::hub_routes::{build_response, err_resp, etag_matches, json_resp, read_strict_json_body, require_str};
use crate::hub_state::{
    canonical_json_bytes, format_unix_rfc3339, is_hex_len, is_valid_channel, is_valid_semver,
    is_valid_uuid, now_unix_secs, parse_strict_json_object, sha256_hex, CatalogError, CatalogEvent,
    DeploymentRequestRecord, GrantEventRecord, PromotionRunReceipt, ReleaseHubState,
    StencilGrantRecord, StoredRelease, WorkflowJobRecord, MAX_BODY_BYTES, MAX_REQUEST_BODY_BYTES,
    MAX_STENCIL_BODY_BYTES, MAX_STORED_REQUESTS, OCI_IMAGE_MANIFEST_MEDIA_TYPE,
};
use crate::stencils::{compose_stencil_response, stencil_catalog_payload, stencil_decisions_payload};
use fdai_http_runtime::axum::extract::{Path as AxPath, Query, Request, State};
use fdai_http_runtime::axum::http::{HeaderMap, Method, StatusCode};
use fdai_http_runtime::axum::response::Response;
use fdai_http_runtime::axum::routing::{get, post};
use fdai_http_runtime::axum::Router;
use fdai_http_runtime::format_utc_rfc3339_now;
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::sync::Arc;

fn is_valid_slug_id(s: &str) -> bool {
    let b = s.as_bytes();
    !b.is_empty()
        && b.len() <= 63
        && b[0].is_ascii_lowercase()
        && b.iter().all(|&c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'-')
}

pub(crate) fn require_customer_grant<'a>(
    st: &ReleaseHubState,
    headers: &HeaderMap,
    grants: &'a BTreeMap<String, StencilGrantRecord>,
) -> Result<&'a StencilGrantRecord, CatalogError> {
    let inst_id = headers
        .get("x-fdai-installation-id")
        .and_then(|v| v.to_str().ok())
        .map(str::trim)
        .filter(|s| is_valid_slug_id(s))
        .ok_or_else(|| CatalogError::bad_request("Missing or invalid X-FDAI-Installation-Id header."))?;
    let actor = st.current_actor();
    if actor == "local-operator" {
        return Err(CatalogError::new(
            401,
            "Customer catalog/artifact access requires an authenticated Entra/remote session.",
        ));
    }
    if let Some(hp) = headers
        .get("x-fdai-customer-principal")
        .and_then(|v| v.to_str().ok())
        .map(str::trim)
    {
        if !hp.is_empty() && hp != actor && format!("entra:{hp}") != actor {
            return Err(CatalogError::new(
                403,
                "Authenticated session principal does not match X-FDAI-Customer-Principal.",
            ));
        }
    }
    let raw_grant_hdr = headers
        .get("x-fdai-distribution-grant")
        .and_then(|v| v.to_str().ok())
        .filter(|s| !s.trim().is_empty())
        .ok_or_else(|| {
            CatalogError::new(
                401,
                "Customer catalog and artifact access requires a signed X-FDAI-Distribution-Grant.",
            )
        })?;
    if raw_grant_hdr.len() > 32_768 {
        return Err(CatalogError::bad_request("X-FDAI-Distribution-Grant header too large."));
    }
    let presented = parse_strict_json_object(raw_grant_hdr.as_bytes())
        .map_err(|_| CatalogError::bad_request("Malformed X-FDAI-Distribution-Grant header."))?;
    st.verify_grant_signature(&presented)?;
    let pres_inst = presented.get("installation_id").and_then(Value::as_str).unwrap_or("");
    if pres_inst != inst_id {
        return Err(CatalogError::new(403, "Presented distribution grant installation_id mismatch."));
    }
    let grant = grants
        .get(inst_id)
        .ok_or_else(|| CatalogError::new(403, "No active Stencil distribution grant for installation."))?;
    if grant.customer_principal != actor && format!("entra:{}", grant.customer_principal) != actor {
        return Err(CatalogError::new(403, "Distribution grant principal mismatch."));
    }
    if let Some(pgid) = presented.get("grant_id").and_then(Value::as_str) {
        if pgid != grant.grant_id {
            return Err(CatalogError::new(403, "Presented distribution grant_id does not match registered grant."));
        }
    }
    let now_s = format_utc_rfc3339_now();
    if grant.expires_at.as_str() <= now_s.as_str() {
        return Err(CatalogError::new(403, "Stencil distribution grant has expired."));
    }
    Ok(grant)
}

async fn handle_list_deployment_requests(
    State(st): State<Arc<ReleaseHubState>>,
    Query(params): Query<Vec<(String, String)>>,
) -> Response {
    let mut seen = BTreeMap::new();
    for (k, v) in params {
        if !matches!(k.as_str(), "limit" | "offset" | "subscription_id") || seen.insert(k, v).is_some() {
            return err_resp(&CatalogError::unprocessable("Invalid request filters or pagination."));
        }
    }
    let limit = match seen.get("limit") {
        Some(s) if s.bytes().all(|b| b.is_ascii_digit()) => match s.parse::<usize>() {
            Ok(n) if (1..=100).contains(&n) => n,
            _ => return err_resp(&CatalogError::unprocessable("Invalid request filters or pagination.")),
        },
        Some(_) => return err_resp(&CatalogError::unprocessable("Invalid request filters or pagination.")),
        None => 25,
    };
    let offset = match seen.get("offset") {
        Some(s) if s.bytes().all(|b| b.is_ascii_digit()) => match s.parse::<usize>() {
            Ok(n) if n <= MAX_STORED_REQUESTS => n,
            _ => return err_resp(&CatalogError::unprocessable("Invalid request filters or pagination.")),
        },
        Some(_) => return err_resp(&CatalogError::unprocessable("Invalid request filters or pagination.")),
        None => 0,
    };
    let sub_filter = match seen.get("subscription_id") {
        Some(s) if is_valid_uuid(s) => Some(s.clone()),
        Some(_) => return err_resp(&CatalogError::unprocessable("Invalid request filters or pagination.")),
        None => None,
    };
    let guard = match st.data.read() {
        Ok(g) => g,
        Err(_) => return err_resp(&CatalogError::unavailable("Local storage is unavailable.")),
    };
    let mut rows: Vec<DeploymentRequestRecord> = guard
        .deployment_requests
        .values()
        .filter(|r| sub_filter.as_ref().is_none_or(|sf| &r.subscription_id == sf))
        .cloned()
        .collect();
    rows.sort_by(|a, b| b.recorded_at.cmp(&a.recorded_at).then_with(|| b.request_id.cmp(&a.request_id)));
    let slice: Vec<DeploymentRequestRecord> = rows.iter().skip(offset).take(limit + 1).cloned().collect();
    let has_more = slice.len() > limit;
    let page_items: Vec<DeploymentRequestRecord> = slice.into_iter().take(limit).collect();
    json_resp(
        StatusCode::OK,
        &json!({"requests": page_items, "limit": limit, "offset": offset, "has_more": has_more}),
        &[],
        false,
    )
}

async fn handle_post_deployment_request(
    State(st): State<Arc<ReleaseHubState>>,
    req: Request,
) -> Response {
    let Ok(_permit) = st.intake_semaphore.try_acquire() else {
        return err_resp(&CatalogError::new(429, "Too many requests in flight."));
    };
    let (_, body) = match read_strict_json_body(req, MAX_REQUEST_BODY_BYTES).await {
        Ok(v) => v,
        Err(e) => return err_resp(&e),
    };
    let allowed = ["request_id", "subscription_id", "release_id", "channel", "region", "source_commit", "catalog_digest"];
    if body.keys().any(|k| !allowed.contains(&k.as_str())) {
        return err_resp(&CatalogError::unprocessable("Invalid deployment request metadata."));
    }
    let req_id = match require_str(&body, "request_id") { Ok(v) if is_hex_len(v, 64) => v.to_string(), _ => return err_resp(&CatalogError::unprocessable("Invalid deployment request metadata.")) };
    let sub_id = match require_str(&body, "subscription_id") { Ok(v) if is_valid_uuid(v) => v.to_string(), _ => return err_resp(&CatalogError::unprocessable("Invalid deployment request metadata.")) };
    let rel_id = match require_str(&body, "release_id") { Ok(v) if is_valid_semver(v) => v.to_string(), _ => return err_resp(&CatalogError::unprocessable("Invalid deployment request metadata.")) };
    let channel = match require_str(&body, "channel") { Ok(v) if is_valid_channel(v) => v.to_string(), _ => return err_resp(&CatalogError::unprocessable("Invalid deployment request metadata.")) };
    let region = match require_str(&body, "region") {
        Ok(v) if !v.is_empty() && v.len() <= 64 && v.as_bytes()[0].is_ascii_lowercase() && v.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit()) => v.to_string(),
        _ => return err_resp(&CatalogError::unprocessable("Invalid deployment request metadata.")),
    };
    let commit = match require_str(&body, "source_commit") { Ok(v) if is_hex_len(v, 40) => v.to_string(), _ => return err_resp(&CatalogError::unprocessable("Invalid deployment request metadata.")) };
    let cat_digest = match require_str(&body, "catalog_digest") { Ok(v) if is_hex_len(v, 64) => v.to_string(), _ => return err_resp(&CatalogError::unprocessable("Invalid deployment request metadata.")) };

    let mut guard = match st.data.write() {
        Ok(g) => g,
        Err(_) => return err_resp(&CatalogError::unavailable("Local storage is unavailable.")),
    };
    if let Some(existing) = guard.deployment_requests.get(&req_id) {
        if existing.subscription_id != sub_id || existing.release_id != rel_id || existing.channel != channel
            || existing.region != region || existing.source_commit != commit || existing.catalog_digest != cat_digest
        {
            return err_resp(&CatalogError::conflict("Request id already belongs to different metadata."));
        }
        return json_resp(StatusCode::OK, &json!(existing), &[], false);
    }
    if guard.deployment_requests.len() >= MAX_STORED_REQUESTS {
        return err_resp(&CatalogError::unavailable("Deployment request capacity reached. Contact the Hub operator."));
    }
    let Some(rel) = guard.releases.get(&rel_id) else {
        return err_resp(&CatalogError::conflict("Requested Release is unavailable or recalled."));
    };
    if rel.published_at.is_none() || rel.recalled_at.is_some() {
        return err_resp(&CatalogError::conflict("Requested Release is unavailable or recalled."));
    }
    if let Some(ref sig) = rel.signature {
        if let Err(e) = st.verify_bytes_b64(rel.manifest.as_bytes(), sig) { return err_resp(&e); }
    }
    let in_ch = guard.channel_memberships.get(&channel).is_some_and(|v| v.contains(&rel_id));
    if !in_ch {
        return err_resp(&CatalogError::conflict("Requested Release does not belong to the selected channel."));
    }
    let rec = DeploymentRequestRecord {
        request_id: req_id.clone(),
        subscription_id: sub_id,
        release_id: rel_id,
        channel,
        region,
        source_commit: commit,
        catalog_digest: cat_digest,
        recorded_at: format_utc_rfc3339_now(),
        status: String::from("requested"),
        trust: String::from("self-reported"),
    };
    guard.deployment_requests.insert(req_id, rec.clone());
    if let Err(e) = st.persist(&guard) { return err_resp(&e); }
    json_resp(StatusCode::CREATED, &json!(rec), &[], false)
}

async fn handle_stencils_catalog(State(st): State<Arc<ReleaseHubState>>) -> Response {
    json_resp(StatusCode::OK, &stencil_catalog_payload(&st), &[], false)
}

async fn handle_stencils_compose(State(st): State<Arc<ReleaseHubState>>, req: Request) -> Response {
    let (_, body) = match read_strict_json_body(req, MAX_STENCIL_BODY_BYTES).await {
        Ok(v) => v,
        Err(e) => return err_resp(&e),
    };
    match compose_stencil_response(&st, &body) {
        Ok(val) => json_resp(StatusCode::OK, &val, &[], false),
        Err(e) => err_resp(&e),
    }
}

async fn handle_stencils_decisions() -> Response {
    json_resp(StatusCode::OK, &stencil_decisions_payload(), &[], false)
}

async fn handle_stencil_variants(
    State(st): State<Arc<ReleaseHubState>>,
    Query(q): Query<BTreeMap<String, String>>,
) -> Response {
    let base_ver = q.get("base_release_version").map(String::as_str);
    let guard = match st.data.read() {
        Ok(g) => g,
        Err(_) => return err_resp(&CatalogError::unavailable("Local storage is unavailable.")),
    };
    let variants: Vec<Value> = guard
        .releases
        .values()
        .filter(|r| base_ver.is_none_or(|bv| r.id == bv || r.id.starts_with(&format!("{bv}-"))))
        .map(|r| json!({
            "release_id": r.id,
            "stencil_id": r.stencil_id.as_deref().unwrap_or("standard-sre"),
            "digest": r.digest,
            "published": r.published_at.is_some(),
        }))
        .collect();
    json_resp(StatusCode::OK, &json!({"variants": variants}), &[], false)
}

async fn handle_post_grant(State(st): State<Arc<ReleaseHubState>>, req: Request) -> Response {
    let (_, body) = match read_strict_json_body(req, MAX_STENCIL_BODY_BYTES).await {
        Ok(v) => v,
        Err(e) => return err_resp(&e),
    };
    let env = body.get("envelope").and_then(Value::as_object).unwrap_or(&body);
    if let Err(e) = st.verify_grant_signature(env) { return err_resp(&e); }
    let inst_id = env.get("installation_id").and_then(Value::as_str).unwrap_or("").trim();
    let principal = env.get("customer_principal").and_then(Value::as_str).unwrap_or("").trim();
    if !is_valid_slug_id(inst_id) || principal.is_empty() || principal.len() > 160 {
        return err_resp(&CatalogError::unprocessable("Grant requires valid installation_id and customer_principal."));
    }
    let grant_id = env.get("grant_id").and_then(Value::as_str).unwrap_or("grant-1").trim().to_string();
    let revision = env.get("revision").and_then(Value::as_u64).unwrap_or(1);
    let allowed_stencils: Vec<String> = env.get("allowed_stencil_ids").and_then(Value::as_array)
        .map(|a| a.iter().filter_map(Value::as_str).map(String::from).collect())
        .unwrap_or_else(|| vec![String::from("standard-sre")]);
    let allowed_channels: Vec<String> = env.get("allowed_channels").and_then(Value::as_array)
        .map(|a| a.iter().filter_map(Value::as_str).map(String::from).collect())
        .unwrap_or_else(|| vec![String::from("RELEASE")]);
    let expires_at = env.get("expires_at").and_then(Value::as_str)
        .map(String::from)
        .unwrap_or_else(|| format_unix_rfc3339(now_unix_secs().saturating_add(30 * 86_400)));
    let now_s = format_utc_rfc3339_now();
    if expires_at.as_str() <= now_s.as_str() {
        return err_resp(&CatalogError::unprocessable("Grant expires_at must be in the future."));
    }
    let scope_digest = format!("sha256:{}", sha256_hex(&canonical_json_bytes(&Value::Object(env.clone()))));
    let reason = body.get("reason").and_then(Value::as_str).unwrap_or("register-or-renew-grant").to_string();
    let actor = st.current_actor();

    let mut guard = match st.data.write() {
        Ok(g) => g,
        Err(_) => return err_resp(&CatalogError::unavailable("Local storage is unavailable.")),
    };
    if let Some(prev) = guard.stencil_grants.get(inst_id) {
        if revision < prev.revision {
            return err_resp(&CatalogError::conflict("Grant revision rollback is forbidden."));
        }
    }
    let rec = StencilGrantRecord {
        installation_id: inst_id.to_string(),
        customer_principal: principal.to_string(),
        grant_id,
        revision,
        allowed_stencil_ids: allowed_stencils,
        allowed_channels,
        scope_digest,
        expires_at,
        envelope: Value::Object(env.clone()),
        registered_by: actor.clone(),
        registered_at: now_s.clone(),
    };
    guard.stencil_grants.insert(inst_id.to_string(), rec.clone());
    let seq = guard.grant_events.len() as u64 + 1;
    guard.grant_events.push(GrantEventRecord {
        sequence: seq,
        installation_id: inst_id.to_string(),
        action: String::from("register"),
        actor,
        reason,
        recorded_at: now_s,
    });
    if let Err(e) = st.persist(&guard) { return err_resp(&e); }
    json_resp(StatusCode::OK, &json!(rec), &[], false)
}

async fn handle_get_grant(
    State(st): State<Arc<ReleaseHubState>>,
    AxPath(inst_id): AxPath<String>,
) -> Response {
    let guard = match st.data.read() {
        Ok(g) => g,
        Err(_) => return err_resp(&CatalogError::unavailable("Local storage is unavailable.")),
    };
    let Some(grant) = guard.stencil_grants.get(&inst_id) else {
        return err_resp(&CatalogError::not_found("Grant not found."));
    };
    let events: Vec<&GrantEventRecord> = guard
        .grant_events
        .iter()
        .filter(|e| e.installation_id == inst_id)
        .collect();
    json_resp(StatusCode::OK, &json!({"grant": grant, "events": events}), &[], false)
}

async fn handle_workflow_jobs_get(
    State(st): State<Arc<ReleaseHubState>>,
    AxPath(release_id): AxPath<String>,
) -> Response {
    let guard = match st.data.read() {
        Ok(g) => g,
        Err(_) => return err_resp(&CatalogError::unavailable("Local storage is unavailable.")),
    };
    let jobs: Vec<&WorkflowJobRecord> = guard
        .workflow_jobs
        .values()
        .filter(|j| j.release_id == release_id)
        .collect();
    json_resp(StatusCode::OK, &json!({"jobs": jobs}), &[], false)
}

async fn handle_workflow_jobs_post(
    State(st): State<Arc<ReleaseHubState>>,
    AxPath(release_id): AxPath<String>,
    req: Request,
) -> Response {
    if !is_valid_semver(&release_id) {
        return err_resp(&CatalogError::unprocessable("Release id must be canonical SemVer."));
    }
    let (_, body) = match read_strict_json_body(req, MAX_BODY_BYTES).await {
        Ok(v) => v,
        Err(e) => return err_resp(&e),
    };
    let idem_key = match require_str(&body, "idempotency_key") {
        Ok(v) if !v.trim().is_empty() && v.len() <= 128 => v.trim().to_string(),
        _ => return err_resp(&CatalogError::unprocessable("Non-empty idempotency_key (1..=128) is required.")),
    };
    let manifest_val = match body.get("manifest") {
        Some(Value::String(s)) if serde_json::from_str::<Value>(s).is_ok_and(|v| v.is_object()) => s.clone(),
        Some(v @ Value::Object(_)) => String::from_utf8_lossy(&canonical_json_bytes(v)).to_string(),
        _ => return err_resp(&CatalogError::unprocessable("manifest must be a valid JSON object or JSON object string.")),
    };
    let stencil_id = body.get("stencil_id").and_then(Value::as_str).unwrap_or("standard-sre").to_string();
    let source_commit = body.get("source_commit").and_then(Value::as_str).unwrap_or("0000000000000000000000000000000000000000").to_string();
    if !is_hex_len(&source_commit, 40) {
        return err_resp(&CatalogError::unprocessable("source_commit must be a 40-char lowercase hex SHA."));
    }
    let label = body.get("label").and_then(Value::as_str).unwrap_or("").to_string();
    let reason = body.get("reason").and_then(Value::as_str).unwrap_or("Automated Stencil vendor publication workflow").to_string();
    let job_id = body.get("job_id").and_then(Value::as_str).map(String::from).unwrap_or_else(|| format!("job-{release_id}"));
    let input_digest = format!("sha256:{}", sha256_hex(&canonical_json_bytes(&json!({
        "release_id": release_id, "stencil_id": stencil_id, "source_commit": source_commit, "manifest": manifest_val,
    }))));
    let manifest_digest = format!("sha256:{}", sha256_hex(manifest_val.as_bytes()));
    let actor = st.current_actor();

    let mut guard = match st.data.write() {
        Ok(g) => g,
        Err(_) => return err_resp(&CatalogError::unavailable("Local storage is unavailable.")),
    };
    if let Some(existing) = guard.workflow_jobs.get(&idem_key) {
        if existing.input_digest != input_digest {
            return err_resp(&CatalogError::conflict("Idempotency key conflicts with different workflow job inputs."));
        }
        return json_resp(StatusCode::OK, &json!({
            "job_id": existing.job_id,
            "idempotency_key": existing.idempotency_key,
            "release_id": existing.release_id,
            "stencil_id": existing.stencil_id,
            "source_commit": existing.source_commit,
            "stage": existing.stage,
            "status": "resumed",
            "resumed_from_durable_state": true,
            "input_digest": existing.input_digest,
            "manifest_digest": existing.manifest_digest,
            "actor": existing.actor,
            "result": existing.result,
            "created_at": existing.created_at,
            "updated_at": existing.updated_at,
        }), &[], false);
    }
    let now_u = now_unix_secs().max(guard.last_updated_unix);
    let now_s = format_unix_rfc3339(now_u);
    if !guard.releases.contains_key(&release_id) {
        let sig = st.sign_bytes_b64(manifest_val.as_bytes());
        guard.releases.insert(release_id.clone(), StoredRelease {
            id: release_id.clone(),
            label,
            manifest: manifest_val.clone(),
            digest: sha256_hex(manifest_val.as_bytes()),
            signature: Some(sig),
            published_at: Some(now_s.clone()),
            recalled_at: None,
            capability_ids: Vec::new(),
            stencil_id: Some(stencil_id.clone()),
        });
        let dev = guard.channel_memberships.entry(String::from("DEV")).or_default();
        if !dev.contains(&release_id) { dev.push(release_id.clone()); }
        guard.revision += 1;
        let reg_rev = guard.revision;
        guard.events.push(CatalogEvent {
            revision: reg_rev,
            release_id: release_id.clone(),
            action: String::from("register"),
            reason: reason.clone(),
            channel: None,
            occurred_at: now_s.clone(),
            actor: actor.clone(),
        });
        guard.revision += 1;
        guard.last_updated_unix = now_u;
        let pub_rev = guard.revision;
        guard.events.push(CatalogEvent {
            revision: pub_rev,
            release_id: release_id.clone(),
            action: String::from("publish"),
            reason,
            channel: Some(String::from("DEV")),
            occurred_at: now_s.clone(),
            actor: actor.clone(),
        });
    }
    let result_val = json!({"release_id": release_id, "channel": "DEV", "revision": guard.revision});
    let rec = WorkflowJobRecord {
        job_id,
        idempotency_key: idem_key.clone(),
        release_id,
        stencil_id,
        source_commit,
        stage: String::from("published_dev"),
        status: String::from("completed"),
        input_digest,
        manifest_digest,
        actor,
        result: result_val,
        created_at: now_s.clone(),
        updated_at: now_s,
    };
    guard.workflow_jobs.insert(idem_key, rec.clone());
    if let Err(e) = st.persist(&guard) { return err_resp(&e); }
    json_resp(StatusCode::OK, &json!(rec), &[], false)
}

async fn handle_promotion_receipts(
    State(st): State<Arc<ReleaseHubState>>,
    AxPath(release_id): AxPath<String>,
) -> Response {
    let guard = match st.data.read() {
        Ok(g) => g,
        Err(_) => return err_resp(&CatalogError::unavailable("Local storage is unavailable.")),
    };
    let receipts: Vec<&PromotionRunReceipt> = guard
        .promotion_receipts
        .iter()
        .filter(|r| r.release_id == release_id)
        .collect();
    json_resp(StatusCode::OK, &json!({"receipts": receipts}), &[], false)
}

async fn handle_customer_export(
    State(st): State<Arc<ReleaseHubState>>,
    method: Method,
    headers: HeaderMap,
) -> Response {
    let guard = match st.data.read() {
        Ok(g) => g,
        Err(_) => return err_resp(&CatalogError::unavailable("Local storage is unavailable.")),
    };
    let grant = match require_customer_grant(&st, &headers, &guard.stencil_grants) {
        Ok(g) => g,
        Err(e) => return err_resp(&e),
    };
    let (raw, digest_hex, sig) = match st.build_signed_export_locked(&guard) {
        Ok(v) => v,
        Err(e) => return err_resp(&e),
    };
    let etag = format!("\"{digest_hex}\"");
    let scope_sig = st.sign_bytes_b64(format!("{digest_hex}:{}", grant.scope_digest).as_bytes());
    if etag_matches(&headers, &etag) {
        return build_response(
            StatusCode::NOT_MODIFIED,
            "application/json",
            Vec::new(),
            &[("etag", etag), ("x-fdai-grant-scope-digest", grant.scope_digest.clone())],
            true,
        );
    }
    build_response(
        StatusCode::OK,
        "application/json",
        raw,
        &[
            ("etag", etag),
            ("x-fdai-export-signature", sig),
            ("x-fdai-export-key-id", st.key_id.clone()),
            ("x-fdai-grant-scope-digest", grant.scope_digest.clone()),
            ("x-fdai-grant-scope-signature", scope_sig),
            ("x-fdai-recovery-only", String::from("false")),
        ],
        method == Method::HEAD,
    )
}

async fn handle_customer_releases(
    State(st): State<Arc<ReleaseHubState>>,
    headers: HeaderMap,
) -> Response {
    let guard = match st.data.read() {
        Ok(g) => g,
        Err(_) => return err_resp(&CatalogError::unavailable("Local storage is unavailable.")),
    };
    let grant = match require_customer_grant(&st, &headers, &guard.stencil_grants) {
        Ok(g) => g,
        Err(e) => return err_resp(&e),
    };
    let items: Vec<Value> = guard
        .releases
        .values()
        .filter(|r| r.published_at.is_some() && r.recalled_at.is_none())
        .filter(|r| {
            let sid = r.stencil_id.as_deref().unwrap_or("standard-sre");
            grant.allowed_stencil_ids.iter().any(|a| a == sid)
        })
        .map(|r| json!({"id": r.id, "digest": r.digest, "stencil_id": r.stencil_id}))
        .collect();
    json_resp(StatusCode::OK, &json!({"releases": items, "grant_scope_digest": grant.scope_digest}), &[], false)
}

async fn handle_customer_release_detail(
    State(st): State<Arc<ReleaseHubState>>,
    AxPath(release_id): AxPath<String>,
    headers: HeaderMap,
) -> Response {
    let guard = match st.data.read() {
        Ok(g) => g,
        Err(_) => return err_resp(&CatalogError::unavailable("Local storage is unavailable.")),
    };
    let grant = match require_customer_grant(&st, &headers, &guard.stencil_grants) {
        Ok(g) => g,
        Err(e) => return err_resp(&e),
    };
    let Some(rel) = guard.releases.get(&release_id) else {
        return err_resp(&CatalogError::not_found("Release not found."));
    };
    let sid = rel.stencil_id.as_deref().unwrap_or("standard-sre");
    if !grant.allowed_stencil_ids.iter().any(|a| a == sid) {
        return err_resp(&CatalogError::new(403, "Release is outside customer Stencil grant scope."));
    }
    json_resp(StatusCode::OK, &json!({"release": rel, "grant_scope_digest": grant.scope_digest}), &[], false)
}

async fn handle_customer_artifact_pull(
    State(st): State<Arc<ReleaseHubState>>,
    AxPath((release_id, component)): AxPath<(String, String)>,
    method: Method,
    headers: HeaderMap,
) -> Response {
    let guard = match st.data.read() {
        Ok(g) => g,
        Err(_) => return err_resp(&CatalogError::unavailable("Local storage is unavailable.")),
    };
    let grant = match require_customer_grant(&st, &headers, &guard.stencil_grants) {
        Ok(g) => g,
        Err(e) => return err_resp(&e),
    };
    if !guard.releases.contains_key(&release_id) {
        return err_resp(&CatalogError::not_found("Release not found."));
    }
    let Some((bytes, dg)) = ReleaseHubState::build_default_oci_manifest(&component, "latest") else {
        return err_resp(&CatalogError::not_found("Component manifest not found."));
    };
    build_response(
        StatusCode::OK,
        OCI_IMAGE_MANIFEST_MEDIA_TYPE,
        bytes,
        &[
            ("docker-distribution-api-version", String::from("registry/2.0")),
            ("docker-content-digest", dg),
            ("x-fdai-grant-scope-digest", grant.scope_digest.clone()),
        ],
        method == Method::HEAD,
    )
}

pub fn build_stencil_and_customer_routes() -> Router<Arc<ReleaseHubState>> {
    Router::new()
        .route(
            "/v1/deployment-requests",
            get(handle_list_deployment_requests).post(handle_post_deployment_request),
        )
        .route("/v1/stencils", get(handle_stencils_catalog))
        .route("/v1/stencils/compose", post(handle_stencils_compose))
        .route("/v1/stencils/decisions", get(handle_stencils_decisions))
        .route("/v1/stencil-variants", get(handle_stencil_variants))
        .route("/v1/stencil-grants", post(handle_post_grant))
        .route("/v1/stencil-grants/{installation_id}", get(handle_get_grant))
        .route("/v1/customer/catalog/export", get(handle_customer_export).head(handle_customer_export))
        .route("/v1/customer/catalog/releases", get(handle_customer_releases))
        .route("/v1/customer/catalog/releases/{release_id}", get(handle_customer_release_detail))
        .route(
            "/v1/customer/artifacts/{release_id}/components/{component}",
            get(handle_customer_artifact_pull).head(handle_customer_artifact_pull),
        )
        .route(
            "/v1/releases/{release_id}/workflow-jobs",
            get(handle_workflow_jobs_get).post(handle_workflow_jobs_post),
        )
        .route(
            "/v1/releases/{release_id}/promotion-receipts",
            get(handle_promotion_receipts),
        )
}
