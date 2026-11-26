use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct AksScheduledJobPreparation {
    #[allow(clippy::type_complexity)]
    pub jobs: BTreeMap<String, BTreeMap<String, String>>,
    pub protected_template_digests: BTreeMap<String, String>,
    #[allow(clippy::type_complexity)]
    pub protected_identity_bindings: BTreeMap<String, BTreeMap<String, String>>,
    pub catalog_review_available: bool,
}

pub const SERVICE_ACCOUNT_ROOT: &str = "/var/run/secrets/kubernetes.io/serviceaccount";
pub const AKS_CANARY_TOPIC: &str = "fdai.control.canary";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn build_aks_scheduled_job(mut refs: std::collections::BTreeMap<String, String>, mut identity: std::collections::BTreeMap<String, String>, mut command: Vec<String>, mut schedule: String, mut environment: std::collections::BTreeMap<String, String>, mut secret_environment: std::collections::BTreeMap<String, String>, mut component: String, mut deadline_seconds: i64, mut retry_limit: i64, mut suspend: bool) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let image: Option<String> = (refs.clone()).get("core-control-plane").cloned();
    if !(true) {
        return Err("AKS scheduled job image is unavailable");
    }
    Ok(std::collections::BTreeMap::from([(String::from("component"), component.clone()), (String::from("image"), (image.clone()).unwrap_or_default()), (String::from("identity_resource_id"), String::new()), (String::from("identity_client_id"), String::new()), (String::from("command"), String::new()), (String::from("args"), String::new()), (String::from("schedule"), schedule.clone()), (String::from("suspend"), String::new()), (String::from("deadline_seconds"), String::new()), (String::from("retry_limit"), String::new()), (String::from("cpu"), String::from("500m")), (String::from("memory"), String::from("1Gi")), (String::from("environment"), String::new()), (String::from("secret_environment"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::too_many_arguments)]
pub fn prepare_aks_scheduled_jobs(mut refs: std::collections::BTreeMap<String, String>, mut core_identity: std::collections::BTreeMap<String, String>, mut inventory_identity: std::collections::BTreeMap<String, String>, mut canary_identity: std::collections::BTreeMap<String, String>, mut core_environment: std::collections::BTreeMap<String, String>, mut substrate_outputs: std::collections::BTreeMap<String, String>, mut source_revision: String, mut tenant_id: String, mut subscription_id: String, mut catalog_review_selected: bool, mut cluster_id: String, mut namespace: String) -> AksScheduledJobPreparation {
    let inventory_environment: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("AZURE_CLIENT_ID"), String::new()), (String::from("FDAI_MI_CLIENT_ID"), String::new())]);
    let mut jobs: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("analyzer"), String::new()), (String::from("canary"), String::new()), (String::from("inventory"), String::new()), (String::from("observation-campaign"), String::new())]);
    AksScheduledJobPreparation::default()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn aks_inventory_binding_environment(mut cluster_id: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let normalized_cluster_id: String = cluster_id.trim().to_string();
    Ok(std::collections::BTreeMap::from([(String::from("FDAI_KUBERNETES_API_SERVER"), String::from("https://kubernetes.default.svc")), (String::from("FDAI_KUBERNETES_CLUSTER_REF"), normalized_cluster_id.clone()), (String::from("FDAI_KUBERNETES_AUTH_MODE"), String::from("service-account")), (String::from("FDAI_KUBERNETES_CA_PATH"), format!("{}/ca.crt", String::from(SERVICE_ACCOUNT_ROOT))), (String::from("FDAI_KUBERNETES_TOKEN_PATH"), format!("{}/token", String::from(SERVICE_ACCOUNT_ROOT)))]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn aks_kubernetes_direct_api_environment(mut cluster_id: String, mut namespace: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let normalized_cluster_id: String = cluster_id.trim().to_string();
    Ok(std::collections::BTreeMap::from([(String::from("FDAI_KUBERNETES_DIRECT_API_JSON"), String::new())]))
}

pub const PUBLIC_EXPORTS: &[&str] = &["AksScheduledJobPreparation", "aks_inventory_binding_environment", "aks_kubernetes_direct_api_environment", "build_aks_scheduled_job", "prepare_aks_scheduled_jobs"];
