#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn prepare_source_deployment(mut source_root: String, mut work_dir: String, mut runtime_profile: String, mut region: String, mut monthly_cost_ceiling: i64, mut hub_selection_digest: Option<String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut intent: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from("fdai.source-deployment-intent.v1")), (String::from("source"), String::new()), (String::from("source_input_digest"), String::new()), (String::from("runtime_profile"), String::new()), (String::from("environment"), String::from("dev")), (String::from("region"), region.clone()), (String::from("monthly_cost_ceiling"), String::new())]);
    if let Some(mut hub_selection_digest) = hub_selection_digest.clone() {
        intent.insert(String::from("hub_selection_digest"), hub_selection_digest.clone());
        intent.insert(String::from("artifact_source"), String::from("hub-signed-images"));
    }
    let mut result: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from("fdai.source-deployment-preparation.v1")), (String::from("state"), String::from("prepared")), (String::from("provenance"), String::from("operator-selected-source")), (String::from("source_commit"), String::new()), (String::from("source_input_digest"), String::new()), (String::from("source_snapshot_digest"), String::new()), (String::from("intent_digest"), String::new()), (String::from("runtime_profile_digest"), String::new()), (String::from("release_signature_verified"), String::new()), (String::from("apply_authorized"), String::new()), (String::from("mutation_performed"), String::new()), (String::from("deployment_ready"), String::new()), (String::from("subscription_ready"), String::new())]);
    if let Some(mut hub_selection_digest) = hub_selection_digest.clone() {
        result.insert(String::from("hub_selection_digest"), hub_selection_digest.clone());
        result.insert(String::from("image_artifact_source"), String::from("hub-signed-images"));
    }
    return Ok(result.clone());
}

