#[derive(Clone, Debug, Default, PartialEq)]
pub struct PollLimits {
    pub max_polls: i64,
    pub interval_seconds: f64,
    pub max_duration_seconds: f64,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn poll_bounded(mut poll: String, mut limits: PollLimits, mut monotonic: String, mut sleep: String) -> i64 {
    0_i64
}

