use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Role {
    #[default]
    Reader,
    Contributor,
    Approver,
    Owner,
    BreakGlass,
}

impl Role {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Reader => "reader",
            Self::Contributor => "contributor",
            Self::Approver => "approver",
            Self::Owner => "owner",
            Self::BreakGlass => "break_glass",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Principal {
    pub id: String,
    pub role: Role,
    pub display_name: String,
    pub groups: Vec<String>,
    pub authentication_receipt_ref: Option<String>,
    pub authentication_request_ref: Option<String>,
}

impl Principal {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.id.trim().is_empty() { return Err("id must be non-empty"); }
        if self.display_name.trim().is_empty() { return Err("display_name must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Turn {
    pub turn_id: String,
    pub direction: String,
    pub content: String,
    pub tool_name: Option<String>,
    pub arguments: BTreeMap<String, String>,
    pub result_preview: String,
    pub tier: String,
    pub timestamp: String,
}

impl Turn {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.direction.as_str(), "inbound" | "outbound" | "tool_call" | "tool_result" | "system") { return Err("invalid direction literal"); }
        if !matches!(self.tier.as_str(), "T0" | "T1" | "T2" | "system") { return Err("invalid tier literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConversationSession {
    pub session_id: String,
    pub principal: Box<Principal>,
    pub channel_id: String,
    pub started_at: String,
    pub turns: Vec<Turn>,
}

impl ConversationSession {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn append(&self, mut turn: Turn) {
        core::sync::atomic::compiler_fence(core::sync::atomic::Ordering::SeqCst);
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn snapshot(&self) -> Vec<Turn> {
        self.turns.clone()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn principal_has_role_at_least(mut principal_role: Role, mut min_role: Role) -> bool {
    core::hint::black_box(false)
}

pub const PUBLIC_EXPORTS: &[&str] = &["ConversationSession", "Principal", "Role", "Turn", "TurnDirection", "principal_has_role_at_least"];
