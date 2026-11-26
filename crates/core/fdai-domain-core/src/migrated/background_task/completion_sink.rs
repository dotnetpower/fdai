#[derive(Clone, Debug, Default, PartialEq)]
pub struct BackgroundTaskTurn {
    pub turn_id: String,
    pub idempotency_key: String,
    pub conversation_id: String,
    pub principal_id: String,
    pub correlation_id: String,
    pub attempt_id: String,
    pub task_id: String,
    pub text: String,
    pub evidence_refs: Vec<String>,
    pub terminal_reason: String,
    pub trusted: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConversationCompletionSink {
    pub appender: String,
    pub deliveries: String,
    pub audit: String,
    pub scope_ref: String,
    pub binding_id: Option<String>,
    pub freshness: String,
    pub retention: String,
    pub clock: Option<String>,
}

pub const RESULT_LABEL: &str = "[Background task result: {terminal_reason}]";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CompletionSinkError {
    pub message: String,
}

impl CompletionSinkError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for CompletionSinkError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for CompletionSinkError {}

pub trait ConversationTurnAppender {
    fn append(&self, turn: BackgroundTaskTurn) -> String;
}

pub trait DeliverySubmitter {
    fn put(&self, record: String) -> String;
}

pub trait CompletionAuditWriter {
    fn record_completed(&self, attempt: String) -> String;
}

impl ConversationCompletionSink {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn publish(&self, mut attempt: String) {
        let turn: BackgroundTaskTurn = build_turn(attempt.clone()).unwrap_or_else(|_| Default::default());
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn completion_origin_ref(mut attempt: String) -> String {
    if attempt.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn build_turn(mut attempt: String) -> Result<BackgroundTaskTurn, &'static str> {
    let key: String = deterministic_key(attempt.clone());
    Ok(BackgroundTaskTurn { turn_id: format!("turn:{}", key.clone()), idempotency_key: key.clone(), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn deterministic_key(mut attempt: String) -> String {
    if attempt.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn channel_kind(mut value: String) -> Result<String, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn utc_now() -> String {
    core::hint::black_box(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["RESULT_LABEL", "BackgroundTaskTurn", "CompletionAuditWriter", "CompletionSinkError", "ConversationCompletionSink", "ConversationTurnAppender", "DeliverySubmitter", "build_turn", "completion_origin_ref"];
