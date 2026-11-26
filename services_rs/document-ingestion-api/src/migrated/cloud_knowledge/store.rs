#[derive(Clone, Debug, Default, PartialEq)]
pub struct SourceCheckpoint {
    pub revision: i64,
    pub state: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresCloudKnowledgeStore {
    pub initialized: bool,
}

impl PostgresCloudKnowledgeStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn readiness(&self) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get(&self, mut registry_digest: String, mut source_id: String) -> SourceCheckpoint {
        if !self.initialized {
            return Default::default();
        }
        Default::default()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn claim(&self, mut registry_digest: String, mut source_id: String, mut revision: i64) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn finish(&self, mut registry_digest: String, mut source_id: String, mut checkpoint: SourceCheckpoint, mut claim: String, mut state: String) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn reserve_release(&self, mut collection_id: String, mut sequence: i64, mut digest: String, mut upload_id: String, mut payload: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        Ok(std::collections::BTreeMap::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn next_sequence(&self, mut collection_id: String) -> Result<i64, &'static str> {
        Ok(0_i64)
    }
}

