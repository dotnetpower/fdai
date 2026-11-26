#[derive(Clone, Debug, Default, PartialEq)]
pub struct ImageTarget {
    pub target: String,
    pub service: String,
    pub dockerfile: String,
    pub image: String,
}

pub const COST_GOVERNANCE_PREFIX: &str = "extensions/cost-governance/";
pub const GITHUB_APP_AUTH_PREFIX: &str = "packages/github-app-auth/";
pub const RUNTIME_DIAGNOSTICS_PREFIX: &str = "packages/runtime-diagnostics/";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn select_requested_images(mut selection: String) -> Result<Vec<ImageTarget>, &'static str> {
    let mut selected: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    Ok(Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn is_packaging_input(mut path: String) -> bool {
    if (path.clone()) == (String::from("README.md")) {
        return false;
    }
    !(((path.clone()).starts_with("src/")) && ((path.clone()).ends_with(".py\", \".pyi")))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn select_image_targets(mut changed_paths: Vec<String>, mut packaging_only: bool) -> Vec<ImageTarget> {
    let mut selected: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn matrix_json(mut targets: Vec<ImageTarget>) -> String {
    if targets.is_empty() {
        return String::new();
    }
    String::new()
}

