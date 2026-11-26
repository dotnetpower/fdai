pub const PREFIX: &str = "cloud-reference:";
pub const SINGULAR: &[&str] = &["provider", "resource_type", "service_generation"];
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn cloud_reference_constraints(mut judgment: String, mut utterance: String) -> Result<Vec<String>, &'static str> {
    let mut constraints: Vec<String> = Vec::<String>::new();
    Ok(((constraints.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).into_iter().collect::<Vec<String>>())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn cloud_reference_arguments(mut frame: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let values: std::collections::BTreeMap<String, Vec<String>> = std::collections::BTreeMap::<String, Vec<String>>::new();
    if (values.clone()).is_empty() {
        return Ok(std::collections::BTreeMap::<String, String>::new());
    }
    let mut arguments: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("guidance_mode"), String::new())]);
    Ok(arguments.clone())
}

