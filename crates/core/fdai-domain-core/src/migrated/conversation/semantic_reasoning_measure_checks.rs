#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn is_health_lookup(mut goal: String) -> bool {
    if goal.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn is_state_history(mut goal: String) -> bool {
    if goal.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn metric_scope_violations(mut node: String, mut goal: String, mut evaluation_time: Option<String>) -> Vec<String> {
    Vec::<String>::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn expected_measure_arguments(mut name: Option<String>, mut goal: String, mut lookback_seconds: Option<i64>, mut evaluation_time: Option<String>) -> Option<std::collections::BTreeMap<String, String>> {
    if name.is_none() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn window_matches(mut arguments: std::collections::BTreeMap<String, String>, mut lookback: i64, mut limit: i64, mut evaluation_time: String) -> bool {
    if arguments.is_empty() {
        return false;
    }
    false
}

pub const PUBLIC_EXPORTS: &[&str] = &["window_matches", "expected_measure_arguments", "is_health_lookup", "is_state_history", "metric_scope_violations"];
