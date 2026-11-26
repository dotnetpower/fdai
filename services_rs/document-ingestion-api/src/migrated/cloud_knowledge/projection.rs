pub trait ListVersions {
    fn call(&self, actor_id: String, actor_groups: std::collections::BTreeSet<String>, document_id: String) -> (String, String);
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn project_source(mut version: String, mut serialized: String, mut read_checkpoint: String, mut clock: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::from([(String::from("source_id"), String::new()), (String::from("collected_at"), String::new()), (String::from("checked_at"), String::new()), (String::from("update_pending"), String::new()), (String::from("freshness"), String::new()), (String::from("source_url"), String::new()), (String::from("applicability"), String::new()), (String::from("retrieval_mode"), String::from("lexical")), (String::from("live_observation"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::too_many_arguments)]
pub async fn project_status(mut actor_id: String, mut actor_groups: std::collections::BTreeSet<String>, mut registry: String, mut list_versions: String, mut read_checkpoint: String, mut check_policy: String, mut content_admitted: String, mut clock: String, mut document_id_for: String) -> std::collections::BTreeMap<String, String> {
    let mut rows: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
    let mut collections: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
    let mut policy_current: bool = true;
    std::collections::BTreeMap::from([(String::from("available"), String::new()), (String::from("policy_current"), String::new()), (String::from("reason"), String::new()), (String::from("registry_revision"), String::new()), (String::from("registry_valid_until"), String::new()), (String::from("sources"), String::new()), (String::from("collections"), String::new()), (String::from("automatic_activation"), String::new()), (String::from("approval_required"), String::new())])
}

