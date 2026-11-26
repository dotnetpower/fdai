//! Lifecycle Hub transactional state, Ed25519 plan signing, append-only plan events, and hash-chained audit.

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

pub const DEFAULT_RELEASE_HUB_ENDPOINT: &str = "http://127.0.0.1:8022";
pub const MAX_REPORT_BYTES: usize = 16 * 1024;
pub const MAX_ENROLLMENT_BYTES: usize = 64 * 1024;
pub const MAX_STATE_BYTES: usize = 64 * 1024;
pub const MAX_APPROVAL_BYTES: usize = 4 * 1024;
pub const MAX_CATALOG_BYTES: usize = 16 * 1024 * 1024;

#[derive(Clone, Debug)]
pub struct HubError {
    pub status: u16,
    pub code: String,
}

impl HubError {
    #[must_use]
    pub fn new(status: u16, code: impl Into<String>) -> Self {
        Self { status, code: code.into() }
    }
    #[must_use] pub fn not_found(code: impl Into<String>) -> Self { Self::new(404, code) }
    #[must_use] pub fn conflict(code: impl Into<String>) -> Self { Self::new(409, code) }
    #[must_use] pub fn unprocessable(code: impl Into<String>) -> Self { Self::new(422, code) }
    #[must_use] pub fn unavailable(code: impl Into<String>) -> Self { Self::new(503, code) }
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
pub fn is_valid_installation_id(id: &str) -> bool {
    let b = id.as_bytes();
    !b.is_empty()
        && b.len() <= 63
        && b[0].is_ascii_lowercase()
        && b.iter().all(|&c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'-')
}

#[must_use]
pub fn parse_semver(s: &str) -> Option<(u64, u64, u64, String)> {
    let (core, pre) = match s.trim().split_once('-') {
        Some((c, p)) => (c, p.to_string()),
        None => (s.trim(), String::new()),
    };
    let mut parts = core.split('.');
    let maj = parts.next()?.parse::<u64>().ok()?;
    let min = parts.next()?.parse::<u64>().ok()?;
    let pat = parts.next()?.parse::<u64>().ok()?;
    if parts.next().is_some() { return None; }
    Some((maj, min, pat, pre))
}

#[must_use]
pub fn compare_semver(a: &str, b: &str) -> std::cmp::Ordering {
    match (parse_semver(a), parse_semver(b)) {
        (Some((a1, a2, a3, ap)), Some((b1, b2, b3, bp))) => {
            (a1, a2, a3).cmp(&(b1, b2, b3)).then_with(|| match (ap.is_empty(), bp.is_empty()) {
                (true, true) => std::cmp::Ordering::Equal,
                (true, false) => std::cmp::Ordering::Greater,
                (false, true) => std::cmp::Ordering::Less,
                (false, false) => ap.cmp(&bp),
            })
        }
        _ => a.cmp(b),
    }
}

#[must_use]
pub fn semver_matches_range(version: &str, range: &str) -> bool {
    let trimmed = range.trim();
    if trimmed.is_empty() || trimmed == "*" {
        return true;
    }
    let Some((v_maj, v_min, v_pat, _)) = parse_semver(version) else {
        return false;
    };
    for clause in trimmed.split(',').map(str::trim).filter(|c| !c.is_empty()) {
        let ok = if let Some(rest) = clause.strip_prefix(">=") {
            compare_semver(version, rest.trim()) != std::cmp::Ordering::Less
        } else if let Some(rest) = clause.strip_prefix("<=") {
            compare_semver(version, rest.trim()) != std::cmp::Ordering::Greater
        } else if let Some(rest) = clause.strip_prefix('>') {
            compare_semver(version, rest.trim()) == std::cmp::Ordering::Greater
        } else if let Some(rest) = clause.strip_prefix('<') {
            compare_semver(version, rest.trim()) == std::cmp::Ordering::Less
        } else if let Some(rest) = clause.strip_prefix('^') {
            parse_semver(rest.trim()).is_some_and(|(m, n, p, _)| {
                let ge = (v_maj, v_min, v_pat) >= (m, n, p);
                let lt = if m > 0 { v_maj == m } else if n > 0 { v_maj == 0 && v_min == n } else { v_maj == 0 && v_min == 0 && v_pat == p };
                ge && lt
            })
        } else if let Some(rest) = clause.strip_prefix('~') {
            parse_semver(rest.trim()).is_some_and(|(m, n, p, _)| v_maj == m && v_min == n && v_pat >= p)
        } else if let Some(rest) = clause.strip_prefix('=') {
            compare_semver(version, rest.trim()) == std::cmp::Ordering::Equal
        } else {
            compare_semver(version, clause) == std::cmp::Ordering::Equal
        };
        if !ok {
            return false;
        }
    }
    true
}

pub fn parse_strict_json_object(raw: &[u8]) -> Result<Map<String, Value>, HubError> {
    let text = std::str::from_utf8(raw).map_err(|_| HubError::unprocessable("invalid_json"))?;
    check_no_duplicate_json_keys(text)?;
    let parsed: Value = serde_json::from_str(text).map_err(|_| HubError::unprocessable("invalid_json"))?;
    match parsed {
        Value::Object(m) => Ok(m),
        _ => Err(HubError::unprocessable("invalid_json")),
    }
}

fn check_no_duplicate_json_keys(src: &str) -> Result<(), HubError> {
    let bytes = src.as_bytes();
    let mut idx = 0_usize;
    skip_ws(bytes, &mut idx);
    scan_json_val(bytes, &mut idx, 0)
}

fn skip_ws(b: &[u8], i: &mut usize) {
    while *i < b.len() && matches!(b[*i], b' ' | b'\t' | b'\r' | b'\n') { *i += 1; }
}

fn scan_json_str(b: &[u8], i: &mut usize) -> Result<String, HubError> {
    if *i >= b.len() || b[*i] != b'"' { return Err(HubError::unprocessable("invalid_json")); }
    let start = *i;
    *i += 1;
    while *i < b.len() {
        match b[*i] {
            b'\\' => { *i += 2; }
            b'"' => {
                *i += 1;
                let slice = std::str::from_utf8(&b[start..*i]).map_err(|_| HubError::unprocessable("invalid_json"))?;
                return serde_json::from_str::<String>(slice).map_err(|_| HubError::unprocessable("invalid_json"));
            }
            _ => { *i += 1; }
        }
    }
    Err(HubError::unprocessable("invalid_json"))
}

fn scan_json_val(b: &[u8], i: &mut usize, depth: usize) -> Result<(), HubError> {
    if depth > 64 { return Err(HubError::unprocessable("json_too_deep")); }
    skip_ws(b, i);
    if *i >= b.len() { return Err(HubError::unprocessable("invalid_json")); }
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
                    return Err(HubError::unprocessable("duplicate_json_key"));
                }
                skip_ws(b, i);
                if *i >= b.len() || b[*i] != b':' { return Err(HubError::unprocessable("invalid_json")); }
                *i += 1;
                scan_json_val(b, i, depth + 1)?;
                skip_ws(b, i);
                if *i < b.len() && b[*i] == b',' { *i += 1; continue; }
                if *i < b.len() && b[*i] == b'}' { *i += 1; return Ok(()); }
                return Err(HubError::unprocessable("invalid_json"));
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
                return Err(HubError::unprocessable("invalid_json"));
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
pub struct MaintenanceWindow {
    pub start: String,
    pub duration_minutes: u32,
    pub timezone: String,
    pub allows_downtime: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EntityRecord {
    pub entity_id: String,
    pub kind: String,
    pub managed: bool,
    pub ownership_gap: Option<String>,
    pub release_id: Option<String>,
    pub health: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SuppressionRecord {
    pub scope: String,
    pub starts_at: String,
    pub ends_at: String,
    pub origin: String,
    pub failed_plan_id: Option<String>,
    #[serde(default)]
    pub lifted: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PlanEventRecord {
    pub kind: String,
    pub recorded_at: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CandidateCheckRecord {
    pub release_id: String,
    pub blocks: Vec<Value>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EvaluationRecord {
    pub outcome: String,
    pub target_release_id: Option<String>,
    pub plan_id: Option<String>,
    pub checks: Vec<CandidateCheckRecord>,
    pub evaluated_at: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PlanReportRecord {
    pub plan_id: String,
    pub attempt: u64,
    pub outcome: String,
    pub reason_code: String,
    pub exact_plan_digest: Option<String>,
    pub summary: String,
    pub reported_at: String,
    pub received_at: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PlanRecord {
    pub plan_id: String,
    pub installation_id: String,
    pub sequence: u64,
    pub plan_type: String,
    pub target_release_id: String,
    pub source_state_digest: String,
    pub configuration_digest: String,
    pub hub_key_id: String,
    pub entity_ids: Vec<String>,
    pub expires_at: String,
    pub exact_plan_digest: String,
    pub signature: String,
    pub events: Vec<PlanEventRecord>,
    pub evaluations: Vec<EvaluationRecord>,
    pub reports: Vec<PlanReportRecord>,
}

impl PlanRecord {
    /// A Plan is open if and only if it has NO `SUPERSEDED` event (append-only event invariant).
    #[must_use]
    pub fn is_open(&self) -> bool {
        !self.events.iter().any(|e| e.kind == "SUPERSEDED")
    }

    #[must_use]
    pub fn derived_status(&self) -> &'static str {
        if self.is_open() { "open" } else { "superseded" }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PendingEnrollmentRecord {
    pub installation_id: String,
    pub installation_key_id: String,
    pub requested_at: String,
    pub request_id: Option<String>,
    pub requested_by: Option<String>,
    pub requested_via: Option<String>,
    pub channel: String,
    pub version_range: String,
    pub region: String,
    pub allowed_regions: Vec<String>,
    pub entities: Vec<EntityRecord>,
    pub reported_at: String,
    pub schema_revision: u64,
    pub configuration_digest: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct InstallationRecord {
    pub installation_id: String,
    pub enrollment: String,
    pub installation_key_id: String,
    pub channel: String,
    pub version_range: String,
    pub region: String,
    pub allowed_regions: Vec<String>,
    pub windows: Vec<MaintenanceWindow>,
    pub plan_duration_minutes: u32,
    pub product: Option<String>,
    pub settings_digest: String,
    pub configuration_digest: String,
    pub reported_at: String,
    pub schema_revision: u64,
    pub current_release: Option<String>,
    pub health: Option<String>,
    pub entities: Vec<EntityRecord>,
    pub suppressions: Vec<SuppressionRecord>,
    pub last_evaluation: Option<EvaluationRecord>,
    pub plan_sequence: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct AuditRecord {
    pub sequence: u64,
    pub recorded_at: String,
    pub action: String,
    pub installation_id: String,
    pub subject: String,
    pub previous_hash: String,
    pub record_hash: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LifecycleCommandRecord {
    pub command_id: String,
    pub installation_id: String,
    pub kind: String,
    pub actor: String,
    pub reason: String,
    pub scope: String,
    pub starts_at: String,
    pub expires_at: String,
    pub target_action_type: Option<String>,
    pub target_mode: Option<String>,
    pub target_autonomy: Option<String>,
    pub engage_kill_switch: bool,
    pub bypass_scopes: Vec<String>,
    pub override_count: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct DestructiveConfirmationRecord {
    pub installation_id: String,
    pub plan_id: String,
    pub exact_plan_digest: String,
    pub change_kind: String,
    pub title: String,
    pub summary: String,
    pub impact: String,
    pub replace_count: u64,
    pub delete_count: u64,
    pub affected_addresses: Vec<String>,
    pub foundation_ownership_verified: bool,
    pub within_local_envelope: bool,
    pub dry_run_succeeded: bool,
    pub status: String,
    pub created_at: String,
    pub decided_by: Option<String>,
    pub decided_at: Option<String>,
    pub decision_reason: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct BundleImportRecord {
    pub bundle_id: String,
    pub extends_bundle_id: Option<String>,
    pub catalog_export_sha256: String,
    pub imported_at: String,
    pub operator: String,
    pub verification: Value,
    pub contents: Value,
    pub recall_sequence_end: u64,
    pub metadata_expiry_days: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct AcceptedCatalogRelease {
    pub release_id: String,
    pub digest: String,
    pub source_commit: String,
    pub platform_tag: String,
    pub channels: Vec<String>,
    pub schema_target: Option<u64>,
    pub schema_range: Option<Value>,
    pub images: Vec<Value>,
    pub recall_notices: Vec<Value>,
    #[serde(default)]
    pub recalled: bool,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct CatalogTrustState {
    pub trusted_key_id: Option<String>,
    pub trusted_public_key_b64: Option<String>,
    pub approved_by: Option<String>,
    pub approved_at: Option<String>,
    pub root_version: u64,
    pub snapshot_version: u64,
    pub timestamp_version: u64,
    pub max_recall_sequence: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct AcceptedCatalogState {
    pub revision: u64,
    pub sha256: String,
    pub expires_at: String,
    pub releases: Vec<AcceptedCatalogRelease>,
    pub channels: BTreeMap<String, Vec<String>>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ReleaseHubConnectionState {
    pub endpoint: String,
    pub configured_endpoint: Option<String>,
    pub revision: u64,
    pub source: String,
    pub editable: bool,
    pub requires_migration: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PersistedLifecycleHubData {
    pub installations: BTreeMap<String, InstallationRecord>,
    pub pending_enrollments: BTreeMap<String, PendingEnrollmentRecord>,
    pub plans: BTreeMap<String, PlanRecord>,
    pub audit_records: Vec<AuditRecord>,
    pub commands: Vec<LifecycleCommandRecord>,
    pub confirmations: Vec<DestructiveConfirmationRecord>,
    pub bundle_imports: Vec<BundleImportRecord>,
    pub release_connection: ReleaseHubConnectionState,
    pub catalog_trust: CatalogTrustState,
    pub accepted_catalog: Option<AcceptedCatalogState>,
    pub pending_candidate_export: Option<Value>,
    pub last_update_check: Option<Value>,
    pub update_events: Vec<Value>,
    pub local_channels: BTreeMap<String, Vec<String>>,
    pub configuration_keys: BTreeMap<String, Value>,
    pub configurations: BTreeMap<String, Value>,
    pub native_ownership: BTreeMap<String, Value>,
    pub stencil_states: BTreeMap<String, Value>,
    #[serde(default)]
    pub entitlement_handoffs: BTreeMap<String, Value>,
}

impl PersistedLifecycleHubData {
    #[must_use]
    pub fn fresh(default_endpoint: String, source: String) -> Self {
        Self {
            installations: BTreeMap::new(),
            pending_enrollments: BTreeMap::new(),
            plans: BTreeMap::new(),
            audit_records: Vec::new(),
            commands: Vec::new(),
            confirmations: Vec::new(),
            bundle_imports: Vec::new(),
            release_connection: ReleaseHubConnectionState {
                endpoint: default_endpoint,
                configured_endpoint: None,
                revision: 0,
                source,
                editable: true,
                requires_migration: false,
            },
            catalog_trust: CatalogTrustState::default(),
            accepted_catalog: None,
            pending_candidate_export: None,
            last_update_check: None,
            update_events: Vec::new(),
            local_channels: BTreeMap::new(),
            configuration_keys: BTreeMap::new(),
            configurations: BTreeMap::new(),
            native_ownership: BTreeMap::new(),
            stencil_states: BTreeMap::new(),
            entitlement_handoffs: BTreeMap::new(),
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ActiveEntraSession {
    pub principal: String,
    pub display_name: String,
    pub tenant_id: String,
    pub auth_method: String,
    pub signed_in_at: String,
}

fn encode_ed25519_spki_pem(pub_bytes: &[u8]) -> String {
    if pub_bytes.len() != 32 { return String::new(); }
    const SPKI_PREFIX: [u8; 12] = [0x30, 0x2a, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x70, 0x03, 0x21, 0x00];
    let mut der = Vec::with_capacity(44);
    der.extend_from_slice(&SPKI_PREFIX);
    der.extend_from_slice(pub_bytes);
    let b64 = B64.encode(&der);
    format!("-----BEGIN PUBLIC KEY-----\n{b64}\n-----END PUBLIC KEY-----\n")
}

#[must_use]
pub fn parse_rfc3339_to_unix(s: &str) -> Option<u64> {
    let clean = s.trim().strip_suffix('Z').unwrap_or(s.trim());
    let (date_p, time_p) = clean.split_once('T')?;
    let mut dp = date_p.split('-');
    let y = dp.next()?.parse::<i64>().ok()?;
    let m = dp.next()?.parse::<i64>().ok()?;
    let d = dp.next()?.parse::<i64>().ok()?;
    let time_core = time_p.split('.').next()?.split('+').next()?;
    let mut tp = time_core.split(':');
    let hh = tp.next()?.parse::<u64>().ok()?;
    let mm = tp.next()?.parse::<u64>().ok()?;
    let ss = tp.next()?.parse::<u64>().ok()?;
    let yr = if m <= 2 { y - 1 } else { y };
    let era = if yr >= 0 { yr } else { yr - 399 } / 400;
    let yoe = (yr - era * 400) as u64;
    let mp = if m > 2 { (m - 3) as u64 } else { (m + 9) as u64 };
    let doy = (153 * mp + 2) / 5 + (d as u64) - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    let days = era * 146_097 + (doe as i64) - 719_468;
    if days < 0 { return None; }
    Some((days as u64) * 86_400 + hh * 3600 + mm * 60 + ss)
}

#[must_use]
pub fn add_minutes_rfc3339(start: &str, mins: u32) -> String {
    match parse_rfc3339_to_unix(start) {
        Some(u) => format_unix_rfc3339(u.saturating_add(u64::from(mins) * 60)),
        None => start.to_string(),
    }
}

pub struct LifecycleHubState {
    pub state_path: Option<PathBuf>,
    pub pg_ledger: Option<fdai_http_runtime::HubPgLedger>,
    pub remote_policy: fdai_http_runtime::HubRemotePolicy,
    pub authenticator: fdai_http_runtime::OperatorAuthenticator,
    pub op_semaphore: Arc<tokio::sync::Semaphore>,
    pub hub_key_id: String,
    pub hub_public_key_b64: String,
    pub hub_public_key_pem: String,
    pub hub_public_key_bytes: Vec<u8>,
    keypair: Option<Ed25519KeyPair>,
    pub data: RwLock<PersistedLifecycleHubData>,
    pub entra_session: RwLock<Option<ActiveEntraSession>>,
}

impl LifecycleHubState {
    #[must_use]
    pub fn open_from_env() -> Arc<Self> {
        let state_path = std::env::var("FDAI_LIFECYCLE_HUB_STATE_PATH")
            .ok()
            .filter(|s| !s.trim().is_empty())
            .map(PathBuf::from)
            .or_else(|| Some(PathBuf::from(".fdai/lifecycle-hub-state.json")));
        let key_path = std::env::var("FDAI_LIFECYCLE_HUB_KEY_FILE")
            .ok()
            .filter(|s| !s.trim().is_empty())
            .map(PathBuf::from)
            .or_else(|| Some(PathBuf::from(".fdai/lifecycle-hub-ed25519.pkcs8")));
        let (ep, src) = match std::env::var("FDAI_RELEASE_HUB_ENDPOINT") {
            Ok(v) if !v.trim().is_empty() => (v.trim().trim_end_matches('/').to_string(), String::from("environment")),
            _ => (String::from(DEFAULT_RELEASE_HUB_ENDPOINT), String::from("local-default")),
        };
        let pg_ledger = fdai_http_runtime::HubPgLedger::from_env("hub");
        let remote_policy = fdai_http_runtime::HubRemotePolicy::from_env("hub");
        let st = Self::open_with_config(state_path, key_path, ep, src, pg_ledger, remote_policy);
        if let Ok(handle) = tokio::runtime::Handle::try_current() {
            let st_bg = Arc::clone(&st);
            handle.spawn(async move {
                st_bg.hydrate_from_pg_if_configured().await;
            });
            Self::spawn_background_update_poller(Arc::clone(&st));
        }
        st
    }

    #[must_use]
    pub fn open_ephemeral(release_hub_endpoint: &str) -> Arc<Self> {
        Self::open_with_config(
            None,
            None,
            release_hub_endpoint.to_string(),
            String::from("local-default"),
            None,
            fdai_http_runtime::HubRemotePolicy::from_env("hub"),
        )
    }

    #[must_use]
    pub fn open_with_paths(
        state_path: Option<PathBuf>,
        key_path: Option<PathBuf>,
        default_endpoint: String,
        source: String,
    ) -> Arc<Self> {
        Self::open_with_config(
            state_path,
            key_path,
            default_endpoint,
            source,
            None,
            fdai_http_runtime::HubRemotePolicy::from_env("hub"),
        )
    }

    #[must_use]
    pub fn open_with_config(
        state_path: Option<PathBuf>,
        key_path: Option<PathBuf>,
        default_endpoint: String,
        source: String,
        pg_ledger: Option<fdai_http_runtime::HubPgLedger>,
        remote_policy: fdai_http_runtime::HubRemotePolicy,
    ) -> Arc<Self> {
        let keypair = load_or_generate_ed25519(key_path.as_deref()).ok();
        let pub_bytes = keypair.as_ref().map(|k| k.public_key().as_ref().to_vec()).unwrap_or_default();
        let hub_key_id = sha256_hex(&pub_bytes).chars().take(16).collect::<String>();
        let hub_public_key_b64 = B64.encode(&pub_bytes);
        let hub_public_key_pem = encode_ed25519_spki_pem(&pub_bytes);
        let data = state_path
            .as_deref()
            .and_then(|p| fs::read(p).ok())
            .and_then(|b| serde_json::from_slice::<PersistedLifecycleHubData>(&b).ok())
            .unwrap_or_else(|| PersistedLifecycleHubData::fresh(default_endpoint, source));
        let authenticator = fdai_http_runtime::OperatorAuthenticator::from_env()
            .unwrap_or_else(|_| fdai_http_runtime::OperatorAuthenticator::new(fdai_http_runtime::AuthMode::FailClosedUnconfigured));
        Arc::new(Self {
            state_path,
            pg_ledger,
            remote_policy,
            authenticator,
            op_semaphore: Arc::new(tokio::sync::Semaphore::new(16)),
            hub_key_id,
            hub_public_key_b64,
            hub_public_key_pem,
            hub_public_key_bytes: pub_bytes,
            keypair,
            data: RwLock::new(data),
            entra_session: RwLock::new(None),
        })
    }

    pub async fn hydrate_from_pg_if_configured(&self) {
        let Some(ref pg) = self.pg_ledger else { return; };
        if let Ok(Some(raw)) = pg.load_state_json().await {
            if let Ok(loaded) = serde_json::from_str::<PersistedLifecycleHubData>(&raw) {
                if let Ok(mut guard) = self.data.write() {
                    if loaded.audit_records.len() >= guard.audit_records.len() {
                        *guard = loaded;
                    }
                }
            }
        }
    }

    pub fn spawn_background_update_poller(st: Arc<Self>) {
        let Some(interval_secs) = std::env::var("FDAI_LIFECYCLE_HUB_UPDATE_CHECK_SECONDS")
            .ok()
            .and_then(|v| v.parse::<u64>().ok())
            .filter(|&s| s >= 1)
        else {
            return;
        };
        if let Ok(handle) = tokio::runtime::Handle::try_current() {
            handle.spawn(async move {
                let mut ticker = tokio::time::interval(std::time::Duration::from_secs(interval_secs));
                ticker.tick().await;
                loop {
                    ticker.tick().await;
                    let _ = crate::hub_routes::execute_live_update_check(&st).await;
                }
            });
        }
    }

    #[must_use]
    pub fn sign_b64(&self, msg: &[u8]) -> String {
        self.keypair
            .as_ref()
            .map(|k| B64.encode(k.sign(msg).as_ref()))
            .unwrap_or_default()
    }

    pub fn verify_ed25519_b64(pub_b64: &str, msg: &[u8], sig_b64: &str) -> bool {
        let (Ok(pk), Ok(sig)) = (B64.decode(pub_b64), B64.decode(sig_b64)) else {
            return false;
        };
        UnparsedPublicKey::new(&ED25519, &pk).verify(msg, &sig).is_ok()
    }

    pub fn persist(&self, data: &PersistedLifecycleHubData) -> Result<(), HubError> {
        let Some(ref path) = self.state_path else { return Ok(()); };
        if let Some(parent) = path.parent() {
            if !parent.as_os_str().is_empty() {
                fs::create_dir_all(parent).map_err(|_| HubError::unavailable("storage_unavailable"))?;
            }
        }
        let encoded = serde_json::to_vec_pretty(data)
            .map_err(|_| HubError::unavailable("storage_unavailable"))?;
        let tmp = path.with_extension(format!("json.tmp.{}", std::process::id()));
        {
            use std::io::Write as _;
            let mut file = fs::File::create(&tmp).map_err(|_| HubError::unavailable("storage_unavailable"))?;
            file.write_all(&encoded).map_err(|_| HubError::unavailable("storage_unavailable"))?;
            file.sync_all().map_err(|_| HubError::unavailable("storage_unavailable"))?;
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt as _;
            let _ = fs::set_permissions(&tmp, fs::Permissions::from_mode(0o600));
        }
        fs::rename(&tmp, path).map_err(|_| HubError::unavailable("storage_unavailable"))?;
        if let Some(ref pg) = self.pg_ledger {
            let pg_clone = pg.clone();
            let rev = data.audit_records.len() as u64;
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

    pub fn append_audit(
        data: &mut PersistedLifecycleHubData,
        action: &str,
        installation_id: &str,
        subject: &str,
    ) {
        let seq = data.audit_records.len() as u64 + 1;
        let prev = data
            .audit_records
            .last()
            .map_or_else(|| "0".repeat(64), |r| r.record_hash.clone());
        let now_s = format_utc_rfc3339_now();
        let material = format!("{seq}|{now_s}|{action}|{installation_id}|{subject}|{prev}");
        let rec_hash = sha256_hex(material.as_bytes());
        data.audit_records.push(AuditRecord {
            sequence: seq,
            recorded_at: now_s,
            action: action.to_string(),
            installation_id: installation_id.to_string(),
            subject: subject.to_string(),
            previous_hash: prev,
            record_hash: rec_hash,
        });
    }

    #[must_use]
    pub fn verify_audit_chain(records: &[AuditRecord]) -> bool {
        let mut expected_prev = "0".repeat(64);
        for (idx, r) in records.iter().enumerate() {
            if r.sequence != (idx as u64 + 1) || r.previous_hash != expected_prev {
                return false;
            }
            let mat = format!("{}|{}|{}|{}|{}|{}", r.sequence, r.recorded_at, r.action, r.installation_id, r.subject, r.previous_hash);
            if sha256_hex(mat.as_bytes()) != r.record_hash {
                return false;
            }
            expected_prev.clone_from(&r.record_hash);
        }
        true
    }

    #[must_use]
    pub fn current_actor(&self) -> String {
        self.entra_session
            .read()
            .ok()
            .and_then(|g| g.as_ref().map(|s| s.principal.clone()))
            .unwrap_or_else(|| String::from("local-operator"))
    }

    /// Supersede any open plans for an installation by appending a `SUPERSEDED` event (never mutating status).
    pub fn supersede_open_plans(data: &mut PersistedLifecycleHubData, installation_id: &str, now_s: &str) -> usize {
        let mut count = 0_usize;
        for plan in data.plans.values_mut() {
            if plan.installation_id == installation_id && plan.is_open() {
                plan.events.push(PlanEventRecord {
                    kind: String::from("SUPERSEDED"),
                    recorded_at: now_s.to_string(),
                });
                count += 1;
            }
        }
        count
    }

    /// Deterministically evaluate eligible releases and issue or withdraw plans for an installation.
    pub fn evaluate_and_plan_locked(
        &self,
        data: &mut PersistedLifecycleHubData,
        installation_id: &str,
    ) -> Result<EvaluationRecord, HubError> {
        let Some(inst) = data.installations.get(installation_id).cloned() else {
            return Err(HubError::not_found("unknown_installation"));
        };
        let now_u = now_unix_secs();
        let now_s = format_unix_rfc3339(now_u);
        let managed_ids: Vec<String> = inst.entities.iter().filter(|e| e.managed).map(|e| e.entity_id.clone()).collect();
        if managed_ids.is_empty() {
            Self::supersede_open_plans(data, installation_id, &now_s);
            let eval = EvaluationRecord {
                outcome: String::from("no-managed-entity"),
                target_release_id: None,
                plan_id: None,
                checks: Vec::new(),
                evaluated_at: now_s,
            };
            if let Some(slot) = data.installations.get_mut(installation_id) {
                slot.last_evaluation = Some(eval.clone());
            }
            return Ok(eval);
        }

        let active_suppression = inst.suppressions.iter().any(|s| !s.lifted && s.ends_at.as_str() > now_s.as_str());
        let mut checks = Vec::new();
        let mut chosen: Option<AcceptedCatalogRelease> = None;

        if let Some(ref cat) = data.accepted_catalog {
            let mut candidates: Vec<AcceptedCatalogRelease> = cat
                .releases
                .iter()
                .filter(|r| {
                    r.channels.iter().any(|c| c == &inst.channel)
                        || data.local_channels.get(&inst.channel).is_some_and(|ids| ids.contains(&r.release_id))
                })
                .cloned()
                .collect();
            candidates.sort_by(|a, b| compare_semver(&b.release_id, &a.release_id));
            for cand in candidates {
                let mut blocks = Vec::new();
                if cand.recalled {
                    blocks.push(json!({"reason_code": "release_recalled", "details": [cand.release_id]}));
                }
                if !semver_matches_range(&cand.release_id, &inst.version_range) {
                    blocks.push(json!({"reason_code": "version_range_mismatch", "details": [format!("{} not in {}", cand.release_id, inst.version_range)]}));
                }
                if active_suppression {
                    blocks.push(json!({"reason_code": "suppression_active", "details": ["active suppression window"]}));
                }
                if !inst.allowed_regions.is_empty() && !inst.allowed_regions.contains(&inst.region) {
                    blocks.push(json!({"reason_code": "region_not_allowed", "details": [inst.region]}));
                }
                if let Some(target_schema) = cand.schema_target {
                    if target_schema < inst.schema_revision {
                        blocks.push(json!({"reason_code": "schema_downgrade_blocked", "details": [format!("{target_schema} < {}", inst.schema_revision)]}));
                    }
                }
                let ok = blocks.is_empty();
                checks.push(CandidateCheckRecord { release_id: cand.release_id.clone(), blocks });
                if ok && chosen.is_none() {
                    chosen = Some(cand);
                }
            }
        }

        let Some(target) = chosen else {
            if active_suppression {
                Self::supersede_open_plans(data, installation_id, &now_s);
            }
            let outcome = if active_suppression { "waiting" } else { "no-eligible-release" };
            let eval = EvaluationRecord {
                outcome: String::from(outcome),
                target_release_id: None,
                plan_id: None,
                checks,
                evaluated_at: now_s,
            };
            if let Some(slot) = data.installations.get_mut(installation_id) {
                slot.last_evaluation = Some(eval.clone());
            }
            return Ok(eval);
        };

        if inst.current_release.as_deref() == Some(target.release_id.as_str()) {
            Self::supersede_open_plans(data, installation_id, &now_s);
            let eval = EvaluationRecord {
                outcome: String::from("up-to-date"),
                target_release_id: Some(target.release_id),
                plan_id: None,
                checks,
                evaluated_at: now_s,
            };
            if let Some(slot) = data.installations.get_mut(installation_id) {
                slot.last_evaluation = Some(eval.clone());
            }
            return Ok(eval);
        }

        if let Some(existing_open) = data.plans.values().find(|p| p.installation_id == installation_id && p.is_open() && p.target_release_id == target.release_id) {
            let eval = EvaluationRecord {
                outcome: String::from("unchanged"),
                target_release_id: Some(target.release_id),
                plan_id: Some(existing_open.plan_id.clone()),
                checks,
                evaluated_at: now_s,
            };
            if let Some(slot) = data.installations.get_mut(installation_id) {
                slot.last_evaluation = Some(eval.clone());
            }
            return Ok(eval);
        }

        Self::supersede_open_plans(data, installation_id, &now_s);
        let next_seq = inst.plan_sequence + 1;
        let plan_id = format!("plan-{installation_id}-{next_seq}");
        let expires_at = format_unix_rfc3339(now_u.saturating_add(u64::from(inst.plan_duration_minutes.max(15)) * 60));
        let source_state_digest = sha256_hex(format!("{installation_id}|{}|{}", inst.reported_at, inst.schema_revision).as_bytes());
        let plan_payload = json!({
            "plan_id": plan_id,
            "installation_id": installation_id,
            "sequence": next_seq,
            "plan_type": "upgrade",
            "target_release_id": target.release_id,
            "source_state_digest": source_state_digest,
            "configuration_digest": inst.configuration_digest,
            "hub_key_id": self.hub_key_id,
            "entity_ids": managed_ids,
            "expires_at": expires_at,
        });
        let canonical = canonical_json_bytes(&plan_payload);
        let exact_plan_digest = sha256_hex(&canonical);
        let sig = self.sign_b64(&canonical);
        let eval = EvaluationRecord {
            outcome: String::from("issued"),
            target_release_id: Some(target.release_id.clone()),
            plan_id: Some(plan_id.clone()),
            checks,
            evaluated_at: now_s.clone(),
        };
        let plan = PlanRecord {
            plan_id: plan_id.clone(),
            installation_id: installation_id.to_string(),
            sequence: next_seq,
            plan_type: String::from("upgrade"),
            target_release_id: target.release_id,
            source_state_digest,
            configuration_digest: inst.configuration_digest,
            hub_key_id: self.hub_key_id.clone(),
            entity_ids: managed_ids,
            expires_at,
            exact_plan_digest,
            signature: sig,
            events: vec![PlanEventRecord { kind: String::from("ISSUED"), recorded_at: now_s }],
            evaluations: vec![eval.clone()],
            reports: Vec::new(),
        };
        data.plans.insert(plan_id.clone(), plan);
        if let Some(slot) = data.installations.get_mut(installation_id) {
            slot.plan_sequence = next_seq;
            slot.last_evaluation = Some(eval.clone());
        }
        Self::append_audit(data, "plan_issued", installation_id, &plan_id);
        Ok(eval)
    }

    #[must_use]
    pub fn build_installation_summary(data: &PersistedLifecycleHubData, inst: &InstallationRecord) -> Value {
        let open_plan = data.plans.values().find(|p| p.installation_id == inst.installation_id && p.is_open());
        let first_win = inst.windows.first();
        let now_s = format_utc_rfc3339_now();
        let win_end = first_win.map(|w| add_minutes_rfc3339(&w.start, w.duration_minutes));
        let win_open = match (first_win, win_end.as_deref()) {
            (Some(w), Some(end)) => w.start.as_str() <= now_s.as_str() && now_s.as_str() < end,
            _ => false,
        };
        json!({
            "installation_id": inst.installation_id,
            "channel": inst.channel,
            "version_range": inst.version_range,
            "current_release": inst.current_release,
            "target_release_id": open_plan.map(|p| p.target_release_id.as_str()).or_else(|| inst.last_evaluation.as_ref().and_then(|e| e.target_release_id.as_deref())),
            "outcome": inst.last_evaluation.as_ref().map(|e| e.outcome.as_str()),
            "health": inst.health,
            "next_window_starts_at": first_win.map(|w| w.start.as_str()),
            "next_window_ends_at": win_end,
            "next_window_open": win_open,
            "last_evaluated_at": inst.last_evaluation.as_ref().map(|e| e.evaluated_at.as_str()),
        })
    }

    #[must_use]
    pub fn build_installation_detail(data: &PersistedLifecycleHubData, inst: &InstallationRecord) -> Value {
        let open_plan = data.plans.values().find(|p| p.installation_id == inst.installation_id && p.is_open()).map(|p| {
            json!({
                "plan_id": p.plan_id,
                "sequence": p.sequence,
                "target_release_id": p.target_release_id,
                "expires_at": p.expires_at,
            })
        });
        let mut reports: Vec<&PlanReportRecord> = data
            .plans
            .values()
            .filter(|p| p.installation_id == inst.installation_id)
            .flat_map(|p| p.reports.iter())
            .collect();
        reports.sort_by(|a, b| b.received_at.cmp(&a.received_at));
        let active_supps: Vec<&SuppressionRecord> = inst.suppressions.iter().filter(|s| !s.lifted).collect();
        json!({
            "installation_id": inst.installation_id,
            "enrollment": inst.enrollment,
            "console_url": Value::Null,
            "settings": {
                "channel": inst.channel,
                "version_range": inst.version_range,
                "region": inst.region,
                "allowed_regions": inst.allowed_regions,
                "windows": inst.windows,
            },
            "configuration_digest": inst.configuration_digest,
            "reported_at": inst.reported_at,
            "schema_revision": inst.schema_revision,
            "current_release": inst.current_release,
            "health": inst.health,
            "entities": inst.entities,
            "suppressions": active_supps,
            "open_plan": open_plan,
            "last_evaluation": inst.last_evaluation,
            "reports": reports,
        })
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
            return Ed25519KeyPair::from_seed_unchecked(&[9_u8; 32])
                .map_err(|_| String::from("fallback ed25519 failed"));
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
        .or_else(|_| Ed25519KeyPair::from_seed_unchecked(&[9_u8; 32]))
        .map_err(|_| String::from("ed25519 init failed"))
}

#[must_use]
pub fn compute_settings_digest(product: Option<&str>, windows: &[MaintenanceWindow], plan_dur: u32) -> String {
    let val = json!({"product": product, "windows": windows, "plan_duration_minutes": plan_dur});
    sha256_hex(&canonical_json_bytes(&val))
}

#[must_use]
pub fn detect_workstation_accounts() -> Vec<Value> {
    let Some(home) = std::env::var_os("HOME") else { return Vec::new(); };
    let target = PathBuf::from(home).join(".azure/azureProfile.json");
    let Ok(meta) = fs::metadata(&target) else { return Vec::new(); };
    if !meta.is_file() || meta.len() > 2 * 1024 * 1024 { return Vec::new(); }
    let Ok(raw) = fs::read(&target) else { return Vec::new(); };
    let text = std::str::from_utf8(&raw).unwrap_or("").trim_start_matches('\u{feff}');
    let Ok(doc) = serde_json::from_str::<Value>(text) else { return Vec::new(); };
    let Some(subs) = doc.get("subscriptions").and_then(Value::as_array) else { return Vec::new(); };
    let mut seen: BTreeSet<String> = BTreeSet::new();
    let mut out = Vec::new();
    for sub in subs {
        let name = sub.get("user").and_then(|u| u.get("name")).and_then(Value::as_str).unwrap_or("").trim();
        let tid = sub.get("tenantId").and_then(Value::as_str).unwrap_or("").trim().to_ascii_lowercase();
        if name.is_empty() || tid.len() != 36 { continue; }
        let key = format!("{}|{}", name.to_ascii_lowercase(), tid);
        if seen.insert(key) {
            let lbl = sub.get("tenantDisplayName").or_else(|| sub.get("name")).and_then(Value::as_str).unwrap_or("Microsoft Entra Tenant");
            out.push(json!({
                "principal": name,
                "tenant_id": tid,
                "tenant_label": lbl,
                "is_default": sub.get("isDefault").and_then(Value::as_bool).unwrap_or(false),
            }));
        }
    }
    out
}
