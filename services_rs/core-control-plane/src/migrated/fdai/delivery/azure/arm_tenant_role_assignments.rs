pub const MAX_SUBSCRIPTIONS: i64 = 200;
pub const MAX_MANAGEMENT_GROUPS: i64 = 200;

pub const MANAGEMENT_GROUP_API_VERSION: &str = "2020-05-01";
pub const MANAGEMENT_GROUP_TYPE: &str = "microsoft.management/managementgroups";
pub const SUBSCRIPTION_TYPE: &str = "microsoft.management/managementgroups/subscriptions";
pub const SUBSCRIPTION_SCOPE: &str = "^/subscriptions/[^/]+$";
pub const RESOURCE_GROUP_SCOPE: &str = "^/subscriptions/[^/]+/resourcegroups/[^/]+$";
pub const RESOURCE_SCOPE: &str = "^/subscriptions/[^/]+/resourcegroups/[^/]+/providers/.+";
pub const SUBSCRIPTION_PROVIDER_SCOPE: &str = "^/subscriptions/[^/]+/providers/.+";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn tenant_role_assignments_by_principal(mut tenant_id: String, mut arm_endpoint: String, mut read_arm: String, mut graph_endpoint: Option<String>, mut read_graph: Option<String>) -> Result<std::collections::BTreeMap<String, Vec<std::collections::BTreeMap<String, String>>>, &'static str> {
    if (tenant_id.trim().to_string()).is_empty() {
        return Err("tenant id is required");
    }
    let mut subscriptions: Vec<String> = Vec::<String>::new();
    let rows: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>> = std::collections::BTreeMap::<String, std::collections::BTreeMap<String, String>>::new();
    let mut definitions: std::collections::BTreeMap<String, (String, Vec<String>, Vec<String>)> = std::collections::BTreeMap::<String, (String, Vec<String>, Vec<String>)>::new();
    let mut members: std::collections::BTreeMap<String, Vec<String>> = std::collections::BTreeMap::<String, Vec<String>>::new();
    let by_principal: std::collections::BTreeMap<String, Vec<std::collections::BTreeMap<String, String>>> = std::collections::BTreeMap::<String, Vec<std::collections::BTreeMap<String, String>>>::new();
    Ok(by_principal.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn service_principal_members(mut read_graph: Option<String>, mut graph_endpoint: Option<String>, mut group_id: String) -> Result<Vec<String>, &'static str> {
    if (read_graph.is_none()) || (graph_endpoint.is_none()) {
        return Err("group role assignments need Microsoft Graph membership");
    }
    let mut identifiers: Vec<String> = Vec::<String>::new();
    Ok(identifiers.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn scope_level(mut scope: String) -> Result<String, &'static str> {
    Err("role assignment scope is not recognized")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn definition(mut read: String, mut arm_endpoint: String, mut definition_id: String) -> Result<(String, Vec<String>, Vec<String>), &'static str> {
    let actions: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let data_actions: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    Ok((String::new(), Vec::new(), Vec::new()))
}

pub const PUBLIC_EXPORTS: &[&str] = &["MANAGEMENT_GROUP_API_VERSION", "MAX_MANAGEMENT_GROUPS", "MAX_SUBSCRIPTIONS", "tenant_role_assignments_by_principal"];
