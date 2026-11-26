pub const CONTRIBUTOR_MARKERS: &[&str] = &["role:Contributor", "role:Approver", "role:Owner"];
pub const OWNER_MARKERS: &[&str] = &["role:Owner"];
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ClaimsDocumentAccessProvider {
    pub initialized: bool,
}

impl ClaimsDocumentAccessProvider {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn authorize_create(&self, mut actor_id: String, mut actor_groups: std::collections::BTreeSet<String>, mut collection_id: String) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn authorize_read(&self, mut actor_id: String, mut actor_groups: std::collections::BTreeSet<String>, mut version: String) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn authorize_delete(&self, mut actor_id: String, mut actor_groups: std::collections::BTreeSet<String>, mut version: String) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

