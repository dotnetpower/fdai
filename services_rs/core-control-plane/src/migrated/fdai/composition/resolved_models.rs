#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_resolved_models(mut path_or_ref: String, mut expected_digest: Option<String>) -> Result<String, &'static str> {
    let stripped: String = path_or_ref.trim().to_string();
    if (stripped.clone()).starts_with("{") {
        let mut content: String = path_or_ref.clone();
    }
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn capability(mut resolved: String, mut name: String, mut held_capabilities: std::collections::BTreeSet<String>) -> Option<String> {
    if (held_capabilities.clone()).contains(name.as_str()) {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn default_dim_for_family(mut family: String) -> Result<i64, &'static str> {
    if !(matches!(family.as_str(), "text-embedding-3-small" | "text-embedding-3-large")) {
        return Err("embedding family familyr does not support the FDAI 384-dimension contrac");
    }
    Ok(384_i64)
}

