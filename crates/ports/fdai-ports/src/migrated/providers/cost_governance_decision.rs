#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CostDecisionOutcome {
    #[default]
    NoOp,
    Deny,
    Hold,
    Approval,
    Execute,
    Rollback,
}

impl CostDecisionOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::NoOp => "no-op",
            Self::Deny => "deny",
            Self::Hold => "hold",
            Self::Approval => "approval",
            Self::Execute => "execute",
            Self::Rollback => "rollback",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CostRecoveryStep {
    #[default]
    ReacquireContext,
    IndependentSource,
    RemoveUnsafeOptions,
    ReduceScope,
    SelectSafeOption,
    BoundedHold,
    ResidualApproval,
}

impl CostRecoveryStep {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ReacquireContext => "reacquire-context",
            Self::IndependentSource => "independent-source",
            Self::RemoveUnsafeOptions => "remove-unsafe-options",
            Self::ReduceScope => "reduce-scope",
            Self::SelectSafeOption => "select-safe-option",
            Self::BoundedHold => "bounded-hold",
            Self::ResidualApproval => "residual-approval",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CostRecoveryAttemptStatus {
    #[default]
    Success,
    Unavailable,
    Timeout,
    Conflict,
    Exhausted,
}

impl CostRecoveryAttemptStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Success => "success",
            Self::Unavailable => "unavailable",
            Self::Timeout => "timeout",
            Self::Conflict => "conflict",
            Self::Exhausted => "exhausted",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CostAutonomyCeiling {
    #[default]
    Observation,
    Approval,
    ExecutionEligible,
}

impl CostAutonomyCeiling {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Observation => "observation",
            Self::Approval => "approval",
            Self::ExecutionEligible => "execution_eligible",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostTargetScope {
    pub target_refs: Vec<String>,
    pub duration_seconds: i64,
    pub capacity_delta: i64,
    pub impact_units: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostActionOption {
    pub option_id: String,
    pub action_type_id: Option<String>,
    pub scope: Box<CostTargetScope>,
    pub unsafe_reasons: Vec<String>,
    pub reversible: bool,
    pub safeguards_complete: bool,
    pub no_action: bool,
    pub policy_requires_approval: bool,
    pub irreversible: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostDecisionFrame {
    pub episode_id: String,
    pub package_id: String,
    pub ontology_release_digest: String,
    pub semantic_profile_digest: String,
    pub evidence_cutoff: String,
    pub scope: Box<CostTargetScope>,
    pub options: Vec<CostActionOption>,
    pub selected_option_id: Option<String>,
    pub unresolved_facts: Vec<String>,
    pub evidence_refs: Vec<String>,
    pub policy_denied: bool,
    pub residual_risk: bool,
    pub rollback_required: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostRecoveryAttempt {
    pub step: CostRecoveryStep,
    pub status: CostRecoveryAttemptStatus,
    pub hypothesis_id: String,
    pub input_frame_digest: String,
    pub autonomy_ceiling: CostAutonomyCeiling,
    pub evidence_refs: Vec<String>,
    pub attempted_at: String,
    #[allow(clippy::type_complexity)]
    pub output_frame: Option<Box<CostDecisionFrame>>,
    pub independent_source_authority: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostDependencySnapshot {
    pub saga_available: bool,
    pub vidar_available: bool,
    pub forseti_available: bool,
    pub heimdall_available: bool,
    pub var_available: bool,
    pub observed_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostCoordinationRequest {
    pub frame: Box<CostDecisionFrame>,
    pub attempts: Vec<CostRecoveryAttempt>,
    pub dependencies: Box<CostDependencySnapshot>,
    pub initial_ceiling: CostAutonomyCeiling,
    pub hold_deadline: String,
    pub saga_intent_audit_digest: Option<String>,
    pub terminal_audit_digest: Option<String>,
    pub approval_granted: Option<bool>,
    pub approval_receipt_digest: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostDecisionRecord {
    pub episode_id: String,
    pub outcome: CostDecisionOutcome,
    pub reason: String,
    pub decision_frame_digest: String,
    pub terminal: bool,
    pub observation_mode: bool,
    pub selected_option_id: Option<String>,
    pub hold_deadline: Option<String>,
    pub evidence_refs: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostCompletenessReceipt {
    pub effect_id: String,
    pub effect_source_digest: String,
    pub receipt_digest: String,
    pub complete: bool,
    pub coverage_through_at: String,
    pub lane: String,
    pub source_authority: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostEffectObservation {
    pub observation_id: String,
    pub effect_id: String,
    pub effect_source_digest: String,
    pub target_ref: String,
    pub metric: String,
    pub value: i64,
    pub observed_at: String,
    pub lane: String,
    pub source_authority: String,
    pub evidence_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostInterventionObservation {
    pub intervention_id: String,
    pub target_ref: String,
    pub effective_at: String,
    pub source_authority: String,
    pub evidence_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostEffectSettlement {
    pub effect_id: String,
    pub kind: String,
    pub status: String,
    pub reason: String,
    pub terminal: bool,
    pub observed_value: Option<i64>,
    pub observation_digest: Option<String>,
    pub completeness_digest: Option<String>,
    pub settled_at: String,
    pub savings_evidence_class: Option<String>,
    pub currency: Option<String>,
    pub baseline_window_digest: Option<String>,
    pub treatment_window_digest: Option<String>,
    pub demand_normalization_digest: Option<String>,
    pub finalized_billing_receipt_digest: Option<String>,
    pub allocation_rule_digest: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostPostRecoveryObservation {
    pub recovery_request_id: String,
    pub observed_at: String,
    pub restored: bool,
    pub complete: bool,
    pub lane: String,
    pub source_authority: String,
    pub evidence_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostRollbackRequest {
    pub request_id: String,
    pub episode_id: String,
    pub decision_frame_digest: String,
    pub failed_effect_ids: Vec<String>,
    pub stop_requested: bool,
    pub rollback_requested: bool,
    pub reason: String,
    pub requested_at: String,
    pub evidence_refs: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostEpisodeSettlement {
    pub episode_id: String,
    pub decision_frame_digest: String,
    pub action_ref: String,
    pub action_revision: i64,
    pub effects: Vec<CostEffectSettlement>,
    pub terminal: bool,
    pub realized_savings: i64,
    pub realized_savings_currency: Option<String>,
    pub realized_savings_evidence_class: Option<String>,
    #[allow(clippy::type_complexity)]
    pub rollback_request: Option<Box<CostRollbackRequest>>,
    pub recovery_observed: bool,
    pub settled_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostCaseProjection {
    pub episode_id: String,
    pub revision: i64,
    pub decision: Box<CostDecisionRecord>,
    #[allow(clippy::type_complexity)]
    pub settlement: Option<Box<CostEpisodeSettlement>>,
    pub recovery_attempts: Vec<CostRecoveryAttempt>,
    pub evidence_refs: Vec<String>,
    pub terminal_audit_digest: Option<String>,
    pub lineage_complete: bool,
    pub projection_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostLearningCohortInput {
    pub cohort_id: String,
    pub case_refs: Vec<String>,
    pub positive_count: i64,
    pub negative_count: i64,
    pub lineage_digest: String,
    pub inert: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostEpisodePersistenceRecord {
    pub episode_id: String,
    pub revision: i64,
    pub idempotency_key: String,
    pub outcome: CostDecisionOutcome,
    pub reason: String,
    pub decision_frame_digest: String,
    pub terminal: bool,
    pub recorded_at: String,
    pub retention_until: String,
    pub legal_hold: bool,
    pub legal_hold_ref: Option<String>,
    pub purged_at: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostEvidenceRecord {
    pub episode_id: String,
    pub episode_revision: i64,
    pub evidence_sequence: i64,
    pub evidence_ref: String,
    pub evidence_digest: String,
    pub source_authority: String,
    pub recorded_at: String,
    pub idempotency_key: String,
}

impl CostTargetScope {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn does_not_widen(&self, mut previous: CostTargetScope) -> bool {
        core::hint::black_box(false)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("capacity_delta"), (self.capacity_delta).to_string()), (String::from("duration_seconds"), String::new()), (String::from("impact_units"), String::new()), (String::from("target_refs"), String::new())])
    }
}

impl CostActionOption {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn safe(&self) -> bool {
        ((self.unsafe_reasons.clone()).is_empty()) && (((self.no_action) || (self.safeguards_complete)) && ((self.no_action) || ((self.reversible) || (self.irreversible))))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("action_type_id"), (self.action_type_id.clone()).unwrap_or_default()), (String::from("irreversible"), String::new()), (String::from("no_action"), String::new()), (String::from("option_id"), self.option_id.clone()), (String::from("policy_requires_approval"), String::new()), (String::from("reversible"), String::new()), (String::from("safeguards_complete"), String::new()), (String::from("scope"), String::new()), (String::from("unsafe_reasons"), String::new())])
    }
}

impl CostDecisionFrame {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn digest(&self) -> String {
        core::hint::black_box(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn selected_option(&self) -> Option<CostActionOption> {
        core::hint::black_box(None)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("episode_id"), self.episode_id.clone()), (String::from("evidence_cutoff"), String::new()), (String::from("evidence_refs"), String::new()), (String::from("ontology_release_digest"), self.ontology_release_digest.clone()), (String::from("options"), String::new()), (String::from("package_id"), self.package_id.clone()), (String::from("policy_denied"), String::new()), (String::from("residual_risk"), String::new()), (String::from("rollback_required"), String::new()), (String::from("scope"), String::new()), (String::from("selected_option_id"), (self.selected_option_id.clone()).unwrap_or_default()), (String::from("semantic_profile_digest"), self.semantic_profile_digest.clone()), (String::from("unresolved_facts"), String::new())])
    }
}

pub trait CostGovernanceEpisodeStore {
    fn append_cost_episode(&self, record: CostEpisodePersistenceRecord, expected_revision: i64) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn effects_or_unique(mut effect_ids: Vec<String>) -> bool {
    (!(effect_ids.clone()).is_empty()) && ((((effect_ids.clone()).len() as i64)) == ((((effect_ids.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)))
}

pub const PUBLIC_EXPORTS: &[&str] = &["COST_RECOVERY_ORDER", "CostActionOption", "CostAutonomyCeiling", "CostCaseProjection", "CostCompletenessReceipt", "CostCoordinationRequest", "CostDecisionFrame", "CostDecisionOutcome", "CostDecisionRecord", "CostDependencySnapshot", "CostEffectKind", "CostEffectObservation", "CostEffectSettlement", "CostEvidenceRecord", "CostEpisodePersistenceRecord", "CostEpisodeSettlement", "CostExpectedEffect", "CostGovernanceEpisodeStore", "CostInterventionObservation", "CostLearningCohortInput", "CostObservationLane", "CostPostRecoveryObservation", "CostRecoveryAttempt", "CostRecoveryAttemptStatus", "CostRecoveryStep", "CostRollbackRequest", "CostSettlementStatus", "CostSavingsEvidenceClass", "CostTargetScope"];
