pub const FALSE_VALUES: &[&str] = &["0", "false", "no", "off"];
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn pantheon_start_enabled(mut environ: std::collections::BTreeMap<String, String>) -> bool {
    let raw: String = (((environ.clone()).get("FDAI_START_PANTHEON").cloned().unwrap_or_else(|| String::from(""))).trim().to_string()).to_lowercase();
    false
}

pub const PUBLIC_EXPORTS: &[&str] = &["pantheon_start_enabled"];
