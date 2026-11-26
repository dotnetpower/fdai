#[derive(Clone, Debug, Default, PartialEq)]
pub struct StaticMalwareScanner {
    pub verdict: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryDocumentAccessProvider {
    pub initialized: bool,
}

impl InMemoryDocumentAccessProvider {
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

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryDocumentMetadataStore {
    pub initialized: bool,
}

impl InMemoryDocumentMetadataStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn create(&self, mut session: String, mut version: String) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get_upload(&self, mut upload_id: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn save_upload(&self, mut session: String) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get_version(&self, mut document_id: String, mut version_id: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn save_version(&self, mut version: String) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn list_versions(&self, mut document_id: String) -> Result<Vec<String>, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn list_uploads_by_state(&self, mut state: String, mut limit: i64) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn claim_worker_stage(&self, mut upload_id: String, mut stage: String, mut owner: String, mut attempt_id: String, mut lease_seconds: i64) -> Result<Option<String>, &'static str> {
        if ((owner.clone()).is_empty()) || ((lease_seconds) < (1_i64)) {
            return Err("document worker owner and lease MUST be valid");
        }
        Ok(None)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn complete_worker_stage(&self, mut upload_id: String, mut stage: String, mut owner: String, mut attempt_id: String, mut expected_revision: i64) -> String {
        self.finish_worker_stage(upload_id.clone(), stage.clone(), owner.clone(), attempt_id.clone(), expected_revision, String::new()).await.unwrap_or_else(|_| String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn renew_worker_stage(&self, mut upload_id: String, mut stage: String, mut owner: String, mut attempt_id: String, mut expected_revision: i64, mut lease_seconds: i64) -> Result<String, &'static str> {
        if (lease_seconds) < (1_i64) {
            return Err("document worker lease MUST be positive");
        }
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn release_worker_stage(&self, mut upload_id: String, mut stage: String, mut owner: String, mut attempt_id: String, mut expected_revision: i64) -> String {
        self.finish_worker_stage(upload_id.clone(), stage.clone(), owner.clone(), attempt_id.clone(), expected_revision, String::new()).await.unwrap_or_else(|_| String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn finish_worker_stage(&self, mut upload_id: String, mut stage: String, mut owner: String, mut attempt_id: String, mut expected_revision: i64, mut status: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryDocumentObjectStore {
    pub initialized: bool,
}

impl InMemoryDocumentObjectStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn issue_upload(&self, mut session: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn resume_upload(&self, mut session: String) -> Result<String, &'static str> {
        Ok(self.issue_upload(session.clone()).await)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn put(&self, mut object_key: String, mut content: Vec<u8>) -> String {
        object_info(object_key.clone(), content.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn put_stream(&self, mut object_key: String, mut chunks: Vec<Vec<u8>>, mut expected_size: i64, mut max_size: i64) -> Result<String, &'static str> {
        Ok(self.put(object_key.clone(), Vec::new()).await)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn stat(&self, mut object_key: String) -> Result<String, &'static str> {
        Ok(object_info(object_key.clone(), Vec::new()))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn read(&self, mut object_key: String) -> Result<Vec<Vec<u8>>, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn revoke_upload(&self, mut upload_id: String) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn delete(&self, mut object_key: String) {
        if !self.initialized {
            return;
        }
    }
}

impl StaticMalwareScanner {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn scan(&self, mut chunks: Vec<Vec<u8>>) -> String {
        self.verdict.clone()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryDocumentArtifactStore {
    pub initialized: bool,
}

impl InMemoryDocumentArtifactStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn put(&self, mut envelope: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn delete(&self, mut document_id: String, mut version_id: String) {
        if !self.initialized {
            return;
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryDocumentIndex {
    pub initialized: bool,
}

impl InMemoryDocumentIndex {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn commit(&self, mut envelope: String) -> i64 {
        0_i64
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn delete(&self, mut document_id: String, mut version_id: String) {
        if !self.initialized {
            return;
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RecordingDocumentActivitySink {
    pub initialized: bool,
}

impl RecordingDocumentActivitySink {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn audit(&self, mut record: std::collections::BTreeMap<String, String>) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn publish(&self, mut topic: String, mut key: String, mut payload: std::collections::BTreeMap<String, String>) {
        if !self.initialized {
            return;
        }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn object_info(mut object_key: String, mut content: Vec<u8>) -> String {
    if object_key.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["InMemoryDocumentAccessProvider", "InMemoryDocumentArtifactStore", "InMemoryDocumentIndex", "InMemoryDocumentMetadataStore", "InMemoryDocumentObjectStore", "RecordingDocumentActivitySink", "StaticMalwareScanner"];
