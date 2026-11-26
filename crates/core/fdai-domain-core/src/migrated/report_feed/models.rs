use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ReportCategory {
    #[default]
    Workload,
    Security,
}

impl ReportCategory {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Workload => "workload",
            Self::Security => "security",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SignalKind {
    #[default]
    Anomaly,
    Investigation,
    Chaos,
    Irp,
    SecurityAssessment,
}

impl SignalKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Anomaly => "anomaly",
            Self::Investigation => "investigation",
            Self::Chaos => "chaos",
            Self::Irp => "irp",
            Self::SecurityAssessment => "security_assessment",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReportSignal {
    pub signal_id: String,
    pub kind: SignalKind,
    pub category: ReportCategory,
    pub severity: String,
    pub resource_ref: String,
    pub title: String,
    pub detail: String,
    pub occurred_at: String,
    pub evidence_refs: Vec<String>,
    pub metadata: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReportFeedResult {
    pub signals: Vec<ReportSignal>,
    pub source_errors: Vec<String>,
}

impl ReportFeedResult {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn workload(&self) -> Vec<ReportSignal> {
        core::hint::black_box(Vec::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn security(&self) -> Vec<ReportSignal> {
        core::hint::black_box(Vec::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn counts_by_category(&self) -> std::collections::BTreeMap<String, i64> {
        std::collections::BTreeMap::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn severity_rank(mut severity: String) -> i64 {
    0_i64
}

pub const PUBLIC_EXPORTS: &[&str] = &["ReportCategory", "ReportFeedResult", "ReportSignal", "SignalKind", "severity_rank"];
