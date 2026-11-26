#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn without_controls(mut value: String) -> Result<String, &'static str> {
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn aware_datetime(mut value: String) -> Result<String, &'static str> {
    Ok(value.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["AwareDatetime", "BoundedText", "Identifier", "MediaType", "Sha256Digest"];
