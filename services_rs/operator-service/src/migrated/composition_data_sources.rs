#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_data_sources(mut configured: bool, mut inventory_configured: bool) -> Vec<String> {
    let reason: Option<String> = if configured { None } else { Some(String::from("Authoritative service-local projections are not configured.")) };
    Vec::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["_build_data_sources"];
