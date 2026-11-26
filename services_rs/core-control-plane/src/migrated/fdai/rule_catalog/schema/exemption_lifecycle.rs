use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ExemptionLifecycleAction {
    #[default]
    AlertAheadOfExpiry,
    Expire,
}

impl ExemptionLifecycleAction {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::AlertAheadOfExpiry => "alert_ahead_of_expiry",
            Self::Expire => "expire",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExemptionLifecycleDecision {
    pub exemption_id: String,
    pub rule_id: String,
    pub action: ExemptionLifecycleAction,
    pub expires_at: String,
    pub at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExemptionAssignmentBinding {
    pub assignment_id: String,
    pub assignment_version: String,
    pub scope_ref: String,
}

impl ExemptionAssignmentBinding {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.assignment_id.trim().is_empty() { return Err("assignment_id must be non-empty"); }
        if self.assignment_version.trim().is_empty() { return Err("assignment_version must be non-empty"); }
        if self.scope_ref.trim().is_empty() { return Err("scope_ref must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExemptionExpiryCommand {
    pub schema_version: String,
    pub idempotency_key: String,
    pub exemption_id: String,
    pub active_exemption_revision: String,
    pub expired_exemption_revision: String,
    pub assignment_id: String,
    pub assignment_version: String,
    pub rule_id: String,
    pub scope_ref: String,
    #[allow(clippy::type_complexity)]
    pub scope: BTreeMap<String, Option<String>>,
    pub expires_at: String,
    pub issued_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExemptionExpiryDigestItem {
    pub exemption_id: String,
    pub exemption_revision: String,
    pub rule_id: String,
    pub requested_by: String,
    pub expires_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExemptionExpiryDigest {
    pub schema_version: String,
    pub generated_at: String,
    pub items: Vec<ExemptionExpiryDigestItem>,
}

impl ExemptionExpiryCommand {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn action_params(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("exemption_id"), self.exemption_id.clone()), (String::from("active_exemption_revision"), self.active_exemption_revision.clone()), (String::from("expired_exemption_revision"), self.expired_exemption_revision.clone()), (String::from("assignment_id"), self.assignment_id.clone()), (String::from("assignment_version"), self.assignment_version.clone()), (String::from("rule_id"), self.rule_id.clone()), (String::from("scope_ref"), self.scope_ref.clone()), (String::from("scope"), String::new()), (String::from("expires_at"), String::new())])
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn exemption_revision(mut exemption: String, mut state: Option<String>) -> String {
    if exemption.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn build_exemption_expiry_command(mut exemption: String, mut binding: ExemptionAssignmentBinding, mut issued_at: String) -> Result<ExemptionExpiryCommand, &'static str> {
    let active_revision: String = exemption_revision(exemption.clone(), None);
    let expired_revision: String = exemption_revision(exemption.clone(), None);
    Ok(ExemptionExpiryCommand { schema_version: String::from("1.0.0"), active_exemption_revision: active_revision.clone(), expired_exemption_revision: expired_revision.clone(), assignment_id: binding.assignment_id.clone(), assignment_version: binding.assignment_version.clone(), scope_ref: binding.scope_ref.clone(), issued_at: issued_at.clone(), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn plan_exemption_lifecycle(mut exemptions: Vec<String>, mut now: String, mut alert_lead: String) -> Result<Vec<ExemptionLifecycleDecision>, &'static str> {
    let mut decisions: Vec<ExemptionLifecycleDecision> = Vec::<ExemptionLifecycleDecision>::new();
    Ok(decisions.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["ExemptionAssignmentBinding", "ExemptionExpiryCommand", "ExemptionExpiryDigest", "ExemptionExpiryDigestItem", "ExemptionLifecycleAction", "ExemptionLifecycleDecision", "build_exemption_expiry_command", "exemption_revision", "plan_exemption_lifecycle"];
