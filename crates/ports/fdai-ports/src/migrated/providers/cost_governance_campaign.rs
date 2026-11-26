use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CostCampaignOutcome {
    #[default]
    BeneficialAction,
    NoOp,
    Deny,
    HoldUnresolved,
    Approval,
    Execute,
    Rollback,
}

impl CostCampaignOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::BeneficialAction => "beneficial-action",
            Self::NoOp => "no-op",
            Self::Deny => "deny",
            Self::HoldUnresolved => "hold-unresolved",
            Self::Approval => "approval",
            Self::Execute => "execute",
            Self::Rollback => "rollback",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CostCampaignSettlement {
    #[default]
    Verified,
    Failed,
    Censored,
    Unscorable,
}

impl CostCampaignSettlement {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Verified => "verified",
            Self::Failed => "failed",
            Self::Censored => "censored",
            Self::Unscorable => "unscorable",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CostValidationStopCondition {
    #[default]
    OntologyCompetencyRegression,
    WrongTopicOwner,
    MissingProtectedObjective,
    MissingSafeguard,
    MissingHardDependency,
    MissingEffectPath,
    UnexplainedParityDifference,
    PolicyEscape,
    ObjectiveRegression,
    MissingSettlement,
    FailedRollback,
    DisclosureLeak,
}

impl CostValidationStopCondition {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::OntologyCompetencyRegression => "ontology-competency-regression",
            Self::WrongTopicOwner => "wrong-topic-owner",
            Self::MissingProtectedObjective => "missing-protected-objective",
            Self::MissingSafeguard => "missing-safeguard",
            Self::MissingHardDependency => "missing-hard-dependency",
            Self::MissingEffectPath => "missing-effect-path",
            Self::UnexplainedParityDifference => "unexplained-parity-difference",
            Self::PolicyEscape => "policy-escape",
            Self::ObjectiveRegression => "objective-regression",
            Self::MissingSettlement => "missing-settlement",
            Self::FailedRollback => "failed-rollback",
            Self::DisclosureLeak => "disclosure-leak",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostCampaignEpisode {
    pub schema_version: String,
    pub campaign_id: String,
    pub episode_id: String,
    pub revision: i64,
    pub idempotency_key: String,
    pub revision_pin_digest: String,
    pub evidence_kind: String,
    pub outcome: CostCampaignOutcome,
    pub reason: String,
    pub target_refs: Vec<String>,
    pub settlement_statuses: Vec<CostCampaignSettlement>,
    pub recovery_attempts: i64,
    pub policy_excluded: bool,
    pub policy_escape: bool,
    pub objective_regression: bool,
    pub audit_complete: bool,
    pub hard_dependencies_complete: bool,
    pub unauthorized_disclosure: bool,
    pub ontology_competency_passed: bool,
    pub topic_owner_correct: bool,
    pub protected_objectives_complete: bool,
    pub safeguards_complete: bool,
    pub effect_path_complete: bool,
    pub parity_explained: bool,
    pub rollback_evidence_complete: bool,
    pub decision_correct: bool,
    pub observed_at: String,
    pub evidence_refs: Vec<String>,
    pub retention_until: String,
    pub legal_hold: bool,
    pub legal_hold_ref: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostCampaignReport {
    pub schema_version: String,
    pub campaign_id: String,
    pub review_target_id: Option<String>,
    pub revision_pin: String,
    pub sample_count: i64,
    pub eligible_count: i64,
    pub excluded_count: i64,
    pub beneficial_action_count: i64,
    pub no_op_count: i64,
    pub deny_count: i64,
    pub hold_unresolved_count: i64,
    pub approval_count: i64,
    pub execute_count: i64,
    pub rollback_count: i64,
    pub recovery_attempt_count: i64,
    pub verified_settlement_count: i64,
    pub failed_settlement_count: i64,
    pub censored_settlement_count: i64,
    pub unscorable_settlement_count: i64,
    pub policy_escape_count: i64,
    pub objective_regression_count: i64,
    pub audit_complete_count: i64,
    pub hard_dependency_complete_count: i64,
    pub unauthorized_disclosure_count: i64,
    pub correct_decision_count: i64,
    pub shadow_dwell_seconds: i64,
    pub evidence_kinds: Vec<String>,
    pub stop_conditions: Vec<CostValidationStopCondition>,
    pub approval_reason_counts: BTreeMap<String, i64>,
    pub evidence_refs: Vec<String>,
}

pub const DIGEST_PATTERN: &str = "^sha256:[0-9a-f]{64}$";
impl CostCampaignEpisode {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn digest(&self) -> String {
        canonical_digest(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::new()
    }
}

impl CostCampaignReport {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn accuracy(&self) -> i64 {
        0_i64
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn digest(&self) -> String {
        canonical_digest(String::new())
    }
}

pub trait CostCampaignStore {
    fn append_cost_campaign_episode(&self, episode: CostCampaignEpisode, expected_revision: i64) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn text(mut name: String, mut value: String) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn digest(mut name: String, mut value: String) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn aware(mut name: String, mut value: String) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn canonical_digest(mut value: String) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["CostCampaignEpisode", "CostCampaignOutcome", "CostCampaignReport", "CostCampaignSettlement", "CostCampaignStore", "CostValidationStopCondition"];
