use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct VerifierRoleAssignment {
    pub scope: String,
    pub role_definition_id: String,
    pub role_name: String,
    pub actions: Vec<String>,
    pub data_actions: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct VerifierOwnRoleReadback {
    pub principal_id: String,
    pub assignments: Vec<VerifierRoleAssignment>,
    pub complete: bool,
    pub observed_scopes: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OwnRolePolicy {
    pub verifier_principal_id: String,
    #[allow(clippy::type_complexity)]
    pub allowed_role_scopes: BTreeMap<String, Vec<String>>,
    pub allowed_management_read_roles: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct VerifierOwnRoleReadbackError {
    pub message: String,
}

impl VerifierOwnRoleReadbackError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for VerifierOwnRoleReadbackError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for VerifierOwnRoleReadbackError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn evaluate_verifier_own_roles(mut readback: VerifierOwnRoleReadback, mut policy: OwnRolePolicy) -> Vec<String> {
    let mut reasons: Vec<String> = Vec::<String>::new();
    if (readback.principal_id.clone()) != (policy.verifier_principal_id.clone()) {
        reasons.push(String::from("role_readback_principal_mismatch"));
    }
    if !(readback.complete) {
        reasons.push(String::from("role_readback_partial"));
    }
    if (readback.observed_scopes.clone()).is_empty() {
        reasons.push(String::from("role_readback_unavailable"));
    }
    for assignment in readback.assignments.clone() {
        let role_name: String = (assignment.role_name.clone()).trim().to_string();
        if ((role_name.clone()).is_empty()) || (((assignment.actions.clone()).is_empty()) && ((assignment.data_actions.clone()).is_empty())) {
            reasons.push(String::from("role_definition_unresolved"));
            continue;
        }
        if !(scope_is_exact(assignment.scope.clone(), Vec::new())) {
            reasons.push(String::from("role_scope_not_allowed"));
            continue;
        }
        if has_write_access(assignment.clone()) {
            reasons.push(String::from("write_role_outside_proof_store"));
            continue;
        }
        if (has_data_plane_access(assignment.clone())) && (!((policy.allowed_management_read_roles.clone()).contains(&(role_name.clone())))) {
            reasons.push(String::from("data_plane_role_outside_proof_store"));
            continue;
        }
        if !((policy.allowed_management_read_roles.clone()).contains(&(role_name.clone()))) {
            reasons.push(String::from("unapproved_role_outside_proof_store"));
        }
    }
    ((reasons.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).into_iter().collect::<Vec<String>>()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn scope_is_exact(mut scope: String, mut allowed: Vec<String>) -> bool {
    if scope.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn has_data_plane_access(mut assignment: VerifierRoleAssignment) -> bool {
    let role: String = (assignment.role_name.clone()).to_lowercase();
    (!(assignment.data_actions.clone()).is_empty()) || (((role.clone()).contains("data ")) || ((role.clone()).ends_with(" data reader")))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn has_write_access(mut assignment: VerifierRoleAssignment) -> bool {
    let role: String = (assignment.role_name.clone()).to_lowercase();
    false
}

pub const PUBLIC_EXPORTS: &[&str] = &["OwnRolePolicy", "VerifierOwnRoleReadback", "VerifierOwnRoleReadbackError", "VerifierRoleAssignment", "evaluate_verifier_own_roles"];
