#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DocumentState {
    #[default]
    Created,
    Uploading,
    Received,
    Quarantined,
    Scanning,
    ProtectionCheck,
    Extracting,
    Indexing,
    Ready,
    ReadyWithWarnings,
    Held,
    Failed,
    Deleting,
    Deleted,
}

impl DocumentState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Created => "created",
            Self::Uploading => "uploading",
            Self::Received => "received",
            Self::Quarantined => "quarantined",
            Self::Scanning => "scanning",
            Self::ProtectionCheck => "protection_check",
            Self::Extracting => "extracting",
            Self::Indexing => "indexing",
            Self::Ready => "ready",
            Self::ReadyWithWarnings => "ready_with_warnings",
            Self::Held => "held",
            Self::Failed => "failed",
            Self::Deleting => "deleting",
            Self::Deleted => "deleted",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ProtectionState {
    #[default]
    None,
    LabeledUnencrypted,
    RightsManagedAccessible,
    RightsManagedAccessDenied,
    PasswordEncrypted,
    UnsupportedProtection,
    Unknown,
}

impl ProtectionState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::None => "none",
            Self::LabeledUnencrypted => "labeled_unencrypted",
            Self::RightsManagedAccessible => "rights_managed_accessible",
            Self::RightsManagedAccessDenied => "rights_managed_access_denied",
            Self::PasswordEncrypted => "password_encrypted",
            Self::UnsupportedProtection => "unsupported_protection",
            Self::Unknown => "unknown",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SourceStorageMode {
    #[default]
    ManagedCopy,
    LinkedSource,
    EphemeralProcessing,
    MetadataOnly,
}

impl SourceStorageMode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ManagedCopy => "managed_copy",
            Self::LinkedSource => "linked_source",
            Self::EphemeralProcessing => "ephemeral_processing",
            Self::MetadataOnly => "metadata_only",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum MalwareVerdict {
    #[default]
    Clean,
    Infected,
    Unavailable,
}

