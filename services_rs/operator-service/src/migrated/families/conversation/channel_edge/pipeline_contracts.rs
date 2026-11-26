#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChannelPrincipalContext {
    pub scope: String,
    pub scope_ref: String,
    pub locale: String,
}

impl ChannelPrincipalContext {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.scope.trim().is_empty() { return Err("scope must be non-empty"); }
        if self.scope_ref.trim().is_empty() { return Err("scope_ref must be non-empty"); }
        if self.locale.trim().is_empty() { return Err("locale must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChannelDeliveryPipelineConfig {
    pub worker_id: String,
    pub lease_seconds: i64,
    pub delivery_ttl: String,
    pub retention: String,
    pub retry_delay: String,
}

impl ChannelDeliveryPipelineConfig {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.worker_id.trim().is_empty() { return Err("worker_id must be non-empty"); }
        if self.delivery_ttl.trim().is_empty() { return Err("delivery_ttl must be non-empty"); }
        if self.retention.trim().is_empty() { return Err("retention must be non-empty"); }
        if self.retry_delay.trim().is_empty() { return Err("retry_delay must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChannelPipelineResult {
    pub delivery_id: String,
    pub state: String,
    pub duplicate: bool,
}

pub trait ChannelPrincipalResolver {
    fn resolve(&self, principal_id: String) -> String;
}

pub trait ChannelMessageLedger {
    fn claim(&self, idempotency_key: String) -> String;
}

pub trait ChannelBindingStore {
    fn create(&self, binding: String) -> String;
}

pub trait ChannelDeliveryStore {
    fn put(&self, record: String) -> String;
}

pub trait ChannelPublisher {
    fn send(&self, message: String) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["ChannelBindingStore", "ChannelDeliveryPipelineConfig", "ChannelDeliveryStore", "ChannelMessageLedger", "ChannelPipelineResult", "ChannelPrincipalContext", "ChannelPrincipalResolver", "ChannelPublisher"];
