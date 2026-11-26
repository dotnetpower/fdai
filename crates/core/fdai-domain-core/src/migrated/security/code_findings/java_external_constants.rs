#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn walk(mut node: String) -> Vec<String> {
    let mut stack: Vec<String> = vec![node.clone()];
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn field(mut node: Option<String>, mut name: String) -> Option<String> {
    if node.is_none() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn text(mut node: Option<String>) -> String {
    if node.is_none() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn static_string(mut node: Option<String>, mut constants: std::collections::BTreeMap<String, String>) -> Option<String> {
    let Some(mut node) = node.clone() else { return None; };
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn qualified_string_constants(mut root: String, mut source: Vec<u8>, mut max_file_bytes: i64) -> std::collections::BTreeMap<String, String> {
    let mut resolved: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    resolved.clone()
}

pub const PUBLIC_EXPORTS: &[&str] = &["qualified_string_constants"];
