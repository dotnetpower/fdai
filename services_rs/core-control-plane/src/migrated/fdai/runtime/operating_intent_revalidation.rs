#[derive(Clone, Debug, Default, PartialEq)]
pub struct OperatingIntentSourceRevalidationWorker {
    pub runtime: String,
}

impl OperatingIntentSourceRevalidationWorker {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn interval_seconds(&self) -> i64 {
        0_i64
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn run_once(&self, mut now: Option<String>) {
        if now.is_none() {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn run(&self, mut stop: String) {
        if stop.is_empty() {
            return;
        }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["OperatingIntentSourceRevalidationWorker"];
