#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn canonical_catalog_digest(mut record: String, mut exclude: std::collections::BTreeSet<String>) -> String {
    if record.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["canonical_catalog_digest"];
