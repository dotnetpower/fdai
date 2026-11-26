#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn add_finalization_parser(mut subcommands: String, mut services: std::collections::BTreeSet<String>) {
    if subcommands.is_empty() {
        return;
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn finalize_service_update(mut args: String, mut work_dir: String, mut private_json: String, mut replace_private_json: String, mut service_update_record: String, mut service_update_review: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut result: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from("fdai.aks-service-update-finalization.v1")), (String::from("state"), String::from("finalized")), (String::from("operation"), String::new()), (String::from("service"), String::new()), (String::from("update_digest"), String::new()), (String::from("apply_receipt_digest"), String::new()), (String::from("mutation_performed"), String::new()), (String::from("subscription_ready"), String::new())]);
    Ok(result.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn finalize_service_update_fn(mut args: String, mut work_dir: String) -> std::collections::BTreeMap<String, String> {
    finalize_service_update(args.clone(), work_dir.clone(), String::new(), String::new(), String::new(), String::new()).unwrap_or_else(|_| std::collections::BTreeMap::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["add_finalization_parser", "finalize_service_update"];
