use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadContext {
    pub subscription_id: String,
    pub region: String,
    pub azure_cli: String,
    pub capture: String,
    pub cwd: String,
    pub environment: BTreeMap<String, String>,
}

pub const SKU_EVIDENCE_NAME: &str = "runner-image-sku-evidence.json";
pub const QUOTA_EVIDENCE_NAME: &str = "runner-image-quota-evidence.json";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn select_image_vm_inputs(mut inputs: String, mut terraform_root: String, mut destination: String, mut azure_cli: String, mut capture: String, mut cwd: String, mut environment: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
    let selected: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from("fdai.runner-image-sku-selection.v1")), (String::from("build_vm_size"), String::new()), (String::from("verify_vm_size"), String::new()), (String::from("policy_digest"), String::new()), (String::from("sku_evidence_digest"), String::new()), (String::from("quota_evidence_digest"), String::new()), (String::from("checked_at"), String::new()), (String::from("capacity_reserved"), String::new())]);
    let values: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("build_vm_size"), String::new()), (String::from("verify_vm_size"), String::new())]);
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn recheck_image_vm_inputs(mut projection: Vec<u8>, mut selection: String, mut terraform_root: String, mut subscription_id: String, mut region: String, mut azure_cli: String, mut capture: String, mut cwd: String, mut environment: std::collections::BTreeMap<String, String>) -> Result<(), &'static str> {
    if false {
        return Ok(());
    }
    Ok(())
}

