#[derive(Clone, Debug, Default, PartialEq)]
pub struct ShadowDeliveryRecord {
    pub record_id: String,
    pub channel_id: String,
    pub category: String,
    pub trust_tier: String,
    pub correlation_id: String,
    pub envelope: String,
    pub recorded_at: String,
    pub audit_id: Option<String>,
    pub rendered_payload: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ShadowNotificationChannel {
    pub channel_kind: String,
    pub channel_id: String,
    pub trust_tiers: Vec<String>,
    pub recorder: String,
    pub payload_renderer: Option<String>,
    pub limits: String,
    pub max_rendered_payload_bytes: i64,
    pub clock: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ShadowDeliveryConflictError {
    pub message: String,
}

impl ShadowDeliveryConflictError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ShadowDeliveryConflictError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ShadowDeliveryConflictError {}

pub trait ShadowDeliveryRecorder {
    fn record(&self, entry: ShadowDeliveryRecord) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryShadowDeliveryRecorder {
    pub initialized: bool,
}

impl InMemoryShadowDeliveryRecorder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn record(&self, mut entry: ShadowDeliveryRecord) -> Result<(), &'static str> {
        if !(same_shadow_content(Default::default(), entry.clone())) {
            return Err("shadow delivery id already exists with different bounded content");
        }
        Ok(())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn entries(&self) -> Vec<ShadowDeliveryRecord> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

impl ShadowNotificationChannel {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn send(&self, mut message: String) -> Result<String, &'static str> {
        let record_id: String = record_id(self.channel_id.clone(), message.clone());
        Ok(String::new())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn utc_now() -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn record_id(mut channel_id: String, mut message: String) -> String {
    if channel_id.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn same_shadow_content(mut left: ShadowDeliveryRecord, mut right: ShadowDeliveryRecord) -> bool {
    core::hint::black_box(false)
}

pub const PUBLIC_EXPORTS: &[&str] = &["InMemoryShadowDeliveryRecorder", "ShadowDeliveryConflictError", "ShadowDeliveryRecord", "ShadowDeliveryRecorder", "ShadowNotificationChannel"];
