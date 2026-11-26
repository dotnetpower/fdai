#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DrExperimentKind {
    #[default]
    Chaos,
    SiteRecoveryTestFailover,
}

impl DrExperimentKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Chaos => "chaos",
            Self::SiteRecoveryTestFailover => "site_recovery_test_failover",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum DrRunStatus {
    #[default]
    Running,
    Succeeded,
    Failed,
    Stopped,
}

impl DrRunStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Running => "running",
            Self::Succeeded => "succeeded",
            Self::Failed => "failed",
            Self::Stopped => "stopped",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DrRunHandle {
    pub experiment_id: String,
    pub kind: DrExperimentKind,
    pub provider_ref: String,
    pub run_id: String,
    pub started_at: String,
    pub status_url: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DrRunnerError {
    pub message: String,
}

impl DrRunnerError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for DrRunnerError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for DrRunnerError {}

pub trait DrExperimentRunner {
    fn start(&self, experiment: String) -> DrRunHandle;
    fn check(&self, handle: DrRunHandle) -> DrRunStatus;
    fn rollback(&self, handle: DrRunHandle);
}

pub const PUBLIC_EXPORTS: &[&str] = &["DrExperimentKind", "DrExperimentRunner", "DrRunHandle", "DrRunStatus", "DrRunnerError"];
