#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn reviewed_property_paths(mut reads: Vec<String>) -> std::collections::BTreeMap<String, std::collections::BTreeSet<String>> {
    let by_path: std::collections::BTreeMap<String, std::collections::BTreeSet<String>> = std::collections::BTreeMap::<String, std::collections::BTreeSet<String>>::new();
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn reviewed_fields_for_resource_set(mut node: String, mut reviewed: std::collections::BTreeMap<String, std::collections::BTreeSet<String>>) -> std::collections::BTreeMap<String, std::collections::BTreeSet<String>> {
    let mut resource_types: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    std::collections::BTreeMap::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["reviewed_fields_for_resource_set", "reviewed_property_paths"];
