#[derive(Clone, Debug, Default, PartialEq)]
pub struct BackpressureConfig {
    pub max_concurrency: i64,
    pub max_queued: i64,
    pub acquire_timeout_s: Option<f64>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Backpressure {
    pub config: Box<BackpressureConfig>,
    pub shed_count: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct LoadShedError {
    pub message: String,
}

impl LoadShedError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for LoadShedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for LoadShedError {}

impl Backpressure {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn slot(&mut self) -> Result<Vec<()>, &'static str> {
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn snapshot(&self) -> std::collections::BTreeMap<String, i64> {
        std::collections::BTreeMap::from([(String::from("in_flight"), 0_i64), (String::from("waiting"), 0_i64), (String::from("shed_count"), self.shed_count), (String::from("max_concurrency"), 0_i64), (String::from("max_queued"), 0_i64)])
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["Backpressure", "BackpressureConfig", "LoadShedError"];
