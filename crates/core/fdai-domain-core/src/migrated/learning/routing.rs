pub trait RuleHintSubmitter {
    fn submit_rule_hint(&self, hint: String, proposed_by: String, at: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct GovernedPostTurnProposalRouter {
    pub initialized: bool,
}

impl GovernedPostTurnProposalRouter {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn route(&self, mut proposal: String, mut proposed_by: String, mut at: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["GovernedPostTurnProposalRouter", "RuleHintSubmitter"];
