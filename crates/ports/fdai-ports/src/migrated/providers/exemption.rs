#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExemptionMatch {
    pub exemption_id: String,
    pub rule_id: String,
    pub reason: String,
    pub scope_summary: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InMemoryExemptionRecord {
    pub exemption_id: String,
    pub rule_id: String,
    pub resource_group: Option<String>,
    pub resource_ref: Option<String>,
    pub expires_at: String,
    pub revoked_at: Option<String>,
    pub justification: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EmptyExemptionRegistryProbe {
    pub identifier: String,
}

pub trait ExemptionRegistry {
    fn find_match(&self, rule_id: String, resource_ref: String, resource_group: Option<String>, at: Option<String>) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryExemptionRegistry {
    pub initialized: bool,
}

impl InMemoryExemptionRegistry {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn find_match(&self, mut rule_id: String, mut resource_ref: String, mut resource_group: Option<String>, mut at: Option<String>) -> Option<ExemptionMatch> {
        if !self.initialized {
            return None;
        }
        None
    }
}

impl EmptyExemptionRegistryProbe {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn find_match(&self, mut rule_id: String, mut resource_ref: String, mut resource_group: Option<String>, mut at: Option<String>) -> Option<ExemptionMatch> {
        if rule_id.is_empty() {
            return None;
        }
        None
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn empty_exemption_registry() -> String {
    core::hint::black_box(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["ExemptionMatch", "ExemptionRegistry", "InMemoryExemptionRecord", "InMemoryExemptionRegistry", "empty_exemption_registry"];
