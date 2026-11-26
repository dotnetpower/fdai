#[derive(Clone, Debug, Default, PartialEq)]
pub struct OperationalProfile {
    pub profile_id: String,
    pub source_repository: String,
    pub source_revision: String,
    pub conformance_claimed: bool,
}

impl OperationalProfile {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.profile_id.trim().is_empty() { return Err("profile_id must be non-empty"); }
        if self.source_repository.trim().is_empty() { return Err("source_repository must be non-empty"); }
        if self.source_revision.trim().is_empty() { return Err("source_revision must be non-empty"); }
        Ok(())
    }
}

impl OperationalProfile {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn audit_context(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("safety_profile"), self.profile_id.clone()), (String::from("profile_source_ref"), format!("{}@{}", self.source_repository.clone(), self.source_revision.clone())), (String::from("conformance_claimed"), String::new())])
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["DEFAULT_PROFILE", "OperationalProfile"];
