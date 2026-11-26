#[derive(Clone, Debug, Default, PartialEq)]
pub struct CaseHistoryRevisionRecord {
    pub case_id: String,
    pub revision: i64,
    pub kind: String,
    pub correlation_id: String,
    pub purpose: String,
    pub access_scope_digest: String,
    pub manifest_digest: String,
    pub parent_manifest_digest: Option<String>,
    pub source_set_digest: String,
    pub storage_ref: Option<String>,
    pub artifact_size: i64,
    pub outcome_label: String,
    pub detector_id: Option<String>,
    pub detector_version: Option<String>,
    pub metric: Option<String>,
    pub event_time_cutoff: String,
    pub created_by_agent: String,
    pub sealed_at: String,
    pub retention_until: String,
    pub deletion_due_at: String,
    pub metadata: Vec<String>,
    pub legal_hold: bool,
    pub legal_hold_ref: Option<String>,
    pub deleted_at: Option<String>,
    pub state_revision: i64,
    pub deletion_started_at: Option<String>,
    pub deletion_storage_refs: Vec<String>,
}

impl CaseHistoryRevisionRecord {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.case_id.trim().is_empty() { return Err("case_id must be non-empty"); }
        if self.kind.trim().is_empty() { return Err("kind must be non-empty"); }
        if self.correlation_id.trim().is_empty() { return Err("correlation_id must be non-empty"); }
        if self.purpose.trim().is_empty() { return Err("purpose must be non-empty"); }
        if self.access_scope_digest.trim().is_empty() { return Err("access_scope_digest must be non-empty"); }
        if self.manifest_digest.trim().is_empty() { return Err("manifest_digest must be non-empty"); }
        if self.source_set_digest.trim().is_empty() { return Err("source_set_digest must be non-empty"); }
        if self.outcome_label.trim().is_empty() { return Err("outcome_label must be non-empty"); }
        if self.event_time_cutoff.trim().is_empty() { return Err("event_time_cutoff must be non-empty"); }
        if self.created_by_agent.trim().is_empty() { return Err("created_by_agent must be non-empty"); }
        if self.sealed_at.trim().is_empty() { return Err("sealed_at must be non-empty"); }
        if self.retention_until.trim().is_empty() { return Err("retention_until must be non-empty"); }
        if self.deletion_due_at.trim().is_empty() { return Err("deletion_due_at must be non-empty"); }
        Ok(())
    }
}

pub trait CaseHistoryMetadataStore {
    fn append_revision(&self, record: CaseHistoryRevisionRecord) -> String;
}

pub trait CaseHistoryArtifactStore {
    fn put(&self, storage_ref: String, content: Vec<u8>, digest: String) -> String;
}

pub trait CaseHistoryDerivedDataStore {
    fn purge(&self, record: CaseHistoryRevisionRecord) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn digest(mut name: String, mut value: String) -> Result<(), &'static str> {
    if !(is_digest(value.clone())) {
        return Err("case history name MUST be lowercase SHA-256");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn is_digest(mut value: String) -> bool {
    if value.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn canonical_identifier(mut value: String) -> bool {
    if value.is_empty() {
        return false;
    }
    false
}

pub const PUBLIC_EXPORTS: &[&str] = &["CaseHistoryArtifactStore", "CaseHistoryMetadataStore", "CaseHistoryRevisionRecord"];
