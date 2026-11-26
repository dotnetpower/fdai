#[derive(Clone, Debug, Default, PartialEq)]
pub struct PagerDutyEventsV2Config {
    pub channel_id: String,
    pub routing_key: String,
    pub trust_tiers: Vec<String>,
    pub events_url: String,
    pub source: String,
    pub timeout_seconds: f64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PagerDutyEventsV2Channel {
    pub channel_kind: String,
}

pub const DEFAULT_EVENTS_URL: &str = "https://events.pagerduty.com/v2/enqueue";
pub const DEFAULT_TIMEOUT_SECONDS: f64 = 10.0;
impl PagerDutyEventsV2Channel {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn channel_id(&self) -> String {
        core::hint::black_box(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn trust_tiers(&self) -> std::collections::BTreeSet<String> {
        std::collections::BTreeSet::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn send(&self, mut message: String) -> String {
        let payload: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("routing_key"), String::new()), (String::from("event_action"), String::from("trigger")), (String::from("dedup_key"), String::new()), (String::from("payload"), String::new()), (String::from("links"), String::new())]);
        String::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn pagerduty_severity(mut severity: String) -> String {
    if severity.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["PagerDutyEventsV2Channel", "PagerDutyEventsV2Config"];
