#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn provision_plan(mut args: String, mut print_mapping: String) -> i64 {
    0_i64
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn provision_update(mut args: String, mut print_mapping: String, mut deploy: String) -> Result<i64, &'static str> {
    Ok(0_i64)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn provision_service_update(mut args: String) -> i64 {
    0_i64
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn attach_timing(mut result: std::collections::BTreeMap<String, String>, mut progress: String, mut work_dir: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("timing_receipt_digest"), String::new())])
}

pub const PUBLIC_EXPORTS: &[&str] = &["attach_timing", "provision_plan", "provision_service_update", "provision_update"];
