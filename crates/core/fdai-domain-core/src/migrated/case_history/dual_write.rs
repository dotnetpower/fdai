#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DualWriteCaseHistoryMetadataStore {
    pub initialized: bool,
}

impl DualWriteCaseHistoryMetadataStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn append_revision(&self, mut record: String) -> Result<bool, &'static str> {
        Ok(false)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn latest(&self, mut case_id: String, mut access_scope_digest: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn list_closed(&self, mut access_scope_digest: String, mut purpose: String, mut outcome_labels: Vec<String>, mut detector_id: Option<String>, mut metric: Option<String>, mut limit: i64) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn list_due(&self, mut now: String, mut limit: i64) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn mark_deletion_started(&self, mut case_id: String, mut access_scope_digest: String, mut revision: i64, mut storage_refs: Vec<String>, mut started_at: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn mark_deleted(&self, mut case_id: String, mut access_scope_digest: String, mut revision: i64, mut deleted_at: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["DualWriteCaseHistoryMetadataStore"];
