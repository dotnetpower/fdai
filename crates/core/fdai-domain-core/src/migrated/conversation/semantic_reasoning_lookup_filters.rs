pub const UNSUPPORTED: &str = "filter_unsupported_for_operation:lookup";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn restates_lookup_subject(mut goal: String, mut item: String) -> bool {
    if goal.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn lookup_filter_failure(mut goal: String, mut ctx: String) -> Option<String> {
    if goal.is_empty() {
        return None;
    }
    None
}

