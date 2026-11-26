use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum HilApprovalDecision {
    #[default]
    Approve,
    Reject,
}

impl HilApprovalDecision {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Approve => "approve",
            Self::Reject => "reject",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum MutationTarget {
    #[default]
    PrNative,
    DirectApi,
    ToolCall,
}

impl MutationTarget {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::PrNative => "pr_native",
            Self::DirectApi => "direct_api",
            Self::ToolCall => "tool_call",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct HilPendingItem {
    pub idempotency_key: String,
    pub approval_id: String,
    pub event_id: String,
    pub action_id: String,
    pub action_kind: String,
    pub target_resource_ref: String,
    pub reason: String,
    pub submitter_oid: String,
    pub citing_rule_ids: Vec<String>,
    pub requested_at: Option<String>,
    pub correlation_id: Option<String>,
    pub action_hash: String,
    pub mutation_target: Option<MutationTarget>,
    pub metadata: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct HilDecisionReceipt {
    pub approval_id: String,
    pub idempotency_key: String,
    pub decision: HilApprovalDecision,
    pub approver_oid: String,
    pub decided_at: String,
    pub receipt_ref: String,
    pub already_recorded: bool,
    pub justification: String,
    pub delivered: bool,
    pub delivery_attempts: i64,
    pub delivery_abandoned: bool,
    pub last_delivery_error: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct HilRegistryError {
    pub message: String,
}

impl HilRegistryError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for HilRegistryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for HilRegistryError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct HilItemNotFoundError {
    pub message: String,
}

impl HilItemNotFoundError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for HilItemNotFoundError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for HilItemNotFoundError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct HilItemAlreadyResolvedError {
    pub message: String,
}

impl HilItemAlreadyResolvedError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for HilItemAlreadyResolvedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for HilItemAlreadyResolvedError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct HilDuplicateApproverError {
    pub message: String,
}

impl HilDuplicateApproverError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for HilDuplicateApproverError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for HilDuplicateApproverError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct HilSelfApprovalForbiddenError {
    pub message: String,
}

impl HilSelfApprovalForbiddenError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for HilSelfApprovalForbiddenError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for HilSelfApprovalForbiddenError {}

pub trait HilWorkflowDecisionRegistry {
    fn get_decision_route(&self, approval_id: String) -> String;
}

pub trait HilApprovalRegistry {
    fn list_pending(&self, limit: i64) -> Option<String>;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn mutation_target_from_execution_path(mut execution_path: Option<String>) -> Option<MutationTarget> {
    let Some(mut execution_path) = execution_path.clone() else { return None; };
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn hil_pending_item_from_action(mut action: String, mut action_type: Option<String>, mut approval_id: String, mut submitter_oid: String, mut reason: String, mut citing_rule_ids: Option<Vec<String>>, mut correlation_id: Option<String>, mut requested_at: Option<String>, mut action_hash: String, mut metadata: Option<std::collections::BTreeMap<String, String>>) -> Result<HilPendingItem, &'static str> {
    if (approval_id.clone()).is_empty() {
        return Err("approval_id MUST be non-empty");
    }
    if (submitter_oid.clone()).is_empty() {
        return Err("submitter_oid MUST be non-empty");
    }
    if citing_rule_ids.is_some() {
        let mut resolved_citing: Option<Vec<String>> = citing_rule_ids.clone();
    }
    Ok(HilPendingItem { approval_id: approval_id.clone(), reason: reason.clone(), submitter_oid: submitter_oid.clone(), requested_at: requested_at.clone(), correlation_id: correlation_id.clone(), action_hash: action_hash.clone(), mutation_target: mutation_target_from_execution_path(None), ..Default::default() })
}

pub const PUBLIC_EXPORTS: &[&str] = &["HilApprovalDecision", "HilApprovalRegistry", "HilDecisionReceipt", "HilDuplicateApproverError", "HilItemAlreadyResolvedError", "HilSelfApprovalForbiddenError", "HilWorkflowDecisionRegistry", "HilItemNotFoundError", "HilPendingItem", "HilRegistryError", "MutationTarget", "hil_pending_item_from_action", "mutation_target_from_execution_path"];
