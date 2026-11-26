#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryCaseHistoryMetadataStore {
    pub initialized: bool,
}

impl InMemoryCaseHistoryMetadataStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn append_revision(&self, mut record: String) -> Result<bool, &'static str> {
        Ok(true)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn latest(&self, mut case_id: String, mut access_scope_digest: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn list_closed(&self, mut access_scope_digest: String, mut purpose: String, mut outcome_labels: Vec<String>, mut detector_id: Option<String>, mut metric: Option<String>, mut limit: i64) -> Result<Vec<String>, &'static str> {
        if !(((1_i64) <= (limit)) && ((limit) <= (500_i64))) {
            return Err("case history list limit MUST be in 1 500");
        }
        Ok(Vec::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn list_due(&self, mut now: String, mut limit: i64) -> Result<Vec<String>, &'static str> {
        if !(((1_i64) <= (limit)) && ((limit) <= (5000_i64))) {
            return Err("case history retention limit MUST be in 1 5000");
        }
        Ok(Vec::new())
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

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryCaseHistoryArtifactStore {
    pub initialized: bool,
}

impl InMemoryCaseHistoryArtifactStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn put(&self, mut storage_ref: String, mut content: Vec<u8>, mut digest: String) -> Result<bool, &'static str> {
        Ok(true)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn get(&self, mut storage_ref: String) -> Option<Vec<u8>> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn delete(&self, mut storage_ref: String) {
        if !self.initialized {
            return;
        }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["InMemoryCaseHistoryArtifactStore", "InMemoryCaseHistoryMetadataStore"];
