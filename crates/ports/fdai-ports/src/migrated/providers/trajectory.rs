use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum TrajectorySourceKind {
    #[default]
    Audit,
    Conversation,
    Tool,
    Approval,
    Outcome,
}

impl TrajectorySourceKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Audit => "audit",
            Self::Conversation => "conversation",
            Self::Tool => "tool",
            Self::Approval => "approval",
            Self::Outcome => "outcome",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum TrajectoryDatasetState {
    #[default]
    Pending,
    Completed,
    Cancelled,
    Quarantined,
    Deleting,
    Deleted,
}

impl TrajectoryDatasetState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Completed => "completed",
            Self::Cancelled => "cancelled",
            Self::Quarantined => "quarantined",
            Self::Deleting => "deleting",
            Self::Deleted => "deleted",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TrajectoryBatchFilters {
    pub started_at: Option<String>,
    pub ended_at: Option<String>,
    pub verticals: Vec<String>,
    pub action_types: Vec<String>,
    pub tiers: Vec<String>,
    pub outcomes: Vec<String>,
    pub evidence_profiles: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AuthorizedTrajectoryScope {
    pub principal_id: String,
    pub access_scope: String,
    pub principal_scope_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ImmutableTrajectorySnapshot {
    pub source_kind: TrajectorySourceKind,
    pub record_id: String,
    pub record_digest: String,
    pub trace_id: String,
    pub correlation_id: String,
    pub occurred_at: String,
    pub step_kind: String,
    pub payload: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TrajectoryDatasetRecord {
    pub dataset_id: String,
    pub purpose: String,
    pub access_scope: String,
    pub principal_scope_digest: String,
    pub state: TrajectoryDatasetState,
    pub schema_version: String,
    pub storage_ref: Option<String>,
    pub record_count: i64,
    pub dataset_checksum: Option<String>,
    pub manifest_checksum: Option<String>,
    pub created_at: String,
    pub retention_until: String,
    pub deletion_due_at: String,
    pub legal_hold: bool,
    pub legal_hold_ref: Option<String>,
    pub deleted_at: Option<String>,
}

pub const SHA256: &str = "^[0-9a-f]{64}$";
pub trait TrajectoryDatasetStore {
    fn put(&self, record: TrajectoryDatasetRecord) -> String;
}

pub trait TrajectoryArtifactDeleter {
    fn delete(&self, storage_ref: String) -> String;
}

pub trait TrajectoryAccessAuthorizer {
    fn authorize(&self, principal_id: String, access_scope: String, purpose: String) -> String;
}

pub trait AuditSnapshotProvider {
    fn snapshot(&self, scope: AuthorizedTrajectoryScope, filters: TrajectoryBatchFilters) -> String;
}

pub trait ConversationSnapshotProvider {
    fn snapshot(&self, scope: AuthorizedTrajectoryScope, filters: TrajectoryBatchFilters) -> String;
}

pub trait ToolSnapshotProvider {
    fn snapshot(&self, scope: AuthorizedTrajectoryScope, filters: TrajectoryBatchFilters) -> String;
}

pub trait ApprovalSnapshotProvider {
    fn snapshot(&self, scope: AuthorizedTrajectoryScope, filters: TrajectoryBatchFilters) -> String;
}

pub trait OutcomeSnapshotProvider {
    fn snapshot(&self, scope: AuthorizedTrajectoryScope, filters: TrajectoryBatchFilters) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn digest(mut name: String, mut value: String) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn freeze_mapping(mut value: std::collections::BTreeMap<String, String>) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn freeze_value(mut value: String) -> String {
    value.clone()
}

pub const PUBLIC_EXPORTS: &[&str] = &["ApprovalSnapshotProvider", "AuditSnapshotProvider", "AuthorizedTrajectoryScope", "ConversationSnapshotProvider", "ImmutableTrajectorySnapshot", "OutcomeSnapshotProvider", "ToolSnapshotProvider", "TrajectoryAccessAuthorizer", "TrajectoryArtifactDeleter", "TrajectoryBatchFilters", "TrajectoryDatasetRecord", "TrajectoryDatasetState", "TrajectoryDatasetStore", "TrajectorySourceKind"];
