#[derive(Clone, Debug, Default, PartialEq)]
pub struct AzureMonitorWebhookOutboxDrainer {
    pub store: String,
    pub publisher: String,
    pub topic: String,
    pub worker_id: String,
    pub lease_seconds: i64,
}

impl AzureMonitorWebhookOutboxDrainer {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.store.trim().is_empty() { return Err("store must be non-empty"); }
        if self.publisher.trim().is_empty() { return Err("publisher must be non-empty"); }
        if self.topic.trim().is_empty() { return Err("topic must be non-empty"); }
        if self.worker_id.trim().is_empty() { return Err("worker_id must be non-empty"); }
        Ok(())
    }
}

pub trait AzureMonitorEventPublisher {
    fn publish(&self, topic: String, key: String, payload: std::collections::BTreeMap<String, String>) -> String;
}

impl AzureMonitorWebhookOutboxDrainer {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn run_once(&self) -> Result<bool, &'static str> {
        Ok(false)
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureMonitorWebhookBridge {
    pub initialized: bool,
}

impl AzureMonitorWebhookBridge {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn workers_ready(&self) -> bool {
        self.initialized
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn start(&mut self) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn aclose(&self) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn run(&self) {
        if !self.initialized {
            return;
        }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AzureMonitorEventPublisher", "AzureMonitorWebhookBridge", "AzureMonitorWebhookOutboxDrainer"];
