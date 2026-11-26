#[derive(Clone, Debug, Default, PartialEq)]
pub struct DevelopmentRuntimeBindings {
    pub profile: String,
    pub executor_principal: String,
    pub owner_authorizer: String,
    pub binding_source: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ApprovalRuntimeBindings {
    pub profile: String,
    pub bootstrap_profile: Option<String>,
    pub signature_verifier: Option<String>,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn configure_authority_agents(mut agents: std::collections::BTreeMap<String, String>, mut approver_authorizer: Option<String>, mut var_state_store: Option<String>, mut rollback_executors: Option<std::collections::BTreeMap<String, String>>, mut action_rollback_executors: Option<std::collections::BTreeMap<String, String>>, mut rollback_contracts_by_action_type: Option<std::collections::BTreeMap<String, String>>, mut vidar_state_store: Option<String>, mut development: Option<DevelopmentRuntimeBindings>, mut approval: Option<ApprovalRuntimeBindings>, mut admin_channel: Option<String>, mut rollback_rehearsal_port: Option<String>) {
    if agents.is_empty() {
        return;
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn bind_thor_development_authority(mut thor: String, mut development: Option<DevelopmentRuntimeBindings>) {
    if thor.is_empty() {
        return;
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn development_requires_enforce_bindings(mut development: Option<DevelopmentRuntimeBindings>) -> bool {
    development.is_some()
}

pub const PUBLIC_EXPORTS: &[&str] = &["ApprovalRuntimeBindings", "DevelopmentRuntimeBindings", "bind_thor_development_authority", "configure_authority_agents", "development_requires_enforce_bindings"];
