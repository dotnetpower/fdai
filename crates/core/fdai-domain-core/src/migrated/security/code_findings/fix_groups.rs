#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn group_key(mut issue: String) -> (String, String) {
    (String::new(), String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn project_for(mut path: String, mut roots: Vec<String>) -> Option<String> {
    if path.is_empty() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn allowed_paths(mut issues: Vec<String>, mut test_globs: Vec<String>, mut include_flow_paths: bool) -> Vec<String> {
    let mut paths: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_fix_groups(mut issues: Vec<String>, mut catalog: String, mut project_roots: Vec<String>, mut include_flow_paths: bool) -> Vec<String> {
    let mut drafts: Vec<((i64, i64, String, String), String)> = Vec::<((i64, i64, String, String), String)>::new();
    Vec::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["build_fix_groups"];
