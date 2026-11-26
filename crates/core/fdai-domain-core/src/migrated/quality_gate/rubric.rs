#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RubricCriterion {
    #[default]
    Faithfulness,
    EvidenceActionAlignment,
    Completeness,
    ReasoningCoherence,
}

impl RubricCriterion {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Faithfulness => "faithfulness",
            Self::EvidenceActionAlignment => "evidence_action_alignment",
            Self::Completeness => "completeness",
            Self::ReasoningCoherence => "reasoning_coherence",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RubricVerdict {
    #[default]
    Pass,
    Fail,
    Abstain,
}

impl RubricVerdict {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Pass => "pass",
            Self::Fail => "fail",
            Self::Abstain => "abstain",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RubricScore {
    pub criterion: String,
    pub score: f64,
    pub threshold: f64,
    pub rationale: String,
    pub supporting_rule_ids: Vec<String>,
}

impl RubricScore {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.criterion.trim().is_empty() { return Err("criterion must be non-empty"); }
        if self.rationale.trim().is_empty() { return Err("rationale must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RubricOutput {
    pub scores: Vec<RubricScore>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RubricDecision {
    pub verdict: RubricVerdict,
    pub min_score: f64,
    pub failed_criteria: Vec<String>,
    pub scores: Vec<RubricScore>,
    pub reasons: Vec<String>,
}

impl RubricScore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn passed(&self) -> bool {
        (self.score) >= (self.threshold)
    }
}

pub trait RubricEvaluator {
    fn score(&self, candidate: String) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn evaluate_rubric_output(mut output: RubricOutput, mut known_rule_ids: Vec<String>, mut required_criteria: Vec<String>, mut known_criteria: Option<Vec<String>>, mut supports: Option<String>) -> RubricDecision {
    let known: std::collections::BTreeSet<String> = (known_rule_ids.clone()).into_iter().collect::<std::collections::BTreeSet<String>>();
    let required: Vec<String> = required_criteria.clone();
    let scores: Vec<RubricScore> = output.scores.clone();
    if (scores.clone()).is_empty() {
        return RubricDecision { min_score: 0.0, scores: scores.clone(), ..Default::default() };
    }
    if let Some(mut known_criteria) = known_criteria.clone() {
        let valid: std::collections::BTreeSet<String> = (known_criteria.clone()).into_iter().collect::<std::collections::BTreeSet<String>>();
    }
    RubricDecision { scores: scores.clone(), ..Default::default() }
}

pub const PUBLIC_EXPORTS: &[&str] = &["RubricCriterion", "RubricDecision", "RubricEvaluator", "RubricOutput", "RubricScore", "RubricVerdict", "evaluate_rubric_output"];
