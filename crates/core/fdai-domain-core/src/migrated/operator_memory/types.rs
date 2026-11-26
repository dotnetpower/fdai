#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ScopeKind {
    #[default]
    ResourceGroup,
    Resource,
}

impl ScopeKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ResourceGroup => "resource-group",
            Self::Resource => "resource",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum MemorySource {
    #[default]
    HilReject,
    HilApproveReason,
    OverrideCreate,
    ChatopsPreference,
    PrReview,
    MemoryCompaction,
    PostTurnReview,
}

impl MemorySource {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::HilReject => "hil.reject",
            Self::HilApproveReason => "hil.approve.reason",
            Self::OverrideCreate => "override.create",
            Self::ChatopsPreference => "chatops.preference",
            Self::PrReview => "pr.review",
            Self::MemoryCompaction => "memory.compaction",
            Self::PostTurnReview => "post-turn.review",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum MemoryCategory {
    #[default]
    Preference,
    OverrideNote,
    ForbiddenAction,
    RunbookHint,
}

impl MemoryCategory {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Preference => "preference",
            Self::OverrideNote => "override-note",
            Self::ForbiddenAction => "forbidden-action",
            Self::RunbookHint => "runbook-hint",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OperatorMemoryEntry {
    pub id: String,
    pub scope_kind: ScopeKind,
    pub scope_ref: String,
    pub category: MemoryCategory,
    pub body: String,
    pub source_event: MemorySource,
    pub source_ref: String,
    pub author: String,
    pub approved_by: String,
    pub created_at: String,
    pub superseded_by: Option<String>,
    pub ttl_seconds: Option<i64>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OperatorScope {
    pub resource_group_ref: String,
    pub resource_ref: Option<String>,
}

pub const PUBLIC_EXPORTS: &[&str] = &["MemoryCategory", "MemorySource", "OperatorMemoryEntry", "OperatorScope", "ScopeKind"];
