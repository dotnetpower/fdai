#[derive(Clone, Debug, Default, PartialEq)]
pub struct SseEvent {
    pub id: Option<String>,
    pub event: String,
    pub data: String,
    pub retry_ms: Option<i64>,
}

pub trait SseSink {
    fn publish(&self, channel: String, event: SseEvent);
    fn subscribe(&self, channel: String) -> Vec<SseEvent>;
}

pub const PUBLIC_EXPORTS: &[&str] = &["SseEvent", "SseSink"];
