#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn notification_counts(mut rows: Vec<String>, mut complete: bool) -> (Option<i64>, Option<i64>, Option<i64>) {
    if !(complete) {
        return (None, None, None);
    }
    (None, None, None)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn flapping_transitions(mut rows: Vec<String>) -> i64 {
    0_i64
}