impl MalwareVerdict {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Clean => "clean",
            Self::Infected => "infected",
            Self::Unavailable => "unavailable",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DocumentPurpose {
    #[default]
    KnowledgeBase,
    ManualDistillation,
    HandoverBootstrap,
    HandoverEvidence,
    CloudReference,
    ReportLineBootstrap,
}

impl DocumentPurpose {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::KnowledgeBase => "knowledge_base",
            Self::ManualDistillation => "manual_distillation",
            Self::HandoverBootstrap => "handover_bootstrap",
            Self::HandoverEvidence => "handover_evidence",
            Self::CloudReference => "cloud_reference",
            Self::ReportLineBootstrap => "report_line_bootstrap",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DocumentWorkerStage {
    #[default]
    ReceivedReplay,
    Inspection,
    ProtectionReplay,
    SafetyDecision,
    Indexing,
}

impl DocumentWorkerStage {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ReceivedReplay => "received_replay",
            Self::Inspection => "inspection",
            Self::ProtectionReplay => "protection_replay",
            Self::SafetyDecision => "safety_decision",
            Self::Indexing => "indexing",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DocumentWorkerClaimStatus {
    #[default]
    Active,
    Completed,
    Released,
}

impl DocumentWorkerClaimStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Active => "active",
            Self::Completed => "completed",
            Self::Released => "released",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AccessDescriptor {
    pub reference: String,
    pub collection_id: String,
    pub reader_groups: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RetentionPolicy {
    pub policy_version: String,
    pub source_expires_at: Option<String>,
    pub derived_expires_at: Option<String>,
    pub legal_hold: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct UploadSession {
    pub upload_id: String,
    pub document_id: String,
    pub version_id: String,
    pub actor_id: String,
    pub source_name: String,
    pub collection_id: String,
    pub object_key: String,
    pub media_type_hint: String,
    pub expected_size: i64,
    pub expected_sha256: String,
    pub state: DocumentState,
    pub storage_mode: SourceStorageMode,
    pub purposes: Vec<DocumentPurpose>,
    pub access: Box<AccessDescriptor>,
    pub retention: Box<RetentionPolicy>,
    pub created_at: String,
    pub expires_at: String,
    pub supersedes_version_id: Option<String>,
    pub failure_code: Option<String>,
}

impl UploadSession {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(0_i64..=9223372036854775807_i64).contains(&self.expected_size) { return Err("expected_size out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DocumentWorkerClaim {
    pub schema_version: String,
    pub upload_id: String,
    pub stage: DocumentWorkerStage,
    pub owner: String,
    pub attempt_id: String,
    pub revision: i64,
    pub status: DocumentWorkerClaimStatus,
    pub claimed_at: String,
    pub lease_expires_at: String,
    pub finished_at: Option<String>,
}

impl DocumentWorkerClaim {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(1_i64..=9223372036854775807_i64).contains(&self.revision) { return Err("revision out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DocumentWorkerAuditEvent {
    pub schema_version: String,
    pub producer_principal: String,
    pub kind: String,
    pub audited_topic: String,
    pub correlation_id: String,
    pub idempotency_key: String,
    pub stage: String,
    pub decision: String,
    pub reason: String,
    pub document_id: String,
    pub upload_id: String,
    pub initiator_principal: String,
    pub approvers: Vec<String>,
}

impl DocumentWorkerAuditEvent {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.producer_principal.as_str(), "Saga") { return Err("invalid producer_principal literal"); }
        if !matches!(self.kind.as_str(), "document_ingestion") { return Err("invalid kind literal"); }
        if !matches!(self.audited_topic.as_str(), "object.verdict" | "object.approval") { return Err("invalid audited_topic literal"); }
        if !matches!(self.stage.as_str(), "received" | "protection_check") { return Err("invalid stage literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DocumentWorkerIndexCommand {
    pub schema_version: String,
    pub producer_principal: String,
    pub kind: String,
    pub stage: String,
    pub command: String,
    pub correlation_id: String,
    pub idempotency_key: String,
    pub resource_id: String,
    pub document_id: String,
    pub upload_id: String,
}

impl DocumentWorkerIndexCommand {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.producer_principal.as_str(), "Muninn") { return Err("invalid producer_principal literal"); }
        if !matches!(self.kind.as_str(), "document_ingestion") { return Err("invalid kind literal"); }
        if !matches!(self.stage.as_str(), "indexing") { return Err("invalid stage literal"); }
        if !matches!(self.command.as_str(), "index") { return Err("invalid command literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DocumentVersion {
    pub document_id: String,
    pub version_id: String,
    pub upload_id: String,
    pub source_name: String,
    pub source_sha256: String,
    pub size_bytes: i64,
    pub media_type: String,
    pub observed_format: Option<String>,
    pub state: DocumentState,
    pub protection_state: ProtectionState,
    pub classification: String,
    pub sensitivity_label: Option<String>,
    pub access: Box<AccessDescriptor>,
    pub retention: Box<RetentionPolicy>,
    pub purposes: Vec<DocumentPurpose>,
    pub uploader_id: String,
    pub created_at: String,
    pub updated_at: String,
    pub active: bool,
    pub available: bool,
    pub supersedes_version_id: Option<String>,
    pub failure_code: Option<String>,
    pub warnings: Vec<String>,
    pub cloud_knowledge: Option<String>,
}

impl DocumentVersion {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(0_i64..=9223372036854775807_i64).contains(&self.size_bytes) { return Err("size_bytes out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct StructuralUnit {
    pub unit_id: String,
    pub kind: String,
    pub locator: String,
    pub text: String,
    pub table_cell_role: Option<String>,
}

impl StructuralUnit {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "text" | "paragraph" | "table" | "slide" | "sheet" | "page") { return Err("invalid kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DocumentSourceSpan {
    pub document_id: String,
    pub version_id: String,
    pub unit_id: String,
    pub locator: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DocumentEnvelope {
    pub schema_version: String,
    pub document_id: String,
    pub version_id: String,
    pub source_sha256: String,
    pub media_type: String,
    pub observed_format: String,
    pub size_bytes: i64,
    pub collection_id: String,
    pub purposes: Vec<DocumentPurpose>,
    pub protection_state: ProtectionState,
    pub access_descriptor_ref: String,
    pub units: Vec<StructuralUnit>,
    pub extractor_name: String,
    pub extractor_version: String,
    pub goal_ref: Option<String>,
    pub warnings: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct IngestionCapabilities {
    pub supported_formats: Vec<String>,
    pub storage_modes: Vec<SourceStorageMode>,
    pub max_file_size: i64,
    pub max_batch_count: i64,
    pub archives_enabled: bool,
    pub policy_versions: Vec<String>,
    pub direct_upload: bool,
}

impl DocumentWorkerClaim {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_lifecycle(&self) -> Result<DocumentWorkerClaim, &'static str> {
        if (self.lease_expires_at.clone()) <= (self.claimed_at.clone()) {
            return Err("document worker claim lease MUST expire after it is claimed");
        }
        Ok(self.clone())
    }
}

impl DocumentSourceSpan {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn reference(&self) -> String {
        format!("document://{}/versions/{}#{}", self.document_id.clone(), self.version_id.clone(), self.unit_id.clone())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AccessDescriptor", "DocumentEnvelope", "DocumentPurpose", "DocumentSourceSpan", "DocumentState", "DocumentVersion", "DocumentWorkerClaim", "DocumentWorkerClaimStatus", "DocumentWorkerAuditEvent", "DocumentWorkerIndexCommand", "DocumentWorkerStage", "IngestionCapabilities", "MalwareVerdict", "ProtectionState", "RetentionPolicy", "SourceStorageMode", "StructuralUnit", "UploadSession"];
