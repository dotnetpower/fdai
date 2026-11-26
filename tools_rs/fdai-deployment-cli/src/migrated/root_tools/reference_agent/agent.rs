#[derive(Clone, Debug, Default, PartialEq)]
pub struct AgentDecision {
    pub tier: String,
    pub decision: String,
    pub citing_rule_ids: Vec<String>,
}

impl AgentDecision {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.tier.as_str(), "t0" | "t1" | "t2") { return Err("invalid tier literal"); }
        if !matches!(self.decision.as_str(), "auto" | "hil" | "abstain" | "deny") { return Err("invalid decision literal"); }
        Ok(())
    }
}

impl AgentDecision {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn touched_by_human(&self) -> bool {
        (self.decision.clone()) == (String::from("hil"))
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ReferenceAgent {
    pub initialized: bool,
}

impl ReferenceAgent {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn decide(&self, mut event: std::collections::BTreeMap<String, String>) -> AgentDecision {
        AgentDecision { tier: String::from("t2"), decision: String::from("hil"), ..Default::default() }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AgentDecision", "Decision", "ReferenceAgent", "Tier"];
