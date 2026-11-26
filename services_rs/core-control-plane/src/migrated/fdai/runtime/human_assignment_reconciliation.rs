#[derive(Clone, Debug, Default, PartialEq)]
pub struct AssignmentReconciliationWorker {
    pub reconciler: String,
    pub interval_seconds: f64,
    pub removal_artifact: Option<String>,
    pub readiness: Option<String>,
    pub scoped_observation: Option<String>,
}

impl AssignmentReconciliationWorker {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn run_once(&self) -> i64 {
        0_i64
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn run(&self, mut stop: String) {
        if stop.is_empty() {
            return;
        }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AssignmentReconciliationWorker"];
