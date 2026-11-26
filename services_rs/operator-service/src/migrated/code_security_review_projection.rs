pub const MAX_ITEMS: i64 = 200;
pub const MAX_REVIEWS: i64 = 500;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CodeSecurityScanRequestBody {
    pub repository_alias: String,
    pub r#ref: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CodeSecurityRepositoryChangeBody {
    pub action: String,
    pub repository_alias: String,
    pub location: Option<String>,
    pub default_ref: Option<String>,
    pub exposure: Option<String>,
}

impl CodeSecurityRepositoryChangeBody {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.action.as_str(), "register" | "enable" | "disable") { return Err("invalid action literal"); }
        Ok(())
    }
}

pub const CODE_SECURITY_REVIEW_STATE_PREFIX: &str = "runtime:code-security-review:";
pub const CODE_SECURITY_PACK_STATE_PREFIX: &str = "runtime:code-security-pack:";
pub const CODE_SECURITY_REPOSITORY_STATE_PREFIX: &str = "runtime:code-security-repository:";
pub const SCAN_REQUEST_OPERATION: &str = "code_security.scan_request";
pub const CODE_SECURITY_WORKER_STATUS_KEY: &str = "runtime:code-security-worker:v1";
pub const GAP_REPOSITORY_MALFORMED: &str = "code_security_repository_malformed";
pub const GAP_REQUEST_MALFORMED: &str = "code_security_scan_request_malformed";
pub const GAP_WORKER_STATUS_MALFORMED: &str = "code_security_worker_status_malformed";
pub const GAP_MALFORMED: &str = "code_security_review_malformed";
pub const GAP_PACK_MALFORMED: &str = "code_security_pack_malformed";
pub const GAP_TRUNCATED: &str = "code_security_review_truncated";
pub const ALIAS: &str = "^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$";
pub const REVISION: &str = "^[0-9a-f]{40}([0-9a-f]{24})?$";
pub const DIGEST: &str = "^[0-9a-f]{64}$";
pub const ISSUE: &str = "^FDAI-SEC-[0-9a-f]{12}$";
pub const PRIORITIES: &[&str] = &["P0", "P1", "P2", "P3", "P4"];
pub const SEVERITIES: &[&str] = &["critical", "high", "medium", "low", "undetermined"];
pub const CONFIDENCES: &[&str] = &["hypothesis", "reported", "corroborated", "verified", "proven"];
pub const EXPOSURES: &[&str] = &["exposed", "internal", "not_deployed", "unknown"];
pub const PACK_ID: &str = "^[0-9a-f]{12}$";
pub const PRINCIPAL: &str = "^[A-Za-z0-9@._:/+-]{1,128}$";
pub const VERDICTS: &[&str] = &["fixed_verified", "still_present", "inconclusive", "not_applicable"];
pub const DECISIONS: &[&str] = &["accepted", "rejected"];
pub const DISPOSITIONS: &[&str] = &["false_positive", "open"];
pub const SOURCE_KINDS: &[&str] = &["local_path", "git_repository", "external_sarif"];
pub const REVISION_KINDS: &[&str] = &["commit", "snapshot"];
pub const TRIGGERS: &[&str] = &["cli", "console", "schedule"];
pub const PROVIDER: &str = "^[a-z0-9][a-z0-9-]{0,31}$";
pub const PRODUCER: &str = "^[A-Za-z0-9][A-Za-z0-9 ._+-]{0,63}$";
pub const REQUEST_ID: &str = "^operator-[0-9a-f]{32}$";
pub const LOCATION: &str = "^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$";
pub const REF_PATTERN: &str = "^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$";
pub const ALIAS_PATTERN: &str = "^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$";
pub const REPOSITORY_CHANGE_OPERATION: &str = "code_security.repository_change";
pub const CHANGE_ACTIONS: &[&str] = &["register", "enable", "disable", "connect", "disconnect"];
pub const LOCATION_PATTERN: &str = "^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$";
impl CodeSecurityRepositoryChangeBody {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn fields_match_action(&self) -> Result<CodeSecurityRepositoryChangeBody, &'static str> {
        if ((self.action.clone()) == (String::from("register"))) && (self.location.is_none()) {
            return Err("register needs a location");
        }
        if ((self.action.clone()) != (String::from("register"))) && ((self.location.is_some()) || ((self.default_ref.is_some()) || (self.exposure.is_some()))) {
            return Err("enable and disable take only the alias");
        }
        Ok(self.clone())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct MalformedError {
    pub message: String,
}

impl MalformedError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for MalformedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for MalformedError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn r#match(mut value: String, mut pattern: String) -> Result<String, &'static str> {
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn count(mut value: String) -> Result<i64, &'static str> {
    Ok(0_i64)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn counts(mut value: String, mut keys: Vec<String>) -> Result<std::collections::BTreeMap<String, i64>, &'static str> {
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn decision(mut review: std::collections::BTreeMap<String, String>) -> String {
    String::from("open\" if review[\"issue_count\"] else \"clear")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn review(mut key: String, mut value: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if !(false) {
        return Err("_MalformedError");
    }
    let alias: String = r#match(String::new(), String::from(ALIAS)).unwrap_or_else(|_| String::new());
    let revision: String = r#match(String::new(), String::from(REVISION)).unwrap_or_else(|_| String::new());
    if (key.clone()) != (format!("{}{}:{}", String::from(CODE_SECURITY_REVIEW_STATE_PREFIX), alias.clone(), revision.clone())) {
        return Err("_MalformedError");
    }
    let mut review: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("repository_alias"), alias.clone()), (String::from("revision"), revision.clone()), (String::from("review_digest"), r#match(String::new(), String::from(DIGEST)).unwrap_or_else(|_| String::new())), (String::from("recorded_at"), String::new()), (String::from("issue_count"), String::new()), (String::from("by_priority"), String::new()), (String::from("by_severity"), String::new()), (String::from("by_confidence"), String::new()), (String::from("known_exploited_count"), String::new()), (String::from("exposure"), String::new()), (String::from("coverage_complete"), String::new()), (String::from("top_issue_ids"), String::new()), (String::from("source"), String::new()), (String::from("producers"), String::new())]);
    review.insert(String::from("decision"), decision(review.clone()));
    Ok(review.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn source(mut value: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if !(false) {
        return Err("_MalformedError");
    }
    Ok(std::collections::BTreeMap::from([(String::from("kind"), String::new()), (String::from("provider"), r#match(String::new(), String::from(PROVIDER)).unwrap_or_else(|_| String::new())), (String::from("revision_kind"), String::new()), (String::from("trigger"), String::new()), (String::from("request_id"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn timestamp(mut value: String) -> Result<String, &'static str> {
    if !(true) {
        return Err("_MalformedError");
    }
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn aware_timestamp(mut value: String) -> Result<(String, String), &'static str> {
    let rendered: String = timestamp(value.clone()).unwrap_or_else(|_| String::new());
    Ok((String::new(), String::new()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn pack_reviews(mut raw: String) -> Result<(Option<std::collections::BTreeMap<String, String>>, Vec<std::collections::BTreeMap<String, String>>), &'static str> {
    if (!(false)) || ((((raw.clone()).len() as i64)) > (MAX_REVIEWS)) {
        return Err("_MalformedError");
    }
    let mut latest: Option<std::collections::BTreeMap<String, String>> = None;
    let mut adjudications: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
    Ok((latest.clone(), adjudications.clone()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn pack(mut key: String, mut value: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if !(false) {
        return Err("_MalformedError");
    }
    let pack_id: String = r#match(String::new(), String::from(PACK_ID)).unwrap_or_else(|_| String::new());
    if (key.clone()) != (format!("{}{}", String::from(CODE_SECURITY_PACK_STATE_PREFIX), pack_id.clone())) {
        return Err("_MalformedError");
    }
    Ok(std::collections::BTreeMap::from([(String::from("pack_id"), pack_id.clone()), (String::from("base_commit"), r#match(String::new(), String::from(REVISION)).unwrap_or_else(|_| String::new())), (String::from("issue_count"), String::new()), (String::from("recorded_at"), timestamp(String::new()).unwrap_or_else(|_| String::new())), (String::from("expires_at"), timestamp(String::new()).unwrap_or_else(|_| String::new())), (String::from("revoked"), String::new()), (String::from("latest_verification"), String::new()), (String::from("adjudications"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn code_security_packs_projection(mut rows: Vec<std::collections::BTreeMap<String, String>>) -> std::collections::BTreeMap<String, String> {
    let mut packs: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
    let mut gaps: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
    if (((rows.clone()).len() as i64)) > (MAX_ITEMS) {
        gaps.push(std::collections::BTreeMap::from([(String::from("reason_code"), String::from(GAP_TRUNCATED))]));
    }
    std::collections::BTreeMap::from([(String::from("surface"), String::from("code-security-packs")), (String::from("available"), String::new()), (String::from("complete"), String::new()), (String::from("source"), String::from("postgresql:state_kv:code-security-pack")), (String::from("packs"), String::new()), (String::from("gaps"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn code_security_reviews_projection(mut rows: Vec<std::collections::BTreeMap<String, String>>) -> std::collections::BTreeMap<String, String> {
    let mut reviews: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
    let mut gaps: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
    if (((rows.clone()).len() as i64)) > (MAX_ITEMS) {
        gaps.push(std::collections::BTreeMap::from([(String::from("reason_code"), String::from(GAP_TRUNCATED))]));
    }
    std::collections::BTreeMap::from([(String::from("surface"), String::from("code-security-reviews")), (String::from("available"), String::new()), (String::from("complete"), String::new()), (String::from("source"), String::from("postgresql:state_kv:code-security-review")), (String::from("reviews"), String::new()), (String::from("gaps"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn repository(mut key: String, mut value: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let alias: String = r#match(String::new(), String::new()).unwrap_or_else(|_| String::new());
    if (key.clone()) != (format!("{}{}", String::from(CODE_SECURITY_REPOSITORY_STATE_PREFIX), alias.clone())) {
        return Err("_MalformedError");
    }
    Ok(std::collections::BTreeMap::from([(String::from("repository_alias"), alias.clone()), (String::from("provider"), String::from("github")), (String::from("location"), r#match(String::new(), String::from(LOCATION)).unwrap_or_else(|_| String::new())), (String::from("default_ref"), r#match(String::new(), String::new()).unwrap_or_else(|_| String::new())), (String::from("exposure"), String::new()), (String::from("enabled"), String::new()), (String::from("registered_at"), timestamp(String::new()).unwrap_or_else(|_| String::new()))]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn code_security_repositories_projection(mut rows: Vec<std::collections::BTreeMap<String, String>>) -> std::collections::BTreeMap<String, String> {
    let mut repositories: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
    let mut gaps: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
    if (((rows.clone()).len() as i64)) > (MAX_ITEMS) {
        gaps.push(std::collections::BTreeMap::from([(String::from("reason_code"), String::from(GAP_TRUNCATED))]));
    }
    std::collections::BTreeMap::from([(String::from("surface"), String::from("code-security-repositories")), (String::from("available"), String::new()), (String::from("complete"), String::new()), (String::from("source"), String::from("postgresql:state_kv:code-security-repository")), (String::from("repositories"), String::new()), (String::from("gaps"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn scan_request(mut value: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut request: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("request_id"), r#match(String::new(), String::from(REQUEST_ID)).unwrap_or_else(|_| String::new())), (String::from("kind"), String::from("repository_change\" if is_change else \"scan")), (String::from("action"), String::new()), (String::from("location"), String::new()), (String::from("repository_alias"), r#match(String::new(), String::new()).unwrap_or_else(|_| String::new())), (String::from("ref"), String::new()), (String::from("status"), String::new()), (String::from("accepted_at"), timestamp(String::new()).unwrap_or_else(|_| String::new())), (String::from("closed_at"), String::new()), (String::from("rejection_reason"), String::new()), (String::from("result"), String::new())]);
    Ok(request.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn scan_result(mut result: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let decision: Option<String> = (result.clone()).get("decision").cloned();
    if !(matches!(((decision.clone()).unwrap_or_default()).as_str(), "urgent" | "open" | "clear" | "coverage_incomplete")) {
        return Err("_MalformedError");
    }
    Ok(std::collections::BTreeMap::from([(String::from("revision"), r#match(String::new(), String::from(REVISION)).unwrap_or_else(|_| String::new())), (String::from("review_digest"), r#match(String::new(), String::from(DIGEST)).unwrap_or_else(|_| String::new())), (String::from("decision"), (decision.clone()).unwrap_or_default()), (String::from("issue_count"), String::new()), (String::from("coverage_complete"), String::new()), (String::from("published"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn code_security_worker_status_projection(mut rows: Vec<std::collections::BTreeMap<String, String>>, mut now: Option<String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if (rows.clone()).is_empty() {
        return Ok(std::collections::BTreeMap::from([(String::from("surface"), String::from("code-security-worker-status")), (String::from("available"), String::new()), (String::from("complete"), String::new()), (String::from("source"), String::from("postgresql:state_kv:code-security-worker")), (String::from("status"), String::new()), (String::from("gaps"), String::new())]));
    }
    let mut gaps: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
    let expected: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("kind"), String::from("schema_version"), String::from("state"), String::from("phase"), String::from("recorded_at"), String::from("request_interval_seconds"), String::from("schedule_interval_seconds"), String::from("next_request_at"), String::from("next_schedule_at"), String::from("request_processed"), String::from("schedule_checked"), String::from("schedule_scanned"), String::from("schedule_unchanged"), String::from("schedule_failed")]);
    let request_interval: i64 = count(String::new()).unwrap_or_else(|_| 0_i64);
    let schedule_interval: i64 = count(String::new()).unwrap_or_else(|_| 0_i64);
    if (!(((1_i64) <= (request_interval)) && ((request_interval) <= (60_i64)))) || (!(((60_i64) <= (schedule_interval)) && ((schedule_interval) <= (86400_i64)))) {
        return Err("_MalformedError");
    }
    let mut status: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("state"), String::new()), (String::from("phase"), String::new()), (String::from("fresh"), String::new()), (String::from("recorded_at"), String::new()), (String::from("next_request_at"), String::new()), (String::from("next_schedule_at"), String::new()), (String::from("request_interval_seconds"), String::new()), (String::from("schedule_interval_seconds"), String::new()), (String::from("request_processed"), String::new()), (String::from("schedule_checked"), String::new()), (String::from("schedule_scanned"), String::new()), (String::from("schedule_unchanged"), String::new()), (String::from("schedule_failed"), String::new())]);
    Ok(std::collections::BTreeMap::from([(String::from("surface"), String::from("code-security-worker-status")), (String::from("available"), String::new()), (String::from("complete"), String::new()), (String::from("source"), String::from("postgresql:state_kv:code-security-worker")), (String::from("status"), String::new()), (String::from("gaps"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn code_security_scan_requests_projection(mut rows: Vec<std::collections::BTreeMap<String, String>>) -> std::collections::BTreeMap<String, String> {
    let mut requests: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
    let mut gaps: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
    if (((rows.clone()).len() as i64)) > (MAX_ITEMS) {
        gaps.push(std::collections::BTreeMap::from([(String::from("reason_code"), String::from(GAP_TRUNCATED))]));
    }
    std::collections::BTreeMap::from([(String::from("surface"), String::from("code-security-scan-requests")), (String::from("available"), String::new()), (String::from("complete"), String::new()), (String::from("source"), String::from("postgresql:state_kv:operator-proposal")), (String::from("requests"), String::new()), (String::from("gaps"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn read_code_security_projection(mut operation: String, mut fetch_all: String, mut params: Option<std::collections::BTreeMap<String, Vec<String>>>) -> std::collections::BTreeMap<String, String> {
    if (operation.clone()) == (String::from("code_security.packs")) {
        return code_security_packs_projection(Vec::new());
    }
    if matches!(operation.as_str(), "code_security.repositories" | "knowledge.github.sources") {
        return code_security_repositories_projection(Vec::new());
    }
    if (operation.clone()) == (String::from("code_security.scan_requests")) {
        return code_security_scan_requests_projection(Vec::new());
    }
    if (operation.clone()) == (String::from("code_security.worker_status")) {
        return code_security_worker_status_projection(Vec::new(), None).unwrap_or_else(|_| std::collections::BTreeMap::new());
    }
    code_security_reviews_projection(Vec::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["CODE_SECURITY_OPERATIONS", "CODE_SECURITY_REPOSITORY_STATE_PREFIX", "REPOSITORY_CHANGE_OPERATION", "CodeSecurityRepositoryChangeBody", "code_security_worker_status_projection", "GAP_REPOSITORY_MALFORMED", "GAP_REQUEST_MALFORMED", "SCAN_REQUEST_OPERATION", "CodeSecurityScanRequestBody", "code_security_repositories_projection", "code_security_scan_requests_projection", "CODE_SECURITY_PACK_STATE_PREFIX", "CODE_SECURITY_REVIEW_STATE_PREFIX", "GAP_PACK_MALFORMED", "code_security_packs_projection", "GAP_MALFORMED", "GAP_TRUNCATED", "code_security_reviews_projection", "read_code_security_projection"];
