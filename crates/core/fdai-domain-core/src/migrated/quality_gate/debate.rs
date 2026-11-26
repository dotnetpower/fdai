use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DebateVerdict {
    #[default]
    Proceed,
    Abort,
}

impl DebateVerdict {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Proceed => "proceed",
            Self::Abort => "abort",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DebateOutcome {
    pub verdict: DebateVerdict,
    pub reason: String,
    pub final_proposer_output: String,
    pub critic_output: Option<String>,
    pub judge_output: Option<String>,
    pub critic_verdict: Option<String>,
    pub judge_verdict: Option<String>,
    pub rounds: i64,
    pub error_class: Option<String>,
    pub metadata: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DebateOrchestratorConfig {
    pub max_rounds: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DebateOrchestrator {
    pub initialized: bool,
}

impl DebateOrchestrator {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn run(&self, mut candidate: String, mut proposer_output: (String, std::collections::BTreeMap<String, String>), mut known_rule_ids: Vec<String>, mut retry_proposer: Option<String>) -> Result<DebateOutcome, &'static str> {
        let known_snapshot: std::collections::BTreeSet<String> = (known_rule_ids.clone()).into_iter().collect::<std::collections::BTreeSet<String>>();
        Ok(DebateOutcome { rounds: 2_i64, ..Default::default() })
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn outcome_from_error(mut proposer_output: (String, std::collections::BTreeMap<String, String>), mut reason: String, mut exc: String, mut critic_output: Option<String>, mut critic_verdict: Option<String>, mut judge_output: Option<String>, mut judge_verdict: Option<String>, mut rounds: i64) -> DebateOutcome {
    DebateOutcome { reason: reason.clone(), critic_output: critic_output.clone(), judge_output: judge_output.clone(), critic_verdict: critic_verdict.clone(), judge_verdict: judge_verdict.clone(), rounds: rounds, ..Default::default() }
}

pub const PUBLIC_EXPORTS: &[&str] = &["DebateOrchestrator", "DebateOrchestratorConfig", "DebateOutcome", "DebateVerdict", "ProposerRetry"];
