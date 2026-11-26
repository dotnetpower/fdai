#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn tracked_root_files(mut root: String, mut cached: bool) -> std::collections::BTreeSet<String> {
    std::collections::BTreeSet::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn untracked_root_files(mut root: String) -> std::collections::BTreeSet<String> {
    std::collections::BTreeSet::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn allowed_root_files(mut path: String) -> std::collections::BTreeSet<String> {
    std::collections::BTreeSet::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn py_validate(mut root: String, mut allowlist: String, mut cached: bool) -> (Vec<String>, Vec<String>) {
    let tracked: std::collections::BTreeSet<String> = tracked_root_files(root.clone(), cached);
    let allowed: std::collections::BTreeSet<String> = allowed_root_files(allowlist.clone());
    (Vec::new(), Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn main(mut argv: Option<Vec<String>>) -> i64 {
    0_i64
}

