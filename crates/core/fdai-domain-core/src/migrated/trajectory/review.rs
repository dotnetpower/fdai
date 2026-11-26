#[derive(Clone, Debug, Default, PartialEq)]
pub struct TrajectoryLearningAggregate {
    pub record_count: i64,
    pub outcome_counts: Vec<String>,
    pub tool_request_counts: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReviewedTrajectoryDataset {
    pub dataset_id: String,
    pub manifest_checksum: String,
    pub reviewed_by: String,
    pub reviewed_at: String,
    pub review_ref: String,
    pub aggregate: Box<TrajectoryLearningAggregate>,
}

impl ReviewedTrajectoryDataset {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.dataset_id.trim().is_empty() { return Err("dataset_id must be non-empty"); }
        if self.manifest_checksum.trim().is_empty() { return Err("manifest_checksum must be non-empty"); }
        if self.reviewed_by.trim().is_empty() { return Err("reviewed_by must be non-empty"); }
        if self.reviewed_at.trim().is_empty() { return Err("reviewed_at must be non-empty"); }
        if self.review_ref.trim().is_empty() { return Err("review_ref must be non-empty"); }
        Ok(())
    }
}

pub const DIGEST: &str = "^[0-9a-f]{64}$";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn ordered_counts(mut name: String, mut values: Vec<(String, i64)>) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["ReviewedTrajectoryDataset", "TrajectoryLearningAggregate"];
