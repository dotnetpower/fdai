#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChatDocumentRef {
    pub document_id: String,
    pub version_id: String,
}

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
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct GovernedDocumentSearchResult {
    pub hits: Vec<String>,
    pub index_generation: String,
    pub complete: bool,
    pub limitation: Option<String>,
}

impl GovernedDocumentSearchResult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.index_generation.trim().is_empty() { return Err("index_generation must be non-empty"); }
        Ok(())
    }
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

pub trait DocumentAccessProvider {
    fn authorize_create(&self, actor_id: String, actor_groups: std::collections::BTreeSet<String>, collection_id: String) -> String;
}

pub trait DocumentMetadataStore {
    fn create(&self, session: String, version: String) -> String;
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

pub trait GovernedDocumentSearch {
    fn search_governed(&self, query: String, collection_id: String, allowed_access_refs: std::collections::BTreeSet<String>, k: i64) -> String;
}

pub trait ExactGovernedDocumentSearch {
    #[allow(clippy::type_complexity)]
    fn search_governed_exact(&self, query: String, exact_refs: Vec<(String, String)>, context_source: String, conversation_ref: String, k: i64) -> String;
}

pub trait CurrentDocumentMetadataStore {
    fn get_current_version(&self, document_id: String, version_id: String) -> String;
}

pub trait DocumentReadyConsumer {
    fn purpose(&self) -> String;
}

pub trait DocumentActivitySink {
    fn audit(&self, record: std::collections::BTreeMap<String, String>) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["CurrentDocumentMetadataStore", "ExactGovernedDocumentSearch", "ChatDocumentRef", "DirectUploadStore", "DocumentAccessDeniedError", "DocumentAccessProvider", "DocumentActivitySink", "DocumentArtifactStore", "DocumentExtractor", "DocumentIndex", "DocumentIngestionError", "DocumentMetadataStore", "DocumentNotFoundError", "DocumentObjectStore", "DocumentReadyConsumer", "DocumentSearch", "DocumentWorkerClaimConflictError", "ImageOcrProvider", "MalwareScanner", "ProtectionInspection", "ProtectionInspector", "PromotableDocumentObjectStore", "ProviderUnavailableError", "StoredObjectInfo", "StreamingUploadStore", "UploadGrant"];
