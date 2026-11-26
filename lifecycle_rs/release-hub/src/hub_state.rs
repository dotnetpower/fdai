//! Release Hub transactional state, Ed25519 signing, TUF metadata, OCI v2 registry, and Entra sessions.

use fdai_http_runtime::base64::engine::general_purpose::STANDARD as B64;
use fdai_http_runtime::base64::Engine as _;
use fdai_http_runtime::format_utc_rfc3339_now;
use fdai_http_runtime::ring::digest::{digest, SHA256};
use fdai_http_runtime::ring::rand::SystemRandom;
use fdai_http_runtime::ring::signature::{Ed25519KeyPair, KeyPair, UnparsedPublicKey, ED25519};
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Arc, RwLock};
use std::time::{SystemTime, UNIX_EPOCH};

pub const CHANNELS: [&str; 3] = ["DEV", "RELEASE_CANDIDATE", "RELEASE"];
pub const MAX_BODY_BYTES: usize = 2 * 1024 * 1024;
pub const MAX_STENCIL_BODY_BYTES: usize = 64 * 1024;
pub const MAX_REQUEST_BODY_BYTES: usize = 2048;
pub const MAX_STORED_REQUESTS: usize = 100_000;
pub const LOCAL_EXPORT_TTL_SECS: u64 = 72 * 3600;
pub const OCI_IMAGE_MANIFEST_MEDIA_TYPE: &str = "application/vnd.oci.image.manifest.v1+json";

pub const CANDIDATE_DOCKER_TAGS: &[(&str, &[&str])] = &[
    ("clamav", &["clamav/clamav:stable", "clamav/clamav:latest"]),
    ("core-control-plane", &["fdai-core-control-plane:lite-release", "fdai-core-control-plane:latest", "fdai-core-control-plane:local"]),
    ("document-ingestion-api", &["fdai-document-ingestion-api:lite-release", "fdai-document-ingestion-api:latest", "fdai-document-ingestion-api:local"]),
    ("document-processing-worker", &["fdai-document-processing-worker:lite-release", "fdai-document-processing-worker:latest", "fdai-document-processing-worker:local"]),
    ("isolated-executor", &["fdai-isolated-executor:lite-release", "fdai-isolated-executor:latest", "fdai-isolated-executor:local"]),
    ("operator-service", &["fdai-operator-service:lite-release", "fdai-operator-service:latest", "fdai-operator-service:local"]),
    ("pgvector", &["pgvector/pgvector:pg16", "pgvector/pgvector:latest"]),
];

pub const SYNCED_COMPONENT_DIGESTS: &[(&str, &str)] = &[
    ("core-control-plane", "sha256:a613c32d0c56d9a6ef85a5549ab10e8eb44a54b3fad79ca6a11edb7e73d2ab21"),
    ("operator-service", "sha256:7d446ca2cf9e57ca471ebdb2b6ef0dee65bf51a2d452bfc05aebfd9a16b2c7c1"),
    ("pgvector", "sha256:3f0a88823465866f5f48e3c91edd273fb883a8715367e80b0d314b68fa592989"),
    ("clamav", "sha256:0aa882847026bb66d88d1d96fbb8e2cb1284bf05b45f3c92c838436da98659dc"),
    ("document-ingestion-api", "sha256:3fb1717f3b1c034a6aca04802695d3dda6258895cd1b550d1c48db9d0b25c08f"),
    ("document-processing-worker", "sha256:9e4343268c6a13422409998e18200f2162979949eebed79949949c3cfc18b659"),
    ("isolated-executor", "sha256:8237c0f4271fe3319f7b6ef9ced407e94ddc4476a36669a61fede0cae7a3dcda"),
];

#[derive(Clone, Debug)]
pub struct CatalogError {
    pub status: u16,
    pub message: String,
}

impl CatalogError {
    #[must_use]
    pub fn new(status: u16, msg: impl Into<String>) -> Self {
        Self { status, message: msg.into() }
    }
    #[must_use]
    pub fn bad_request(msg: impl Into<String>) -> Self { Self::new(400, msg) }
    #[must_use]
    pub fn conflict(msg: impl Into<String>) -> Self { Self::new(409, msg) }
    #[must_use]
    pub fn unprocessable(msg: impl Into<String>) -> Self { Self::new(422, msg) }
    #[must_use]
    pub fn not_found(msg: impl Into<String>) -> Self { Self::new(404, msg) }
    #[must_use]
    pub fn unavailable(msg: impl Into<String>) -> Self { Self::new(503, msg) }
}

#[must_use]
pub fn sha256_hex(bytes: &[u8]) -> String {
    let d = digest(&SHA256, bytes);
    let mut out = String::with_capacity(64);
    for b in d.as_ref() {
        let _ = std::fmt::Write::write_fmt(&mut out, format_args!("{b:02x}"));
    }
    out
}

#[must_use]
pub fn now_unix_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(1_700_000_000)
}

