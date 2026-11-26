pub const GENESIS_HASH: &str = "0000000000000000000000000000000000000000000000000000000000000000";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn canonical_entry(mut entry: std::collections::BTreeMap<String, String>) -> String {
    if entry.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn next_hash(mut previous: String, mut entry: std::collections::BTreeMap<String, String>) -> String {
    if previous.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["GENESIS_HASH", "canonical_entry", "next_hash"];
