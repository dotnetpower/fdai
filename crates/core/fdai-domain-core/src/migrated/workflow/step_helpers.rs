#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn redacted_params(mut step: String, mut params: std::collections::BTreeMap<String, String>, mut action_types: std::collections::BTreeMap<String, String>) -> (std::collections::BTreeMap<String, String>, std::collections::BTreeSet<String>) {
    (std::collections::BTreeMap::new(), std::collections::BTreeSet::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::too_many_arguments)]
pub fn branch_event(mut process_id: String, mut step: String, mut branch: String, mut kind: String, mut suffix: String, mut recorded_at: String, mut correlation_id: String, mut attempt: i64) -> String {
    if process_id.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn timed_out(mut step: String, mut context: std::collections::BTreeMap<String, String>, mut now: String) -> bool {
    if step.is_empty() {
        return false;
    }
    false
}

pub const PUBLIC_EXPORTS: &[&str] = &["branch_event", "redacted_params", "timed_out"];
