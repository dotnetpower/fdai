#[derive(Clone, Debug, Default, PartialEq)]
pub struct CreateUploadRequest {
    pub source_name: String,
    pub collection_id: String,
    pub media_type_hint: String,
    pub expected_size: i64,
    pub expected_sha256: String,
    pub storage_mode: String,
    pub purposes: Vec<String>,
    pub access_descriptor_ref: String,
    pub reader_groups: Vec<String>,
    pub retention_policy_version: String,
    pub document_id: Option<String>,
    pub supersedes_version_id: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DocumentIngestionService {
    pub initialized: bool,
}

impl DocumentIngestionService {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn capabilities(&self) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn create_upload(&self, mut actor_id: String, mut request: CreateUploadRequest, mut actor_groups: std::collections::BTreeSet<String>) -> Result<(String, String), &'static str> {
        if ((request.document_id.clone()).is_none()) && ((request.supersedes_version_id.clone()).is_some()) {
            return Err("supersedes_version_id requires document_id");
        }
        if (request.document_id.clone()).is_some() {
            if (request.supersedes_version_id.clone()).is_none() {
                return Err("a replacement requires supersedes_version_id");
            }
        }
        if (request.purposes.clone()).is_empty() {
            return Err("at least one document purpose is required");
        }
        Ok((String::new(), String::new()))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn resume_upload(&self, mut actor_id: String, mut upload_id: String, mut actor_groups: std::collections::BTreeSet<String>) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn put_local_content(&self, mut actor_id: String, mut upload_id: String, mut content: Vec<u8>, mut actor_groups: std::collections::BTreeSet<String>) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn put_streaming_content(&self, mut actor_id: String, mut upload_id: String, mut chunks: Vec<Vec<u8>>, mut actor_groups: std::collections::BTreeSet<String>) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn complete_upload(&self, mut actor_id: String, mut upload_id: String, mut actor_groups: std::collections::BTreeSet<String>) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get_upload(&self, mut actor_id: String, mut upload_id: String, mut actor_groups: std::collections::BTreeSet<String>) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn list_versions(&self, mut actor_id: String, mut document_id: String, mut actor_groups: std::collections::BTreeSet<String>) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn cancel_upload(&self, mut actor_id: String, mut upload_id: String, mut actor_groups: std::collections::BTreeSet<String>) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn authorized_upload(&self, mut actor_id: String, mut upload_id: String) -> (String, String) {
        (String::new(), String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn record(&self, mut session: String, mut actor_id: String, mut action: String) {
        let record: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("action"), action.clone()), (String::from("actor_id"), actor_id.clone()), (String::from("collection_id"), String::new()), (String::from("document_id"), String::new()), (String::from("version_id"), String::new()), (String::from("upload_id"), String::new()), (String::from("source_sha256"), String::new()), (String::from("state"), String::new()), (String::from("policy_version"), String::new()), (String::from("access_descriptor_ref"), String::new())]);
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn collection_segment(mut collection_id: String) -> String {
    if collection_id.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["CreateUploadRequest", "DocumentIngestionService"];
