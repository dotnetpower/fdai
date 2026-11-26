#[derive(Clone, Debug, Default, PartialEq)]
pub struct OperatingModelSnapshot {
    pub source_revision: String,
    pub objects: Vec<String>,
    pub links: Vec<String>,
}

impl OperatingModelSnapshot {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.source_revision.trim().is_empty() { return Err("source_revision must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OperatingModelUpdate {
    pub cursor: String,
    pub sequence: i64,
    pub snapshot: Box<OperatingModelSnapshot>,
}

impl OperatingModelUpdate {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.cursor.trim().is_empty() { return Err("cursor must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OperatingIntentSourceProvenance {
    pub source_url: String,
    pub resolved_ref: String,
    pub retrieved_at: String,
}

impl OperatingIntentSourceProvenance {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.source_url.trim().is_empty() { return Err("source_url must be non-empty"); }
        if self.resolved_ref.trim().is_empty() { return Err("resolved_ref must be non-empty"); }
        if self.retrieved_at.trim().is_empty() { return Err("retrieved_at must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OperatingIntentSourceDocument {
    pub snapshot: Box<OperatingModelSnapshot>,
    pub provenance: Box<OperatingIntentSourceProvenance>,
}

pub const OPERATING_MODEL_TOPIC: &str = "fdai.operating-model";
pub trait OperatingModelProvider {
    fn load(&self) -> OperatingModelSnapshot;
}

pub trait ContinuousOperatingModelProvider {
    fn updates(&self, after_cursor: Option<String>, stop: String) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn snapshot_payload(mut snapshot: OperatingModelSnapshot) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("source_revision"), snapshot.source_revision.clone()), (String::from("objects"), String::new()), (String::from("links"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn canonical_sha256(mut payload: String) -> String {
    if payload.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn operating_model_snapshot_digest(mut snapshot: OperatingModelSnapshot) -> String {
    canonical_sha256(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn operating_intent_source_document_digest(mut document: OperatingIntentSourceDocument) -> String {
    canonical_sha256(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["OPERATING_MODEL_TOPIC", "REQUIRED_OPERATING_INTENT_OBJECT_TYPES", "ContinuousOperatingModelProvider", "OperatingIntentSourceDocument", "OperatingIntentSourceProvenance", "OperatingModelProvider", "OperatingModelSnapshot", "OperatingModelUpdate", "operating_intent_source_document_digest", "operating_model_snapshot_digest"];
