#[derive(Clone, Debug, Default, PartialEq)]
pub struct DecisionQueueApprovalControl {
    pub requires_human_approval: bool,
    pub required_role: String,
    pub quorum: i64,
    pub no_self_approval: bool,
    pub approval_status: String,
}

impl DecisionQueueApprovalControl {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.required_role.trim().is_empty() { return Err("required_role must be non-empty"); }
        if self.approval_status.trim().is_empty() { return Err("approval_status must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DecisionQueueItem {
    pub case_id: String,
    pub process_id: Option<String>,
    pub target_resource_ref: String,
    pub recommended_option_id: Option<String>,
    pub recommended_action_type: Option<String>,
    pub expected_effects: Vec<String>,
    pub uncertainty: f64,
    pub blast_radius_tier: String,
    pub change_risk_tier: String,
    pub cost_of_delay_amount: Option<i64>,
    pub cost_of_delay_currency: Option<String>,
    pub evidence_refs: Vec<String>,
    pub approval_control: Box<DecisionQueueApprovalControl>,
    pub created_at: String,
    pub read_only: bool,
    pub execution_authority: bool,
}

impl DecisionQueueItem {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.case_id.trim().is_empty() { return Err("case_id must be non-empty"); }
        if self.target_resource_ref.trim().is_empty() { return Err("target_resource_ref must be non-empty"); }
        if self.blast_radius_tier.trim().is_empty() { return Err("blast_radius_tier must be non-empty"); }
        if self.change_risk_tier.trim().is_empty() { return Err("change_risk_tier must be non-empty"); }
        if self.created_at.trim().is_empty() { return Err("created_at must be non-empty"); }
        if !self.read_only { return Err("read_only violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DecisionQueueProjection {
    pub items: Vec<DecisionQueueItem>,
    pub ranking_currency: Option<String>,
    pub as_of: String,
    pub projection_digest: String,
    pub read_only: bool,
    pub execution_authority: bool,
}

impl DecisionQueueProjection {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !self.read_only { return Err("read_only violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

pub const VALID_TIERS: &[&str] = &["low", "medium", "high", "critical", "unknown"];
pub const APPROVAL_STATUSES: &[&str] = &["pending", "approved", "rejected", "expired"];
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn build_decision_queue_item(mut case: String, mut selection: String, mut target_resource_ref: String, mut approval_control: DecisionQueueApprovalControl, mut blast_radius_tier: String, mut change_risk_tier: String, mut cost_of_delay_reading: Option<std::collections::BTreeMap<String, String>>, mut envelope_uncertainty: Option<f64>) -> DecisionQueueItem {
    let mut amount: Option<i64> = None;
    let mut currency: Option<String> = None;
    DecisionQueueItem { target_resource_ref: target_resource_ref.clone(), blast_radius_tier: blast_radius_tier.clone(), change_risk_tier: change_risk_tier.clone(), cost_of_delay_amount: amount.clone(), cost_of_delay_currency: currency.clone(), approval_control: Box::new(approval_control.clone()), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn build_decision_queue_projection(mut items: Vec<DecisionQueueItem>, mut as_of: String, mut ranking_currency: Option<String>) -> Result<DecisionQueueProjection, &'static str> {
    Ok(DecisionQueueProjection { as_of: as_of.clone(), ..Default::default() })
}

pub const PUBLIC_EXPORTS: &[&str] = &["DecisionQueueApprovalControl", "DecisionQueueItem", "DecisionQueueProjection", "build_decision_queue_item", "build_decision_queue_projection"];
