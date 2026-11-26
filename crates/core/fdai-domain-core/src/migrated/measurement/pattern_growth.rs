#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum IntakeOutcome {
    #[default]
    Accepted,
    RejectedRolledBack,
    RejectedNotAuto,
    RejectedNotVerified,
}

impl IntakeOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Accepted => "accepted",
            Self::RejectedRolledBack => "rejected_rolled_back",
            Self::RejectedNotAuto => "rejected_not_auto",
            Self::RejectedNotVerified => "rejected_not_verified",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum HoldoutOutcome {
    #[default]
    Pass,
    FailFpRate,
    InsufficientData,
}

impl HoldoutOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Pass => "pass",
            Self::FailFpRate => "fail_fp_rate",
            Self::InsufficientData => "insufficient_data",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OutcomeRecord {
    pub action_id: String,
    pub action_type_id: String,
    pub observed_at: String,
    pub was_auto: bool,
    pub was_verified: bool,
    pub was_rolled_back: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct IntakeDecision {
    pub action_id: String,
    pub outcome: IntakeOutcome,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PatternCandidate {
    pub pattern_id: String,
    pub action_type_id: String,
    pub learned_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PatternValidationSample {
    pub pattern_id: String,
    pub observed_at: String,
    pub was_correct: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct HoldoutDecision {
    pub pattern_id: String,
    pub outcome: HoldoutOutcome,
    pub observed_fp_rate: f64,
    pub sample_size: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TemporalHoldoutConfig {
    pub min_samples: i64,
    pub fp_rate_ceiling: f64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct TemporalHoldoutValidator {
    pub initialized: bool,
}

impl TemporalHoldoutValidator {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn evaluate(&self, mut candidate: PatternCandidate, mut holdout: Vec<PatternValidationSample>) -> HoldoutDecision {
        HoldoutDecision { pattern_id: candidate.pattern_id.clone(), ..Default::default() }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn evaluate_intake(mut record: OutcomeRecord) -> IntakeDecision {
    if record.was_rolled_back {
        return IntakeDecision::default();
    }
    if !(record.was_auto) {
        return IntakeDecision::default();
    }
    if !(record.was_verified) {
        return IntakeDecision::default();
    }
    IntakeDecision::default()
}

pub const PUBLIC_EXPORTS: &[&str] = &["HoldoutDecision", "HoldoutOutcome", "IntakeDecision", "IntakeOutcome", "OutcomeRecord", "PatternCandidate", "PatternValidationSample", "TemporalHoldoutConfig", "TemporalHoldoutValidator", "evaluate_intake"];
