use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadbackFacts {
    pub evidence_digest: String,
    pub source_identity: String,
    pub authentication: BTreeMap<String, String>,
    pub completeness: BTreeMap<String, String>,
    pub conflict: BTreeMap<String, String>,
    pub provenance: BTreeMap<String, String>,
    pub event_at: String,
    pub evidence_cutoff: String,
    pub valid_until_cap: Option<String>,
    pub matched_grants: Vec<String>,
    #[allow(clippy::type_complexity)]
    pub authentication_receipts: Vec<BTreeMap<String, String>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LineageRecord {
    pub purpose_id: String,
    pub lookup_digest: String,
    pub receipt_digest: String,
    pub pins_digest: String,
    pub binding: String,
    pub verified_at: String,
    pub valid_until: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadbackContext {
    pub request: String,
    pub trust: String,
    pub grants: String,
    pub history: String,
    pub venue: String,
    pub read_at: String,
    pub clock: String,
    pub lineage: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ReadbackUnavailableError {
    pub message: String,
}

impl ReadbackUnavailableError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ReadbackUnavailableError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ReadbackUnavailableError {}

pub trait ProofLineageReader {
    fn admission_by_receipt(&self, receipt_digest: String) -> String;
}

impl ReadbackContext {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn access_scope_digest(&self) -> String {
        core::hint::black_box(String::new())
    }
}

pub trait PurposeReadback {
    fn read(&self, context: ReadbackContext) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["LineageRecord", "ProofLineageReader", "PurposeReadback", "ReadbackContext", "ReadbackFacts", "ReadbackRejection", "ReadbackUnavailableError"];
