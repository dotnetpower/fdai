pub const MAX_SNAPSHOT_LIMIT: i64 = 1000;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LatencySummary {
    pub count: i64,
    pub average_ms: Option<f64>,
    pub p95_ms: Option<f64>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProgressiveConversationAggregate {
    pub conversation_count: i64,
    pub first_progress: Box<LatencySummary>,
    pub first_confirmed: Box<LatencySummary>,
    pub branch: Box<LatencySummary>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConversationDeliveryPanel {
    pub reader: String,
    pub limit: i64,
}

pub trait DeliverySnapshotReader {
    fn snapshot(&self, limit: i64) -> String;
}

impl LatencySummary {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("count"), String::new()), (String::from("average_ms"), String::new()), (String::from("p95_ms"), String::new())])
    }
}

impl ProgressiveConversationAggregate {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("conversation_count"), String::new()), (String::from("first_progress_latency"), String::new()), (String::from("first_confirmed_latency"), String::new()), (String::from("branch_latency"), String::new())])
    }
}

impl ConversationDeliveryPanel {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn read(&self, mut progressive: Option<ProgressiveConversationAggregate>) -> std::collections::BTreeMap<String, String> {
        project_conversation_delivery_panel(String::new(), progressive.clone())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn project_conversation_delivery_panel(mut snapshot: String, mut progressive: Option<ProgressiveConversationAggregate>) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("read_only"), String::new()), (String::from("mutations_available"), String::new()), (String::from("delivery_count"), String::new()), (String::from("delivery_latency"), String::new()), (String::from("state_counts"), String::new()), (String::from("duplicate_risk_count"), String::new()), (String::from("retry_count"), String::new()), (String::from("abandoned_count"), String::new()), (String::from("attempt_count"), String::new()), (String::from("acknowledgement_count"), String::new()), (String::from("breaker_state_counts"), String::new()), (String::from("progressive"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn summarize_latency(mut samples: Vec<f64>) -> Result<LatencySummary, &'static str> {
    Ok(LatencySummary::default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn latency(mut deliveries: Vec<String>) -> LatencySummary {
    summarize_latency(Vec::new()).unwrap_or_else(|_| Default::default())
}

pub const PUBLIC_EXPORTS: &[&str] = &["ConversationDeliveryPanel", "DeliverySnapshotReader", "LatencySummary", "ProgressiveConversationAggregate", "project_conversation_delivery_panel", "summarize_latency"];
