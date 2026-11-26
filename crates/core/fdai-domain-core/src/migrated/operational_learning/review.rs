pub const MAX_REVIEW_REF_LENGTH: i64 = 512;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CatalogReviewPublicationReceipt {
    pub package_digest: String,
    pub review_ref: String,
    pub already_existed: bool,
    pub candidate_digest: Option<String>,
    pub binding_digest: Option<String>,
    pub observation_digest: Option<String>,
    pub required_labels: Vec<String>,
    pub observed_labels: Vec<String>,
    pub head_sha: Option<String>,
    pub review_document_digest: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CatalogReviewOutcome {
    pub idempotency_key: String,
    pub correlation_id: String,
    pub candidate_digest: Option<String>,
    pub package_digest: Option<String>,
    pub outcome: String,
    pub reason: String,
    pub review_ref: Option<String>,
}

pub const SHA256: &str = "^[0-9a-f]{64}$";
pub const GIT_SHA: &str = "^(?:[0-9a-f]{40}|[0-9a-f]{64})$";
pub const LABEL: &str = "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$";
pub trait CatalogReviewPublisher {
    fn publish(&self, package: String) -> CatalogReviewPublicationReceipt;
}

pub const PUBLIC_EXPORTS: &[&str] = &["CatalogReviewOutcome", "CatalogReviewPublicationReceipt", "CatalogReviewPublisher"];
