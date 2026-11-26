pub const RESOURCE_TYPE_MISMATCH_REASON: &str = "t1_reuse_resource_type_mismatch";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn guard_reuse_resource_type(mut decision: String, mut rules_by_id: std::collections::BTreeMap<String, String>, mut resource_type: Option<String>) -> String {
    if decision.is_empty() {
        return String::new();
    }
    String::new()
}

