#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ReadInvestigationExecutionMode {
    #[default]
    Direct,
    Streamed,
    Detached,
}

impl ReadInvestigationExecutionMode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Direct => "direct",
            Self::Streamed => "streamed",
            Self::Detached => "detached",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InvestigationExecutionPolicy {
    pub direct_max_ms: i64,
    pub streamed_max_ms: i64,
    pub minimum_profile_samples: i64,
    pub detach_on_multi_source: bool,
}

impl InvestigationExecutionPolicy {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn select(&self, mut plan: String, mut estimate: String) -> ReadInvestigationExecutionMode {
        if plan.is_empty() {
            return Default::default();
        }
        Default::default()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn interactive_investigation_policy() -> InvestigationExecutionPolicy {
    InvestigationExecutionPolicy { direct_max_ms: 20000_i64, streamed_max_ms: 30000_i64, detach_on_multi_source: false, ..Default::default() }
}

pub const PUBLIC_EXPORTS: &[&str] = &["InvestigationExecutionPolicy", "ReadInvestigationExecutionMode", "interactive_investigation_policy"];
