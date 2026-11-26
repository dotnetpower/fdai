#[derive(Clone, Debug, Default, PartialEq)]
pub struct ObservationWorkerReport {
    pub considered: i64,
    pub verified: i64,
    pub mismatched: i64,
    pub held: i64,
    pub ownership_conflicts: i64,
    pub provider_failures: i64,
    pub execution_authority: bool,
}

pub trait PendingEffectObserver {
    fn call(&self, record: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PendingEffectObservationWorker {
    pub initialized: bool,
}

impl PendingEffectObservationWorker {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn run_once(&self) -> ObservationWorkerReport {
        ObservationWorkerReport::default()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn observe(&self, mut record: String, mut now: String) -> String {
        let mut provider_failed: bool = false;
        if provider_failed {
            return String::from("provider_failure");
        }
        String::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ObservationWorkerReport", "PendingEffectObservationWorker", "PendingEffectObserver"];
