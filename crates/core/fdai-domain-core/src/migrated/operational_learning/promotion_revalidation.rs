pub const PREPARATION_SECONDS: i64 = 5;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PreparedReplayReview {
    pub valid_from: String,
    pub valid_until: String,
    pub monotonic_deadline: f64,
    pub receipt_digest: String,
    pub verification_bundle_digest: String,
    pub evaluated_receipt_digest: String,
}

pub const REVIEWED_REPLAY_PROMOTION_PURPOSE: &str = "reviewed-replay-promotion";
impl PreparedReplayReview {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn current(&self, mut now: String) -> bool {
        if now.is_empty() {
            return false;
        }
        false
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::too_many_arguments)]
pub async fn prepare_replay_review(mut evidence: String, mut source: String, mut admission_provider: String, mut materializer: String, mut case_metadata: String, mut action_type: String, mut evaluator: String, mut clock: String) -> Option<PreparedReplayReview> {
    let mut source_deadlines: Vec<String> = Vec::<String>::new();
    Some(PreparedReplayReview::default())
}

