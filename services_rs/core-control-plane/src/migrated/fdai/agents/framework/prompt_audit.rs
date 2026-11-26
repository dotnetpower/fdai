#[derive(Clone, Debug, Default, PartialEq)]
pub struct PromptAuditItem {
    pub item_id: i64,
    pub name: String,
    pub passed: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PromptAuditResult {
    pub agent: String,
    pub score: i64,
    pub items: Vec<PromptAuditItem>,
    pub prompt_sha256: String,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn audit_agent_prompt(mut spec: String) -> PromptAuditResult {
    PromptAuditResult::default()
}

pub const PUBLIC_EXPORTS: &[&str] = &["PromptAuditItem", "PromptAuditResult", "audit_agent_prompt"];
