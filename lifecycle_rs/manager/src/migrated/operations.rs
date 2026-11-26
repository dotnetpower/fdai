pub const IMAGE: &str = ".+@sha256:[0-9a-f]{64}\\Z";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn write_catalog_requests(mut prepared: String, mut publication_receipt: String) -> Result<(String, String), &'static str> {
    let _ = write_json(String::new(), String::new()).unwrap_or_else(|_| ());
    let _ = write_json(String::new(), String::new()).unwrap_or_else(|_| ());
    Ok((String::new(), String::new()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn write_native_acceptance(mut prepared: String, mut proof: String) -> Result<String, &'static str> {
    if prepared.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::too_many_arguments)]
pub fn write_agent_tfvars(mut prepared: String, mut destination: String, mut subscription_id: String, mut tenant_id: String, mut location: String, mut resource_group_name: String, mut prefix: String, mut kubeconfig_path: String, mut kubeconfig_context: String, mut cluster_oidc_issuer_url: String, mut hub_url: String, mut hub_api_client_id: String, mut hub_agent_role_id: String, mut agent_image: String, mut enable_agent: bool, mut native_state_path: Option<String>) -> Result<String, &'static str> {
    let value: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("subscription_id"), subscription_id.clone()), (String::from("tenant_id"), tenant_id.clone()), (String::from("location"), location.clone()), (String::from("resource_group_name"), resource_group_name.clone()), (String::from("prefix"), prefix.clone()), (String::from("tags"), String::new()), (String::from("kubeconfig_path"), kubeconfig_path.clone()), (String::from("kubeconfig_context"), kubeconfig_context.clone()), (String::from("cluster_oidc_issuer_url"), cluster_oidc_issuer_url.clone()), (String::from("hub"), String::new()), (String::from("installation"), String::new()), (String::from("agent_image"), agent_image.clone()), (String::from("enable_agent"), String::new())]);
    let _ = write_json(destination.clone(), String::new()).unwrap_or_else(|_| ());
    Ok(destination.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn prepared(mut path: String) -> Result<(String, String), &'static str> {
    Ok((String::new(), String::new()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn write_json(mut path: String, mut value: String) -> Result<(), &'static str> {
    if path.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["write_agent_tfvars", "write_catalog_requests", "write_native_acceptance"];
