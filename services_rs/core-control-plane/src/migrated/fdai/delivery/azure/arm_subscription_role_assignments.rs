pub const MAX_PAGES: i64 = 64;

pub const ROLE_ASSIGNMENT_API_VERSION: &str = "2022-04-01";
pub const PIM_API_VERSION: &str = "2020-10-01";
pub const PIM_LICENSE_REQUIRED: &str = "AadPremiumLicenseRequired";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RoleAssignmentReadError {
    pub message: String,
}

impl RoleAssignmentReadError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for RoleAssignmentReadError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for RoleAssignmentReadError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn subscription_role_assignments(mut subscription_id: String, mut arm_endpoint: String, mut graph_endpoint: String, mut read_arm: String, mut read_graph: String) -> Result<Vec<std::collections::BTreeMap<String, String>>, &'static str> {
    if (!(true)) || ((subscription_id.trim().to_string()).is_empty()) {
        return Err("subscription_id MUST be non-empty");
    }
    let mut definitions: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    let mut principal_types: std::collections::BTreeMap<String, Vec<String>> = std::collections::BTreeMap::<String, Vec<String>>::new();
    let mut projected: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
    Ok(projected.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn pages(mut read: String, mut url: String, mut prefix: String) -> Result<Vec<std::collections::BTreeMap<String, String>>, &'static str> {
    let mut collected: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
    let mut current: Option<String> = Some(url.clone());
    let mut seen_urls: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    for page in 0_i64..(MAX_PAGES).clamp(0, 10_000) {
        let Some(mut current) = current.clone() else { return Ok(collected.clone()); };
        if (seen_urls.clone()).contains(current.as_str()) {
            return Err("listing continuation did not advance");
        }
        seen_urls.insert(current.clone());
    }
    Err("listing page cap exceeded")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn standing(mut read: String, mut arm_endpoint: String, mut scope: String) -> Result<Option<std::collections::BTreeMap<String, bool>>, &'static str> {
    let mut standing: std::collections::BTreeMap<String, bool> = std::collections::BTreeMap::<String, bool>::new();
    Ok(Some(standing.clone()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn role_name(mut read: String, mut arm_endpoint: String, mut definition_id: String) -> Result<String, &'static str> {
    if read.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn principal_types(mut read: String, mut graph_endpoint: String, mut kind: String, mut principal: String) -> Result<Vec<String>, &'static str> {
    if (kind.clone()) == (String::from("User")) {
        return Ok(vec![String::from("Guest\" if user_type == \"Guest\" else \"User")]);
    }
    if (kind.clone()) == (String::from("Group")) {
        return Ok(vec![String::from("Group"), String::from("Guest\"] if guests else [\"Group")]);
    }
    Ok(vec![kind.clone()])
}

pub const PUBLIC_EXPORTS: &[&str] = &["PIM_LICENSE_REQUIRED", "RoleAssignmentReadError", "subscription_role_assignments"];
