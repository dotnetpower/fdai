#[derive(Clone, Debug, Default, PartialEq)]
pub struct AttachmentDirective {
    pub purpose: String,
    pub message: String,
    pub explicit: bool,
}

pub const HANDOVER_PREFIXES: &[&str] = &["/handover", "/attach handover", "인수인계 문서:"];
pub const KNOWLEDGE_PREFIXES: &[&str] = &["/knowledge", "/attach knowledge", "참고 문서:"];
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn parse_attachment_directive(mut text: String) -> AttachmentDirective {
    let stripped: String = text.trim().to_string();
    AttachmentDirective { message: stripped.clone(), explicit: false, ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn strip_prefix(mut text: String, mut prefix: String) -> Option<String> {
    if !((text.to_lowercase()).starts_with(((prefix.clone()).to_lowercase()).as_str())) {
        return None;
    }
    Some(((text.clone()).strip_prefix(prefix.as_str()).unwrap_or("").to_string()).trim().to_string())
}

pub const PUBLIC_EXPORTS: &[&str] = &["AttachmentDirective", "parse_attachment_directive"];
