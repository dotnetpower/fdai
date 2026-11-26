pub const DIGEST: &str = "^[a-f0-9]{64}$";
pub const IDENTIFIER: &str = "^[A-Za-z][A-Za-z0-9_.:-]{0,199}$";
pub const PROPERTY: &str = "^[a-z][a-z0-9_]{0,63}$";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_bounded(mut value: String, mut label: String, mut maximum: i64) -> Result<(), &'static str> {
    if ((value.trim().to_string()).is_empty()) || ((((value.clone()).len() as i64)) > (maximum)) {
        return Err("label MUST be bounded and non-empty");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_digest(mut value: String, mut label: String) -> Result<(), &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_identifier(mut value: String, mut label: String) -> Result<(), &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_property_names(mut values: Vec<String>) -> Result<(), &'static str> {
    if values.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_unique(mut values: Vec<String>, mut label: String) -> Result<(), &'static str> {
    let materialized: Vec<String> = values.clone();
    if (((materialized.clone()).len() as i64)) != ((((materialized.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) {
        return Err("label MUST be unique");
    }
    Ok(())
}

pub const PUBLIC_EXPORTS: &[&str] = &["require_bounded", "require_digest", "require_identifier", "require_property_names", "require_unique"];