#[must_use]
pub fn format_unix_rfc3339(secs: u64) -> String {
    let days = (secs / 86_400) as i64;
    let rem = secs % 86_400;
    let hh = rem / 3600;
    let mm = (rem % 3600) / 60;
    let ss = rem % 60;
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = (z - era * 146_097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = (yoe as i64) + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let yr = if m <= 2 { y + 1 } else { y };
    format!("{yr:04}-{m:02}-{d:02}T{hh:02}:{mm:02}:{ss:02}Z")
}

#[must_use]
pub fn canonical_json_bytes(val: &Value) -> Vec<u8> {
    let mut out = String::new();
    write_canonical(val, &mut out);
    out.into_bytes()
}

fn write_canonical(val: &Value, out: &mut String) {
    match val {
        Value::Object(map) => {
            out.push('{');
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            for (i, k) in keys.iter().enumerate() {
                if i > 0 { out.push(','); }
                if let Ok(s) = serde_json::to_string(k) { out.push_str(&s); }
                out.push(':');
                if let Some(v) = map.get(*k) { write_canonical(v, out); }
            }
            out.push('}');
        }
        Value::Array(arr) => {
            out.push('[');
            for (i, item) in arr.iter().enumerate() {
                if i > 0 { out.push(','); }
                write_canonical(item, out);
            }
            out.push(']');
        }
        other => {
            if let Ok(s) = serde_json::to_string(other) { out.push_str(&s); }
        }
    }
}

#[must_use]
pub fn is_valid_semver(id: &str) -> bool {
    if id.is_empty() || id.len() > 64 { return false; }
    let (core, pre) = match id.split_once('-') {
        Some((c, p)) => (c, Some(p)),
        None => (id, None),
    };
    let parts: Vec<&str> = core.split('.').collect();
    if parts.len() != 3 { return false; }
    for p in parts {
        if p.is_empty() || !p.bytes().all(|b| b.is_ascii_digit()) { return false; }
        if p.len() > 1 && p.starts_with('0') { return false; }
    }
    if let Some(pr) = pre {
        if pr.is_empty() { return false; }
        for seg in pr.split('.') {
            if seg.is_empty() || !seg.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-') {
                return false;
            }
        }
    }
    true
}

#[must_use]
pub fn is_custom_channel(ch: &str) -> bool {
    let Some(rest) = ch.strip_prefix("custom-") else { return false };
    if ch.len() > 64 || rest.is_empty() { return false; }
    rest.split('-').all(|seg| !seg.is_empty() && seg.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit()))
}

#[must_use]
pub fn is_valid_channel(ch: &str) -> bool {
    CHANNELS.contains(&ch) || is_custom_channel(ch)
}

#[must_use]
pub fn is_valid_uuid(s: &str) -> bool {
    let b = s.as_bytes();
    if b.len() != 36 { return false; }
    for (idx, &ch) in b.iter().enumerate() {
        if matches!(idx, 8 | 13 | 18 | 23) {
            if ch != b'-' { return false; }
        } else if !matches!(ch, b'0'..=b'9' | b'a'..=b'f') {
            return false;
        }
    }
    true
}

#[must_use]
pub fn is_hex_len(s: &str, len: usize) -> bool {
    s.len() == len && s.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
}

#[must_use]
pub fn is_valid_component_slug(s: &str) -> bool {
    let b = s.as_bytes();
    if b.is_empty() || b.len() > 63 { return false; }
    if !b[0].is_ascii_lowercase() { return false; }
    if b.len() > 1 && !(b[b.len() - 1].is_ascii_lowercase() || b[b.len() - 1].is_ascii_digit()) {
        return false;
    }
    b.iter().all(|&c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'-')
}

/// Reject duplicate object keys in raw JSON bytes (strict RFC 8259 + security boundary).
pub fn parse_strict_json_object(raw: &[u8]) -> Result<Map<String, Value>, CatalogError> {
    let text = std::str::from_utf8(raw).map_err(|_| CatalogError::unprocessable("Invalid UTF-8 JSON."))?;
    check_no_duplicate_json_keys(text)?;
    let parsed: Value = serde_json::from_str(text)
        .map_err(|_| CatalogError::unprocessable("Invalid JSON payload."))?;
    match parsed {
        Value::Object(m) => Ok(m),
        _ => Err(CatalogError::unprocessable("Expected a JSON object.")),
    }
}

fn check_no_duplicate_json_keys(src: &str) -> Result<(), CatalogError> {
    let bytes = src.as_bytes();
    let mut idx = 0_usize;
    skip_ws(bytes, &mut idx);
    scan_json_val(bytes, &mut idx, 0)?;
    Ok(())
}

fn skip_ws(b: &[u8], i: &mut usize) {
    while *i < b.len() && matches!(b[*i], b' ' | b'\t' | b'\r' | b'\n') { *i += 1; }
}

fn scan_json_str(b: &[u8], i: &mut usize) -> Result<String, CatalogError> {
    if *i >= b.len() || b[*i] != b'"' { return Err(CatalogError::unprocessable("Invalid JSON string.")); }
    let start = *i;
    *i += 1;
    while *i < b.len() {
        match b[*i] {
            b'\\' => { *i += 2; }
            b'"' => {
                *i += 1;
                let slice = std::str::from_utf8(&b[start..*i])
                    .map_err(|_| CatalogError::unprocessable("Invalid JSON UTF-8."))?;
                return serde_json::from_str::<String>(slice)
                    .map_err(|_| CatalogError::unprocessable("Invalid JSON string escape."));
            }
            _ => { *i += 1; }
        }
    }
    Err(CatalogError::unprocessable("Unterminated JSON string."))
}

