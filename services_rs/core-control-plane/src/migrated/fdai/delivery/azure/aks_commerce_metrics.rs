pub const ENTITY_NAME: &str = "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$";
pub const SERVICE_BUS_TYPE: &str = "Microsoft.ServiceBus/namespaces";
pub const COSMOS_TYPE: &str = "Microsoft.DocumentDB/databaseAccounts";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn aks_commerce_service_bus_queries(mut queue_name: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let clean_queue: String = if true { queue_name.trim().to_string() } else { String::from("") };
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn aks_commerce_cosmos_queries() -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn aks_commerce_metrics_queries(mut queue_name: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn aks_commerce_cosmos_throttling_queries(mut collection_name: Option<String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if let Some(mut collection_name) = collection_name.clone() {
        let clean_coll: String = collection_name.trim().to_string();
    }
    Ok(std::collections::BTreeMap::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["aks_commerce_cosmos_queries", "aks_commerce_cosmos_throttling_queries", "aks_commerce_metrics_queries", "aks_commerce_service_bus_queries"];
