#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ReportingLineCaseState {
    #[default]
    PendingConfirmation,
    PendingOwnerReview,
    ActivationPending,
    Active,
    Conflict,
    Rejected,
    Superseded,
}

impl ReportingLineCaseState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::PendingConfirmation => "pending_confirmation",
            Self::PendingOwnerReview => "pending_owner_review",
            Self::ActivationPending => "activation_pending",
            Self::Active => "active",
            Self::Conflict => "conflict",
            Self::Rejected => "rejected",
            Self::Superseded => "superseded",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum EndpointDecision {
    #[default]
    Confirm,
    Reject,
}

impl EndpointDecision {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Confirm => "confirm",
            Self::Reject => "reject",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OwnerDecision {
    #[default]
    Approve,
    Reject,
}

impl OwnerDecision {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Approve => "approve",
            Self::Reject => "reject",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReportingCitation {
    pub unit_id: String,
    pub locator: String,
}

impl ReportingCitation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.unit_id.trim().is_empty() { return Err("unit_id must be non-empty"); }
        if self.locator.trim().is_empty() { return Err("locator must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EndpointConfirmation {
    pub principal_ref: String,
    pub decision: EndpointDecision,
    pub decided_at: String,
    pub edge_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OwnerReview {
    pub principal_ref: String,
    pub decision: OwnerDecision,
    pub decided_at: String,
    pub edge_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReportingLineCase {
    pub case_id: String,
    pub candidate_id: String,
    pub upload_id: String,
    pub document_id: String,
    pub version_id: String,
    pub source_sha256: String,
    pub subject_ref: String,
    pub manager_ref: String,
    pub requester_ref: String,
    pub citations: Vec<ReportingCitation>,
    pub effective_from: String,
    pub effective_until: String,
    pub recorded_at: String,
    pub state: ReportingLineCaseState,
    pub revision: i64,
    #[allow(clippy::type_complexity)]
    pub confirmation: Option<Box<EndpointConfirmation>>,
    #[allow(clippy::type_complexity)]
    pub owner_review: Option<Box<OwnerReview>>,
    pub supersedes_case_id: Option<String>,
    pub directory_comparison: String,
    pub directory_manager_ref: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ReportingLineModelError {
    pub message: String,
}

impl ReportingLineModelError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ReportingLineModelError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ReportingLineModelError {}

impl ReportingCitation {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("unit_id"), self.unit_id.clone()), (String::from("locator"), self.locator.clone())])
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn from_dict(mut value: std::collections::BTreeMap<String, String>) -> ReportingCitation {
        if value.is_empty() {
            return Default::default();
        }
        Default::default()
    }
}

impl EndpointConfirmation {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("principal_ref"), self.principal_ref.clone()), (String::from("decision"), String::new()), (String::from("decided_at"), String::new()), (String::from("edge_digest"), self.edge_digest.clone())])
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn from_dict(mut value: std::collections::BTreeMap<String, String>) -> EndpointConfirmation {
        if value.is_empty() {
            return Default::default();
        }
        Default::default()
    }
}

impl OwnerReview {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("principal_ref"), self.principal_ref.clone()), (String::from("decision"), String::new()), (String::from("decided_at"), String::new()), (String::from("edge_digest"), self.edge_digest.clone())])
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn from_dict(mut value: std::collections::BTreeMap<String, String>) -> OwnerReview {
        if value.is_empty() {
            return Default::default();
        }
        Default::default()
    }
}

