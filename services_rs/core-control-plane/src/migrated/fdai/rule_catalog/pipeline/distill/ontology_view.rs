#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_ontology_review_view(mut package: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("package_digest"), String::new()), (String::from("document"), String::new()), (String::from("target"), String::new()), (String::from("summary"), String::new()), (String::from("claims"), String::new()), (String::from("proposals"), String::new()), (String::from("issues"), String::new())])
}

pub const PUBLIC_EXPORTS: &[&str] = &["build_ontology_review_view"];
