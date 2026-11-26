#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn argument_name(mut value: String) -> Result<String, &'static str> {
    let parts: Vec<String> = (value.clone()).split(".").map(str::to_string).collect::<Vec<String>>();
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn evidence_refs(mut dependencies: std::collections::BTreeMap<String, String>) -> Vec<String> {
    if dependencies.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["argument_name", "evidence_refs"];
