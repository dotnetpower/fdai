#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn complete_application(mut kit: Option<String>, mut prepared: String, mut status: std::collections::BTreeMap<String, String>, mut scripts: String, mut deadline: String, mut selected_runtime: String, mut trial_token: Option<String>, mut application_state_adoption: Option<String>, mut foundation_state_receipt_digest: String, mut current_operator_object_id: String, mut foundation_adoption_receipt_digest: Option<String>, mut catalog_review_profile: Option<String>, mut operational_evidence_verifier_input: Option<String>, mut notification_recipients: Option<String>, mut development_authority_profile: Option<String>, mut clear_development_authority_profile: bool, mut control_package: Option<String>, mut source_snapshot: Option<String>, mut source_snapshot_digest: Option<String>, mut source_root: Option<String>, mut foundation_recovery_directory: Option<String>, mut hub_selection: Option<String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut entra_bindings: Option<std::collections::BTreeMap<String, String>> = None;
    let mut result: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from("fdai.standalone-azure-deployment.v2")), (String::from("state"), String::from("deployment-ready")), (String::from("source_commit"), String::new()), (String::from("foundation_state_receipt_digest"), foundation_state_receipt_digest.clone()), (String::from("application_receipt_digest"), String::new()), (String::from("catalog_review_receipt_digest"), String::new()), (String::from("catalog_review_state"), String::new()), (String::from("runtime_profile_digest"), String::new()), (String::from("runtime_platform"), String::new()), (String::from("database_placement"), String::new()), (String::from("product_profile"), String::new()), (String::from("application_converged"), String::new()), (String::from("deployment_ready"), String::new()), (String::from("inventory_ready"), String::new()), (String::from("license_mode"), String::new()), (String::from("mutation_performed"), String::new()), (String::from("subscription_ready"), String::new())]);
    if source_snapshot_digest.is_some() {
        result.insert(String::from("source_snapshot_digest"), (source_snapshot_digest.clone()).unwrap_or_default());
        result.insert(String::from("provenance"), String::from("operator-selected-source"));
    }
    if let Some(mut foundation_adoption_receipt_digest) = foundation_adoption_receipt_digest.clone() {
        result.insert(String::from("foundation_adoption_receipt_digest"), foundation_adoption_receipt_digest.clone());
    }
    Ok(result.clone())
}

