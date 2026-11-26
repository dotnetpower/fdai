#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn verify_service_evidence(mut evidence: String, mut service: String) -> Result<bool, &'static str> {
    Ok(true)
}

pub const PUBLIC_EXPORTS: &[&str] = &["verify_service_evidence"];
