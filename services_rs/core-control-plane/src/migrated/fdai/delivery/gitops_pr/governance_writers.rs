use std::collections::BTreeMap;
pub const RESOURCE_GROUP_MAX: i64 = 90;
pub const JUSTIFICATION_MIN: i64 = 20;
pub const JUSTIFICATION_MAX: i64 = 500;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RetirementMode {
    #[default]
    ShadowOnly,
    Retired,
}

impl RetirementMode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ShadowOnly => "shadow_only",
            Self::Retired => "retired",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct GovernanceDocument {
    pub path: String,
    pub document: BTreeMap<String, String>,
    pub execution_path: String,
    pub applied: bool,
}

pub const RULE_ID: &str = "^[a-z0-9][a-z0-9._-]{1,127}$";
pub const EXEMPTION_ID: &str = "^[a-z0-9][a-z0-9._-]{1,127}$";
pub const UUID: &str = "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$";
pub const SCHEMA_VERSION: &str = "1.0.0";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct GovernanceWriterError {
    pub message: String,
}

impl GovernanceWriterError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for GovernanceWriterError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for GovernanceWriterError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn render_rule_retirement(mut rule_id: String, mut mode: RetirementMode, mut justification: String, mut requested_by: String, mut approved_by: String, mut decided_at: String) -> GovernanceDocument {
    let _ = require_rule_id(rule_id.clone()).unwrap_or_else(|_| ());
    let _ = require_justification(justification.clone()).unwrap_or_else(|_| ());
    let _ = require_distinct_principals(requested_by.clone(), approved_by.clone()).unwrap_or_else(|_| ());
    let _ = require_aware(decided_at.clone(), String::from("decided_at")).unwrap_or_else(|_| ());
    GovernanceDocument { path: format!("rule-catalog/retirements/{}.yaml", rule_id.clone()), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::too_many_arguments)]
pub fn render_exemption_grant(mut exemption_id: String, mut rule_id: String, mut subscription_id: String, mut justification: String, mut requested_by: String, mut approved_by: String, mut created_at: String, mut expires_at: String, mut resource_group: Option<String>, mut resource_ref: Option<String>) -> Result<GovernanceDocument, &'static str> {
    let _ = require_rule_id(rule_id.clone()).unwrap_or_else(|_| ());
    let _ = require_justification(justification.clone()).unwrap_or_else(|_| ());
    let _ = require_distinct_principals(requested_by.clone(), approved_by.clone()).unwrap_or_else(|_| ());
    let _ = require_aware(created_at.clone(), String::from("created_at")).unwrap_or_else(|_| ());
    let _ = require_aware(expires_at.clone(), String::from("expires_at")).unwrap_or_else(|_| ());
    if (expires_at.clone()) <= (created_at.clone()) {
        return Err("expires_at MUST be after created_at");
    }
    let mut scope: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("subscription_id"), subscription_id.clone())]);
    if let Some(mut resource_group) = resource_group.clone() {
        if (((resource_group.clone()).trim().to_string()).is_empty()) || ((((resource_group.clone()).len() as i64)) > (RESOURCE_GROUP_MAX)) {
            return Err("resource_group MUST be a bounded non-empty string");
        }
        scope.insert(String::from("resource_group"), resource_group.clone());
    }
    if let Some(mut resource_ref) = resource_ref.clone() {
        if ((resource_ref.clone()).trim().to_string()).is_empty() {
            return Err("resource_ref MUST be a non-empty string");
        }
        scope.insert(String::from("resource_ref"), resource_ref.clone());
    }
    if (!((scope.clone()).contains_key("resource_group"))) && (!((scope.clone()).contains_key("resource_ref"))) {
        return Err("exemption scope MUST name a resource group or resource a  subscription-w");
    }
    Ok(GovernanceDocument { path: format!("rule-catalog/exemptions/{}.json", exemption_id.clone()), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_rule_id(mut rule_id: String) -> Result<(), &'static str> {
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_justification(mut justification: String) -> Result<(), &'static str> {
    if !(((JUSTIFICATION_MIN) <= (((justification.clone()).len() as i64))) && ((((justification.clone()).len() as i64)) <= (JUSTIFICATION_MAX))) {
        return Err("justification MUST be _JUSTIFICATION_MIN-_JUSTIFICATION_MAX characters");
    }
    if (justification.clone()).contains("\0") {
        return Err("justification MUST NOT contain control bytes");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_distinct_principals(mut requested_by: String, mut approved_by: String) -> Result<(), &'static str> {
    if (requested_by.clone()) == (approved_by.clone()) {
        return Err("approved_by MUST differ from requested_by");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_aware(mut value: String, mut name: String) -> Result<(), &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn rfc3339(mut value: String) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["GovernanceDocument", "GovernanceWriterError", "RetirementMode", "render_exemption_grant", "render_rule_retirement"];
