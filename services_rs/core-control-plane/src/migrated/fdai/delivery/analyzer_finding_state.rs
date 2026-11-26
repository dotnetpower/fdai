#[derive(Clone, Debug, Default, PartialEq)]
pub struct AnalyzerFindingStateStore {
    pub state_store: String,
    pub max_cas_attempts: i64,
}

impl AnalyzerFindingStateStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn record(&self, mut receipt: String) -> Result<(), &'static str> {
        Err("Finding projection contention exceeded its bounded retry budget")
    }
}

