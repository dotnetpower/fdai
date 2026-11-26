use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum StageName {
    #[default]
    Ingest,
    Route,
    Verify,
    Gate,
    Execute,
    Audit,
}

impl StageName {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Ingest => "ingest",
            Self::Route => "route",
            Self::Verify => "verify",
            Self::Gate => "gate",
            Self::Execute => "execute",
            Self::Audit => "audit",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum StagePhase {
    #[default]
    Begin,
    Progress,
    Done,
    Failed,
}

impl StagePhase {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Begin => "begin",
            Self::Progress => "progress",
            Self::Done => "done",
            Self::Failed => "failed",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ObservationSource {
    #[default]
    Unknown,
    SyntheticDev,
    Replay,
    RuntimeObserved,
}

impl ObservationSource {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Unknown => "unknown",
            Self::SyntheticDev => "synthetic-dev",
            Self::Replay => "replay",
            Self::RuntimeObserved => "runtime-observed",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct StageEvent {
    pub event_id: String,
    pub correlation_id: String,
    pub stage: StageName,
    pub phase: StagePhase,
    pub source: ObservationSource,
    pub ts: String,
    pub detail: BTreeMap<String, String>,
    pub error: Option<String>,
}

impl StageEvent {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        let mut out: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("event_id"), self.event_id.clone()), (String::from("correlation_id"), self.correlation_id.clone()), (String::from("stage"), String::new()), (String::from("phase"), String::new()), (String::from("source"), String::new()), (String::from("ts"), iso(self.ts.clone()))]);
        if self.error.is_some() {
            out.insert(String::from("error"), (self.error.clone()).unwrap_or_default());
        }
        out.clone()
    }
}

pub trait StagePublisher {
    fn emit(&self, event: StageEvent) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NullStagePublisher {
    pub initialized: bool,
}

impl NullStagePublisher {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn emit(&self, mut event: StageEvent) {
        if !self.initialized {
            return;
        }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn iso(mut ts: String) -> String {
    if ts.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["NullStagePublisher", "ObservationSource", "StageEvent", "StageName", "StagePhase", "StagePublisher"];
