#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum TargetDispatchFenceAcquireDecision {
    #[default]
    Acquired,
    DuplicateSame,
    Blocked,
}

impl TargetDispatchFenceAcquireDecision {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Acquired => "acquired",
            Self::DuplicateSame => "duplicate_same",
            Self::Blocked => "blocked",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TargetDispatchFenceAcquireResult {
    pub candidate_identity: String,
    pub decision: TargetDispatchFenceAcquireDecision,
    pub observed_record: String,
    pub transition_receipt: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TargetDispatchFenceReadback {
    pub record: String,
    pub recorded_at: String,
}

pub trait TargetDispatchFenceStore {
    fn acquire_generation(&self, record: String) -> TargetDispatchFenceAcquireResult;
    fn compare_and_transition(&self, prior_record_digest: String, expected_revision: i64, record: String) -> String;
    fn read(&self, target_digest: String) -> Option<String>;
    fn read_with_timestamp(&self, target_digest: String) -> Option<TargetDispatchFenceReadback>;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn classify_target_fence(mut existing: String, mut candidate: String) -> Result<TargetDispatchFenceAcquireDecision, &'static str> {
    if existing.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn target_mutation_blocked(mut record: Option<String>) -> bool {
    if record.is_none() {
        return false;
    }
    false
}

pub const PUBLIC_EXPORTS: &[&str] = &["TargetDispatchFenceAcquireDecision", "TargetDispatchFenceAcquireResult", "TargetDispatchFenceReadback", "TargetDispatchFenceStore", "classify_target_fence", "target_mutation_blocked"];
