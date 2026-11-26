#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleActivationRequestNotice {
    pub schema_version: String,
    pub proposal_ref: String,
    pub proposal_id: String,
    pub request_id: String,
    pub proposal_digest: String,
    pub operation: String,
    pub accepted_at: String,
    pub producer_service: String,
    pub approval_authority: bool,
    pub activation_authority: bool,
    pub execution_authority: bool,
}

impl RuleActivationRequestNotice {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.operation.as_str(), "rule.activation-request" | "rule.activation-approve") { return Err("invalid operation literal"); }
        if !matches!(self.producer_service.as_str(), "operator-service") { return Err("invalid producer_service literal"); }
        if self.approval_authority { return Err("approval_authority violated literal bool invariant"); }
        if self.activation_authority { return Err("activation_authority violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

pub const RULE_ACTIVATION_REQUEST_TOPIC: &str = "operator.rule-activation.requests";
pub const RULE_ACTIVATION_CONSUMER_GROUP: &str = "core-rule-activation-v1";
pub const RULE_ACTIVATION_PROJECTION_TOPIC: &str = "core.rule-activation.projections";
impl RuleActivationRequestNotice {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn identity(&self) -> Result<RuleActivationRequestNotice, &'static str> {
        if ((self.operation.clone()) == (String::from("rule.activation-request"))) && ((self.request_id.clone()) != (self.proposal_id.clone())) {
            return Err("Rule activation request notice must reference itself");
        }
        Ok(self.clone())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["RULE_ACTIVATION_CONSUMER_GROUP", "RULE_ACTIVATION_PROJECTION_TOPIC", "RULE_ACTIVATION_REQUEST_TOPIC", "RuleActivationRequestNotice"];
