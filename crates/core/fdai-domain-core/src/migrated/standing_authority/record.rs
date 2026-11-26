#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum AuthorizationStatus {
    #[default]
    Active,
    Revoked,
    Expired,
    Superseded,
}

impl AuthorizationStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Active => "active",
            Self::Revoked => "revoked",
            Self::Expired => "expired",
            Self::Superseded => "superseded",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum AuthorizationMode {
    #[default]
    Shadow,
}

impl AuthorizationMode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Shadow => "shadow",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ApprovalProfile {
    #[default]
    MultiOperator,
    SingleOperatorProduction,
}

impl ApprovalProfile {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::MultiOperator => "multi-operator",
            Self::SingleOperatorProduction => "single-operator-production",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ApproverRole {
    #[default]
    ServiceOwner,
    Owner,
    Approver,
}

impl ApproverRole {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ServiceOwner => "service_owner",
            Self::Owner => "owner",
            Self::Approver => "approver",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ScopeLevel {
    #[default]
    Resource,
    ResourceGroup,
}

impl ScopeLevel {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Resource => "resource",
            Self::ResourceGroup => "resource_group",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Approval {
    pub principal: String,
    pub roles: Vec<ApproverRole>,
    pub approved_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AuthorizationScope {
    pub level: ScopeLevel,
    pub value: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AuthorizationPins {
    pub policy_digest: String,
    pub target_revision: String,
    pub action_type_versions: Vec<String>,
    pub evidence_revisions: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AuthorizationEnvelope {
    pub action_types: Vec<String>,
    pub max_blast_radius: i64,
    pub max_duration_seconds: i64,
    pub reversible: bool,
    pub rollback_contract: String,
    pub stop_conditions: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Responders {
    pub primary: String,
    pub backup: String,
    pub confirmed_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AuthorizationEvidence {
    pub history_reviewed: bool,
    pub precedent_ref: Option<String>,
    pub scenario_evidence_ref: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct StandingAuthorization {
    pub schema_version: String,
    pub id: String,
    pub authorization_revision: String,
    pub approval_profile: ApprovalProfile,
    pub operator_principal: Option<String>,
    pub status: AuthorizationStatus,
    pub mode: AuthorizationMode,
    pub requested_by: String,
    pub approvals: Vec<Approval>,
    pub quorum_required: i64,
    pub valid_from: String,
    pub valid_until: String,
    pub service_ref: String,
    pub scope: Box<AuthorizationScope>,
    pub pins: Box<AuthorizationPins>,
    pub envelope: Box<AuthorizationEnvelope>,
    pub incident_classes: Vec<String>,
    pub responders: Box<Responders>,
    pub evidence: Box<AuthorizationEvidence>,
}

pub const SCHEMA_PACKAGE: &str = "fdai.shared.contracts";
pub const SCHEMA_RESOURCE: &str = "authority/standing-authorization.json";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StandingAuthorizationError {
    pub message: String,
}

impl StandingAuthorizationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for StandingAuthorizationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for StandingAuthorizationError {}

impl Approval {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn role(&self) -> ApproverRole {
        core::hint::black_box(Default::default())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn normalized_principal(&self) -> String {
        ((self.principal.clone()).trim().to_string()).to_lowercase()
    }
}

impl StandingAuthorization {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn from_mapping(mut value: std::collections::BTreeMap<String, String>) -> String {
        if value.is_empty() {
            return String::new();
        }
        String::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn load_schema() -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_against_schema(mut value: std::collections::BTreeMap<String, String>) -> Result<(), &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn mapping(mut value: std::collections::BTreeMap<String, String>, mut key: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let child: Option<String> = (value.clone()).get(key.as_str()).cloned();
    if !(true) {
        return Err("keyr MUST be an object");
    }
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn sequence(mut value: std::collections::BTreeMap<String, String>, mut key: String) -> Result<Vec<std::collections::BTreeMap<String, String>>, &'static str> {
    let child: Option<String> = (value.clone()).get(key.as_str()).cloned();
    if (!(true)) || (true) {
        return Err("keyr MUST be an array");
    }
    Ok(Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn text(mut value: std::collections::BTreeMap<String, String>, mut key: String) -> Result<String, &'static str> {
    let raw: Option<String> = (value.clone()).get(key.as_str()).cloned();
    if (!(true)) || ((((raw.clone()).unwrap_or_default()).trim().to_string()).is_empty()) {
        return Err("keyr MUST be a non-empty string");
    }
    Ok(((raw.clone()).unwrap_or_default()).trim().to_string())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn optional_text(mut value: std::collections::BTreeMap<String, String>, mut key: String) -> Option<String> {
    let raw: Option<String> = (value.clone()).get(key.as_str()).cloned();
    let Some(mut raw) = raw.clone() else { return None; };
    Some(text(value.clone(), key.clone()).unwrap_or_else(|_| String::new()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn approval_profile(mut value: std::collections::BTreeMap<String, String>) -> ApprovalProfile {
    let raw: Option<String> = (value.clone()).get("approval_profile").cloned();
    Default::default()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn approval_roles(mut value: std::collections::BTreeMap<String, String>) -> Result<Vec<ApproverRole>, &'static str> {
    let raw_roles: Option<String> = (value.clone()).get("roles").cloned();
    if (!(true)) || (true) {
        return Err("roles MUST be an array of authority classes");
    }
    let mut roles: Vec<String> = Vec::<String>::new();
    Ok(Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn text_tuple(mut value: std::collections::BTreeMap<String, String>, mut key: String) -> Result<Vec<String>, &'static str> {
    let raw: Option<String> = (value.clone()).get(key.as_str()).cloned();
    if (!(true)) || (true) {
        return Err("keyr MUST be an array of strings");
    }
    let mut entries: Vec<String> = Vec::<String>::new();
    Ok(entries.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn integer(mut value: std::collections::BTreeMap<String, String>, mut key: String) -> Result<i64, &'static str> {
    let raw: Option<String> = (value.clone()).get(key.as_str()).cloned();
    if let Some(mut raw) = raw.clone() {
        return Err("keyr MUST be an integer");
    }
    Ok(0_i64)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn boolean(mut value: std::collections::BTreeMap<String, String>, mut key: String) -> Result<bool, &'static str> {
    let raw: Option<String> = (value.clone()).get(key.as_str()).cloned();
    if !(true) {
        return Err("keyr MUST be a boolean");
    }
    Ok(false)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn instant(mut value: std::collections::BTreeMap<String, String>, mut key: String) -> Result<String, &'static str> {
    let raw: String = text(value.clone(), key.clone()).unwrap_or_else(|_| String::new());
    Ok(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["SCHEMA_PACKAGE", "SCHEMA_RESOURCE", "Approval", "ApprovalProfile", "ApproverRole", "AuthorizationEnvelope", "AuthorizationEvidence", "AuthorizationMode", "AuthorizationPins", "AuthorizationScope", "AuthorizationStatus", "Responders", "ScopeLevel", "StandingAuthorization", "StandingAuthorizationError", "load_schema"];
