#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum WorkerEffectKind {
    #[default]
    SourcePromotion,
    EphemeralSourceCleanup,
    DeletionCleanup,
    KnowledgeActivation,
}

impl WorkerEffectKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::SourcePromotion => "source_promotion",
            Self::EphemeralSourceCleanup => "ephemeral_source_cleanup",
            Self::DeletionCleanup => "deletion_cleanup",
            Self::KnowledgeActivation => "knowledge_activation",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum WorkerEffectStatus {
    #[default]
    Pending,
    Completed,
}

impl WorkerEffectStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Completed => "completed",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkerEffect {
    pub effect_id: String,
    pub upload_id: String,
    pub document_id: String,
    pub version_id: String,
    pub kind: WorkerEffectKind,
    pub object_key: String,
    pub status: WorkerEffectStatus,
    pub created_at: String,
    pub completed_at: Option<String>,
}

pub trait WorkerMetadataStore {
    fn list_uploads_by_state_after(&self, state: String, after_upload_id: Option<String>, limit: i64) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn worker_effect_id(mut kind: WorkerEffectKind, mut version_id: String) -> String {
    if version_id.is_empty() {
        return String::new();
    }
    String::new()
}

