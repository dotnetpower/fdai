#[derive(Clone, Debug, Default, PartialEq)]
pub struct PriorityInput {
    pub floor: String,
    pub ceiling: String,
    pub confidence: String,
    pub exposure: String,
    pub known_exploited: bool,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn matches(mut condition: String, mut item: PriorityInput) -> bool {
    if condition.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn assign_priority(mut item: PriorityInput, mut policy: String) -> String {
    if policy.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["PriorityInput", "assign_priority"];
