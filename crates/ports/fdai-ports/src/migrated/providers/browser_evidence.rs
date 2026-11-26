#[derive(Clone, Debug, Default, PartialEq)]
pub struct BrowserCaptureLimits {
    pub max_response_bytes: i64,
    pub max_text_chars: i64,
    pub max_snapshot_chars: i64,
    pub timeout_seconds: f64,
    pub max_screenshot_bytes: i64,
    pub max_selectors: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TrustedBrowserDestination {
    pub scheme: String,
    pub host: String,
    pub path_prefixes: Vec<String>,
    pub port: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BrowserRedirectPolicy {
    pub max_redirects: i64,
    pub trusted_destinations: Vec<TrustedBrowserDestination>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BrowserOriginPolicy {
    pub policy_id: String,
    pub version: i64,
    pub allowed_schemes: Vec<String>,
    pub allowed_hosts: Vec<String>,
    pub allowed_path_prefixes: Vec<String>,
    pub auth_profile_ref: String,
    pub redirect_policy: Box<BrowserRedirectPolicy>,
    pub limits: Box<BrowserCaptureLimits>,
    pub sensitive_region_selectors: Vec<String>,
    pub text_redaction_patterns: Vec<String>,
    pub secret_canary_markers: Vec<String>,
    pub allowed_query_keys: Vec<String>,
    pub retention_days: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BrowserCaptureRequest {
    pub request_id: String,
    pub policy_id: String,
    pub policy_version: i64,
    pub source_url: String,
    pub stable_selectors: Vec<String>,
    pub capture_kinds: Vec<String>,
    pub correlation_id: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BrowserRuntimeIsolation {
    pub executor_identity_present: bool,
    pub host_filesystem_mounted: bool,
    pub environment_scrubbed: bool,
    pub restricted_egress: bool,
    pub ephemeral_profile: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BrowserRedactionEntry {
    pub surface: String,
    pub rule: String,
    pub replacements: i64,
}

impl BrowserRedactionEntry {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.surface.as_str(), "screenshot" | "visible_text" | "aria_snapshot") { return Err("invalid surface literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BrowserCaptureMaterial {
    pub canonical_source_url: String,
    pub canonical_final_url: String,
    #[allow(clippy::type_complexity)]
    pub screenshot: Option<Vec<u8>>,
    pub visible_text: Option<String>,
    pub aria_snapshot: Option<String>,
    pub selectors: Vec<String>,
    pub redacted_selectors: Vec<String>,
    pub redactions: Vec<BrowserRedactionEntry>,
    pub browser_version: String,
    pub isolation: Box<BrowserRuntimeIsolation>,
    pub response_bytes: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BrowserEvidencePayload {
    #[allow(clippy::type_complexity)]
    pub screenshot: Option<Vec<u8>>,
    pub visible_text: Option<String>,
    pub aria_snapshot: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BrowserEvidenceArtifact {
    pub artifact_id: String,
    pub policy_id: String,
    pub policy_version: i64,
    pub canonical_source_url: String,
    pub canonical_final_url: String,
    pub captured_at: String,
    pub selectors: Vec<String>,
    pub screenshot_hash: Option<String>,
    pub text_hash: Option<String>,
    pub snapshot_hash: Option<String>,
    pub redaction_manifest: Vec<BrowserRedactionEntry>,
    pub browser_version: String,
    pub chain_of_custody_audit_ref: String,
    pub content_digest: String,
    pub prompt_injection_findings: Vec<String>,
    pub isolation: Box<BrowserRuntimeIsolation>,
    pub expires_at: String,
    pub untrusted: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct StoredBrowserEvidence {
    pub artifact: Box<BrowserEvidenceArtifact>,
    pub payload: Box<BrowserEvidencePayload>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BrowserEvidenceReceipt {
    pub request_id: String,
    pub status: String,
    pub artifact_id: Option<String>,
    pub content_digest: Option<String>,
    pub chain_of_custody_audit_ref: Option<String>,
    pub reason: Option<String>,
}

impl BrowserEvidenceReceipt {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.status.as_str(), "captured" | "unavailable" | "abstained") { return Err("invalid status literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BrowserEvidenceReference {
    pub kind: String,
    pub status: String,
    pub content_digest: Option<String>,
}

impl BrowserEvidenceReference {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "human" | "api") { return Err("invalid kind literal"); }
        if !matches!(self.status.as_str(), "available" | "unavailable") { return Err("invalid status literal"); }
        Ok(())
    }
}

impl BrowserRuntimeIsolation {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn verified(&self) -> bool {
        (!(self.executor_identity_present)) && ((!(self.host_filesystem_mounted)) && ((self.environment_scrubbed) && ((self.restricted_egress) && (self.ephemeral_profile))))
    }
}

impl BrowserEvidenceArtifact {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn can_authorize_action(&self) -> bool {
        core::hint::black_box(false)
    }
}

pub trait BrowserEvidenceProvider {
    fn capture(&self, policy: BrowserOriginPolicy, request: BrowserCaptureRequest) -> String;
}

pub trait BrowserEvidenceArtifactStore {
    fn put(&self, evidence: StoredBrowserEvidence) -> String;
}

pub trait BrowserEvidenceCustodySink {
    fn record_capture(&self, request_id: String, policy_ref: String, content_digest: String, captured_at: String, correlation_id: String) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn canonical_browser_hostname(mut value: String) -> Result<String, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn browser_path_prefix(mut value: String) -> Result<String, &'static str> {
    if (!((value.clone()).starts_with("/"))) || (((value.clone()).contains("?")) || ((value.clone()).contains("#"))) {
        return Err("browser policy path prefix MUST be an absolute path");
    }
    Ok(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["BrowserCaptureKind", "BrowserCaptureLimits", "BrowserCaptureMaterial", "BrowserCaptureRequest", "BrowserEvidenceArtifact", "BrowserEvidenceArtifactStore", "BrowserEvidenceCustodySink", "BrowserEvidencePayload", "BrowserEvidenceProvider", "BrowserEvidenceReceipt", "BrowserEvidenceReference", "BrowserOriginPolicy", "BrowserReceiptStatus", "BrowserRedactionEntry", "BrowserRedirectPolicy", "BrowserReferenceKind", "BrowserReferenceStatus", "BrowserRuntimeIsolation", "StoredBrowserEvidence", "TrustedBrowserDestination", "canonical_browser_hostname"];
