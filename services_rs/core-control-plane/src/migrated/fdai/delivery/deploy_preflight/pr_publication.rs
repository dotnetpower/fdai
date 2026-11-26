#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PreflightHoldReason {
    #[default]
    Unavailable,
    PatchDrift,
    ScopeDrift,
    StaleEvidence,
    IncompleteCoverage,
    BlockingFinding,
    InvalidReport,
}

impl PreflightHoldReason {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Unavailable => "unavailable",
            Self::PatchDrift => "patch_drift",
            Self::ScopeDrift => "scope_drift",
            Self::StaleEvidence => "stale_evidence",
            Self::IncompleteCoverage => "incomplete_coverage",
            Self::BlockingFinding => "blocking_finding",
            Self::InvalidReport => "invalid_report",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RefreshedPreflight {
    pub report: String,
    pub patch_sha256: String,
}

pub const MAX_FUTURE_SKEW_SECONDS: f64 = 60.0;
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PreflightPublicationHoldError {
    pub message: String,
}

impl PreflightPublicationHoldError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for PreflightPublicationHoldError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for PreflightPublicationHoldError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PreflightVerifiedPrPublisher {
    pub initialized: bool,
}

impl PreflightVerifiedPrPublisher {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn publish(&self, mut pr: String) -> Result<String, &'static str> {
        let age: Option<f64> = age_seconds(String::new(), String::new());
        Ok(String::new())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn age_seconds(mut report: String, mut now: String) -> Option<f64> {
    if report.is_empty() {
        return None;
    }
    None
}

pub const PUBLIC_EXPORTS: &[&str] = &["PreflightHoldReason", "PreflightPublicationHoldError", "PreflightRefresh", "PreflightVerifiedPrPublisher", "RefreshedPreflight"];
