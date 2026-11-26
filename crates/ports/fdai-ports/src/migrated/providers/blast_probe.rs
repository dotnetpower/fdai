use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ProbeVerdict {
    #[default]
    Quiet,
    Active,
    Overloaded,
    NoOpinion,
}

impl ProbeVerdict {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Quiet => "quiet",
            Self::Active => "active",
            Self::Overloaded => "overloaded",
            Self::NoOpinion => "no_opinion",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProbeQuery {
    pub probe_id: String,
    pub target_ref: String,
    pub deadline_seconds: f64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProbeResult {
    pub verdict: ProbeVerdict,
    pub reason: String,
    pub degraded: bool,
    pub metrics: BTreeMap<String, f64>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct BlastProbeError {
    pub message: String,
}

impl BlastProbeError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for BlastProbeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for BlastProbeError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct BlastProbeTimeoutError {
    pub message: String,
}

impl BlastProbeTimeoutError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for BlastProbeTimeoutError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for BlastProbeTimeoutError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct BlastProbeConfigError {
    pub message: String,
}

impl BlastProbeConfigError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for BlastProbeConfigError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for BlastProbeConfigError {}

pub trait LiveBlastProbe {
    fn measure(&self, query: ProbeQuery) -> String;
}

pub trait BlastSignalSource {
    fn read(&self, query: ProbeQuery) -> String;
}

pub trait ProbeFailureStreakSource {
    fn get(&self, query: ProbeQuery) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["BlastProbeConfigError", "BlastProbeError", "BlastProbeTimeoutError", "BlastSignalSource", "LiveBlastProbe", "ProbeQuery", "ProbeFailureStreakSource", "ProbeResult", "ProbeVerdict"];
