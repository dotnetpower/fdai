use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct IacReview {
    pub pr_ref: String,
    pub review_key: String,
    pub findings: Vec<String>,
    pub verdict: String,
    pub mode: String,
    pub generated_at: String,
    pub metadata: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReviewReceipt {
    pub check_ref: String,
    pub url: Option<String>,
    pub already_existed: bool,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct IacReviewPublishError {
    pub message: String,
}

impl IacReviewPublishError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for IacReviewPublishError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for IacReviewPublishError {}

pub trait IacReviewPublisher {
    fn publish(&self, review: IacReview) -> ReviewReceipt;
}

pub const PUBLIC_EXPORTS: &[&str] = &["IacReview", "IacReviewPublishError", "IacReviewPublisher", "ReviewReceipt"];
