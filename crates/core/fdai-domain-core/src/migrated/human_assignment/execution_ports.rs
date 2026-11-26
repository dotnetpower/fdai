#[derive(Clone, Debug, Default, PartialEq)]
pub struct HumanAccessAgentBindings {
    pub judge_request: String,
    pub judge_decision: String,
    pub judge_effect: String,
    pub review: String,
    pub prepare: String,
    pub record_effect: String,
    pub dispatch: String,
    pub observe: String,
    pub observe_notice: String,
    pub judge_recovery: Option<String>,
    pub propose_recovery: Option<String>,
    pub finish_recovery: Option<String>,
    pub resume: Option<String>,
    pub record_failure: Option<String>,
}

impl HumanAccessAgentBindings {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn execution_bound(&self) -> bool {
        core::hint::black_box(false)
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["HumanAccessAgentBindings"];
