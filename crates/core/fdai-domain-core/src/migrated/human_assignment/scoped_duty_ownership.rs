#[derive(Clone, Debug, Default, PartialEq)]
pub struct ScopedDutyMergeObservation {
    pub pr_ref: String,
    pub path: String,
    pub candidate_digest: String,
    pub merge_commit_sha: String,
    pub observed_at: String,
    pub expires_at: String,
}

impl ScopedDutyMergeObservation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.pr_ref.trim().is_empty() { return Err("pr_ref must be non-empty"); }
        if self.path.trim().is_empty() { return Err("path must be non-empty"); }
        if self.candidate_digest.trim().is_empty() { return Err("candidate_digest must be non-empty"); }
        if self.merge_commit_sha.trim().is_empty() { return Err("merge_commit_sha must be non-empty"); }
        if self.observed_at.trim().is_empty() { return Err("observed_at must be non-empty"); }
        if self.expires_at.trim().is_empty() { return Err("expires_at must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ScopedDutyOwnership {
    pub cases: String,
    pub publisher: String,
    pub locks: String,
    pub merges: String,
}

pub trait ScopedDutyMergeReader {
    fn read(&self, pr_ref: String, path: String, candidate_digest: String) -> Option<ScopedDutyMergeObservation>;
}

impl ScopedDutyOwnership {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn open_proposal(&self, mut case_id: String, mut expected_revision: i64) -> Result<String, &'static str> {
        let key: String = format!("{}{}", String::from("human_assignment:scoped-artifact-intent:"), case_id.clone());
        let intent: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("case_id"), case_id.clone()), (String::from("candidate_digest"), String::new()), (String::from("path"), String::new())]);
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn observe(&self, mut current: String) -> Result<Vec<std::collections::BTreeMap<String, String>>, &'static str> {
        if current.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn scoped_artifact(mut case: String) -> (String, String, String) {
    (String::new(), String::new(), String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["ScopedDutyMergeObservation", "ScopedDutyMergeReader", "ScopedDutyOwnership", "scoped_artifact"];
