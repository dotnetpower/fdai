#[derive(Clone, Debug, Default, PartialEq)]
pub struct OperationalFamilyValidation {
    pub primary_intent: String,
    pub normalized_facets: Vec<String>,
}

pub const SUBSCRIPTION_SCOPE_FACETS: &[&str] = &["subscription"];
pub const SUBSCRIPTION_SERVICE_HEALTH_FACETS: &[&str] = &["service_health"];
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn validate_operational_family(mut proposal: String, mut normalized_targets: Vec<String>, mut utterance: String) -> Option<OperationalFamilyValidation> {
    Some(OperationalFamilyValidation::default())
}

