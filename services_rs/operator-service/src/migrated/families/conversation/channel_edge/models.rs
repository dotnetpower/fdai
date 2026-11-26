pub const MAX_ATTACHMENT_COUNT: i64 = 8;
pub const MAX_TEXT_CHARS: i64 = 16000;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChannelAttachment {
    pub source_ref: String,
    pub name: String,
    pub size_bytes: i64,
    pub media_type_hint: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InboundChannelTurn {
    pub channel_kind: String,
    pub channel_id: String,
    pub message_id: String,
    pub sender_id: String,
    pub text: String,
    pub thread_id: Option<String>,
    pub attachments: Vec<ChannelAttachment>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AuthenticatedInboundTurn {
    pub turn: Box<InboundChannelTurn>,
    pub principal_id: String,
    pub verification_ref: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RenderedChannelMessage {
    pub channel_kind: String,
    pub channel_id: String,
    pub payload: String,
    pub thread_id: Option<String>,
    pub edit_message_id: Option<String>,
    pub degraded_to_text: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChannelDeliveryReceipt {
    pub channel_kind: String,
    pub channel_id: String,
    pub message_id: String,
    pub degraded_to_text: bool,
}

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

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn payload_size(mut value: String) -> i64 {
    0_i64
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn bounded(mut name: String, mut value: String, mut maximum: i64) -> Result<(), &'static str> {
    if (((value.clone()).trim().to_string()).is_empty()) || ((((value.clone()).len() as i64)) > (maximum)) {
        return Err("name MUST be a non-empty bounded string");
    }
    Ok(())
}

pub const PUBLIC_EXPORTS: &[&str] = &["MAX_ATTACHMENT_COUNT", "MAX_TEXT_CHARS", "AuthenticatedInboundTurn", "ChannelAttachment", "ChannelDeliveryError", "ChannelDeliveryReceipt", "ChannelKind", "InboundChannelTurn", "RenderedChannelMessage", "payload_size"];
