#[derive(Clone, Debug, Default, PartialEq)]
pub struct AuthorizationRequirementSpec {
    pub requirement_id: String,
    pub version: String,
    pub capability_id: String,
    pub action_type_ids: Vec<String>,
    pub resource_types: Vec<String>,
    pub scope_expressions: Vec<String>,
    pub execution_profile: String,
    pub provenance: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AuthorizationRequirementIssue {
    pub key: String,
    pub message: String,
}

impl AuthorizationRequirementSpec {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn applies_to(&self, mut action_type_id: String, mut resource_type: String) -> bool {
        ((self.action_type_ids.clone()).contains(&(action_type_id.clone()))) && ((self.resource_types.clone()).contains(&(resource_type.clone())))
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AuthorizationRequirementLoadError {
    pub message: String,
}

impl AuthorizationRequirementLoadError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for AuthorizationRequirementLoadError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for AuthorizationRequirementLoadError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn load_schema() -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_authorization_requirement_from_mapping(mut raw: std::collections::BTreeMap<String, String>) -> Result<AuthorizationRequirementSpec, &'static str> {
    Ok(AuthorizationRequirementSpec::default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn load_authorization_requirement_catalog(mut root: String, mut known_action_type_ids: std::collections::BTreeSet<String>, mut known_resource_types: std::collections::BTreeSet<String>, mut known_capability_ids: std::collections::BTreeSet<String>, mut known_execution_profiles: std::collections::BTreeSet<String>) -> Result<Vec<AuthorizationRequirementSpec>, &'static str> {
    let mut loaded: Vec<AuthorizationRequirementSpec> = Vec::<AuthorizationRequirementSpec>::new();
    let mut issues: Vec<AuthorizationRequirementIssue> = Vec::<AuthorizationRequirementIssue>::new();
    let mut seen: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    if !(issues.clone()).is_empty() {
        return Err("issues");
    }
    Ok(Vec::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["AuthorizationRequirementIssue", "AuthorizationRequirementLoadError", "AuthorizationRequirementSpec", "load_authorization_requirement_catalog", "load_authorization_requirement_from_mapping"];
