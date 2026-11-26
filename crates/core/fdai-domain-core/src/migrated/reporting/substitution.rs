pub const TOKEN_RE: &str = "\\$\\$|\\$\\{([A-Za-z_][A-Za-z0-9_]*)\\}|\\$([A-Za-z_][A-Za-z0-9_]*)";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn substitute(mut value: String, mut variables: std::collections::BTreeMap<String, String>) -> String {
    if true {
        return substitute_string(value.clone(), variables.clone()).unwrap_or_else(|_| String::new());
    }
    value.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn substitute_string(mut value: String, mut variables: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
    if !((value.clone()).contains("$")) {
        return Ok(value.clone());
    }
    Ok(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["substitute"];
