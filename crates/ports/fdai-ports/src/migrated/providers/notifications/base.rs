use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ChannelKind {
    #[default]
    Teams,
    Slack,
    Email,
    Webhook,
    Pagerduty,
    Sms,
    DirectLine,
    Console,
}

impl ChannelKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Teams => "teams",
            Self::Slack => "slack",
            Self::Email => "email",
            Self::Webhook => "webhook",
            Self::Pagerduty => "pagerduty",
            Self::Sms => "sms",
            Self::DirectLine => "direct_line",
            Self::Console => "console",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum TrustTier {
    #[default]
    A1HilApproval,
    A2OperationalAlert,
    A3ChatCommand,
    A4Digest,
}

impl TrustTier {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::A1HilApproval => "a1_hil_approval",
            Self::A2OperationalAlert => "a2_operational_alert",
            Self::A3ChatCommand => "a3_chat_command",
            Self::A4Digest => "a4_digest",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Severity {
    #[default]
    Info,
    Warn,
    Error,
    Critical,
}

impl Severity {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Info => "info",
            Self::Warn => "warn",
            Self::Error => "error",
            Self::Critical => "critical",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Link {
    pub label: String,
    pub url: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct NotificationMessage {
    pub category: String,
    pub trust_tier: TrustTier,
    pub correlation_id: String,
    pub title: String,
    pub body_markdown: String,
    pub severity: Severity,
    pub audit_id: Option<String>,
    pub links: Vec<Link>,
    pub metadata: BTreeMap<String, String>,
    pub template_key: Option<String>,
    pub params: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DeliveryReceipt {
    pub channel_kind: ChannelKind,
    pub channel_id: String,
    pub delivered: bool,
    pub accepted: bool,
    pub provider_message_id: Option<String>,
    pub error: Option<String>,
}

pub const CHANNEL_ID: &str = "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ChannelDeliveryError {
    pub message: String,
}

impl ChannelDeliveryError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ChannelDeliveryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ChannelDeliveryError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ChannelUnavailableError {
    pub message: String,
}

impl ChannelUnavailableError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ChannelUnavailableError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ChannelUnavailableError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ChannelAmbiguousError {
    pub message: String,
}

impl ChannelAmbiguousError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ChannelAmbiguousError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ChannelAmbiguousError {}

pub trait NotificationChannel {
    fn send(&self, message: NotificationMessage) -> String;
}

pub trait HilEscalationSink {
    fn escalate(&self, message: NotificationMessage, reason: String) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn require_channel_id(mut value: String) -> Result<String, &'static str> {
    Ok(value.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["ChannelDeliveryError", "ChannelAmbiguousError", "ChannelKind", "ChannelUnavailableError", "DeliveryReceipt", "HilEscalationSink", "Link", "NotificationChannel", "NotificationMessage", "Severity", "TrustTier", "require_channel_id"];
