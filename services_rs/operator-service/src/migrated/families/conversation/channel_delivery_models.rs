pub const MAX_DELIVERY_ATTEMPTS: i64 = 8;
pub const MAX_DELIVERY_LEASE_SECONDS: i64 = 300;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ChannelKind {
    #[default]
    Web,
    Slack,
    Teams,
}

impl ChannelKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Web => "web",
            Self::Slack => "slack",
            Self::Teams => "teams",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ChannelBindingState {
    #[default]
    Active,
    Revoked,
}

impl ChannelBindingState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Active => "active",
            Self::Revoked => "revoked",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ChannelDeliveryState {
    #[default]
    Pending,
    Sending,
    Delivered,
    Ambiguous,
    Failed,
    Abandoned,
}

impl ChannelDeliveryState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Sending => "sending",
            Self::Delivered => "delivered",
            Self::Ambiguous => "ambiguous",
            Self::Failed => "failed",
            Self::Abandoned => "abandoned",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ChannelBreakerMode {
    #[default]
    Closed,
    Open,
    Paused,
}

impl ChannelBreakerMode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Closed => "closed",
            Self::Open => "open",
            Self::Paused => "paused",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct VerifiedChannelEndpoint {
    pub principal_id: String,
    pub scope_ref: String,
    pub channel_kind: ChannelKind,
    pub channel_id: String,
    pub sender_id: String,
    pub thread_id: Option<String>,
    pub verification_ref: String,
    pub verified_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PrincipalChannelBinding {
    pub binding_id: String,
    pub principal_id: String,
    pub scope_ref: String,
    pub conversation_id: String,
    pub endpoint: Box<VerifiedChannelEndpoint>,
    pub created_by: String,
    pub created_at: String,
    pub resumed_from_binding_id: Option<String>,
    pub state: ChannelBindingState,
    pub revoked_by: Option<String>,
    pub revoked_at: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChannelDeliveryRecord {
    pub delivery_id: String,
    pub idempotency_key: String,
    pub principal_id: String,
    pub scope_ref: String,
    pub conversation_id: String,
    pub binding_id: Option<String>,
    pub channel_kind: ChannelKind,
    pub response: String,
    pub response_digest: String,
    pub state: ChannelDeliveryState,
    pub created_at: String,
    pub due_at: String,
    pub expires_at: String,
    pub retention_until: String,
    pub attempt_count: i64,
    pub lease_owner: Option<String>,
    pub lease_expires_at: Option<String>,
    pub last_error_code: Option<String>,
    pub duplicate_risk: bool,
    pub terminal_at: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChannelOriginDeletionResult {
    pub origin_ref: String,
    pub tombstone_key: String,
    pub deleted_delivery_ids: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChannelDeliveryAttempt {
    pub attempt_id: String,
    pub delivery_id: String,
    pub sequence: i64,
    pub worker_id: String,
    pub started_at: String,
    pub completed_at: Option<String>,
    pub outcome: Option<ChannelDeliveryState>,
    pub error_code: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChannelDeliveryAcknowledgement {
    pub delivery_id: String,
    pub attempt_id: String,
    pub provider_message_id: String,
    pub acknowledged_at: String,
    pub degraded_to_text: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChannelAdapterBreaker {
    pub adapter_id: String,
    pub channel_kind: ChannelKind,
    pub mode: ChannelBreakerMode,
    pub failure_timestamps: Vec<String>,
    pub revision: i64,
    pub updated_at: Option<String>,
    pub updated_by: String,
    pub reason: String,
}

impl ChannelAdapterBreaker {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.adapter_id.trim().is_empty() { return Err("adapter_id must be non-empty"); }
        if self.updated_by.trim().is_empty() { return Err("updated_by must be non-empty"); }
        if self.reason.trim().is_empty() { return Err("reason must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChannelDeliverySnapshot {
    pub deliveries: Vec<ChannelDeliveryRecord>,
    pub attempts: Vec<ChannelDeliveryAttempt>,
    pub acknowledgements: Vec<ChannelDeliveryAcknowledgement>,
    pub breakers: Vec<ChannelAdapterBreaker>,
}

impl ChannelDeliveryRecord {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn origin_ref(&self) -> String {
        String::from("")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn origin_refs(&self) -> Vec<String> {
        let mut found: Vec<String> = Vec::<String>::new();
        found.clone()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ChannelOriginPurgedError {
    pub message: String,
}

impl ChannelOriginPurgedError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ChannelOriginPurgedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ChannelOriginPurgedError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ChannelDeliveryReadbackError {
    pub message: String,
}

impl ChannelDeliveryReadbackError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ChannelDeliveryReadbackError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ChannelDeliveryReadbackError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn origin_tombstone_key(mut origin_ref: String) -> Result<String, &'static str> {
    let cleaned: String = if true { origin_ref.trim().to_string() } else { String::from("") };
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn channel_response_digest(mut response: String) -> String {
    if response.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["ChannelAdapterBreaker", "ChannelBindingState", "ChannelBreakerMode", "ChannelDeliveryAcknowledgement", "ChannelDeliveryAttempt", "ChannelDeliveryRecord", "ChannelDeliverySnapshot", "ChannelDeliveryState", "ChannelKind", "MAX_DELIVERY_ATTEMPTS", "MAX_DELIVERY_LEASE_SECONDS", "PrincipalChannelBinding", "VerifiedChannelEndpoint", "channel_response_digest"];
