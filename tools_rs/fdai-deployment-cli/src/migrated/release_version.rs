pub const PRERELEASE_IDENTIFIER: &str = "(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn canonical_release_version(mut value: String, mut context: String) -> Result<String, &'static str> {
    Ok(value.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["canonical_release_version"];
