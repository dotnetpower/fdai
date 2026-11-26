use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CriticStance {
    #[default]
    Agree,
    Challenge,
    Abstain,
}

impl CriticStance {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Agree => "agree",
            Self::Challenge => "challenge",
            Self::Abstain => "abstain",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CriticSeverity {
    #[default]
    Low,
    Medium,
    High,
}

impl CriticSeverity {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Low => "low",
            Self::Medium => "medium",
            Self::High => "high",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CriticVerdict {
    #[default]
    Endorse,
    Retry,
    Abort,
    Abstain,
}

impl CriticVerdict {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Endorse => "endorse",
            Self::Retry => "retry",
            Self::Abort => "abort",
            Self::Abstain => "abstain",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CriticObjection {
    pub severity: CriticSeverity,
    pub cited_rule_id: String,
    pub description: String,
    pub alt_action_type: Option<String>,
}

impl CriticObjection {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.cited_rule_id.trim().is_empty() { return Err("cited_rule_id must be non-empty"); }
        if self.description.trim().is_empty() { return Err("description must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CriticOutput {
    pub stance: CriticStance,
    pub objections: Vec<CriticObjection>,
    pub citations: Vec<String>,
    pub confidence_signals: BTreeMap<String, f64>,
}

pub trait CriticModel {
    #[allow(clippy::type_complexity)]
    fn critique(&self, candidate: String, proposer_output: (String, std::collections::BTreeMap<String, String>)) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn evaluate_critic_output(mut output: CriticOutput, mut known_rule_ids: Vec<String>) -> CriticVerdict {
    let known: std::collections::BTreeSet<String> = (known_rule_ids.clone()).into_iter().collect::<std::collections::BTreeSet<String>>();
    Default::default()
}

pub const PUBLIC_EXPORTS: &[&str] = &["CriticModel", "CriticObjection", "CriticOutput", "CriticSeverity", "CriticStance", "CriticVerdict", "evaluate_critic_output"];
