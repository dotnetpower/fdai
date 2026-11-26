#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn lineage_count_goal(mut goal: String, mut ctx: String, mut selector: String, mut predicates: Vec<std::collections::BTreeMap<String, String>>, mut group: Vec<String>) -> String {
    if goal.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn lineage_traversal_violations(mut lineage_group: bool, mut plans: Vec<String>) -> Vec<String> {
    if plans.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["lineage_count_goal", "lineage_traversal_violations"];
