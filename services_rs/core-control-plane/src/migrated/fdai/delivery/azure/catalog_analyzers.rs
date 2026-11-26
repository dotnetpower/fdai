#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn catalog_analyzer_kind_by_resource_type(mut repo_root: Option<String>) -> std::collections::BTreeMap<String, String> {
    let mut mapping: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_catalog_resource_type_analyzers(mut provider: String, mut wall_clock: Option<String>, mut repo_root: Option<String>) -> Vec<String> {
    let mut analyzers: Vec<String> = Vec::<String>::new();
    analyzers.clone()
}

pub const PUBLIC_EXPORTS: &[&str] = &["build_catalog_resource_type_analyzers", "catalog_analyzer_kind_by_resource_type"];
