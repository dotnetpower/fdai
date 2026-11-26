#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReviewedReplayBinding {
    pub candidate_digest: String,
    pub package_digest: String,
    pub replay_first_digest: String,
    pub replay_second_digest: String,
    pub immutable_case_refs: Vec<String>,
    pub access_scope_digest: String,
    pub purpose: String,
}

impl ReviewedReplayBinding {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.candidate_digest.trim().is_empty() { return Err("candidate_digest must be non-empty"); }
        if self.package_digest.trim().is_empty() { return Err("package_digest must be non-empty"); }
        if self.replay_first_digest.trim().is_empty() { return Err("replay_first_digest must be non-empty"); }
        if self.replay_second_digest.trim().is_empty() { return Err("replay_second_digest must be non-empty"); }
        if self.access_scope_digest.trim().is_empty() { return Err("access_scope_digest must be non-empty"); }
        if self.purpose.trim().is_empty() { return Err("purpose must be non-empty"); }
        Ok(())
    }
}

pub const DIGEST: &str = "^[0-9a-f]{64}$";
impl ReviewedReplayBinding {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("candidate_digest"), self.candidate_digest.clone()), (String::from("package_digest"), self.package_digest.clone()), (String::from("replay_first_digest"), self.replay_first_digest.clone()), (String::from("replay_second_digest"), self.replay_second_digest.clone()), (String::from("immutable_case_refs"), String::new()), (String::from("access_scope_digest"), self.access_scope_digest.clone()), (String::from("purpose"), self.purpose.clone())])
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn from_mapping(mut value: String) -> Result<ReviewedReplayBinding, &'static str> {
        if value.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

