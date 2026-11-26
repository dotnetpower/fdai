#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ExemptionState {
    #[default]
    Active,
    Expired,
    Revoked,
}

impl ExemptionState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Active => "active",
            Self::Expired => "expired",
            Self::Revoked => "revoked",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExemptionIssue {
    pub key: String,
    pub message: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExemptionScope {
    pub subscription_id: String,
    pub resource_group: Option<String>,
    pub resource_ref: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Exemption {
    pub schema_version: String,
    pub id: String,
    pub rule_id: String,
    pub scope: Box<ExemptionScope>,
    pub justification: String,
    pub requested_by: String,
    pub approved_by: String,
    pub state: ExemptionState,
    pub created_at: String,
    pub expires_at: String,
    pub revoked_at: Option<String>,
    pub revoked_by: Option<String>,
}

pub const SCHEMA_PACKAGE: &str = "fdai.rule_catalog.schema";
pub const SCHEMA_FILE: &str = "exemption.schema.json";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ExemptionError {
    pub message: String,
}

impl ExemptionError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ExemptionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ExemptionError {}

impl ExemptionScope {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn require_bounded_scope(&self) -> Result<ExemptionScope, &'static str> {
        if (self.resource_group.is_none()) && (self.resource_ref.is_none()) {
            return Err("exemption scope MUST set resource_group or resource_ref -  subscription-");
        }
        Ok(self.clone())
    }
}

impl Exemption {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn require_utc_timestamp(mut value: Option<String>) -> Result<Option<String>, &'static str> {
        let Some(mut value) = value.clone() else { return Ok(None); };
        Ok(Some(value.clone()))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn require_distinct_approver(&self) -> Result<Exemption, &'static str> {
        if (self.requested_by.clone()) == (self.approved_by.clone()) {
            return Err("requested_by MUST differ from approved_by  architecture.instructions.md ");
        }
        Ok(self.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn require_expiry_in_future_of_creation(&self) -> Result<Exemption, &'static str> {
        if (self.expires_at.clone()) <= (self.created_at.clone()) {
            return Err("expires_at MUST be strictly after created_at");
        }
        Ok(self.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn require_consistent_revocation(&self) -> Result<Exemption, &'static str> {
        let has_revoked_at: bool = self.revoked_at.is_some();
        let has_revoked_by: bool = self.revoked_by.is_some();
        Ok(self.clone())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn exemption_duration_issue(mut exemption: Exemption, mut max_duration: String) -> Option<ExemptionIssue> {
    Some(ExemptionIssue { key: format!("{}:expires_at", exemption.id.clone()), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn exemption_duration_issues(mut exemptions: Vec<Exemption>, mut max_duration: String) -> Vec<ExemptionIssue> {
    let mut issues: Vec<ExemptionIssue> = Vec::<ExemptionIssue>::new();
    for exemption in exemptions.clone() {
        let issue: Option<ExemptionIssue> = exemption_duration_issue(exemption.clone(), max_duration.clone());
        if let Some(mut issue) = issue.clone() {
            issues.push(issue.clone());
        }
    }
    issues.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn load_json_schema() -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn parse_exemption_json(mut text: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_exemption_from_mapping(mut raw: std::collections::BTreeMap<String, String>) -> Result<Exemption, &'static str> {
    let mut issues: Vec<ExemptionIssue> = Vec::<ExemptionIssue>::new();
    let schema: std::collections::BTreeMap<String, String> = load_json_schema();
    if !(issues.clone()).is_empty() {
        return Err("issues");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["Exemption", "ExemptionError", "ExemptionIssue", "ExemptionScope", "ExemptionState", "exemption_duration_issue", "exemption_duration_issues", "load_exemption_from_mapping", "parse_exemption_json"];
