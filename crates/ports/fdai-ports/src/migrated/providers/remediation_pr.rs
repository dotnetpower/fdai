use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct RemediationPr {
    pub action_id: String,
    pub idempotency_key: String,
    pub rule_ids: Vec<String>,
    pub title: String,
    pub body: String,
    pub patch: String,
    pub patch_path: String,
    pub labels: Vec<String>,
    pub mode: String,
    pub metadata: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PublishReceipt {
    pub pr_ref: String,
    pub url: Option<String>,
    pub already_existed: bool,
    pub state: String,
    pub head_sha: Option<String>,
}

pub trait RemediationPrPublisher {
    fn publish(&self, pr: RemediationPr) -> PublishReceipt;
}

pub const PUBLIC_EXPORTS: &[&str] = &["PublishReceipt", "RemediationPr", "RemediationPrPublisher"];
