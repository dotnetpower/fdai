//! Lifecycle Hub live Release Hub integration, TUF/Ed25519 catalog adoption, local channels, and governance sub-APIs.

use crate::hub_state::{
    compute_settings_digest, is_valid_installation_id, sha256_hex,
    AcceptedCatalogRelease, AcceptedCatalogState, EntityRecord, HubError, InstallationRecord,
    LifecycleHubState, PersistedLifecycleHubData, MAX_CATALOG_BYTES,
};
use fdai_http_runtime::format_utc_rfc3339_now;
use fdai_http_runtime::http_body_util::{BodyExt as _, Full, Limited};
use fdai_http_runtime::hyper::body::Bytes;
use fdai_http_runtime::hyper::{HeaderMap, Request as HyperRequest};
use fdai_http_runtime::hyper_rustls::HttpsConnectorBuilder;
use fdai_http_runtime::hyper_util::client::legacy::Client;
use fdai_http_runtime::hyper_util::rt::TokioExecutor;
use serde_json::{json, Map, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::net::IpAddr;
use std::time::Duration;

/// Strictly normalize a Release Hub endpoint origin (HTTP loopback-only or HTTPS:443; no path/query/credentials).
pub fn normalize_release_hub_endpoint(raw: &str) -> Result<String, HubError> {
    let trimmed = raw.trim();
    if trimmed.is_empty()
        || trimmed.len() > 2048
        || trimmed.bytes().any(|b| b < 32 || b == 127 || b.is_ascii_whitespace() || b == b'\\' || b == b'%')
    {
        return Err(HubError::unprocessable("release_hub_endpoint_invalid"));
    }
    let (scheme, rest) = if let Some(r) = trimmed.strip_prefix("http://") {
        ("http", r)
    } else if let Some(r) = trimmed.strip_prefix("https://") {
        ("https", r)
    } else {
        return Err(HubError::unprocessable("release_hub_endpoint_invalid"));
    };
    if rest.contains('@') || rest.contains('?') || rest.contains('#') {
        return Err(HubError::unprocessable("release_hub_endpoint_invalid"));
    }
    let authority = rest.strip_suffix('/').unwrap_or(rest);
    if authority.is_empty() || authority.contains('/') {
        return Err(HubError::unprocessable("release_hub_endpoint_invalid"));
    }
    let (host, port_opt): (&str, Option<u16>) = if authority.starts_with('[') {
        let Some(end_br) = authority.find(']') else {
            return Err(HubError::unprocessable("release_hub_endpoint_invalid"));
        };
        let h = &authority[1..end_br];
        let after = &authority[end_br + 1..];
        let p = if after.is_empty() {
            None
        } else if let Some(ps) = after.strip_prefix(':') {
            Some(ps.parse::<u16>().map_err(|_| HubError::unprocessable("release_hub_endpoint_invalid"))?)
        } else {
            return Err(HubError::unprocessable("release_hub_endpoint_invalid"));
        };
        (h, p)
    } else if let Some((h, ps)) = authority.rsplit_once(':') {
        let p = ps.parse::<u16>().map_err(|_| HubError::unprocessable("release_hub_endpoint_invalid"))?;
        (h, Some(p))
    } else {
        (authority, None)
    };
    if let Some(p) = port_opt {
        if p == 0 {
            return Err(HubError::unprocessable("release_hub_endpoint_invalid"));
        }
    }
    let host_lower = host.to_ascii_lowercase();
    if scheme == "http" {
        let is_loopback = host_lower == "localhost"
            || host_lower.parse::<IpAddr>().is_ok_and(|ip| ip.is_loopback());
        if !is_loopback {
            return Err(HubError::unprocessable("release_hub_endpoint_invalid"));
        }
    } else if port_opt.is_some_and(|p| p != 443) {
        return Err(HubError::unprocessable("release_hub_endpoint_invalid"));
    }
    let canon_host = if host_lower.contains(':') { format!("[{host_lower}]") } else { host_lower };
    let default_port = if scheme == "http" { 80 } else { 443 };
    let norm = match port_opt {
        Some(p) if p != default_port => format!("{scheme}://{canon_host}:{p}"),
        _ => format!("{scheme}://{canon_host}"),
    };
    Ok(norm)
}

pub async fn fetch_http_get_bounded(url: &str, max_bytes: usize) -> Result<(u16, HeaderMap, Vec<u8>), HubError> {
    let https = HttpsConnectorBuilder::new()
        .with_webpki_roots()
        .https_or_http()
        .enable_http1()
        .build();
    let client = Client::builder(TokioExecutor::new()).build::<_, Full<Bytes>>(https);
    let mut builder = HyperRequest::builder()
        .method("GET")
        .uri(url)
        .header("accept", "application/json")
        .header("user-agent", "fdai-lifecycle-hub/1.0");
    if let Ok(tok) = std::env::var("FDAI_RELEASE_HUB_BEARER_TOKEN") {
        let trimmed = tok.trim();
        if !trimmed.is_empty() && !trimmed.bytes().any(|b| b < 32 || b == 127) {
            builder = builder.header("authorization", format!("Bearer {trimmed}"));
        }
    }
    let req = builder
        .body(Full::new(Bytes::new()))
        .map_err(|_| HubError::unavailable("release_hub_unreachable"))?;
    let resp = tokio::time::timeout(Duration::from_secs(5), client.request(req))
        .await
        .map_err(|_| HubError::unavailable("release_hub_timeout"))?
        .map_err(|_| HubError::unavailable("release_hub_unreachable"))?;
    let status = resp.status().as_u16();
    if (300..400).contains(&status) && status != 304 {
        return Err(HubError::unavailable("release_hub_redirect_blocked"));
    }
    let headers = resp.headers().clone();
    let limited = Limited::new(resp.into_body(), max_bytes);
    let collected = tokio::time::timeout(Duration::from_secs(5), limited.collect())
        .await
        .map_err(|_| HubError::unavailable("release_hub_timeout"))?
        .map_err(|_| HubError::unavailable("release_hub_response_too_large"))?;
    let bytes = collected.to_bytes().to_vec();
    Ok((status, headers, bytes))
}

pub async fn fetch_release_hub_catalog_preview(
    endpoint: &str,
    enrolled_installations: &[String],
) -> Value {
    let url = format!("{endpoint}/v1/catalog");
    match fetch_http_get_bounded(&url, MAX_CATALOG_BYTES).await {
        Ok((200, _, bytes)) => match serde_json::from_slice::<Value>(&bytes) {
            Ok(doc) => json!({
                "reachable": true,
                "trusted": false,
                "endpoint": endpoint,
                "revision": doc.get("revision").and_then(Value::as_u64).unwrap_or(0),
                "updated_at": doc.get("updated_at"),
                "expires_at": doc.get("expires_at"),
                "expired": doc.get("expired").and_then(Value::as_bool).unwrap_or(false),
                "key_id": doc.get("key_id"),
                "public_key_b64": doc.get("public_key_b64"),
                "export_sha256": doc.get("export_sha256"),
                "releases": doc.get("releases").cloned().unwrap_or_else(|| json!([])),
                "channels": doc.get("channels").cloned().unwrap_or_else(|| json!({})),
                "enrolled_installations": enrolled_installations,
            }),
            Err(_) => json!({
                "reachable": false,
                "trusted": false,
                "endpoint": endpoint,
                "error": "invalid_release_hub_catalog",
                "enrolled_installations": enrolled_installations,
            }),
        },
        Ok((status, _, _)) => json!({
            "reachable": false,
            "trusted": false,
            "endpoint": endpoint,
            "error": format!("release_hub_http_{status}"),
            "enrolled_installations": enrolled_installations,
        }),
        Err(e) => json!({
            "reachable": false,
            "trusted": false,
            "endpoint": endpoint,
            "error": e.code,
            "enrolled_installations": enrolled_installations,
        }),
    }
}

pub fn parse_export_releases(export_doc: &Value) -> Vec<AcceptedCatalogRelease> {
    let mut out = Vec::new();
    let Some(arr) = export_doc.get("releases").and_then(Value::as_array) else { return out; };
    for item in arr {
        let Some(id) = item.get("id").and_then(Value::as_str) else { continue; };
        let digest = item.get("digest").and_then(Value::as_str).unwrap_or("").to_string();
        let channels: Vec<String> = item.get("channels").and_then(Value::as_array)
            .map(|a| a.iter().filter_map(Value::as_str).map(String::from).collect())
            .unwrap_or_default();
        let recalled = item.get("recalled_at").is_some_and(|v| !v.is_null());
        let manifest_val = item
            .get("manifest")
            .and_then(Value::as_str)
            .and_then(|s| serde_json::from_str::<Value>(s).ok())
            .unwrap_or_else(|| json!({}));
        let source_commit = manifest_val.get("source_commit").and_then(Value::as_str).unwrap_or("").to_string();
        let platform_tag = manifest_val.get("platform_tag").and_then(Value::as_str).unwrap_or("").to_string();
        let schema_target = manifest_val.get("schema_target").and_then(Value::as_u64);
        let schema_range = manifest_val.get("schema_range").cloned();
        let mut images = Vec::new();
        if let Some(img_obj) = manifest_val.get("images").and_then(Value::as_object) {
            for (comp, dg) in img_obj {
                if let Some(dgs) = dg.as_str() {
                    images.push(json!({"section": "workloads", "component": comp, "image_digest": dgs}));
                }
            }
        }
        out.push(AcceptedCatalogRelease {
            release_id: id.to_string(),
            digest,
            source_commit,
            platform_tag,
            channels,
            schema_target,
            schema_range,
            images,
            recall_notices: Vec::new(),
            recalled,
        });
    }
    out
}

pub fn compute_catalog_diff(
    current: Option<&AcceptedCatalogState>,
    next_releases: &[AcceptedCatalogRelease],
    next_channels: &BTreeMap<String, Vec<String>>,
) -> Value {
    let cur_map: BTreeMap<&str, &AcceptedCatalogRelease> = current
        .map(|c| c.releases.iter().map(|r| (r.release_id.as_str(), r)).collect())
        .unwrap_or_default();
    let next_map: BTreeMap<&str, &AcceptedCatalogRelease> = next_releases
        .iter()
        .map(|r| (r.release_id.as_str(), r))
        .collect();
    let mut added = Vec::new();
    let mut changed = Vec::new();
    for (id, rel) in &next_map {
        match cur_map.get(id) {
            None => added.push(json!({"release_id": id, "channels": rel.channels, "schema_target": rel.schema_target})),
            Some(old) if old.digest != rel.digest || old.recalled != rel.recalled => changed.push(Value::String((*id).to_string())),
            _ => {}
        }
    }
    let removed: Vec<Value> = cur_map
        .keys()
        .filter(|id| !next_map.contains_key(*id))
        .map(|id| Value::String((*id).to_string()))
        .collect();
    let cur_channels = current.map(|c| &c.channels);
    let mut ch_adds = Vec::new();
    let mut ch_rems = Vec::new();
    let mut new_chs = Vec::new();
    for (ch, ids) in next_channels {
        let old_set: BTreeSet<&str> = cur_channels
            .and_then(|m| m.get(ch))
            .map(|v| v.iter().map(String::as_str).collect())
            .unwrap_or_default();
        if cur_channels.is_some_and(|m| !m.contains_key(ch)) || cur_channels.is_none() {
            new_chs.push(Value::String(ch.clone()));
        }
        for id in ids {
            if !old_set.contains(id.as_str()) {
                ch_adds.push(json!({"channel": ch, "release_id": id}));
            }
        }
    }
    if let Some(cm) = cur_channels {
        for (ch, old_ids) in cm {
            let new_set: BTreeSet<&str> = next_channels
                .get(ch)
                .map(|v| v.iter().map(String::as_str).collect())
                .unwrap_or_default();
            for id in old_ids {
                if !new_set.contains(id.as_str()) {
                    ch_rems.push(json!({"channel": ch, "release_id": id}));
                }
            }
        }
    }
    json!({
        "added_releases": added,
        "removed_releases": removed,
        "changed_releases": changed,
        "channel_additions": ch_adds,
        "channel_removals": ch_rems,
        "new_channels": new_chs,
        "new_recalls": [],
        "lifted_recalls": [],
        "schema_widened": false,
    })
}

pub fn adopt_export_into_state(
    st: &LifecycleHubState,
    data: &mut PersistedLifecycleHubData,
    raw_bytes: &[u8],
    sig_b64: &str,
    key_id_hdr: Option<&str>,
    actor: &str,
    reason: &str,
) -> Result<(AcceptedCatalogState, Vec<Value>), HubError> {
    let doc: Value = serde_json::from_slice(raw_bytes).map_err(|_| HubError::unprocessable("invalid_catalog_export"))?;
    let rev = doc.get("revision").and_then(Value::as_u64).ok_or_else(|| HubError::unprocessable("invalid_catalog_export"))?;
    let expires_at = doc.get("expires_at").and_then(Value::as_str).unwrap_or("").to_string();
    let now_check = format_utc_rfc3339_now();
    if expires_at.is_empty() || expires_at.as_str() <= now_check.as_str() {
        return Err(HubError::conflict("catalog_expired"));
    }
    let export_sha = sha256_hex(raw_bytes);

    if let Some(ref pinned_pk) = data.catalog_trust.trusted_public_key_b64 {
        if let Some(ref pinned_kid) = data.catalog_trust.trusted_key_id {
            if let Some(hdr_kid) = key_id_hdr {
                if hdr_kid != pinned_kid {
                    return Err(HubError::conflict("untrusted_catalog_key_id"));
                }
            }
        }
        if !LifecycleHubState::verify_ed25519_b64(pinned_pk, raw_bytes, sig_b64) {
            return Err(HubError::conflict("catalog_signature_invalid"));
        }
    }
    if let Some(ref cur) = data.accepted_catalog {
        if rev < cur.revision {
            return Err(HubError::conflict("catalog_rollback_blocked"));
        }
    }
    let releases = parse_export_releases(&doc);
    let mut channels = BTreeMap::new();
    if let Some(ch_obj) = doc.get("channels").and_then(Value::as_object) {
        for (ch, v) in ch_obj {
            if let Some(arr) = v.as_array() {
                channels.insert(ch.clone(), arr.iter().filter_map(Value::as_str).map(String::from).collect());
            }
        }
    }
    let accepted = AcceptedCatalogState {
        revision: rev,
        sha256: export_sha.clone(),
        expires_at,
        releases,
        channels,
    };
    data.accepted_catalog = Some(accepted.clone());
    data.catalog_trust.snapshot_version = data.catalog_trust.snapshot_version.max(rev);
    data.catalog_trust.timestamp_version = data.catalog_trust.timestamp_version.max(rev);
    let now_s = format_utc_rfc3339_now();
    data.update_events.push(json!({
        "action": "adopted",
        "actor": actor,
        "revision": rev,
        "sha256": export_sha,
        "reason": reason,
        "recorded_at": now_s,
    }));
    LifecycleHubState::append_audit(data, "catalog_adopted", "hub", &format!("rev-{rev}"));

    let inst_ids: Vec<String> = data.installations.keys().cloned().collect();
    let mut plan_outcomes = Vec::new();
    for iid in inst_ids {
        if let Ok(eval) = st.evaluate_and_plan_locked(data, &iid) {
            plan_outcomes.push(json!({"installation_id": iid, "outcome": eval.outcome}));
        }
    }
    Ok((accepted, plan_outcomes))
}

pub fn provision_from_release_catalog(
    st: &LifecycleHubState,
    data: &mut PersistedLifecycleHubData,
    endpoint: &str,
    catalog_doc: &Value,
    body: &Map<String, Value>,
) -> Result<Value, HubError> {
    let inst_id = body.get("installation_id").and_then(Value::as_str).unwrap_or("").trim();
    if !is_valid_installation_id(inst_id) {
        return Err(HubError::unprocessable("release_hub_provision_invalid"));
    }
    let rel_id = body.get("release_id").and_then(Value::as_str).unwrap_or("").trim();
    let channel = body.get("channel").and_then(Value::as_str).unwrap_or("DEV").trim();
    let region = body.get("region").and_then(Value::as_str).unwrap_or("koreacentral").trim();
    let releases = catalog_doc.get("releases").and_then(Value::as_array).ok_or_else(|| HubError::conflict("release_not_found"))?;
    let rel = releases
        .iter()
        .find(|r| r.get("id").and_then(Value::as_str) == Some(rel_id))
        .ok_or_else(|| HubError::conflict("release_not_found"))?;
    if rel.get("state").and_then(Value::as_str) == Some("recalled") {
        return Err(HubError::conflict("release_recalled"));
    }
    let now_s = format_utc_rfc3339_now();
    if !data.installations.contains_key(inst_id) {
        let cfg_dig = sha256_hex(format!("cfg:{inst_id}:{rel_id}").as_bytes());
        let set_dig = compute_settings_digest(None, &[], 60);
        data.installations.insert(inst_id.to_string(), InstallationRecord {
            installation_id: inst_id.to_string(),
            enrollment: String::from("enrolled"),
            installation_key_id: sha256_hex(inst_id.as_bytes())[..16].to_string(),
            channel: channel.to_string(),
            version_range: String::from("*"),
            region: region.to_string(),
            allowed_regions: vec![region.to_string()],
            windows: Vec::new(),
            plan_duration_minutes: 60,
            product: None,
            settings_digest: set_dig,
            configuration_digest: cfg_dig,
            reported_at: now_s.clone(),
            schema_revision: 1,
            current_release: None,
            health: Some(String::from("unknown")),
            entities: vec![EntityRecord {
                entity_id: format!("{inst_id}-core"),
                kind: String::from("application"),
                managed: true,
                ownership_gap: None,
                release_id: None,
                health: Some(String::from("unknown")),
            }],
            suppressions: Vec::new(),
            last_evaluation: None,
            plan_sequence: 0,
        });
    }
    let accepted_rel = AcceptedCatalogRelease {
        release_id: rel_id.to_string(),
        digest: rel.get("digest").and_then(Value::as_str).unwrap_or("").to_string(),
        source_commit: String::new(),
        platform_tag: String::new(),
        channels: vec![channel.to_string()],
        schema_target: Some(1),
        schema_range: None,
        images: Vec::new(),
        recall_notices: Vec::new(),
        recalled: false,
    };
    let cat = data.accepted_catalog.get_or_insert_with(|| AcceptedCatalogState {
        revision: catalog_doc.get("revision").and_then(Value::as_u64).unwrap_or(1),
        sha256: catalog_doc.get("export_sha256").and_then(Value::as_str).unwrap_or("").to_string(),
        expires_at: catalog_doc.get("expires_at").and_then(Value::as_str).unwrap_or(&now_s).to_string(),
        releases: Vec::new(),
        channels: BTreeMap::new(),
    });
    if !cat.releases.iter().any(|r| r.release_id == rel_id) {
        cat.releases.push(accepted_rel);
    }
    let ch_list = cat.channels.entry(channel.to_string()).or_default();
    if !ch_list.contains(&rel_id.to_string()) {
        ch_list.push(rel_id.to_string());
    }
    let eval = st.evaluate_and_plan_locked(data, inst_id)?;
    LifecycleHubState::append_audit(data, "release_hub_provision", inst_id, rel_id);
    Ok(json!({
        "installation_id": inst_id,
        "release_id": rel_id,
        "channel": channel,
        "endpoint": endpoint,
        "plan_id": eval.plan_id,
        "outcome": eval.outcome,
        "effect_verified": false,
    }))
}

pub async fn fetch_and_verify_tuf_metadata(
    endpoint: &str,
    pinned_pk: Option<&str>,
    trust: &crate::hub_state::CatalogTrustState,
) -> Option<Value> {
    let (status, _, bytes) = fetch_http_get_bounded(&format!("{endpoint}/v1/catalog/metadata"), MAX_CATALOG_BYTES).await.ok()?;
    if status != 200 { return None; }
    let doc: Value = serde_json::from_slice(&bytes).ok()?;
    let root_signed = doc.get("root").and_then(|r| r.get("signed"))?;
    let snap_signed = doc.get("snapshot").and_then(|r| r.get("signed"))?;
    let ts_signed = doc.get("timestamp").and_then(|r| r.get("signed"))?;
    let tgt_signed = doc.get("targets").and_then(|r| r.get("signed"))?;
    let pk = pinned_pk.or_else(|| root_signed.get("public_key_b64").and_then(Value::as_str))?;

    let check_role = |role_name: &str| -> bool {
        let Some(role) = doc.get(role_name) else { return false; };
        let Some(signed) = role.get("signed") else { return false; };
        let Some(sig) = role.get("signature").and_then(Value::as_str) else { return false; };
        LifecycleHubState::verify_ed25519_b64(pk, &crate::hub_state::canonical_json_bytes(signed), sig)
    };
    let sigs_ok = check_role("root") && check_role("targets") && check_role("snapshot") && check_role("timestamp");
    let root_ver = root_signed.get("version").and_then(Value::as_u64).unwrap_or(0);
    let snap_ver = snap_signed.get("version").and_then(Value::as_u64).unwrap_or(0);
    let ts_ver = ts_signed.get("version").and_then(Value::as_u64).unwrap_or(0);
    let max_recall = tgt_signed.get("max_recall_sequence").and_then(Value::as_u64).unwrap_or(0);
    let floor_ok = root_ver >= trust.root_version
        && snap_ver >= trust.snapshot_version
        && ts_ver >= trust.timestamp_version
        && max_recall >= trust.max_recall_sequence;
    let now_s = format_utc_rfc3339_now();
    let root_exp = root_signed.get("expires_at").and_then(Value::as_str).unwrap_or("");
    let snap_exp = snap_signed.get("expires_at").and_then(Value::as_str).unwrap_or("");
    let ts_exp = ts_signed.get("expires_at").and_then(Value::as_str).unwrap_or("");
    let expired = root_exp.is_empty()
        || snap_exp.is_empty()
        || ts_exp.is_empty()
        || root_exp <= now_s.as_str()
        || snap_exp <= now_s.as_str()
        || ts_exp <= now_s.as_str();
    let verified = sigs_ok && floor_ok && !expired;
    let reason = if !sigs_ok {
        "tuf_signature_invalid"
    } else if expired {
        "tuf_metadata_expired"
    } else if !floor_ok {
        "tuf_rollback_detected"
    } else {
        "verified"
    };
    Some(json!({
        "mode": "tuf",
        "verified": verified,
        "reason": reason,
        "root": {"version": root_ver, "expires_at": root_signed.get("expires_at")},
        "snapshot": {"version": snap_ver, "expires_at": snap_signed.get("expires_at")},
        "timestamp": {"version": ts_ver, "expires_at": ts_signed.get("expires_at")},
        "expired": expired,
        "root_rotation": root_ver > trust.root_version && trust.root_version > 0,
        "previous_root_version": trust.root_version,
        "max_recall_sequence": max_recall,
        "allowed_plan_types": ["upgrade"],
        "demote_operator_overrides_to_shadow": false,
    }))
}

#[must_use]
pub fn build_update_status_payload(data: &PersistedLifecycleHubData) -> Value {
    let accepted = data.accepted_catalog.as_ref().map(|c| {
        json!({
            "revision": c.revision,
            "sha256": c.sha256,
            "expires_at": c.expires_at,
            "release_count": c.releases.len(),
        })
    });
    let integrity = json!({
        "mode": "tuf",
        "root_version": data.catalog_trust.root_version,
        "snapshot_version": data.catalog_trust.snapshot_version,
        "snapshot_expires_at": data.accepted_catalog.as_ref().map(|c| c.expires_at.as_str()),
        "timestamp_version": data.catalog_trust.timestamp_version,
        "timestamp_expires_at": data.accepted_catalog.as_ref().map(|c| c.expires_at.as_str()),
        "max_recall_sequence": data.catalog_trust.max_recall_sequence,
        "observed_at": data.catalog_trust.approved_at,
        "last": Value::Null,
    });
    json!({
        "mode": "review",
        "allowed_channels": ["DEV", "RELEASE_CANDIDATE", "RELEASE"],
        "max_new_releases": 25,
        "check_interval_seconds": 300,
        "access": "anonymous",
        "authorization": Value::Null,
        "accepted": accepted,
        "last_check": data.last_update_check,
        "events": data.update_events,
        "integrity": integrity,
    })
}
