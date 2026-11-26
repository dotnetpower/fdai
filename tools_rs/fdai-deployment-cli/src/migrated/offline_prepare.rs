#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn prepare_offline_release(mut kit: String, mut work_dir: String, mut profile: String, mut source_commit: String, mut release_root_pem: Vec<u8>, mut bundle_public_key_pem: Vec<u8>, mut cli_version: String, mut platform_tag: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut binding: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("source_commit"), source_commit.clone()), (String::from("profile_digest"), String::new()), (String::from("target_binding"), String::new()), (String::from("monthly_cost_ceiling"), String::new()), (String::from("offline_manifest_digest"), String::new()), (String::from("runtime_release_digest"), String::new()), (String::from("deployment_bundle_digest"), String::new()), (String::from("genesis_manifest_digest"), String::new()), (String::from("image_content_digests"), String::new())]);
    let result: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from("fdai.offline-preparation.v2")), (String::from("state"), String::from("prepared")), (String::from("subscription_ready"), String::new()), (String::from("mutation_performed"), String::new()), (String::from("production_release_eligibility"), String::from("unverified")), (String::from("binding"), String::new()), (String::from("preparation_digest"), String::new()), (String::from("stage_order"), String::new()), (String::from("next_action"), String::from("review-foundation-plan")), (String::from("required_checkpoints"), String::new())]);
    Ok(result.clone())
}

