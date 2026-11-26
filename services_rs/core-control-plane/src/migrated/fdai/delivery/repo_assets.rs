pub const ASSET_MARKERS: &[&str] = &["rule-catalog", "config"];
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn repo_asset_root(mut start: Option<String>) -> Result<String, &'static str> {
    Err("repository asset root not found above origin")
}

pub const PUBLIC_EXPORTS: &[&str] = &["repo_asset_root"];
