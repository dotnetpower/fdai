pub const SCHEDULER_KEY: &str = "__cross_vertical_timeout_scheduler__";
pub trait ForsetiTimeoutHost {
    fn expire_cross_vertical_candidates(&self, correlation_id: String) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn start_cross_vertical_timeout(mut host: String, mut correlation_id: String, mut delay_seconds: Option<f64>) {
    if host.is_empty() {
        return;
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn ensure_timeout_scheduler(mut host: String) {
    if host.is_empty() {
        return;
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn run_timeout_scheduler(mut host: String) {
    if host.is_empty() {
        return;
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn observe_cross_vertical_timeout_task(mut host: String, mut task: String) {
    if host.is_empty() {
        return;
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn cancel_cross_vertical_timeout(mut task: String) {
    if task.is_empty() {
        return;
    }
}

