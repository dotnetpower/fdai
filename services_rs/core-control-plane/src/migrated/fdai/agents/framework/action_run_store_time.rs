#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn lease_expiry(mut seconds: i64, mut clock: Option<String>) -> Result<String, &'static str> {
    if clock.is_none() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn claim_lease_expiry(mut claim: std::collections::BTreeMap<String, String>) -> String {
    let raw: Option<String> = (claim.clone()).get("lease_expires_at").cloned();
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["claim_lease_expiry", "lease_expiry"];
