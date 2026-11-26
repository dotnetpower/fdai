#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Vertical {
    #[default]
    ResilienceSafetyHold,
    Resilience,
    ChangeSafety,
    Cost,
}

impl Vertical {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ResilienceSafetyHold => "resilience_safety_hold",
            Self::Resilience => "resilience",
            Self::ChangeSafety => "change_safety",
            Self::Cost => "cost",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PrecedenceOutcome {
    #[default]
    Win,
    Defer,
    EscalateHil,
}

impl PrecedenceOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Win => "win",
            Self::Defer => "defer",
            Self::EscalateHil => "escalate_hil",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CandidateAction {
    pub action_id: String,
    pub resource_id: String,
    pub vertical: Vertical,
    pub deferrable: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PrecedenceDecision {
    pub action_id: String,
    pub vertical: Vertical,
    pub outcome: PrecedenceOutcome,
    pub reasons: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PrecedenceResolver {
    pub initialized: bool,
}

impl PrecedenceResolver {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn resolve(&self, mut candidates: Vec<CandidateAction>) -> Vec<PrecedenceDecision> {
        let mut decisions: Vec<PrecedenceDecision> = Vec::<PrecedenceDecision>::new();
        let by_resource: std::collections::BTreeMap<String, Vec<CandidateAction>> = std::collections::BTreeMap::<String, Vec<CandidateAction>>::new();
        for (resource_id, group) in by_resource.clone() {
            if (((group.clone()).len() as i64)) == (1_i64) {
                decisions.push(PrecedenceDecision::default());
                continue;
            }
            decisions.push(PrecedenceDecision::default());
        }
        decisions.clone()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["CandidateAction", "PrecedenceDecision", "PrecedenceOutcome", "PrecedenceResolver", "Vertical"];
