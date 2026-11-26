#[derive(Clone, Debug, Default, PartialEq)]
pub struct ClaimedBackgroundTaskProjection {
    pub outbox_sequence: i64,
    pub projection_id: String,
    pub task_id: String,
    pub attempt_id: String,
    pub record: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BackgroundTaskProjectionPublisher {
    pub outbox: String,
    pub topic: String,
    pub worker_id: String,
    pub batch_size: i64,
    pub lease_seconds: i64,
    pub idle_seconds: f64,
    pub clock: String,
    pub lease_token_factory: String,
}

impl BackgroundTaskProjectionPublisher {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.outbox.trim().is_empty() { return Err("outbox must be non-empty"); }
        if self.topic.trim().is_empty() { return Err("topic must be non-empty"); }
        if self.worker_id.trim().is_empty() { return Err("worker_id must be non-empty"); }
        if self.clock.trim().is_empty() { return Err("clock must be non-empty"); }
        if self.lease_token_factory.trim().is_empty() { return Err("lease_token_factory must be non-empty"); }
        Ok(())
    }
}

pub trait BackgroundTaskProjectionOutbox {
    fn verify_schema(&self) -> String;
}

impl BackgroundTaskProjectionPublisher {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn run(&self, mut bus: String, mut stop: String) {
        if bus.is_empty() {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn run_once(&self, mut bus: String) -> bool {
        let mut published_any: bool = false;
        true
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn release_claims(&self, mut claims: Vec<ClaimedBackgroundTaskProjection>, mut lease_token: String, mut error_code: String) {
        if claims.is_empty() {
            return;
        }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn lease_token() -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn utc_now() -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn payload(mut record: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["BackgroundTaskProjectionOutbox", "BackgroundTaskProjectionPublisher", "ClaimedBackgroundTaskProjection"];
