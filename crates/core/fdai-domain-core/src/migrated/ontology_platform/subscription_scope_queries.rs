#[derive(Clone, Debug, Default, PartialEq)]
pub struct SubscriptionScopeObservation {
    pub display_name: String,
    pub state: String,
    pub masked_subscription_id: String,
    pub observed_at: String,
    pub evidence_digest: String,
}

impl SubscriptionScopeObservation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.display_name.trim().is_empty() { return Err("display_name must be non-empty"); }
        if self.state.trim().is_empty() { return Err("state must be non-empty"); }
        if self.masked_subscription_id.trim().is_empty() { return Err("masked_subscription_id must be non-empty"); }
        if self.observed_at.trim().is_empty() { return Err("observed_at must be non-empty"); }
        if self.evidence_digest.trim().is_empty() { return Err("evidence_digest must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SubscriptionScopeCollection {
    #[allow(clippy::type_complexity)]
    pub observation: Option<Box<SubscriptionScopeObservation>>,
    pub observed_at: String,
    pub complete: bool,
    pub limitation: Option<String>,
    pub attempt_ref: String,
}

pub const SUBSCRIPTION_SCOPE_FUNCTION_NAME: &str = "query.subscription_scope_identity";
pub const SUBSCRIPTION_SCOPE_STATES: &[&str] = &["Deleted", "Disabled", "Enabled", "PastDue", "Warned"];
pub const DIGEST: &str = "^sha256:[a-f0-9]{64}$";
pub const MASKED_ID: &str = "^[a-f0-9]{4}\\.\\.\\.[a-f0-9]{4}$";
pub trait SubscriptionScopeReader {
    fn read(&self) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn subscription_scope_function_type() -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn subscription_scope_function(mut ontology_release: String, mut reader: String) -> Result<String, &'static str> {
    if ontology_release.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["SUBSCRIPTION_SCOPE_FUNCTION_NAME", "SUBSCRIPTION_SCOPE_MEASURE_CONCEPTS", "SUBSCRIPTION_SCOPE_STATES", "SubscriptionScopeCollection", "SubscriptionScopeObservation", "SubscriptionScopeReader", "subscription_scope_function", "subscription_scope_function_type"];
