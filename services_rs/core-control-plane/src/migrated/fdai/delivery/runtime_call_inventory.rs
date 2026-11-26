use std::collections::BTreeMap;
pub const MAX_RUNTIME_CALL_OBSERVATIONS: i64 = 2000;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuntimeCallTelemetryRecord {
    pub envelope: String,
    pub claimed_context: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuntimeCallTelemetryBatch {
    pub records: Vec<RuntimeCallTelemetryRecord>,
    pub observed_at: Option<String>,
    pub complete: bool,
    pub reason: Option<String>,
    pub coverage: BTreeMap<String, i64>,
}

pub const RUNTIME_CALL_SOURCE_NAME: &str = "runtime_call_graph";
pub trait RuntimeCallTelemetrySource {
    fn collect(&self, observation: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct UnavailableRuntimeCallInventoryEnricher {
    pub initialized: bool,
}

impl UnavailableRuntimeCallInventoryEnricher {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn enrich(&self, mut observation: String) -> String {
        unavailable(observation.clone(), String::from("telemetry_source_unavailable"), None)
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RuntimeCallInventoryEnricher {
    pub initialized: bool,
}

impl RuntimeCallInventoryEnricher {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn enrich(&self, mut observation: String) -> String {
        let mut projected: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
        String::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn unavailable(mut observation: String, mut reason: String, mut coverage: Option<std::collections::BTreeMap<String, i64>>) -> String {
    if observation.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["RUNTIME_CALL_SOURCE_NAME", "RuntimeCallInventoryEnricher", "RuntimeCallTelemetryBatch", "RuntimeCallTelemetryRecord", "RuntimeCallTelemetrySource", "UnavailableRuntimeCallInventoryEnricher"];