impl ReportingLineCase {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn edge_digest(&self) -> String {
        let value: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("candidate_id"), self.candidate_id.clone()), (String::from("upload_id"), self.upload_id.clone()), (String::from("document_id"), self.document_id.clone()), (String::from("version_id"), self.version_id.clone()), (String::from("source_sha256"), self.source_sha256.clone()), (String::from("subject_ref"), self.subject_ref.clone()), (String::from("manager_ref"), self.manager_ref.clone()), (String::from("citations"), String::new()), (String::from("effective_from"), String::new()), (String::from("effective_until"), String::new()), (String::from("supersedes_case_id"), (self.supersedes_case_id.clone()).unwrap_or_default()), (String::from("directory_comparison"), String::new()), (String::from("directory_manager_ref"), (self.directory_manager_ref.clone()).unwrap_or_default())]);
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn is_currently_effective(&self) -> bool {
        ((self.effective_from.clone()) <= (self.recorded_at.clone())) && ((self.recorded_at.clone()) < (self.effective_until.clone()))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.0.0")), (String::from("case_id"), self.case_id.clone()), (String::from("candidate_id"), self.candidate_id.clone()), (String::from("upload_id"), self.upload_id.clone()), (String::from("document_id"), self.document_id.clone()), (String::from("version_id"), self.version_id.clone()), (String::from("source_sha256"), self.source_sha256.clone()), (String::from("subject_ref"), self.subject_ref.clone()), (String::from("manager_ref"), self.manager_ref.clone()), (String::from("requester_ref"), self.requester_ref.clone()), (String::from("citations"), String::new()), (String::from("effective_from"), String::new()), (String::from("effective_until"), String::new()), (String::from("recorded_at"), String::new()), (String::from("state"), String::new()), (String::from("revision"), String::new()), (String::from("confirmation"), String::new()), (String::from("owner_review"), String::new()), (String::from("supersedes_case_id"), (self.supersedes_case_id.clone()).unwrap_or_default()), (String::from("directory_comparison"), String::new()), (String::from("directory_manager_ref"), (self.directory_manager_ref.clone()).unwrap_or_default()), (String::from("edge_digest"), String::new()), (String::from("execution_authority"), String::new()), (String::from("approval_authority"), String::new())])
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn from_dict(mut value: std::collections::BTreeMap<String, String>) -> Result<ReportingLineCase, &'static str> {
        if ((value.clone()).get("schema_version").cloned()) != Some(String::from("1.0.0")) {
            return Err("unsupported reporting-line case schema");
        }
        let citations: Option<String> = (value.clone()).get("citations").cloned();
        if !(true) {
            return Err("reporting-line citations MUST be an array");
        }
        let confirmation: Option<String> = (value.clone()).get("confirmation").cloned();
        let owner_review: Option<String> = (value.clone()).get("owner_review").cloned();
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::too_many_arguments)]
    pub fn from_candidate(mut case_id: String, mut artifact_upload_id: String, mut artifact_document_id: String, mut artifact_version_id: String, mut artifact_source_sha256: String, mut candidate: String, mut requester_ref: String, mut effective_from: String, mut effective_until: String, mut recorded_at: String, mut supersedes_case_id: Option<String>) -> Result<ReportingLineCase, &'static str> {
        if case_id.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn reporting_instant(mut value: String) -> Result<String, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn normalize_principal(mut value: String) -> Result<String, &'static str> {
    if (!(true)) || (((value.clone()).is_empty()) || (((value.clone()) != (value.trim().to_string())) || ((((value.clone()).len() as i64)) > (256_i64)))) {
        return Err("reporting-line principal references MUST be exact non-empty strings");
    }
    Ok(value.to_lowercase())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn digest(mut value: String, mut name: String) -> Result<(), &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn mapping(mut value: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if !(false) {
        return Err("reporting-line nested value MUST be an object");
    }
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn text(mut value: std::collections::BTreeMap<String, String>, mut key: String) -> Result<String, &'static str> {
    let item: Option<String> = (value.clone()).get(key.as_str()).cloned();
    if (!(true)) || (!((item.clone()).is_some())) {
        return Err("key MUST be a non-empty string");
    }
    Ok((item.clone()).unwrap_or_default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn optional_text(mut value: std::collections::BTreeMap<String, String>, mut key: String) -> Result<Option<String>, &'static str> {
    let item: Option<String> = (value.clone()).get(key.as_str()).cloned();
    let Some(mut item) = item.clone() else { return Ok(None); };
    if (!(true)) || ((item.clone()).is_empty()) {
        return Err("key MUST be null or a non-empty string");
    }
    Ok(Some(item.clone()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn integer(mut value: std::collections::BTreeMap<String, String>, mut key: String) -> Result<i64, &'static str> {
    let item: Option<String> = (value.clone()).get(key.as_str()).cloned();
    if let Some(mut item) = item.clone() {
        return Err("key MUST be an integer");
    }
    Ok(0_i64)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn instant(mut value: std::collections::BTreeMap<String, String>, mut key: String) -> Result<String, &'static str> {
    let raw: String = text(value.clone(), key.clone()).unwrap_or_else(|_| String::new());
    Ok(reporting_instant(String::new()).unwrap_or_else(|_| String::new()))
}

pub const PUBLIC_EXPORTS: &[&str] = &["EndpointConfirmation", "EndpointDecision", "OwnerDecision", "OwnerReview", "ReportingCitation", "ReportingLineCase", "ReportingLineCaseState", "ReportingLineModelError", "normalize_principal", "reporting_instant"];
