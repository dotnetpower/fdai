use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct GroundedDecisionToolCallReceipt {
    pub function_name: String,
    pub target_ref: String,
    pub output: BTreeMap<String, String>,
    pub invocation_receipt: String,
    pub execution_authority: bool,
}

impl GroundedDecisionToolCallReceipt {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkflowIntentSpec {
    pub name: String,
    pub description: String,
    pub signal_type: String,
    pub ontology_gate_functions: Vec<String>,
    pub approval_role: String,
    pub approval_quorum: i64,
    pub action_type_ref: String,
    pub compensated_by: Option<String>,
    #[allow(clippy::type_complexity)]
    pub action_params: Option<BTreeMap<String, String>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct IncidentRcaHypothesisSelection {
    pub incident_id: String,
    pub admitted_hypotheses: Vec<String>,
    pub withheld_hypothesis_ids: Vec<String>,
    pub receipt_digests: Vec<String>,
    pub selection_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AbstentionRecoveryPlan {
    pub target_ref: String,
    pub action_type_ref: String,
    pub required_probes: Vec<String>,
    pub unresolved_reasons: Vec<String>,
    pub plan_digest: String,
    pub execution_authority: bool,
}

impl AbstentionRecoveryPlan {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.action_type_ref.as_str(), "tool.run-investigation") { return Err("invalid action_type_ref literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ApproverDecisionBriefing {
    pub process_id: String,
    pub workflow_name: String,
    pub target_resource_ref: String,
    pub recommended_action_type: String,
    pub compensated_by: Option<String>,
    pub blast_radius_tier: String,
    pub change_risk_tier: String,
    pub impacted_service_refs: Vec<String>,
    pub supported_hypothesis_id: Option<String>,
    pub refuted_or_withheld_count: i64,
    pub cost_of_delay_amount: Option<i64>,
    pub cost_of_delay_currency: Option<String>,
    pub evidence_refs: Vec<String>,
    pub briefing_digest: String,
    pub generated_at: String,
    pub read_only: bool,
    pub execution_authority: bool,
}

impl ApproverDecisionBriefing {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !self.read_only { return Err("read_only violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct OntologyDecisionToolAdapter {
    pub initialized: bool,
}

impl OntologyDecisionToolAdapter {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn invoke_decision_tool(&self, mut caller_agent: String, mut function_name: String, mut target_ref: String, mut arguments: std::collections::BTreeMap<String, String>) -> Result<GroundedDecisionToolCallReceipt, &'static str> {
        if ((target_ref.clone()).trim().to_string()).is_empty() {
            return Err("target_ref MUST be non-empty");
        }
        Ok(GroundedDecisionToolCallReceipt { function_name: function_name.clone(), target_ref: target_ref.clone(), ..Default::default() })
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn compile_intent_to_shadow_workflow(mut intent: WorkflowIntentSpec, mut registered_action_types: std::collections::BTreeSet<String>) -> Result<String, &'static str> {
    if !((registered_action_types.clone()).contains((intent.action_type_ref.clone()).as_str())) {
        return Err("Unknown action_type_ref: intent.action_type_refr");
    }
    if ((intent.compensated_by.clone()).is_some()) && (!((registered_action_types.clone()).contains(((intent.compensated_by.clone()).unwrap_or_default()).as_str()))) {
        return Err("Unknown compensated_by ActionType: intent.compensated_byr");
    }
    if (intent.ontology_gate_functions.clone()).is_empty() {
        return Err("Compiled workflow intent MUST include at least one ontology gate");
    }
    let mut steps: Vec<String> = Vec::<String>::new();
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn select_graded_hypotheses_for_incident_rca(mut incident_id: String, mut candidates: Vec<(String, String)>) -> Result<IncidentRcaHypothesisSelection, &'static str> {
    if (incident_id.trim().to_string()).is_empty() {
        return Err("incident_id MUST be non-empty");
    }
    let mut admitted: Vec<String> = Vec::<String>::new();
    let mut withheld: Vec<String> = Vec::<String>::new();
    let mut digests: Vec<String> = Vec::<String>::new();
    let ordered_withheld: Vec<String> = { let mut _v = withheld.clone(); _v.sort(); _v };
    let ordered_digests: Vec<String> = ((digests.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).into_iter().collect::<Vec<String>>();
    Ok(IncidentRcaHypothesisSelection { incident_id: incident_id.clone(), withheld_hypothesis_ids: ordered_withheld.clone(), receipt_digests: ordered_digests.clone(), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn plan_evidence_recovery_on_abstention(mut target_ref: String, mut decision_reason_codes: Vec<String>, mut missing_refutation_reads: Vec<String>) -> Result<Option<AbstentionRecoveryPlan>, &'static str> {
    if (target_ref.trim().to_string()).is_empty() {
        return Err("target_ref MUST be non-empty");
    }
    let mut probes: Vec<String> = Vec::<String>::new();
    for ref_read in missing_refutation_reads.clone() {
        probes.push(format!("probe.refutation_{}", ref_read.clone()));
    }
    let unique_probes: Vec<String> = ((probes.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).into_iter().collect::<Vec<String>>();
    Ok(Some(AbstentionRecoveryPlan { target_ref: target_ref.clone(), action_type_ref: String::from("tool.run-investigation"), required_probes: unique_probes.clone(), ..Default::default() }))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn build_approver_decision_briefing(mut process_id: String, mut workflow_name: String, mut target_resource_ref: String, mut recommended_action_type: String, mut compensated_by: Option<String>, mut blast_radius_reading: std::collections::BTreeMap<String, String>, mut change_risk_reading: std::collections::BTreeMap<String, String>, mut impacted_service_refs: Vec<String>, mut rca_selection: Option<IncidentRcaHypothesisSelection>, mut cost_of_delay_reading: Option<std::collections::BTreeMap<String, String>>, mut evidence_refs: Vec<String>, mut generated_at: String) -> Result<ApproverDecisionBriefing, &'static str> {
    let blast_tier: String = ((blast_radius_reading.clone()).get("tier").cloned()).unwrap_or_else(|| String::from("unknown"));
    let risk_tier: String = ((change_risk_reading.clone()).get("tier").cloned()).unwrap_or_else(|| String::from("unknown"));
    let services: Vec<String> = ((impacted_service_refs.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).into_iter().collect::<Vec<String>>();
    let mut amount: Option<i64> = None;
    let mut currency: Option<String> = None;
    let refs: Vec<String> = ((evidence_refs.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).into_iter().collect::<Vec<String>>();
    if (refs.clone()).is_empty() {
        return Err("ApproverDecisionBriefing requires at least one evidence_ref");
    }
    Ok(ApproverDecisionBriefing { process_id: process_id.clone(), workflow_name: workflow_name.clone(), target_resource_ref: target_resource_ref.clone(), recommended_action_type: recommended_action_type.clone(), compensated_by: compensated_by.clone(), blast_radius_tier: blast_tier.clone(), change_risk_tier: risk_tier.clone(), impacted_service_refs: services.clone(), cost_of_delay_amount: amount.clone(), cost_of_delay_currency: currency.clone(), evidence_refs: refs.clone(), generated_at: generated_at.clone(), ..Default::default() })
}

pub const PUBLIC_EXPORTS: &[&str] = &["ALLOWED_DECISION_TOOL_NAMES", "AbstentionRecoveryPlan", "ApproverDecisionBriefing", "GroundedDecisionToolCallReceipt", "IncidentRcaHypothesisSelection", "OntologyDecisionToolAdapter", "WorkflowIntentSpec", "build_approver_decision_briefing", "compile_intent_to_shadow_workflow", "plan_evidence_recovery_on_abstention", "select_graded_hypotheses_for_incident_rca"];
