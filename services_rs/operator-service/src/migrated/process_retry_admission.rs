#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn retry_is_permitted(mut status: String, mut events: Vec<std::collections::BTreeMap<String, String>>, mut attempt: i64, mut max_attempts: i64) -> bool {
    if (!(matches!(status.as_str(), "failed" | "timed_out"))) || ((attempt) >= (max_attempts)) {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn event_attempt(mut event: std::collections::BTreeMap<String, String>) -> i64 {
    0_i64
}

pub const PUBLIC_EXPORTS: &[&str] = &["retry_is_permitted"];
