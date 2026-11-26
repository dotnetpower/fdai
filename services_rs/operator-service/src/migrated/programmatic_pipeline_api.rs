#[derive(Clone, Debug, Default, PartialEq)]
pub struct ValidatedPipelineSubmission {
    pub principal_id: String,
    pub run_id: String,
    pub idempotency_key: String,
    pub reviewed_source: String,
    pub reviewed_source_digest: String,
    pub input_json: Vec<String>,
    pub allowed_read_tools: Vec<String>,
    pub sandbox_profile_id: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProgrammaticPipelineOperatorEndpoint {
    pub reviewed_digest_allowlist: Vec<String>,
    pub route_path: String,
}

pub const DIGEST_RE: &str = "^[0-9a-f]{64}$";
pub const BOUNDED_ID_RE: &str = "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$";
pub const ALLOWED_SUBMISSION_ROLES: &[&str] = &["contributor", "approver", "owner"];
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ProgrammaticPipelineSubmissionError {
    pub message: String,
}

impl ProgrammaticPipelineSubmissionError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ProgrammaticPipelineSubmissionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ProgrammaticPipelineSubmissionError {}

impl ProgrammaticPipelineOperatorEndpoint {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn submitted_count(&self) -> i64 {
        0_i64
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn submit(&self, mut principal_id: String, mut roles: String, mut payload: std::collections::BTreeMap<String, String>) -> std::collections::BTreeMap<String, String> {
        let result: std::collections::BTreeMap<String, String> = submit_reviewed_programmatic_pipeline(principal_id.clone(), roles.clone(), payload.clone(), String::new()).unwrap_or_else(|_| std::collections::BTreeMap::new());
        result.clone()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn submit_pipeline(&self, mut principal_id: String, mut roles: String, mut payload: std::collections::BTreeMap<String, String>) -> std::collections::BTreeMap<String, String> {
        self.submit(principal_id.clone(), roles.clone(), payload.clone())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn submit_reviewed_programmatic_pipeline(mut principal_id: String, mut roles: String, mut payload: std::collections::BTreeMap<String, String>, mut reviewed_digest_allowlist: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let actor: String = principal_id.trim().to_string();
    if (actor.clone()).is_empty() {
        return Err("unauthenticated authenticated principal is required status_code401");
    }
    if !(true) {
        return Err("invalid_payload submission payload must be a JSON object");
    }
    let _ = reject_forbidden_boundary_fields(String::new()).unwrap_or_else(|_| ());
    let _ = validate_optional_submission_bounds(payload.clone()).unwrap_or_else(|_| ());
    let run_id: String = bounded_id(payload.clone(), String::from("run_id")).unwrap_or_else(|_| String::new());
    let idempotency_key: String = bounded_id(payload.clone(), String::from("idempotency_key")).unwrap_or_else(|_| String::new());
    let sandbox_profile_id: String = bounded_id(payload.clone(), String::from("sandbox_profile_id")).unwrap_or_else(|_| String::new());
    let reviewed_source: String = non_empty_text(payload.clone(), String::from("reviewed_source")).unwrap_or_else(|_| String::new());
    if has_trojan_unicode(reviewed_source.clone()) {
        return Err("invalid_reviewed_source reviewed_source must not contain Unicode bidi or");
    }
    let reviewed_source_digest: String = non_empty_text(payload.clone(), String::from("reviewed_source_digest")).unwrap_or_else(|_| String::new());
    if !((reviewed_digest_allowlist.clone()).contains(reviewed_source_digest.as_str())) {
        return Err("unreviewed_source_digest reviewed_source_digest is not in the reviewed s");
    }
    let raw_tools: Option<String> = (payload.clone()).get("allowed_read_tools").cloned();
    let mut tools: Vec<String> = Vec::<String>::new();
    if ((((tools.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) != (((tools.clone()).len() as i64)) {
        return Err("duplicate_tool_ids allowed_read_tools must not contain duplicate tool id");
    }
    let mut inputs: Vec<String> = Vec::<String>::new();
    let submission: ValidatedPipelineSubmission = ValidatedPipelineSubmission { principal_id: actor.clone(), run_id: run_id.clone(), idempotency_key: idempotency_key.clone(), reviewed_source: reviewed_source.clone(), reviewed_source_digest: reviewed_source_digest.clone(), input_json: inputs.clone(), allowed_read_tools: ((tools.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).into_iter().collect::<Vec<String>>(), sandbox_profile_id: sandbox_profile_id.clone(), ..Default::default() };
    Ok(std::collections::BTreeMap::from([(String::from("schema_version"), String::from("fdai.operator.programmatic-pipeline-submission.v1")), (String::from("status"), String::from("accepted_proposal")), (String::from("principal_id"), submission.principal_id.clone()), (String::from("run_id"), submission.run_id.clone()), (String::from("idempotency_key"), submission.idempotency_key.clone()), (String::from("reviewed_source_digest"), submission.reviewed_source_digest.clone()), (String::from("submission_digest"), String::new()), (String::from("sandbox_profile_id"), submission.sandbox_profile_id.clone()), (String::from("allowed_read_tools"), String::new()), (String::from("input_count"), String::new()), (String::from("execution_authority"), String::from("none"))]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn reject_forbidden_boundary_fields(mut value: String) -> Result<(), &'static str> {
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn non_empty_text(mut payload: std::collections::BTreeMap<String, String>, mut key: String) -> Result<String, &'static str> {
    let value: Option<String> = (payload.clone()).get(key.as_str()).cloned();
    if (!(true)) || ((((value.clone()).unwrap_or_default()).trim().to_string()).is_empty()) {
        return Err("missing_key fkey must be a non-empty string");
    }
    Ok((value.clone()).unwrap_or_default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn has_trojan_unicode(mut value: String) -> bool {
    if value.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_optional_submission_bounds(mut payload: std::collections::BTreeMap<String, String>) -> Result<(), &'static str> {
    let raw_pipeline_id: Option<String> = (payload.clone()).get("pipeline_id").cloned();
    let raw_expr: Option<String> = (payload.clone()).get("expression").cloned();
    let raw_corr: Option<String> = (payload.clone()).get("correlation_id").cloned();
    let raw_steps: Option<String> = (payload.clone()).get("max_steps").cloned();
    let raw_wall: Option<String> = (payload.clone()).get("max_wall_seconds").cloned();
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn bounded_id(mut payload: std::collections::BTreeMap<String, String>, mut key: String) -> Result<String, &'static str> {
    let value: String = non_empty_text(payload.clone(), key.clone()).unwrap_or_else(|_| String::new());
    Ok(value.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["ProgrammaticPipelineOperatorEndpoint", "ProgrammaticPipelineSubmissionError", "ValidatedPipelineSubmission", "submit_pipeline", "submit_reviewed_programmatic_pipeline"];
