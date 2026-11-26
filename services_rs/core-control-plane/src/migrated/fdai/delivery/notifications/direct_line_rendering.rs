pub const MAX_PAYLOAD_BYTES: i64 = 49152;
pub const MAX_TITLE_CHARS: i64 = 250;
pub const MAX_BODY_CHARS: i64 = 3000;

pub const DIRECT_LINE_DEFAULT_SENDER_ID: &str = "fdai-notifications";
pub const SENDER_NAME: &str = "FDAI";
pub const CONTENT_TYPE: &str = "application/json";
pub const SENDER_ID: &str = "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$";
pub const MARKDOWN_CONTROL: &str = "([\\\\`*_\\[\\]<>|~])";
pub const LINK_TARGET_SAFE: &str = ":/?#[]@!$&'*+,;=%-._~";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn require_direct_line_sender_id(mut sender_id: String) -> Result<String, &'static str> {
    Ok(sender_id.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn render_direct_line_payload(mut envelope: String, mut sender_id: String) -> Result<String, &'static str> {
    if envelope.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn direct_line_idempotency_key(mut envelope: String) -> String {
    if envelope.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn activity(mut message: String, mut sender_id: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("type"), String::from("message")), (String::from("from"), String::new()), (String::from("textFormat"), String::from("markdown")), (String::from("text"), String::new()), (String::from("channelData"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn inline(mut value: String) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn link_target(mut url: String) -> String {
    if url.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["DIRECT_LINE_DEFAULT_SENDER_ID", "direct_line_idempotency_key", "render_direct_line_payload", "require_direct_line_sender_id"];
