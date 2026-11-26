pub const MAX_TEXT_CHARS: i64 = 4000;
pub const MAX_PAYLOAD_BYTES: i64 = 24000;

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn render_answer(mut response: String, mut locale: String) -> String {
    let korean: bool = (locale.clone()) == (String::from("ko"));
    let mut lines: Vec<String> = Vec::<String>::new();
    lines.push(if korean { String::from("`execution_authority=false`이며 이 답변은 변경을 승인하지 않습니다.") } else { String::from("`execution_authority=false`; this answer authorizes no change.") });
    let rendered: String = (lines.clone()).join("\n");
    (rendered.clone()).chars().take((MAX_TEXT_CHARS).max(0) as usize).collect::<String>()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn teams_payload(mut response: String, mut locale: String, mut reply_to_id: String) -> std::collections::BTreeMap<String, String> {
    let text: String = render_answer(response.clone(), locale.clone());
    let payload: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("type"), String::from("message")), (String::from("replyToId"), reply_to_id.clone()), (String::from("text"), text.clone()), (String::from("attachments"), String::new())]);
    payload.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn outgoing_webhook_payload(mut response: String, mut locale: String) -> std::collections::BTreeMap<String, String> {
    let text: String = render_answer(response.clone(), locale.clone());
    let payload: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("type"), String::from("message")), (String::from("text"), text.clone()), (String::from("attachments"), String::new())]);
    payload.clone()
}

pub const PUBLIC_EXPORTS: &[&str] = &["outgoing_webhook_payload", "render_answer", "teams_payload"];
