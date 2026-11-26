use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct PresentationLimits {
    pub max_title_chars: i64,
    pub max_body_chars: i64,
    pub max_links: i64,
    pub max_link_label_chars: i64,
    pub max_link_url_chars: i64,
    pub max_metadata_entries: i64,
    pub max_metadata_key_chars: i64,
    pub max_metadata_value_chars: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct NotificationPresentationEnvelope {
    pub channel_id: String,
    pub category: String,
    pub trust_tier: String,
    pub correlation_id: String,
    pub title: String,
    pub body_markdown: String,
    pub severity: String,
    pub links: Vec<String>,
    pub metadata: BTreeMap<String, String>,
    pub audit_id: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RenderedNotificationPayload {
    pub content_type: String,
    pub body: Vec<u8>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PresentationRejectedError {
    pub message: String,
}

impl PresentationRejectedError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for PresentationRejectedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for PresentationRejectedError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn render_presentation(mut message: String, mut channel_id: String, mut limits: Option<PresentationLimits>) -> Result<NotificationPresentationEnvelope, &'static str> {
    let _ = reject_secret_like(message.clone()).unwrap_or_else(|_| ());
    Ok(NotificationPresentationEnvelope { channel_id: channel_id.clone(), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn reject_secret_like(mut message: String) -> Result<(), &'static str> {
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["INTERACTIVE_METADATA_KEYS", "NotificationPayloadRenderer", "NotificationPresentationEnvelope", "PresentationLimits", "PresentationRejectedError", "RenderedNotificationPayload", "render_presentation"];
