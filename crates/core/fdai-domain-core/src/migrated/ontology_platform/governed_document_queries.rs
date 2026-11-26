pub const GOVERNED_DOCUMENT_MAX_EXCERPTS: i64 = 8;
pub const MAX_EXCERPT_BYTES: i64 = 8192;
pub const MAX_REF_LENGTH: i64 = 512;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct GovernedDocumentExcerpt {
    pub evidence_ref: String,
    pub document_revision: String,
    pub source_name: String,
    pub source_ref: String,
    pub locator: String,
    pub chunk_id: String,
    pub text: String,
    pub content_digest: String,
    pub score: f64,
    pub instruction_authority: bool,
    pub cloud_source: Option<String>,
    pub cloud_status: Option<String>,
    pub applicability_verified: bool,
}

impl GovernedDocumentExcerpt {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.evidence_ref.trim().is_empty() { return Err("evidence_ref must be non-empty"); }
        if self.document_revision.trim().is_empty() { return Err("document_revision must be non-empty"); }
        if self.source_name.trim().is_empty() { return Err("source_name must be non-empty"); }
        if self.source_ref.trim().is_empty() { return Err("source_ref must be non-empty"); }
        if self.locator.trim().is_empty() { return Err("locator must be non-empty"); }
        if self.chunk_id.trim().is_empty() { return Err("chunk_id must be non-empty"); }
        if self.text.trim().is_empty() { return Err("text must be non-empty"); }
        if self.content_digest.trim().is_empty() { return Err("content_digest must be non-empty"); }
        if self.instruction_authority { return Err("instruction_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct GovernedDocumentCollection {
    pub excerpts: Vec<GovernedDocumentExcerpt>,
    pub observed_at: String,
    pub complete: bool,
    pub limitation: Option<String>,
    pub index_generation: String,
    pub access_scope_digest: String,
    pub retrieval_mode: String,
}

impl GovernedDocumentCollection {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.observed_at.trim().is_empty() { return Err("observed_at must be non-empty"); }
        if self.index_generation.trim().is_empty() { return Err("index_generation must be non-empty"); }
        if self.access_scope_digest.trim().is_empty() { return Err("access_scope_digest must be non-empty"); }
        if !matches!(self.retrieval_mode.as_str(), "lexical" | "hybrid") { return Err("invalid retrieval_mode literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TargetKeywords {
    pub target: String,
}

pub const GOVERNED_DOCUMENT_FUNCTION_NAME: &str = "query.governed_documents";
pub const GOVERNED_DOCUMENT_MEASURE_CONCEPT: &str = "document.governed_excerpt";
pub const GOVERNED_DOCUMENT_EVIDENCE_MODES: &[&str] = &["optional", "required", "explicit"];
pub const DIGEST: &str = "sha256:[a-f0-9]{64}";
pub const EVIDENCE_REF: &str = "document:sha256:[a-f0-9]{64}";
pub trait GovernedDocumentReader {
    #[allow(clippy::too_many_arguments)]
    fn search(&self, query: String, principal_ref: String, principal_role: String, principal_groups: std::collections::BTreeSet<String>, purpose: String, limit: i64, target: Option<String>, exact_refs: Vec<String>, context_source: Option<String>, conversation_ref: Option<String>, document_context_digest: Option<String>) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn governed_document_function_type() -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn governed_document_function(mut ontology_release: String, mut reader: String) -> Result<String, &'static str> {
    if ontology_release.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn exact_document_citation(mut source_ref: String) -> Result<String, &'static str> {
    let prefix: String = String::from("document://");
    if !((source_ref.clone()).starts_with(prefix.as_str())) {
        return Err("exact governed document source ref is invalid");
    }
    Ok(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["GOVERNED_DOCUMENT_EVIDENCE_MODES", "GOVERNED_DOCUMENT_FUNCTION_NAME", "GOVERNED_DOCUMENT_MAX_EXCERPTS", "GOVERNED_DOCUMENT_MEASURE_CONCEPT", "GovernedDocumentCollection", "GovernedDocumentExcerpt", "GovernedDocumentReader", "governed_document_function", "governed_document_function_type"];