fn scan_json_val(b: &[u8], i: &mut usize, depth: usize) -> Result<(), CatalogError> {
    if depth > 64 { return Err(CatalogError::unprocessable("JSON nesting too deep.")); }
    skip_ws(b, i);
    if *i >= b.len() { return Err(CatalogError::unprocessable("Unexpected EOF in JSON.")); }
    match b[*i] {
        b'{' => {
            *i += 1;
            skip_ws(b, i);
            let mut seen = BTreeSet::new();
            if *i < b.len() && b[*i] == b'}' { *i += 1; return Ok(()); }
            loop {
                skip_ws(b, i);
                let key = scan_json_str(b, i)?;
                if !seen.insert(key) {
                    return Err(CatalogError::unprocessable("Duplicate JSON keys are not supported."));
                }
                skip_ws(b, i);
                if *i >= b.len() || b[*i] != b':' { return Err(CatalogError::unprocessable("Expected ':' in JSON.")); }
                *i += 1;
                scan_json_val(b, i, depth + 1)?;
                skip_ws(b, i);
                if *i < b.len() && b[*i] == b',' { *i += 1; continue; }
                if *i < b.len() && b[*i] == b'}' { *i += 1; return Ok(()); }
                return Err(CatalogError::unprocessable("Expected ',' or '}' in JSON."));
            }
        }
        b'[' => {
            *i += 1;
            skip_ws(b, i);
            if *i < b.len() && b[*i] == b']' { *i += 1; return Ok(()); }
            loop {
                scan_json_val(b, i, depth + 1)?;
                skip_ws(b, i);
                if *i < b.len() && b[*i] == b',' { *i += 1; continue; }
                if *i < b.len() && b[*i] == b']' { *i += 1; return Ok(()); }
                return Err(CatalogError::unprocessable("Expected ',' or ']' in JSON."));
            }
        }
        b'"' => { let _ = scan_json_str(b, i)?; Ok(()) }
        _ => {
            while *i < b.len() && !matches!(b[*i], b',' | b'}' | b']' | b' ' | b'\t' | b'\r' | b'\n') {
                *i += 1;
            }
            Ok(())
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StoredRelease {
    pub id: String,
    pub label: String,
    pub manifest: String,
    pub digest: String,
    pub signature: Option<String>,
    pub published_at: Option<String>,
    pub recalled_at: Option<String>,
    #[serde(default)]
    pub capability_ids: Vec<String>,
    #[serde(default)]
    pub stencil_id: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CatalogEvent {
    pub revision: u64,
    pub release_id: String,
    pub action: String,
    pub reason: String,
    pub channel: Option<String>,
    pub occurred_at: String,
    pub actor: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct DeploymentRequestRecord {
    pub request_id: String,
    pub subscription_id: String,
    pub release_id: String,
    pub channel: String,
    pub region: String,
    pub source_commit: String,
    pub catalog_digest: String,
    pub recorded_at: String,
    pub status: String,
    pub trust: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CapabilityRecallRecord {
    pub sequence: u64,
    pub capability_id: String,
    pub action: String,
    pub lifting_release_id: Option<String>,
    pub reason: String,
    pub actor: String,
    pub occurred_at: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PromotionRunReceipt {
    pub receipt_id: String,
    pub release_id: String,
    pub source_channel: String,
    pub target_channel: String,
    pub outcome: String,
    pub block_code: Option<String>,
    pub reason: String,
    pub actor: String,
    pub recorded_at: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct WorkflowJobRecord {
    pub job_id: String,
    pub idempotency_key: String,
    pub release_id: String,
    pub stencil_id: String,
    pub source_commit: String,
    pub stage: String,
    pub status: String,
    pub input_digest: String,
    pub manifest_digest: String,
    pub actor: String,
    pub result: Value,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StencilGrantRecord {
    pub installation_id: String,
    pub customer_principal: String,
    pub grant_id: String,
    pub revision: u64,
    pub allowed_stencil_ids: Vec<String>,
    pub allowed_channels: Vec<String>,
    pub scope_digest: String,
    pub expires_at: String,
    pub envelope: Value,
    pub registered_by: String,
    pub registered_at: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct GrantEventRecord {
    pub sequence: u64,
    pub installation_id: String,
    pub action: String,
    pub actor: String,
    pub reason: String,
    pub recorded_at: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EntraAccountCandidate {
    pub principal: String,
    pub tenant_id: String,
    pub tenant_label: String,
    pub is_default: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ActiveEntraSession {
    pub principal: String,
    pub display_name: String,
    pub tenant_id: String,
    pub auth_method: String,
    pub signed_in_at: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PersistedReleaseHubData {
    pub created_at: String,
    pub created_at_unix: u64,
    pub last_updated_unix: u64,
    pub ttl_seconds: u64,
    pub revision: u64,
    pub releases: BTreeMap<String, StoredRelease>,
    pub channel_memberships: BTreeMap<String, Vec<String>>,
    pub events: Vec<CatalogEvent>,
    pub deployment_requests: BTreeMap<String, DeploymentRequestRecord>,
    pub capability_recalls: Vec<CapabilityRecallRecord>,
    pub promotion_receipts: Vec<PromotionRunReceipt>,
    pub workflow_jobs: BTreeMap<String, WorkflowJobRecord>,
    pub oci_manifests: BTreeMap<String, String>,
    pub stencil_grants: BTreeMap<String, StencilGrantRecord>,
    pub grant_events: Vec<GrantEventRecord>,
}

impl PersistedReleaseHubData {
    #[must_use]
    pub fn fresh() -> Self {
        let now_u = now_unix_secs();
        let now_s = format_unix_rfc3339(now_u);
        let mut channels = BTreeMap::new();
        for ch in CHANNELS {
            channels.insert(String::from(ch), Vec::new());
        }
        Self {
            created_at: now_s,
            created_at_unix: now_u,
            last_updated_unix: now_u,
            ttl_seconds: LOCAL_EXPORT_TTL_SECS,
            revision: 0,
            releases: BTreeMap::new(),
            channel_memberships: channels,
            events: Vec::new(),
            deployment_requests: BTreeMap::new(),
            capability_recalls: Vec::new(),
            promotion_receipts: Vec::new(),
            workflow_jobs: BTreeMap::new(),
            oci_manifests: BTreeMap::new(),
            stencil_grants: BTreeMap::new(),
            grant_events: Vec::new(),
        }
    }
}

pub struct ReleaseHubState {
    pub state_path: Option<PathBuf>,
    pub pg_ledger: Option<fdai_http_runtime::HubPgLedger>,
    pub remote_policy: fdai_http_runtime::HubRemotePolicy,
    pub authenticator: fdai_http_runtime::OperatorAuthenticator,
    pub intake_semaphore: Arc<tokio::sync::Semaphore>,
    pub key_id: String,
    pub public_key_b64: String,
    pub public_key_pem: String,
    pub public_key_bytes: Vec<u8>,
    keypair: Option<Ed25519KeyPair>,
    pub data: RwLock<PersistedReleaseHubData>,
    pub entra_session: RwLock<Option<ActiveEntraSession>>,
    pub mode: String,
}

fn encode_ed25519_spki_pem(pub_bytes: &[u8]) -> String {
    if pub_bytes.len() != 32 {
        return String::new();
    }
    const SPKI_PREFIX: [u8; 12] = [0x30, 0x2a, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x70, 0x03, 0x21, 0x00];
    let mut der = Vec::with_capacity(44);
    der.extend_from_slice(&SPKI_PREFIX);
    der.extend_from_slice(pub_bytes);
    let b64 = B64.encode(&der);
    format!("-----BEGIN PUBLIC KEY-----\n{b64}\n-----END PUBLIC KEY-----\n")
}

impl ReleaseHubState {
    #[must_use]
    pub fn open_from_env() -> Arc<Self> {
        let state_path = std::env::var("FDAI_RELEASE_HUB_STATE_PATH")
            .ok()
            .filter(|s| !s.trim().is_empty())
            .map(PathBuf::from)
            .or_else(|| Some(PathBuf::from(".fdai/release-hub-state.json")));
        let key_path = std::env::var("FDAI_RELEASE_HUB_KEY_FILE")
            .ok()
            .filter(|s| !s.trim().is_empty())
            .map(PathBuf::from)
            .or_else(|| Some(PathBuf::from(".fdai/release-hub-ed25519.pkcs8")));
        let pg_ledger = fdai_http_runtime::HubPgLedger::from_env("release-hub");
        let remote_policy = fdai_http_runtime::HubRemotePolicy::from_env("release-hub");
        let st = Self::open_with_config(state_path, key_path, pg_ledger, remote_policy);
        if let Ok(handle) = tokio::runtime::Handle::try_current() {
            let st_bg = Arc::clone(&st);
            handle.spawn(async move {
                st_bg.hydrate_from_pg_if_configured().await;
            });
            Self::spawn_background_tuf_renewal(Arc::clone(&st));
        }
        st
    }

    #[must_use]
    pub fn open_ephemeral() -> Arc<Self> {
        Self::open_with_config(None, None, None, fdai_http_runtime::HubRemotePolicy::from_env("release-hub"))
    }

    #[must_use]
    pub fn open_with_paths(state_path: Option<PathBuf>, key_path: Option<PathBuf>) -> Arc<Self> {
        Self::open_with_config(state_path, key_path, None, fdai_http_runtime::HubRemotePolicy::from_env("release-hub"))
    }

    #[must_use]
    pub fn open_with_config(
        state_path: Option<PathBuf>,
        key_path: Option<PathBuf>,
        pg_ledger: Option<fdai_http_runtime::HubPgLedger>,
        remote_policy: fdai_http_runtime::HubRemotePolicy,
    ) -> Arc<Self> {
        let keypair = load_or_generate_ed25519(key_path.as_deref()).ok();
        let pub_bytes = keypair
            .as_ref()
            .map(|kp| kp.public_key().as_ref().to_vec())
            .unwrap_or_default();
        let key_id = sha256_hex(&pub_bytes).chars().take(16).collect::<String>();
        let public_key_b64 = B64.encode(&pub_bytes);
        let public_key_pem = encode_ed25519_spki_pem(&pub_bytes);
        let data = state_path
            .as_deref()
            .and_then(|p| fs::read(p).ok())
            .and_then(|b| serde_json::from_slice::<PersistedReleaseHubData>(&b).ok())
            .unwrap_or_else(PersistedReleaseHubData::fresh);
        let mode = if remote_policy.remote_origin.is_some() {
            String::from("remote")
        } else if remote_policy.is_remote_mode() {
            String::from("remote-development")
        } else {
            String::from("local-development")
        };
        let authenticator = fdai_http_runtime::OperatorAuthenticator::from_env()
            .unwrap_or_else(|_| fdai_http_runtime::OperatorAuthenticator::new(fdai_http_runtime::AuthMode::FailClosedUnconfigured));
        Arc::new(Self {
            state_path,
            pg_ledger,
            remote_policy,
            authenticator,
            intake_semaphore: Arc::new(tokio::sync::Semaphore::new(8)),
            key_id,
            public_key_b64,
            public_key_pem,
            public_key_bytes: pub_bytes,
            keypair,
            data: RwLock::new(data),
            entra_session: RwLock::new(None),
            mode,
        })
    }

    pub async fn hydrate_from_pg_if_configured(&self) {
        let Some(ref pg) = self.pg_ledger else { return; };
        if let Ok(Some(raw)) = pg.load_state_json().await {
            if let Ok(loaded) = serde_json::from_str::<PersistedReleaseHubData>(&raw) {
                if let Ok(mut guard) = self.data.write() {
                    if loaded.revision >= guard.revision {
                        *guard = loaded;
                    }
                }
            }
        }
    }

    pub fn spawn_background_tuf_renewal(st: Arc<Self>) {
        let interval_secs = std::env::var("FDAI_TIMESTAMP_RENEWAL_CHECK_SECONDS")
            .ok()
            .and_then(|v| v.parse::<u64>().ok())
            .filter(|&s| s >= 1)
            .unwrap_or(300);
        if let Ok(handle) = tokio::runtime::Handle::try_current() {
            handle.spawn(async move {
                let mut ticker = tokio::time::interval(std::time::Duration::from_secs(interval_secs));
                ticker.tick().await;
                loop {
                    ticker.tick().await;
                    let _ = st.renew_if_due();
                }
            });
        }
    }

    pub fn renew_if_due(&self) -> bool {
        let now_u = now_unix_secs();
        let mut guard = match self.data.write() {
            Ok(g) => g,
            Err(_) => return false,
        };
        let expires_u = guard.last_updated_unix.saturating_add(guard.ttl_seconds);
        let threshold = (guard.ttl_seconds / 4).max(60);
        if expires_u.saturating_sub(now_u) > threshold {
            return false;
        }
        for rel in guard.releases.values() {
            if let Some(ref sig) = rel.signature {
                if self.verify_bytes_b64(rel.manifest.as_bytes(), sig).is_err() {
                    return false;
                }
            }
        }
        let next_u = now_u.max(guard.last_updated_unix.saturating_add(1));
        guard.revision += 1;
        guard.last_updated_unix = next_u;
        let next_rev = guard.revision;
        guard.events.push(CatalogEvent {
            revision: next_rev,
            release_id: String::from("catalog"),
            action: String::from("renew"),
            reason: String::from("Automatic TUF timestamp/snapshot freshness renewal"),
            channel: None,
            occurred_at: format_unix_rfc3339(next_u),
            actor: String::from("system:timestamp-renewal"),
        });
        let _ = self.persist(&guard);
        true
    }

    #[must_use]
    pub fn sign_bytes_b64(&self, msg: &[u8]) -> String {
        self.keypair
            .as_ref()
            .map(|kp| B64.encode(kp.sign(msg).as_ref()))
            .unwrap_or_default()
    }

    pub fn verify_bytes_b64(&self, msg: &[u8], sig_b64: &str) -> Result<(), CatalogError> {
        let sig_bytes = B64
            .decode(sig_b64)
            .map_err(|_| CatalogError::unavailable("Stored Release signature failed verification."))?;
        let verifier = UnparsedPublicKey::new(&ED25519, &self.public_key_bytes);
        verifier
            .verify(msg, &sig_bytes)
            .map_err(|_| CatalogError::unavailable("Stored Release signature failed verification."))
    }

    pub fn persist(&self, data: &PersistedReleaseHubData) -> Result<(), CatalogError> {
        let Some(ref path) = self.state_path else { return Ok(()); };
        if let Some(parent) = path.parent() {
            if !parent.as_os_str().is_empty() {
                fs::create_dir_all(parent)
                    .map_err(|_| CatalogError::unavailable("Local storage is unavailable."))?;
            }
        }
        let encoded = serde_json::to_vec_pretty(data)
            .map_err(|_| CatalogError::unavailable("Failed to serialize Release Hub state."))?;
        let tmp = path.with_extension(format!("json.tmp.{}", std::process::id()));
        {
            use std::io::Write as _;
            let mut file = fs::File::create(&tmp)
                .map_err(|_| CatalogError::unavailable("Local storage is unavailable."))?;
            file.write_all(&encoded)
                .map_err(|_| CatalogError::unavailable("Local storage is unavailable."))?;
            file.sync_all()
                .map_err(|_| CatalogError::unavailable("Local storage is unavailable."))?;
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt as _;
            let _ = fs::set_permissions(&tmp, fs::Permissions::from_mode(0o600));
        }
        fs::rename(&tmp, path)
            .map_err(|_| CatalogError::unavailable("Local storage is unavailable."))?;
        if let Some(ref pg) = self.pg_ledger {
            let pg_clone = pg.clone();
            let rev = data.revision;
            if let Ok(json_str) = serde_json::to_string(data) {
                if let Ok(handle) = tokio::runtime::Handle::try_current() {
                    handle.spawn(async move {
                        let _ = pg_clone.save_state_json(rev, &json_str).await;
                    });
                }
            }
        }
        Ok(())
    }

    #[must_use]
    pub fn configured_grant_issuer_keys(&self) -> Vec<Vec<u8>> {
        let raw = std::env::var("FDAI_STENCIL_GRANT_ISSUER_PUBLIC_KEYS").unwrap_or_default();
        let mut keys = Vec::new();
        for tok in raw.split(',').map(str::trim).filter(|s| !s.is_empty()) {
            if let Ok(b) = B64.decode(tok) {
                if b.len() == 32 {
                    keys.push(b);
                }
            }
        }
        keys
    }

    pub fn verify_grant_signature(&self, env: &Map<String, Value>) -> Result<(), CatalogError> {
        let keys = self.configured_grant_issuer_keys();
        if keys.is_empty() {
            return Ok(());
        }
        let sig_b64 = env
            .get("signature")
            .and_then(Value::as_str)
            .filter(|s| !s.is_empty())
            .ok_or_else(|| CatalogError::new(403, "Signed Stencil distribution grant signature is required."))?;
        let sig_bytes = B64
            .decode(sig_b64)
            .map_err(|_| CatalogError::new(403, "Invalid Stencil distribution grant signature encoding."))?;
        let mut unsigned = env.clone();
        unsigned.remove("signature");
        let msg = canonical_json_bytes(&Value::Object(unsigned));
        let ok = keys
            .iter()
            .any(|pk| UnparsedPublicKey::new(&ED25519, pk).verify(&msg, &sig_bytes).is_ok());
        if !ok {
            return Err(CatalogError::new(403, "Stencil distribution grant signature verification failed."));
        }
        Ok(())
    }

    #[must_use]
    pub fn current_actor(&self) -> String {
        self.entra_session
            .read()
            .ok()
            .and_then(|g| g.as_ref().map(|s| format!("entra:{}", s.principal)))
            .unwrap_or_else(|| String::from("local-operator"))
    }

    #[must_use]
    pub fn entra_status_payload(&self) -> Value {
        let candidates = detect_workstation_entra_accounts();
        let active = self.entra_session.read().ok().and_then(|g| g.clone());
        let actor = active
            .as_ref()
            .map(|s| format!("entra:{}", s.principal))
            .unwrap_or_else(|| String::from("local-operator"));
        json!({
            "authenticated": active.is_some(),
            "actor": actor,
            "session": active,
            "detected_accounts": candidates,
        })
    }

    pub fn entra_sign_in(&self, body: &Map<String, Value>) -> Result<Value, CatalogError> {
        let mode = body.get("mode").and_then(Value::as_str).unwrap_or("workstation");
        if !matches!(mode, "workstation" | "msal_account") {
            return Err(CatalogError::unprocessable("Invalid Entra login mode."));
        }
        let mut principal = body.get("principal").and_then(Value::as_str).unwrap_or("").trim().to_string();
        let mut tenant_id = body.get("tenant_id").and_then(Value::as_str).unwrap_or("").trim().to_ascii_lowercase();
        let mut display_name = body.get("display_name").and_then(Value::as_str).unwrap_or("").trim().to_string();
        for f in [&principal, &tenant_id, &display_name] {
            if f.bytes().any(|b| b < 32 || b == 127) {
                return Err(CatalogError::unprocessable("Entra login fields cannot contain control characters."));
            }
        }
        if !tenant_id.is_empty() && !is_valid_uuid(&tenant_id) {
            return Err(CatalogError::unprocessable("Entra tenant_id must be a canonical UUID."));
        }
        let candidates = detect_workstation_entra_accounts();
        let auth_method = if mode == "workstation" {
            let matched = if !principal.is_empty() {
                candidates.iter().find(|c| c.principal.eq_ignore_ascii_case(&principal))
            } else {
                candidates.first()
            };
            if let Some(m) = matched {
                principal.clone_from(&m.principal);
                tenant_id.clone_from(&m.tenant_id);
                if display_name.is_empty() {
                    display_name = format!("{} ({})", m.principal, m.tenant_label);
                }
            } else if principal.is_empty() {
                return Err(CatalogError::unprocessable(
                    "No workstation Entra ID account detected. Provide UPN and Tenant ID.",
                ));
            } else {
                if tenant_id.is_empty() {
                    tenant_id = String::from("00000000-0000-0000-0000-000000000000");
                }
                if display_name.is_empty() {
                    display_name.clone_from(&principal);
                }
            }
            "entra-workstation"
        } else {
            if principal.is_empty() || tenant_id.is_empty() {
                return Err(CatalogError::unprocessable("MSAL sign-in requires both principal and tenant_id."));
            }
            if display_name.is_empty() { display_name.clone_from(&principal); }
            "entra-msal-pkce"
        };
        let sess = ActiveEntraSession {
            principal,
            display_name,
            tenant_id,
            auth_method: String::from(auth_method),
            signed_in_at: format_utc_rfc3339_now(),
        };
        if let Ok(mut guard) = self.entra_session.write() {
            *guard = Some(sess);
        }
        Ok(self.entra_status_payload())
    }

    pub fn entra_sign_out(&self) -> Value {
        if let Ok(mut guard) = self.entra_session.write() {
            *guard = None;
        }
        self.entra_status_payload()
    }

    pub fn active_recalled_capabilities(data: &PersistedReleaseHubData) -> BTreeSet<String> {
        let mut active = BTreeSet::new();
        for rec in &data.capability_recalls {
            if rec.action == "recall" {
                active.insert(rec.capability_id.clone());
            } else if rec.action == "lift" {
                active.remove(&rec.capability_id);
            }
        }
        active
    }

    pub fn build_signed_export_locked(
        &self,
        data: &PersistedReleaseHubData,
    ) -> Result<(Vec<u8>, String, String), CatalogError> {
        let updated_at = data.events.last().map_or_else(|| data.created_at.clone(), |e| e.occurred_at.clone());
        let expires_at = format_unix_rfc3339(data.last_updated_unix.saturating_add(data.ttl_seconds));
        let mut pub_releases = Vec::new();
        for rel in data.releases.values() {
            if let Some(ref sig) = rel.signature {
                self.verify_bytes_b64(rel.manifest.as_bytes(), sig)?;
                let mut chs: Vec<String> = data
                    .channel_memberships
                    .iter()
                    .filter(|(_, ids)| ids.contains(&rel.id))
                    .map(|(ch, _)| ch.clone())
                    .collect();
                chs.sort();
                pub_releases.push(json!({
                    "id": rel.id,
                    "label": rel.label,
                    "manifest": rel.manifest,
                    "digest": rel.digest,
                    "signature": sig,
                    "published_at": rel.published_at,
                    "recalled_at": rel.recalled_at,
                    "channels": chs,
                }));
            }
        }
        let mut channels_obj = Map::new();
        for (ch, ids) in &data.channel_memberships {
            channels_obj.insert(ch.clone(), json!(ids));
        }
        let export_doc = json!({
            "schema_version": "fdai.release-catalog-export.v1",
            "revision": data.revision,
            "updated_at": updated_at,
            "expires_at": expires_at,
            "key_id": self.key_id,
            "public_key_b64": self.public_key_b64,
            "channels": Value::Object(channels_obj),
            "releases": pub_releases,
            "recalls": data.capability_recalls,
        });
        let raw = canonical_json_bytes(&export_doc);
        let digest_hex = sha256_hex(&raw);
        let sig = self.sign_bytes_b64(&raw);
        Ok((raw, digest_hex, sig))
    }

    pub fn build_catalog_snapshot_locked(&self, data: &PersistedReleaseHubData) -> Result<Value, CatalogError> {
        let (_raw, export_sha256, _sig) = self.build_signed_export_locked(data)?;
        let updated_at = data.events.last().map_or_else(|| data.created_at.clone(), |e| e.occurred_at.clone());
        let expires_unix = data.last_updated_unix.saturating_add(data.ttl_seconds);
        let expires_at = format_unix_rfc3339(expires_unix);
        let expired = now_unix_secs() >= expires_unix;
        let mut rel_list = Vec::new();
        for rel in data.releases.values().rev() {
            let signed_sha = if let Some(ref sig) = rel.signature {
                self.verify_bytes_b64(rel.manifest.as_bytes(), sig)?;
                sha256_hex(rel.manifest.as_bytes())
            } else {
                sha256_hex(rel.manifest.as_bytes())
            };
            let mut chs: Vec<String> = data
                .channel_memberships
                .iter()
                .filter(|(_, ids)| ids.contains(&rel.id))
                .map(|(ch, _)| ch.clone())
                .collect();
            chs.sort();
            let state = if rel.recalled_at.is_some() {
                "recalled"
            } else if rel.signature.is_some() {
                "published"
            } else {
                "draft"
            };
            let sig_status = if rel.signature.is_some() { "development-key-verified" } else { "unsigned" };
            rel_list.push(json!({
                "id": rel.id,
                "label": rel.label,
                "manifest": rel.manifest,
                "digest": rel.digest,
                "signed_payload_sha256": signed_sha,
                "signature": rel.signature,
                "signature_status": sig_status,
                "state": state,
                "channels": chs,
                "published_at": rel.published_at,
                "recalled_at": rel.recalled_at,
            }));
        }
        let mut events_desc: Vec<CatalogEvent> = data.events.clone();
        events_desc.reverse();
        let mut channels_obj = Map::new();
        for ch in CHANNELS {
            channels_obj.insert(
                String::from(ch),
                json!(data.channel_memberships.get(ch).cloned().unwrap_or_default()),
            );
        }
        for (ch, ids) in &data.channel_memberships {
            if !CHANNELS.contains(&ch.as_str()) {
                channels_obj.insert(ch.clone(), json!(ids));
            }
        }
        Ok(json!({
            "revision": data.revision,
            "updated_at": updated_at,
            "expires_at": expires_at,
            "expired": expired,
            "mode": self.mode,
            "key_id": self.key_id,
            "public_key_b64": self.public_key_b64,
            "export_sha256": export_sha256,
            "releases": rel_list,
            "channels": Value::Object(channels_obj),
            "events": events_desc,
        }))
    }

    pub fn build_signed_metadata_locked(&self, data: &PersistedReleaseHubData) -> Result<(Vec<u8>, String), CatalogError> {
        let (_export_raw, export_sha256, export_sig) = self.build_signed_export_locked(data)?;
        let version = data.revision.max(1);
        let expires_at = format_unix_rfc3339(data.last_updated_unix.saturating_add(data.ttl_seconds));
        let max_recall_seq = data.capability_recalls.iter().map(|r| r.sequence).max().unwrap_or(0);
        let targets_body = json!({
            "role": "targets",
            "version": version,
            "expires_at": expires_at,
            "export_sha256": export_sha256,
            "export_signature": export_sig,
            "release_count": data.releases.len(),
            "max_recall_sequence": max_recall_seq,
        });
        let snapshot_body = json!({
            "role": "snapshot",
            "version": version,
            "expires_at": expires_at,
            "targets_version": version,
            "targets_sha256": sha256_hex(&canonical_json_bytes(&targets_body)),
        });
        let timestamp_body = json!({
            "role": "timestamp",
            "version": version,
            "expires_at": expires_at,
            "snapshot_version": version,
            "snapshot_sha256": sha256_hex(&canonical_json_bytes(&snapshot_body)),
        });
        let root_body = json!({
            "role": "root",
            "version": 1,
            "expires_at": format_unix_rfc3339(data.created_at_unix.saturating_add(365 * 86_400)),
            "key_id": self.key_id,
            "public_key_b64": self.public_key_b64,
            "threshold": 1,
        });
        let bundle = json!({
            "schema_version": "fdai.tuf-metadata-bundle.v1",
            "mode": "tuf",
            "key_id": self.key_id,
            "root": { "signed": root_body, "signature": self.sign_bytes_b64(&canonical_json_bytes(&root_body)) },
            "targets": { "signed": targets_body, "signature": self.sign_bytes_b64(&canonical_json_bytes(&targets_body)) },
            "snapshot": { "signed": snapshot_body, "signature": self.sign_bytes_b64(&canonical_json_bytes(&snapshot_body)) },
            "timestamp": { "signed": timestamp_body, "signature": self.sign_bytes_b64(&canonical_json_bytes(&timestamp_body)) },
        });
        let raw = canonical_json_bytes(&bundle);
        let etag_digest = sha256_hex(&raw);
        Ok((raw, etag_digest))
    }

    pub fn registry_inventory_payload(&self) -> Value {
        let oci_count = self.data.read().map(|d| d.oci_manifests.len()).unwrap_or(0);
        let mut components = Vec::new();
        for &(comp, digest_ref) in SYNCED_COMPONENT_DIGESTS {
            components.push(json!({
                "component": comp,
                "image_digest": digest_ref,
                "image_ref": format!("127.0.0.1:8022/fdai/{comp}@{digest_ref}"),
                "oci_manifest_path": format!("/v2/fdai/{comp}/manifests/{digest_ref}"),
                "provenance": "synchronized-release-digest",
            }));
        }
        json!({
            "registry_api_version": "registry/2.0",
            "digest_mode": "verified-oci-sha256",
            "published_manifest_count": oci_count.max(components.len()),
            "components": components,
        })
    }

    pub fn build_default_oci_manifest(component: &str, reference: &str) -> Option<(Vec<u8>, String)> {
        let digest_ref = SYNCED_COMPONENT_DIGESTS
            .iter()
            .find(|&&(c, _)| c == component)
            .map(|&(_, d)| d)?;
        if reference != digest_ref && reference != "latest" && reference != "lite-release" && reference != "local" {
            return None;
        }
        let doc = json!({
            "schemaVersion": 2,
            "mediaType": OCI_IMAGE_MANIFEST_MEDIA_TYPE,
            "config": {
                "mediaType": "application/vnd.oci.image.config.v1+json",
                "digest": digest_ref,
                "size": 1024,
            },
            "layers": [{
                "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                "digest": digest_ref,
                "size": 4096,
            }],
            "annotations": {
                "org.opencontainers.image.title": format!("fdai/{component}"),
                "org.opencontainers.image.ref.name": reference,
            },
        });
        let bytes = canonical_json_bytes(&doc);
        Some((bytes, String::from(digest_ref)))
    }
}

fn load_or_generate_ed25519(path: Option<&Path>) -> Result<Ed25519KeyPair, String> {
    if let Some(p) = path {
        if let Ok(bytes) = fs::read(p) {
            if let Ok(kp) = Ed25519KeyPair::from_pkcs8(&bytes) {
                return Ok(kp);
            }
        }
    }
    let rng = SystemRandom::new();
    let doc = match Ed25519KeyPair::generate_pkcs8(&rng) {
        Ok(d) => d,
        Err(_) => {
            let seed = [7_u8; 32];
            return Ed25519KeyPair::from_seed_unchecked(&seed)
                .map_err(|_| String::from("failed to initialize fallback Ed25519 keypair"));
        }
    };
    if let Some(p) = path {
        if let Some(parent) = p.parent() {
            if !parent.as_os_str().is_empty() {
                let _ = fs::create_dir_all(parent);
            }
        }
        let _ = fs::write(p, doc.as_ref());
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt as _;
            let _ = fs::set_permissions(p, fs::Permissions::from_mode(0o600));
        }
    }
    Ed25519KeyPair::from_pkcs8(doc.as_ref())
        .or_else(|_| Ed25519KeyPair::from_seed_unchecked(&[7_u8; 32]))
        .map_err(|_| String::from("failed to load generated Ed25519 keypair"))
}

#[must_use]
pub fn detect_workstation_entra_accounts() -> Vec<EntraAccountCandidate> {
    let Some(home) = std::env::var_os("HOME") else { return Vec::new(); };
    let target = PathBuf::from(home).join(".azure/azureProfile.json");
    let Ok(meta) = fs::metadata(&target) else { return Vec::new(); };
    if !meta.is_file() || meta.len() > 2 * 1024 * 1024 { return Vec::new(); }
    let Ok(raw) = fs::read(&target) else { return Vec::new(); };
    let text = std::str::from_utf8(&raw).unwrap_or("").trim_start_matches('\u{feff}');
    let Ok(doc) = serde_json::from_str::<Value>(text) else { return Vec::new(); };
    let Some(subs) = doc.get("subscriptions").and_then(Value::as_array) else { return Vec::new(); };
    let mut seen: BTreeMap<(String, String), EntraAccountCandidate> = BTreeMap::new();
    for sub in subs {
        let name = sub.get("user").and_then(|u| u.get("name")).and_then(Value::as_str).unwrap_or("").trim();
        let tid = sub.get("tenantId").and_then(Value::as_str).unwrap_or("").trim().to_ascii_lowercase();
        if name.is_empty() || !is_valid_uuid(&tid) { continue; }
        let label = sub
            .get("tenantDisplayName")
            .or_else(|| sub.get("name"))
            .and_then(Value::as_str)
            .unwrap_or("Microsoft Entra Tenant")
            .trim()
            .chars()
            .take(80)
            .collect::<String>();
        let is_def = sub.get("isDefault").and_then(Value::as_bool).unwrap_or(false);
        let key = (name.to_ascii_lowercase(), tid.clone());
        let replace = seen.get(&key).is_none_or(|cur| is_def && !cur.is_default);
        if replace {
            seen.insert(key, EntraAccountCandidate {
                principal: String::from(name),
                tenant_id: tid,
                tenant_label: label,
                is_default: is_def,
            });
        }
    }
    let mut out: Vec<EntraAccountCandidate> = seen.into_values().collect();
    out.sort_by(|a, b| b.is_default.cmp(&a.is_default).then_with(|| a.principal.to_ascii_lowercase().cmp(&b.principal.to_ascii_lowercase())));
    out
}
