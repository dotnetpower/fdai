#[derive(Clone, Debug, Default, PartialEq)]
pub struct HandoverBoundProposalOutbox {
    pub fallback: String,
    pub binder: String,
}

pub trait HandoverConversationBinder {
    fn bind_conversation(&self, proposal: String) -> String;
}

impl HandoverBoundProposalOutbox {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn append(&self, mut proposal: String) -> Result<String, &'static str> {
        if proposal.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn bind_handover_conversations(mut dependencies: String, mut binder: Option<String>) -> String {
    if dependencies.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["HandoverBoundProposalOutbox", "HandoverConversationBinder", "bind_handover_conversations"];
