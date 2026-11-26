pub const RESOURCE_OBJECT_TYPE: &str = "Resource";
pub const RESOURCE_TYPE_PROPERTY: &str = "type";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn resource_type_value_domains(mut registry: String) -> Vec<String> {
    let members: std::collections::BTreeMap<String, std::collections::BTreeSet<String>> = std::collections::BTreeMap::<String, std::collections::BTreeSet<String>>::new();
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn resource_location_value_domains(mut registry: String) -> Vec<String> {
    if registry.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn lifecycle_value_domains() -> Vec<String> {
    core::hint::black_box(Vec::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["lifecycle_value_domains", "resource_location_value_domains", "resource_type_value_domains"];
