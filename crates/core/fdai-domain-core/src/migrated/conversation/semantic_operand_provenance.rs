#[derive(Clone, Debug, Default, PartialEq)]
pub struct IdentityBindingReceipt {
    pub source: String,
    pub lookup: String,
    pub identity: String,
    pub span: Option<String>,
}

impl IdentityBindingReceipt {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.source.trim().is_empty() { return Err("source must be non-empty"); }
        if self.lookup.trim().is_empty() { return Err("lookup must be non-empty"); }
        if self.identity.trim().is_empty() { return Err("identity must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProvenanceScope {
    pub enforced: bool,
    pub receipts: Vec<IdentityBindingReceipt>,
    pub utterance: String,
    pub context: Vec<String>,
}

pub const IDENTITY_PROPERTIES: &[&str] = &["id", "name", "display_name"];
pub const IDENTITY_OPERATORS: &[&str] = &["equals", "in", "equals_ignore_case"];
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn unproven_identity_operands(mut plan: String, mut utterance: String, mut context: Vec<String>, mut receipts: Vec<IdentityBindingReceipt>) -> Vec<String> {
    if plan.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn provenance_scope(mut enforce_when: String, mut bound: String, mut utterance: String, mut context: Vec<String>) -> ProvenanceScope {
    ProvenanceScope::default()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn literally_present(mut operand: String, mut text: String) -> bool {
    if (operand.trim().to_string()).is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn node_operands(mut kind: String, mut value: std::collections::BTreeMap<String, String>) -> Vec<String> {
    let mut found: Vec<String> = Vec::<String>::new();
    found.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn predicate_operands(mut value: std::collections::BTreeMap<String, String>) -> Vec<String> {
    let property_name: Option<String> = (value.clone()).get("property").cloned();
    let operator: Option<String> = (value.clone()).get("operator").cloned();
    let mut found: Vec<String> = Vec::<String>::new();
    found.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn identity_values(mut value: String) -> Vec<String> {
    if value.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["IdentityBindingReceipt", "ProvenanceScope", "provenance_scope", "trusted_bound_context", "unproven_identity_operands"];
