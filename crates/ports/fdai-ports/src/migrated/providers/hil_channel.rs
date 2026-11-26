use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum HilDecision {
    #[default]
    Approve,
    Reject,
    Timeout,
    Pending,
}

impl HilDecision {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Approve => "approve",
            Self::Reject => "reject",
            Self::Timeout => "timeout",
            Self::Pending => "pending",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct HilApprovalRequest {
    pub approval_id: String,
    pub correlation_id: String,
    pub action_id: String,
    pub action_type: String,
    pub rule_ids: Vec<String>,
    pub target_resource_ref: String,
    pub blast_radius_summary: String,
    pub reasons: Vec<String>,
    pub ttl_seconds: i64,
    pub action_hash: String,
    pub metadata: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct HilApprovalReceipt {
    pub approval_id: String,
    pub channel_ref: String,
    pub sent_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct HilResponse {
    pub approval_id: String,
    pub decision: HilDecision,
    pub approver_id: Option<String>,
    pub received_at: Option<String>,
    pub reason: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct HilChannelError {
    pub message: String,
}

impl HilChannelError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for HilChannelError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for HilChannelError {}

pub trait HilChannel {
    fn send(&self, request: HilApprovalRequest) -> HilApprovalReceipt;
    fn poll(&self, receipt: HilApprovalReceipt) -> HilResponse;
}

pub const PUBLIC_EXPORTS: &[&str] = &["HilApprovalReceipt", "HilApprovalRequest", "HilChannel", "HilChannelError", "HilDecision", "HilResponse"];
