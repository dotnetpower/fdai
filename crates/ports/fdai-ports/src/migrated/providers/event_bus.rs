use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct PublishReceipt {
    pub topic: String,
    pub partition: i64,
    pub offset: Option<i64>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EventEnvelope {
    pub topic: String,
    pub key: String,
    pub payload: BTreeMap<String, String>,
    pub offset: Option<i64>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct EventPublishNotAttemptedError {
    pub message: String,
}

impl EventPublishNotAttemptedError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for EventPublishNotAttemptedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for EventPublishNotAttemptedError {}

pub trait EventBus {
    fn publish(&self, topic: String, key: String, payload: std::collections::BTreeMap<String, String>) -> PublishReceipt;
    fn subscribe(&self, topic: String, group_id: String) -> Vec<EventEnvelope>;
    fn dead_letter(&self, topic: String, key: String, payload: std::collections::BTreeMap<String, String>, reason: String);
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn subscription(mut bus: String, mut topic: String, mut group_id: String) -> Vec<Vec<EventEnvelope>> {
    if bus.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn close_quietly(mut stream: Vec<EventEnvelope>, mut topic: String, mut group_id: String) {
    if stream.is_empty() {
        return;
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["EventBus", "EventEnvelope", "EventPublishNotAttemptedError", "PublishReceipt", "subscription"];
