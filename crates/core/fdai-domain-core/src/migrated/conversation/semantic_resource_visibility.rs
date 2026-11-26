pub const OPERATIONAL_RESOURCE_EXCLUDED_TYPES: &[&str] = &["authorization.role-assignment"];
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn exclude_hidden_operational_resources(mut plan: String, mut output_shape: String, mut descriptors: Vec<std::collections::BTreeMap<String, String>>) -> String {
    let excluded_types: Vec<String> = declared_excluded_resource_types(descriptors.clone());
    let mut changed: bool = false;
    let mut nodes: Vec<String> = Vec::<String>::new();
    if !(changed) {
        return plan.clone();
    }
    let payload: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("nodes"), String::new())]);
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn declared_excluded_resource_types(mut descriptors: Vec<std::collections::BTreeMap<String, String>>) -> Vec<String> {
    for descriptor in descriptors.clone() {
        if (((descriptor.clone()).get("kind").cloned()) != Some(String::from("object"))) || (((descriptor.clone()).get("name").cloned()) != Some(String::from("Resource"))) {
            continue;
        }
        let properties: Option<String> = (descriptor.clone()).get("properties").cloned();
    }
    Vec::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["OPERATIONAL_RESOURCE_EXCLUDED_TYPES", "exclude_hidden_operational_resources"];
