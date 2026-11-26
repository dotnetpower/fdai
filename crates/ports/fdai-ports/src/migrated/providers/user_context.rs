use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ConversationStatus {
    #[default]
    Active,
    Closed,
}

impl ConversationStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Active => "active",
            Self::Closed => "closed",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ConversationTurnRole {
    #[default]
    Operator,
    Assistant,
    Tool,
    System,
}

impl ConversationTurnRole {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Operator => "operator",
            Self::Assistant => "assistant",
            Self::Tool => "tool",
            Self::System => "system",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum UserMemoryCategory {
    #[default]
    Preference,
    Context,
    Goal,
}

impl UserMemoryCategory {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Preference => "preference",
            Self::Context => "context",
            Self::Goal => "goal",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConversationRecord {
    pub conversation_id: String,
    pub principal_id: String,
    pub channel_id: String,
    pub started_at: String,
    pub last_active: String,
    pub status: ConversationStatus,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConversationTurnRecord {
    pub turn_id: String,
    pub conversation_id: String,
    pub principal_id: String,
    pub turn_index: i64,
    pub role: ConversationTurnRole,
    pub content: String,
    pub recorded_at: String,
    pub idempotency_key: String,
    pub metadata: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct UserPreferenceRecord {
    pub principal_id: String,
    pub locale: String,
    pub verbosity: String,
    pub answer_detail: String,
    pub answer_format: String,
    pub answer_preferences_enabled: bool,
    pub answer_intent_detail: BTreeMap<String, String>,
    pub answer_intent_format: BTreeMap<String, String>,
    pub timezone: Option<String>,
    pub share_with_learner: bool,
    pub revision: i64,
    pub updated_at: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct UserMemoryFact {
    pub memory_id: String,
    pub principal_id: String,
    pub category: UserMemoryCategory,
    pub body: String,
    pub source_turn_id: String,
    pub consented_at: String,
    pub created_at: String,
    pub expires_at: Option<String>,
    pub superseded_by: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct UserContextConflictError {
    pub message: String,
}

impl UserContextConflictError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for UserContextConflictError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for UserContextConflictError {}

pub trait ConversationHistoryStore {
    fn create_conversation(&self, record: ConversationRecord) -> String;
}

pub trait UserPreferenceStore {
    fn get(&self, principal_id: String) -> String;
}

pub trait UserMemoryStore {
    fn create(&self, fact: UserMemoryFact) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_answer_intent_preferences(mut preferences: std::collections::BTreeMap<String, String>, mut values: std::collections::BTreeSet<String>, mut field_name: String) -> Result<(), &'static str> {
    let intents: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("definition"), String::from("why"), String::from("procedure"), String::from("comparison"), String::from("diagnosis"), String::from("status"), String::from("list"), String::from("summary"), String::from("proposal"), String::from("open_question"), String::from("greeting")]);
    Ok(())
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

pub const PUBLIC_EXPORTS: &[&str] = &["ConversationHistoryStore", "ConversationRecord", "ConversationStatus", "ConversationTurnRecord", "ConversationTurnRole", "UserContextConflictError", "UserMemoryCategory", "UserMemoryFact", "UserMemoryStore", "UserPreferenceRecord", "UserPreferenceStore"];
