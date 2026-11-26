#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn deploy_with_adopted_foundation(mut foundation_directory: Option<String>, mut recovery_directory: Option<String>, mut adopt_runner_image_receipt: Option<String>, mut work_dir: String, mut kit: String, mut tenant_id: String, mut subscription_id: String, mut region: String, mut monthly_cost_ceiling: i64, mut deadline: String, mut selected_runtime: String, mut trial_token: Option<String>, mut application_state_adoption: Option<String>, mut catalog_review_profile: Option<String>, mut operational_evidence_verifier_input: Option<String>, mut current_operator_object_id: String, mut control_package: Option<String>) -> Result<Option<std::collections::BTreeMap<String, String>>, &'static str> {
    if let Some(mut adopt_runner_image_receipt) = adopt_runner_image_receipt.clone() {
        return Err("Foundation adoption cannot combine with runner-image adoption");
    }
    if !(foundation_directory.is_some()) { return Err("assertion_failed"); }
    if !(recovery_directory.is_some()) { return Err("assertion_failed"); }
    Ok(None)
}

