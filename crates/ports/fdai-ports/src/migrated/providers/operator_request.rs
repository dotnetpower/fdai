#[derive(Clone, Debug, Default, PartialEq)]
pub struct OperatorProposalDispatch {
    pub decision: String,
    pub approval_ref: Option<String>,
    pub process_ref: Option<String>,
}

impl OperatorProposalDispatch {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.decision.trim().is_empty() { return Err("decision must be non-empty"); }
        Ok(())
    }
}

pub trait OperatorProposalDispatcher {
    fn dispatch(&self, proposal: std::collections::BTreeMap<String, String>) -> OperatorProposalDispatch;
}

pub const PUBLIC_EXPORTS: &[&str] = &["OperatorProposalDispatch", "OperatorProposalDispatcher"];
