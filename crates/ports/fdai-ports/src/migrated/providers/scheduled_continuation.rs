pub const MAX_ID: i64 = 256;
pub const MAX_SUMMARY: i64 = 100000;
pub const MAX_EVIDENCE_REFS: i64 = 64;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ContinuationMode {
    #[default]
    None,
    OriginThread,
    DedicatedThread,
}

impl ContinuationMode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::None => "none",
            Self::OriginThread => "origin_thread",
            Self::DedicatedThread => "dedicated_thread",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ContinuationAudience {
    #[default]
    Direct,
    Broadcast,
}

impl ContinuationAudience {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Direct => "direct",
            Self::Broadcast => "broadcast",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ContinuationAnchorState {
    #[default]
    Active,
    Expired,
}

impl ContinuationAnchorState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Active => "active",
            Self::Expired => "expired",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ScheduledResultOrigin {
    pub channel_kind: String,
    pub channel_ref: String,
    pub conversation_ref: String,
    pub thread_ref: Option<String>,
    pub audience: ContinuationAudience,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ScheduledConversationAnchor {
    pub anchor_id: String,
    pub task_id: String,
    pub run_id: String,
    pub owner_principal_id: String,
    pub scope_ref: String,
    pub mode: ContinuationMode,
    pub origin: Box<ScheduledResultOrigin>,
    pub result_digest: String,
    pub result_summary: String,
    pub evidence_refs: Vec<String>,
    pub observation_started_at: String,
    pub observation_ended_at: String,
    pub created_at: String,
    pub expires_at: String,
    pub state: ContinuationAnchorState,
}

impl ScheduledConversationAnchor {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.anchor_id.trim().is_empty() { return Err("anchor_id must be non-empty"); }
        if self.task_id.trim().is_empty() { return Err("task_id must be non-empty"); }
        if self.run_id.trim().is_empty() { return Err("run_id must be non-empty"); }
        if self.owner_principal_id.trim().is_empty() { return Err("owner_principal_id must be non-empty"); }
        if self.scope_ref.trim().is_empty() { return Err("scope_ref must be non-empty"); }
        if self.result_digest.trim().is_empty() { return Err("result_digest must be non-empty"); }
        if self.result_summary.trim().is_empty() { return Err("result_summary must be non-empty"); }
        if self.observation_started_at.trim().is_empty() { return Err("observation_started_at must be non-empty"); }
        if self.observation_ended_at.trim().is_empty() { return Err("observation_ended_at must be non-empty"); }
        if self.created_at.trim().is_empty() { return Err("created_at must be non-empty"); }
        if self.expires_at.trim().is_empty() { return Err("expires_at must be non-empty"); }
        Ok(())
    }
}

pub trait ScheduledConversationAnchorStore {
    fn create(&self, anchor: ScheduledConversationAnchor) -> Option<String>;
    fn list_for_principal(&self, principal_id: String, limit: i64) -> String;
}

pub trait ScheduledContinuationDelivery {
    fn deliver(&self, anchor: ScheduledConversationAnchor) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn anchor_id_for_run(mut task_id: String, mut run_id: String) -> String {
    if task_id.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn projected_turn_id_for_anchor(mut anchor_id: String) -> String {
    let _ = identifier(String::from("anchor_id"), anchor_id.clone()).unwrap_or_else(|_| ());
    format!("scheduled-result-{}", anchor_id.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn scheduled_result_fact_text(mut anchor: ScheduledConversationAnchor) -> String {
    let evidence: String = { let _a = (anchor.evidence_refs.clone()).join(","); if !_a.is_empty() { _a } else { String::from("none") } };
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn identifier(mut name: String, mut value: String) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn aware(mut name: String, mut value: String) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["ContinuationAnchorState", "ContinuationAudience", "ContinuationMode", "ScheduledConversationAnchor", "ScheduledConversationAnchorStore", "ScheduledContinuationDelivery", "ScheduledResultOrigin", "anchor_id_for_run", "projected_turn_id_for_anchor", "scheduled_result_fact_text"];
