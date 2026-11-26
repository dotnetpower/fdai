use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ConversationPolicyKind {
    #[default]
    OpeningBriefing,
    ResponseDefaults,
}

impl ConversationPolicyKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::OpeningBriefing => "opening_briefing",
            Self::ResponseDefaults => "response_defaults",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum BriefingKind {
    #[default]
    MajorIssues,
    OperationsDigest,
}

impl BriefingKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::MajorIssues => "major_issues",
            Self::OperationsDigest => "operations_digest",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum BriefingDeliveryMode {
    #[default]
    InApp,
    Teams,
    Email,
}

impl BriefingDeliveryMode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::InApp => "in_app",
            Self::Teams => "teams",
            Self::Email => "email",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum BriefingRunStatus {
    #[default]
    Pending,
    Delivered,
    Partial,
    Failed,
}

impl BriefingRunStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Delivered => "delivered",
            Self::Partial => "partial",
            Self::Failed => "failed",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BriefingSpec {
    pub kind: BriefingKind,
    pub lookback_seconds: i64,
    pub minimum_severity: String,
    pub categories: Vec<String>,
    pub max_items: i64,
    pub include_pending_approvals: bool,
    pub include_failed_actions: bool,
    pub scope_ref: Option<String>,
}

impl BriefingSpec {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.minimum_severity.trim().is_empty() { return Err("minimum_severity must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConversationPolicyRecord {
    pub policy_id: String,
    pub principal_id: String,
    pub kind: ConversationPolicyKind,
    pub enabled: bool,
    pub revision: i64,
    pub confirmed_at: String,
    pub source_turn_id: String,
    #[allow(clippy::type_complexity)]
    pub briefing_spec: Option<Box<BriefingSpec>>,
    pub response_defaults: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BriefingSubscription {
    pub subscription_id: String,
    pub principal_id: String,
    pub name: String,
    pub spec: Box<BriefingSpec>,
    pub cron_expression: String,
    pub timezone: String,
    pub delivery_modes: Vec<BriefingDeliveryMode>,
    pub enabled: bool,
    pub next_run_at: String,
    pub created_at: String,
    pub revision: i64,
    pub channel_binding_ref: Option<String>,
    pub max_lateness_seconds: i64,
    pub continuation_mode: String,
    pub continuation_origin: Option<String>,
    pub continuation_ttl_seconds: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BriefingRun {
    pub run_id: String,
    pub subscription_id: Option<String>,
    pub principal_id: String,
    pub conversation_id: Option<String>,
    pub scheduled_for: String,
    pub started_at: String,
    pub status: BriefingRunStatus,
    pub idempotency_key: String,
    pub title: String,
    pub body_markdown: String,
    pub item_count: i64,
    pub evidence_refs: Vec<String>,
    pub source_errors: Vec<String>,
    pub continuation_mode: String,
    pub continuation_origin: Option<String>,
    pub result_digest: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct BriefingConflictError {
    pub message: String,
}

impl BriefingConflictError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for BriefingConflictError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for BriefingConflictError {}

pub trait ConversationPolicyStore {
    fn put(&self, record: ConversationPolicyRecord, expected_revision: Option<i64>) -> String;
}

pub trait BriefingSubscriptionStore {
    fn create(&self, record: BriefingSubscription) -> String;
}

pub trait BriefingRunStore {
    fn create(&self, run: BriefingRun) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_timezone(mut value: String) -> Result<(), &'static str> {
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_text(mut name: String, mut value: String) -> Result<(), &'static str> {
    if ((value.clone()).trim().to_string()).is_empty() {
        return Err("name MUST be non-empty");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_aware(mut name: String, mut value: String) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["BriefingConflictError", "BriefingDeliveryMode", "BriefingKind", "BriefingRun", "BriefingRunStatus", "BriefingRunStore", "BriefingSpec", "BriefingSubscription", "BriefingSubscriptionStore", "ConversationPolicyKind", "ConversationPolicyRecord", "ConversationPolicyStore"];
