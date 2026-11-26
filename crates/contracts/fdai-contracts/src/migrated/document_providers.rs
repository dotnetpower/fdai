use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct UploadGrant {
    pub upload_id: String,
    pub target: String,
    pub expires_at: String,
    pub completed_parts: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct StoredObjectInfo {
    pub object_key: String,
    pub size_bytes: i64,
    pub sha256: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProtectionInspection {
    pub state: String,
    pub observed_format: String,
    pub media_type: String,
    pub sensitivity_label: Option<String>,
    pub reason_code: Option<String>,
    pub provider_ref: Option<String>,
    pub policy_revision: Option<i64>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct KnowledgeChunk {
    pub doc_id: String,
    pub chunk_id: String,
    pub text: String,
    pub source_ref: String,
    pub metadata: BTreeMap<String, String>,
    pub score: f64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DocumentIngestionError {
    pub message: String,
}

impl DocumentIngestionError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for DocumentIngestionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for DocumentIngestionError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DocumentNotFoundError {
    pub message: String,
}

impl DocumentNotFoundError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for DocumentNotFoundError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for DocumentNotFoundError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DocumentAccessDeniedError {
    pub message: String,
}

impl DocumentAccessDeniedError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for DocumentAccessDeniedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for DocumentAccessDeniedError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DocumentWorkerClaimConflictError {
    pub message: String,
}

impl DocumentWorkerClaimConflictError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for DocumentWorkerClaimConflictError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for DocumentWorkerClaimConflictError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DocumentLifecycleConflictError {
    pub message: String,
}

impl DocumentLifecycleConflictError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for DocumentLifecycleConflictError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for DocumentLifecycleConflictError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ProviderUnavailableError {
    pub message: String,
}

impl ProviderUnavailableError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ProviderUnavailableError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ProviderUnavailableError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DocumentExtractionUnavailableError {
    pub message: String,
}

impl DocumentExtractionUnavailableError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for DocumentExtractionUnavailableError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for DocumentExtractionUnavailableError {}

pub trait DocumentAccessProvider {
    fn authorize_create(&self, actor_id: String, actor_groups: std::collections::BTreeSet<String>, collection_id: String) -> String;
}

pub trait DocumentUploadMetadataStore {
    fn create(&self, session: String, version: String, event: Option<String>) -> String;
}

pub trait DocumentMetadataStore {
    #[allow(clippy::too_many_arguments)]
    fn transition_worker_stage(&self, session: String, version: String, claim: String, expected_upload_state: String, expected_upload_revision: i64, expected_version_state: String, expected_version_revision: i64, event: String);
    fn assert_worker_stage_active(&self, claim: String);
    fn enqueue_worker_event(&self, event: String, claim: String);
    fn claim_worker_stage(&self, upload_id: String, stage: String, owner: String, attempt_id: String, lease_seconds: i64) -> String;
}

pub trait WorkerDocumentObjectStore {
    fn read(&self, object_key: String) -> String;
}

pub trait DocumentObjectStore {
    fn issue_upload(&self, session: String) -> String;
}

pub trait DirectUploadStore {
    fn put(&self, object_key: String, content: Vec<u8>) -> String;
}

pub trait StreamingUploadStore {
    #[allow(clippy::type_complexity)]
    fn put_stream(&self, object_key: String, chunks: Vec<Vec<u8>>, expected_size: i64, max_size: i64) -> String;
}

pub trait PromotableDocumentObjectStore {
    fn governed_key(&self, session: String) -> String;
}

pub trait MalwareScanner {
    #[allow(clippy::type_complexity)]
    fn scan(&self, chunks: Vec<Vec<u8>>) -> String;
}

pub trait ProtectionInspector {
    #[allow(clippy::type_complexity)]
    fn inspect(&self, source_name: String, media_type_hint: String, chunks: Vec<Vec<u8>>) -> String;
}

pub trait DocumentExtractor {
    #[allow(clippy::type_complexity)]
    fn extract(&self, version: String, chunks: Vec<Vec<u8>>) -> String;
}

pub trait ImageOcrProvider {
    fn extract(&self, version: String, content: Vec<u8>) -> String;
}

pub trait DocumentArtifactStore {
    fn put(&self, envelope: String) -> String;
}

pub trait DocumentIndex {
    fn commit(&self, envelope: String) -> String;
}

pub trait DocumentSearch {
    fn search(&self, query: String, collection_id: String, allowed_access_refs: std::collections::BTreeSet<String>, k: i64) -> String;
}

pub trait DocumentReadyConsumer {
    fn purpose(&self) -> String;
}

pub trait StewardPersonDirectory {
    fn resolve(&self, display_name: String) -> String;
}

pub trait HandoverDraftStore {
    fn put(&self, artifact: String) -> String;
}

pub trait StewardshipMergeRecorder {
    fn record(&self, merge: String) -> String;
}

pub trait RepositoryHandoverDraftRecorder {
    fn record(&self, draft: String) -> String;
}

pub trait DocumentOutboxDrainer {
    fn drain(&self, limit: i64) -> String;
}

pub trait EventBus {
    fn publish(&self, topic: String, key: String, payload: std::collections::BTreeMap<String, String>) -> String;
}

