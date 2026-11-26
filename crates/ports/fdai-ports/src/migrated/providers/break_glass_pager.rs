#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct BreakGlassPagerError {
    pub message: String,
}

impl BreakGlassPagerError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for BreakGlassPagerError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for BreakGlassPagerError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct BreakGlassNoChannelError {
    pub message: String,
}

impl BreakGlassNoChannelError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for BreakGlassNoChannelError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for BreakGlassNoChannelError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct BreakGlassDeliveryError {
    pub message: String,
}

impl BreakGlassDeliveryError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for BreakGlassDeliveryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for BreakGlassDeliveryError {}

pub trait BreakGlassPager {
    fn notify_owners(&self, actor_oid: String, actor_display: String, reason_redacted: String, activated_at: String, expires_at: String) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["BreakGlassDeliveryError", "BreakGlassNoChannelError", "BreakGlassPager", "BreakGlassPagerError"];
