pub const APPGW_TYPE: &str = "Microsoft.Network/applicationGateways";
pub const VM_TYPE: &str = "Microsoft.Compute/virtualMachines";
pub const AKS_TYPE: &str = "Microsoft.ContainerService/managedClusters";
pub const APIM_TYPE: &str = "Microsoft.ApiManagement/service";
pub const MODEL_TYPE: &str = "Microsoft.CognitiveServices/accounts";
pub const POSTGRES_TYPE: &str = "Microsoft.DBforPostgreSQL/flexibleServers";
pub const REDIS_TYPE: &str = "Microsoft.Cache/redis";
pub const KEYVAULT_TYPE: &str = "Microsoft.KeyVault/vaults";
pub const EVENTHUB_TYPE: &str = "Microsoft.EventHub/namespaces";
pub const STORAGE_TYPE: &str = "Microsoft.Storage/storageAccounts";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn status_count(mut metric_name: String, mut resource_type: String, mut dimension: String, mut status: String) -> String {
    if metric_name.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn azure_metrics_api_queries() -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn azure_extended_platform_metrics_api_queries(mut include_defaults: bool) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn resolve_azure_metrics_api_template(mut metric_name: String, mut include_extended: bool) -> Option<String> {
    if (!(true)) || ((metric_name.trim().to_string()).is_empty()) {
        return None;
    }
    let clean: String = metric_name.trim().to_string();
    let catalog: std::collections::BTreeMap<String, String> = if include_extended { azure_extended_platform_metrics_api_queries(true) } else { azure_metrics_api_queries() };
    let direct: Option<String> = (catalog.clone()).get(clean.as_str()).cloned();
    if let Some(mut direct) = direct.clone() {
        return Some(direct.clone());
    }
    let folded: String = (clean.clone()).to_lowercase();
    for (key, template) in catalog.clone() {
        if ((key.clone()).to_lowercase()) == (folded.clone()) {
            return Some(template.clone());
        }
    }
    None
}

pub const PUBLIC_EXPORTS: &[&str] = &["azure_extended_platform_metrics_api_queries", "azure_metrics_api_queries", "resolve_azure_metrics_api_template"];
