pub const VERSION_TAG: &str = "^v(\\d+)\\.(\\d+)\\.(\\d+)$";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn next_version(mut tags: Vec<String>) -> String {
    if tags.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn repository_tags() -> Vec<String> {
    core::hint::black_box(Vec::new())
}

