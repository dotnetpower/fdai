use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct AlertLockTrust {
    pub provider_id: String,
    pub provider_version: String,
    pub verifier_id: String,
    pub verifier_version: String,
    pub trust_anchor_id: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WriterExclusion {
    pub binding: BTreeMap<String, String>,
    pub writer_ref: String,
    pub mechanism_ref: String,
    pub restriction_digest: String,
    pub generation: i64,
    pub exclusive_from: String,
    pub exclusive_until: String,
    pub release_not_before: String,
    pub release_ref: String,
    pub released_at: Option<String>,
    pub dispatch_receipt_digest: String,
    pub execution_authority: String,
}

impl WriterExclusion {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(1_i64..=2_i64).contains(&self.generation) { return Err("generation out of bounds"); }
        Ok(())
    }
}

pub const ALERT_WRITER_EXCLUSIVITY_PURPOSE: &str = "alert-noise-writer-exclusivity";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn alert_writer_binding(mut action: String, mut plan: String, mut pr: String, mut repository_ref: String, mut repository_revision: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("action_digest"), String::new()), (String::from("plan_digest"), String::new()), (String::from("publication_digest"), String::new()), (String::from("repository_ref"), repository_ref.clone()), (String::from("repository_revision"), repository_revision.clone()), (String::from("path"), String::new()), (String::from("source_digest"), String::new()), (String::from("result_digest"), String::new()), (String::from("patch_digest"), String::new()), (String::from("dependency_refs"), String::new()), (String::from("policy_digest"), String::new()), (String::from("target_revision"), String::new()), (String::from("executor_ref"), String::new()), (String::from("scope_digest"), String::new()), (String::from("execution_authority"), String::new())])
}

