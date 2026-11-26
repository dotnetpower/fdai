#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn platform_manifest(mut release: String, mut interfaces: String, mut action_types: Vec<String>, mut functions: Vec<String>) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("release_digest"), String::new()), (String::from("interfaces"), String::new()), (String::from("action_types"), String::new()), (String::from("functions"), String::new()), (String::from("mutation_authority"), String::new()), (String::from("write_surface"), String::from("typed_proposal"))])
}

pub const PUBLIC_EXPORTS: &[&str] = &["platform_manifest"];
