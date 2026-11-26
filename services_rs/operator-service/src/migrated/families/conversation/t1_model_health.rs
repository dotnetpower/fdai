#[derive(Clone, Debug, Default, PartialEq)]
pub struct T1ModelHealthReader {
    pub store: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Candidate {
    pub deployment: String,
    pub status: String,
    pub measured_at: Option<String>,
    pub p50_ms: Option<String>,
    pub p95_ms: Option<String>,
    pub samples: i64,
    pub history_ms: Vec<String>,
    pub ttft_p50_ms: Option<String>,
    pub ttft_p95_ms: Option<String>,
    pub ttft_samples: i64,
    pub ttft_history_ms: Vec<String>,
}

impl Candidate {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.status.as_str(), "measured" | "unmeasured" | "failed" | "stale") { return Err("invalid status literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RouterContract {
    pub chose: String,
    pub reason: String,
    pub updated_at: String,
    pub expires_at: String,
    pub interval_seconds: i64,
    pub candidates: Vec<Candidate>,
}

impl RouterContract {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.reason.as_str(), "latency" | "unmeasured" | "stale" | "unavailable" | "disabled") { return Err("invalid reason literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Projection {
    pub schema_version: i64,
    pub source: String,
    pub execution_authority: bool,
    pub model: Option<String>,
    pub router: Box<RouterContract>,
}

impl Projection {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.source.as_str(), "core-t1-mini-routing") { return Err("invalid source literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

pub const T1_ROUTING_STATE_KEY: &str = "conversation:t1-mini-routing:v1";
pub trait T1RoutingStateStore {
    fn read_state(&self, key: String) -> String;
}

impl T1ModelHealthReader {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn read(&self) -> String {
        core::hint::black_box(String::new())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn t1_model_health(mut value: String, mut now: Option<String>) -> Result<String, &'static str> {
    let chosen_expired: bool = false;
    Ok(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["T1ModelHealthReader", "T1_ROUTING_STATE_KEY", "t1_model_health"];
