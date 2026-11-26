#[derive(Clone, Debug, Default, PartialEq)]
pub struct QualificationVenueSelection {
    pub installation_id: String,
    pub venue: String,
    pub target_scope_digest: String,
    pub access_scope_digest: String,
    pub fdai_revision: String,
    pub read_source_revision: String,
    pub graph_source_revision: String,
    pub slo_revision: String,
    pub safety_budget_revision: String,
    pub window_start: String,
    pub window_end: String,
    pub deadline_seconds: f64,
    pub authorized_by_operator: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PredeclaredLearningEvaluationGates {
    pub slo_revision: String,
    pub safety_budget_revision: String,
    pub min_independent_episodes_per_arm: i64,
    pub min_time_separation: String,
    pub observation_window: String,
    pub recurrence_window: String,
    pub min_recovery_rate: f64,
    pub max_recurrence_rate: f64,
    pub max_rollback_rate: f64,
    pub max_side_effect_count: i64,
    pub max_policy_escape_count: i64,
    pub max_mean_absolute_error: f64,
    pub max_brier_score: f64,
    pub min_interval_coverage: f64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FrozenProvenanceQualification {
    pub total_latest_outcomes: i64,
    pub qualified_interventions_count: i64,
    pub unknown_preserved_count: i64,
    pub held_provenance_count: i64,
    pub qualified_outcome_ids: Vec<String>,
    pub unknown_outcome_ids: Vec<String>,
    pub execution_authority: bool,
    pub promotion_authority: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct FrozenT1ShadowIntakeSummary {
    pub evaluated_events: i64,
    pub baseline_selections_preserved: i64,
    pub coherent_qualified_shadow_matches: i64,
    pub leased_qualified_shadow_matches: i64,
    pub withdrawal_rejections_verified: i64,
    pub deadline_and_cancellation_holds_verified: i64,
    pub stale_or_expired_holds_verified: i64,
    pub execution_authority_granted: bool,
    pub promotion_authority_granted: bool,
    pub baseline_mutated: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OperationalLearningEpisode {
    pub episode_id: String,
    pub arm: String,
    pub incident_id: String,
    pub independence_key: String,
    pub common_cause_key: String,
    pub idempotency_key: String,
    pub observed_at: String,
    pub is_retry_or_replay: bool,
    pub execution_mode: String,
    pub decision: String,
    pub recommended: bool,
    pub abstained: bool,
    pub intervention_completed: bool,
    pub outcome_known: bool,
    pub recovered: Option<bool>,
    pub recovery_seconds: Option<f64>,
    pub recurrence_window_complete: bool,
    pub recurred: Option<bool>,
    pub rolled_back: bool,
    pub side_effect_escaped: bool,
    pub policy_escaped: bool,
    pub predicted_recovery_probability: Option<f64>,
    pub point_prediction: Option<f64>,
    pub interval_lower: Option<f64>,
    pub interval_upper: Option<f64>,
    pub observed_value: Option<f64>,
    pub propensity_overlap_verified: bool,
}

impl OperationalLearningEpisode {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.arm.as_str(), "baseline" | "challenger") { return Err("invalid arm literal"); }
        if !matches!(self.execution_mode.as_str(), "shadow" | "enforce") { return Err("invalid execution_mode literal"); }
        if !matches!(self.decision.as_str(), "auto" | "hil" | "deny" | "abstain") { return Err("invalid decision literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RecoveryMetrics {
    pub executed_denominator: i64,
    pub recovered_count: i64,
    pub recovery_rate: Option<f64>,
    pub wilson_95_lower: Option<f64>,
    pub wilson_95_upper: Option<f64>,
    pub mean_recovery_seconds: Option<f64>,
    pub unknown_outcome_count: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RecurrenceMetrics {
    pub completed_window_denominator: i64,
    pub recurred_count: i64,
    pub recurrence_rate: Option<f64>,
    pub wilson_95_lower: Option<f64>,
    pub wilson_95_upper: Option<f64>,
    pub censored_incomplete_window_count: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RollbackAndSideEffectMetrics {
    pub executed_denominator: i64,
    pub rolled_back_count: i64,
    pub rollback_rate: Option<f64>,
    pub rollback_wilson_95_upper: Option<f64>,
    pub side_effect_count: i64,
    pub side_effect_rate: Option<f64>,
    pub side_effect_wilson_95_upper: Option<f64>,
    pub policy_escape_count: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AbstentionAndCoverageMetrics {
    pub independent_episode_denominator: i64,
    pub recommended_count: i64,
    pub recommendation_coverage: Option<f64>,
    pub coverage_wilson_95_lower: Option<f64>,
    pub coverage_wilson_95_upper: Option<f64>,
    pub abstained_count: i64,
    pub abstention_rate: Option<f64>,
    pub abstention_wilson_95_lower: Option<f64>,
    pub abstention_wilson_95_upper: Option<f64>,
    pub conditional_success_rate: Option<f64>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PredictionAndCalibrationMetrics {
    pub scored_scalar_count: i64,
    pub mean_absolute_error: Option<f64>,
    pub root_mean_squared_error: Option<f64>,
    pub interval_coverage: Option<f64>,
    pub interval_coverage_wilson_95_lower: Option<f64>,
    pub interval_coverage_wilson_95_upper: Option<f64>,
    pub mean_interval_width: Option<f64>,
    pub calibration_sample_count: i64,
    pub brier_score: Option<f64>,
    pub expected_calibration_error: Option<f64>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SampleCountAndUncertaintySummary {
    pub raw_observation_count: i64,
    pub excluded_retry_or_replay_count: i64,
    pub excluded_duplicate_group_count: i64,
    pub excluded_time_separation_count: i64,
    pub independent_episode_count: i64,
    pub unknown_outcome_count: i64,
    pub confidence_level: f64,
    pub interval_method: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ArmOperationalMetrics {
    pub arm: String,
    pub recovery: Box<RecoveryMetrics>,
    pub recurrence: Box<RecurrenceMetrics>,
    pub rollback_and_side_effects: Box<RollbackAndSideEffectMetrics>,
    pub abstention_and_coverage: Box<AbstentionAndCoverageMetrics>,
    pub prediction_and_calibration: Box<PredictionAndCalibrationMetrics>,
    pub sample_counts: Box<SampleCountAndUncertaintySummary>,
}

impl ArmOperationalMetrics {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.arm.as_str(), "baseline" | "challenger") { return Err("invalid arm literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OperationalLearningEffectReport {
    pub scope: Box<QualificationVenueSelection>,
    pub gates: Box<PredeclaredLearningEvaluationGates>,
    pub provenance: Box<FrozenProvenanceQualification>,
    pub t1_shadow_intake: Box<FrozenT1ShadowIntakeSummary>,
    pub baseline: Box<ArmOperationalMetrics>,
    pub challenger: Box<ArmOperationalMetrics>,
    pub gates_passed: bool,
    pub gate_failures: Vec<String>,
    pub policy_effect_claimed: bool,
    pub execution_authority: bool,
    pub promotion_authority: bool,
}

pub const HEX64: &str = "^(?:sha256:)?[0-9a-f]{64}$";
pub const WILSON_Z_95: f64 = 1.959963984540054;
impl QualificationVenueSelection {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn scope_manifest_digest(&self) -> String {
        core::hint::black_box(String::new())
    }
}

impl PredeclaredLearningEvaluationGates {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn gate_plan_digest(&self) -> String {
        core::hint::black_box(String::new())
    }
}

impl OperationalLearningEffectReport {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn require_aware(mut value: String, mut label: String) -> Result<String, &'static str> {
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn require_non_empty(mut value: String, mut label: String) -> Result<String, &'static str> {
    let stripped: String = value.trim().to_string();
    if (stripped.clone()).is_empty() {
        return Err("label MUST be non-empty");
    }
    Ok(stripped.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn wilson_95(mut successes: i64, mut denominator: i64) -> (Option<f64>, Option<f64>) {
    if (denominator) <= (0_i64) {
        return (None, None);
    }
    let z2: f64 = (WILSON_Z_95) * (WILSON_Z_95);
    (None, None)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn qualify_frozen_intervention_provenance(mut outcomes: Vec<String>, mut retained_predictions: std::collections::BTreeMap<String, String>, mut model_generation_digests: std::collections::BTreeSet<String>, mut as_of: String) -> FrozenProvenanceQualification {
    let _ = require_aware(as_of.clone(), String::from("as_of")).unwrap_or_else(|_| String::new());
    let mut qualified_ids: Vec<String> = Vec::<String>::new();
    let mut unknown_ids: Vec<String> = Vec::<String>::new();
    let mut held: i64 = 0_i64;
    FrozenProvenanceQualification { qualified_interventions_count: ((qualified_ids.clone()).len() as i64), unknown_preserved_count: ((unknown_ids.clone()).len() as i64), held_provenance_count: held, qualified_outcome_ids: qualified_ids.clone(), unknown_outcome_ids: unknown_ids.clone(), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn evaluate_arm(mut arm: String, mut episodes: Vec<OperationalLearningEpisode>, mut gates: PredeclaredLearningEvaluationGates, mut seen_incidents: std::collections::BTreeSet<String>, mut seen_independence: std::collections::BTreeSet<String>, mut seen_common_cause: std::collections::BTreeSet<String>, mut seen_idempotency: std::collections::BTreeSet<String>) -> (ArmOperationalMetrics, Vec<OperationalLearningEpisode>) {
    let raw_count: i64 = (episodes.clone()).len() as i64;
    let mut retry_excluded: i64 = 0_i64;
    let mut dup_excluded: i64 = 0_i64;
    let mut time_excluded: i64 = 0_i64;
    let mut independent: Vec<OperationalLearningEpisode> = Vec::<OperationalLearningEpisode>::new();
    let mut last_time: Option<String> = None;
    let ind_denom: i64 = (independent.clone()).len() as i64;
    (ArmOperationalMetrics { arm: arm.clone(), recovery: Box::new(RecoveryMetrics::default()), recurrence: Box::new(RecurrenceMetrics::default()), rollback_and_side_effects: Box::new(RollbackAndSideEffectMetrics::default()), abstention_and_coverage: Box::new(AbstentionAndCoverageMetrics { independent_episode_denominator: ind_denom, ..Default::default() }), prediction_and_calibration: Box::new(PredictionAndCalibrationMetrics::default()), sample_counts: Box::new(SampleCountAndUncertaintySummary { raw_observation_count: raw_count, excluded_retry_or_replay_count: retry_excluded, excluded_duplicate_group_count: dup_excluded, excluded_time_separation_count: time_excluded, independent_episode_count: ind_denom, ..Default::default() }), ..Default::default() }, independent.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn evaluate_operational_learning_effects(mut scope: QualificationVenueSelection, mut gates: PredeclaredLearningEvaluationGates, mut provenance: FrozenProvenanceQualification, mut t1_shadow_intake: FrozenT1ShadowIntakeSummary, mut episodes: Vec<OperationalLearningEpisode>, mut claim_policy_effect: bool) -> Result<OperationalLearningEffectReport, &'static str> {
    if ((scope.slo_revision.clone()) != (gates.slo_revision.clone())) || ((scope.safety_budget_revision.clone()) != (gates.safety_budget_revision.clone())) {
        return Err("scope and predeclared gates MUST bind the same SLO and safety revisions");
    }
    let seen_incidents: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let seen_independence: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let seen_common_cause: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let seen_idempotency: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let mut failures: Vec<String> = Vec::<String>::new();
    Ok(OperationalLearningEffectReport { scope: Box::new(scope.clone()), gates: Box::new(gates.clone()), provenance: Box::new(provenance.clone()), t1_shadow_intake: Box::new(t1_shadow_intake.clone()), gates_passed: (failures.clone()).is_empty(), gate_failures: failures.clone(), ..Default::default() })
}

