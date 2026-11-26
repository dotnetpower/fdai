pub const MAX_CLAIMS: i64 = 10000;
pub const MAX_CANDIDATES: i64 = 5000;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OntologyReviewIssue {
    pub reason_code: String,
    pub claim_id: Option<String>,
    pub candidate_id: Option<String>,
    pub proposal_id: Option<String>,
    pub critical: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OntologyReviewSummary {
    pub total_claims: i64,
    pub critical_claims: i64,
    pub mapped_claims: i64,
    pub unresolved_claims: i64,
    pub proposals: i64,
    pub denied_proposals: i64,
    pub review_proposals: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OntologyReviewPackage {
    pub document_id: String,
    pub source_ref: String,
    pub access_policy_ref: String,
    pub content_sha256: String,
    pub extraction_run_id: String,
    pub ontology_release: String,
    pub expected_graph_revision: String,
    pub claims: Vec<String>,
    pub resolutions: Vec<String>,
    pub proposals: Vec<String>,
    pub issues: Vec<OntologyReviewIssue>,
    pub summary: Box<OntologyReviewSummary>,
}

impl OntologyReviewPackage {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.document_id.trim().is_empty() { return Err("document_id must be non-empty"); }
        if self.source_ref.trim().is_empty() { return Err("source_ref must be non-empty"); }
        if self.access_policy_ref.trim().is_empty() { return Err("access_policy_ref must be non-empty"); }
        if self.content_sha256.trim().is_empty() { return Err("content_sha256 must be non-empty"); }
        if self.extraction_run_id.trim().is_empty() { return Err("extraction_run_id must be non-empty"); }
        if self.ontology_release.trim().is_empty() { return Err("ontology_release must be non-empty"); }
        if self.expected_graph_revision.trim().is_empty() { return Err("expected_graph_revision must be non-empty"); }
        Ok(())
    }
}

pub const SHA256: &str = "^[a-f0-9]{64}$";
impl OntologyReviewPackage {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn package_digest(&self) -> String {
        core::hint::black_box(String::new())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn build_ontology_review_package(mut document: String, mut result: String, mut context: String, mut extraction_run_id: String) -> Result<OntologyReviewPackage, &'static str> {
    let mut verified: Vec<String> = Vec::<String>::new();
    let mut seen_proposal_ids: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let summary: OntologyReviewSummary = OntologyReviewSummary { proposals: ((verified.clone()).len() as i64), ..Default::default() };
    Ok(OntologyReviewPackage { extraction_run_id: extraction_run_id.clone(), proposals: verified.clone(), summary: Box::new(summary.clone()), ..Default::default() })
}

pub const PUBLIC_EXPORTS: &[&str] = &["OntologyReviewIssue", "OntologyReviewPackage", "OntologyReviewSummary", "build_ontology_review_package"];
