use std::collections::BTreeMap;
pub const MAX_ATTEMPTS: i64 = 3;
pub const CLAIM_RENEWAL_SECONDS: i64 = 20;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ScanRequest {
    pub request_id: String,
    pub repository_alias: String,
    pub r#ref: Option<String>,
    pub principal_roles: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ClaimedScanRequest {
    pub key: String,
    pub claim_id: String,
    #[allow(clippy::type_complexity)]
    pub request: Option<Box<ScanRequest>>,
    pub attempt: i64,
    pub operation: String,
    pub change: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ScanOutcome {
    pub package: BTreeMap<String, String>,
    #[allow(clippy::type_complexity)]
    pub issues: Vec<BTreeMap<String, String>>,
    pub issues_truncated: bool,
    #[allow(clippy::type_complexity)]
    pub artifacts: Option<BTreeMap<String, String>>,
}

pub const SCAN_REQUEST_OPERATION: &str = "code_security.scan_request";
pub const REQUESTER_ROLES: &[&str] = &["Contributor", "Owner"];
pub const ALIAS: &str = "^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$";
pub const REQUEST_ID: &str = "^operator-[0-9a-f]{32}$";
pub const REJECT_MALFORMED: &str = "request_malformed";
pub const REJECT_ROLE: &str = "requester_role_insufficient";
pub const REJECT_UNREGISTERED: &str = "repository_not_registered";
pub const REJECT_DISABLED: &str = "repository_disabled";
pub const REJECT_SOURCE: &str = "source_unavailable";
pub const REJECT_SCAN: &str = "scan_failed";
pub const REJECT_CONFLICT: &str = "review_conflict";
pub const REJECT_ATTEMPTS: &str = "attempts_exhausted";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ScanRequestClaimLostError {
    pub message: String,
}

impl ScanRequestClaimLostError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ScanRequestClaimLostError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ScanRequestClaimLostError {}

pub trait ScanRequestQueue {
    fn claim(&self) -> String;
}

pub trait ReviewPublisher {
    fn publish_code_security_drift(&self, package: std::collections::BTreeMap<String, String>) -> Option<String>;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn parse_scan_request(mut record: std::collections::BTreeMap<String, String>) -> Option<ScanRequest> {
    if ((record.clone()).get("operation").cloned()) != Some(String::from(SCAN_REQUEST_OPERATION)) {
        return None;
    }
    let request_id: Option<String> = (record.clone()).get("proposal_id").cloned();
    let envelope: Option<String> = (record.clone()).get("payload").cloned();
    if !(true) {
        return None;
    }
    Some(ScanRequest { request_id: (request_id.clone()).unwrap_or_default(), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn scan_result_summary(mut package: std::collections::BTreeMap<String, String>) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("revision"), String::new()), (String::from("review_digest"), String::new()), (String::from("decision"), String::new()), (String::from("issue_count"), String::new()), (String::from("coverage_complete"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn process_scan_requests(mut queue: String, mut store: String, mut runner: String, mut recorder: String, mut publisher: Option<String>, mut max_requests: i64) -> Result<Vec<std::collections::BTreeMap<String, String>>, &'static str> {
    if !(((1_i64) <= (max_requests)) && ((max_requests) <= (20_i64))) {
        return Err("max_requests MUST be in 1 20");
    }
    let mut outcomes: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
    Ok(outcomes.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn process_with_renewal(mut claim: ClaimedScanRequest, mut queue: String, mut store: String, mut runner: String, mut recorder: String, mut publisher: Option<String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn reject(mut queue: String, mut claim: ClaimedScanRequest, mut reason: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::from([(String::from("request_id"), String::new()), (String::from("status"), String::from("rejected")), (String::from("reason_code"), reason.clone())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn process_change(mut claim: ClaimedScanRequest, mut queue: String, mut store: String, mut runner: String, mut recorder: String, mut publisher: Option<String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let change: Option<String> = claim.change.clone();
    let Some(mut change) = change.clone() else { return Ok(reject(queue.clone(), claim.clone(), String::from(REJECT_MALFORMED)).await.unwrap_or_else(|_| std::collections::BTreeMap::new())); };
    if (claim.attempt) > (MAX_ATTEMPTS) {
        return Ok(reject(queue.clone(), claim.clone(), String::from(REJECT_ATTEMPTS)).await.unwrap_or_else(|_| std::collections::BTreeMap::new()));
    }
    Ok(std::collections::BTreeMap::from([(String::from("request_id"), String::new()), (String::from("status"), String::from("published"))]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub async fn run_scan(mut store: String, mut repository: String, mut r#ref: String, mut source: String, mut runner: String, mut recorder: String, mut publisher: Option<String>, mut track_default_revision: bool) -> (Option<std::collections::BTreeMap<String, String>>, Option<String>) {
    let result: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("published"), String::new())]);
    (Some(result.clone()), None)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn process(mut claim: ClaimedScanRequest, mut queue: String, mut store: String, mut runner: String, mut recorder: String, mut publisher: Option<String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let request: Option<ScanRequest> = claim.request.clone().map(|_b| *_b);
    let Some(mut request) = request.clone() else { return Ok(reject(queue.clone(), claim.clone(), String::from(REJECT_MALFORMED)).await.unwrap_or_else(|_| std::collections::BTreeMap::new())); };
    if (claim.attempt) > (MAX_ATTEMPTS) {
        return Ok(reject(queue.clone(), claim.clone(), String::from(REJECT_ATTEMPTS)).await.unwrap_or_else(|_| std::collections::BTreeMap::new()));
    }
    Ok(std::collections::BTreeMap::from([(String::from("request_id"), request.request_id.clone()), (String::from("status"), String::from("published"))]))
}

pub const PUBLIC_EXPORTS: &[&str] = &["MAX_ATTEMPTS", "CLAIM_RENEWAL_SECONDS", "REJECT_ATTEMPTS", "REJECT_CONFLICT", "REJECT_DISABLED", "REJECT_MALFORMED", "REJECT_ROLE", "REJECT_SCAN", "REJECT_SOURCE", "REJECT_UNREGISTERED", "REQUESTER_ROLES", "SCAN_REQUEST_OPERATION", "ClaimedScanRequest", "ReviewPublisher", "ReviewRecorder", "ScanRequest", "ScanOutcome", "ScanRequestQueue", "ScanRunner", "parse_scan_request", "process_scan_requests", "scan_result_summary"];
