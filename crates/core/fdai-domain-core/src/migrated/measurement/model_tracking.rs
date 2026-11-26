#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SwapOutcome {
    #[default]
    NoChange,
    AdoptChallenger,
    BlockedGuardBreach,
}

impl SwapOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::NoChange => "no_change",
            Self::AdoptChallenger => "adopt_challenger",
            Self::BlockedGuardBreach => "blocked_guard_breach",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ModelObservation {
    pub model_id: String,
    pub scenario_set_version: String,
    pub quality_score: f64,
    pub cost_per_verified_answer: f64,
    pub verifier_abstain_rate: f64,
    pub mixed_model_disagreement_rate: f64,
}

impl ModelObservation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.model_id.trim().is_empty() { return Err("model_id must be non-empty"); }
        if self.scenario_set_version.trim().is_empty() { return Err("scenario_set_version must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SwapDecision {
    pub incumbent_model_id: String,
    pub challenger_model_id: String,
    pub outcome: SwapOutcome,
    pub reasons: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ModelSwapConfig {
    pub quality_gain_threshold: f64,
    pub max_abstain_rate: f64,
    pub max_disagreement_rate: f64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ModelSwapPolicy {
    pub initialized: bool,
}

impl ModelSwapPolicy {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn evaluate(&self, mut incumbent: ModelObservation, mut challenger: ModelObservation) -> Result<SwapDecision, &'static str> {
        if (incumbent.scenario_set_version.clone()) != (challenger.scenario_set_version.clone()) {
            return Err("incumbent and challenger MUST share scenario_set_version -  fgot incumbe");
        }
        let mut reasons: Vec<String> = Vec::<String>::new();
        let quality_delta: f64 = (challenger.quality_score) - (incumbent.quality_score);
        let beats_cost: bool = (challenger.cost_per_verified_answer) <= (incumbent.cost_per_verified_answer);
        let mut guard_ok: bool = true;
        Ok(SwapDecision { incumbent_model_id: incumbent.model_id.clone(), challenger_model_id: challenger.model_id.clone(), reasons: reasons.clone(), ..Default::default() })
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ModelObservation", "ModelSwapConfig", "ModelSwapPolicy", "SwapDecision", "SwapOutcome"];
