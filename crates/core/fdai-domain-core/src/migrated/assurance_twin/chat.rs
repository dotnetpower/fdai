#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ChatRole {
    #[default]
    User,
    Assistant,
}

impl ChatRole {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::User => "user",
            Self::Assistant => "assistant",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChatMessage {
    pub role: ChatRole,
    pub text: String,
    pub at: String,
    pub grounding: Vec<String>,
    pub abstain_reason: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChatSession {
    pub session_id: String,
    pub caller_id: String,
    pub caller_role: String,
    pub declared_purposes: Vec<String>,
    pub correlation_id: String,
    pub created_at: String,
    pub messages: Vec<ChatMessage>,
}

impl ChatMessage {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn as_json(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("role"), String::new()), (String::from("text"), self.text.clone()), (String::from("at"), String::new()), (String::from("grounding"), String::new()), (String::from("abstain_reason"), (self.abstain_reason.clone()).unwrap_or_default())])
    }
}

impl ChatSession {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn with_message(&self, mut message: ChatMessage) -> ChatSession {
        core::hint::black_box(Default::default())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn py_new(mut session_id: String, mut caller_id: String, mut caller_role: String, mut declared_purposes: std::collections::BTreeSet<String>, mut correlation_id: String) -> Result<ChatSession, &'static str> {
        if ((session_id.trim().to_string()).is_empty()) || ((((caller_id.clone()).trim().to_string()).is_empty()) || (((correlation_id.clone()).trim().to_string()).is_empty())) {
            return Err("ChatSession requires non-empty session_id caller_id and correlation_id");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn as_json(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("session_id"), self.session_id.clone()), (String::from("caller_id"), self.caller_id.clone()), (String::from("caller_role"), String::new()), (String::from("declared_purposes"), String::new()), (String::from("correlation_id"), self.correlation_id.clone()), (String::from("created_at"), String::new()), (String::from("messages"), String::new())])
    }
}

pub trait ChatSessionStore {
    fn load(&self, session_id: String) -> Option<ChatSession>;
    fn save(&self, session: ChatSession);
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryChatSessionStore {
    pub initialized: bool,
}

impl InMemoryChatSessionStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn load(&self, mut session_id: String) -> Option<ChatSession> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn save(&self, mut session: ChatSession) {
        if !self.initialized {
            return;
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct GroundingRequiredError {
    pub message: String,
}

impl GroundingRequiredError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for GroundingRequiredError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for GroundingRequiredError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn append_assistant_answer(mut session: ChatSession, mut text: String, mut grounding: Vec<String>, mut at: Option<String>) -> Result<ChatSession, &'static str> {
    let message: ChatMessage = ChatMessage { text: text.clone(), ..Default::default() };
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn append_assistant_abstain(mut session: ChatSession, mut reason: String, mut at: Option<String>) -> Result<ChatSession, &'static str> {
    if (reason.trim().to_string()).is_empty() {
        return Err("abstain MUST carry a non-empty reason");
    }
    let message: ChatMessage = ChatMessage { text: String::from(""), abstain_reason: Some(reason.clone()), ..Default::default() };
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn append_user_question(mut session: ChatSession, mut text: String, mut at: Option<String>) -> Result<ChatSession, &'static str> {
    if (text.trim().to_string()).is_empty() {
        return Err("user question MUST be non-empty");
    }
    let message: ChatMessage = ChatMessage { text: text.clone(), ..Default::default() };
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["ChatMessage", "ChatRole", "ChatSession", "ChatSessionStore", "GroundingRequiredError", "InMemoryChatSessionStore", "append_assistant_abstain", "append_assistant_answer", "append_user_question"];
