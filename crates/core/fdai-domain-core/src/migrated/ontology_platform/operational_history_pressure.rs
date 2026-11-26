#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum StoragePressureLevel {
    #[default]
    Normal,
    Warning,
    Critical,
    Hard,
}

impl StoragePressureLevel {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Normal => "normal",
            Self::Warning => "warning",
            Self::Critical => "critical",
            Self::Hard => "hard",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct StoragePressurePolicy {
    pub warning_bytes: i64,
    pub critical_bytes: i64,
    pub hard_bytes: i64,
    pub max_purge_backlog: i64,
    pub max_projection_lag: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct StoragePressureAssessment {
    pub level: StoragePressureLevel,
    pub archive_priority: bool,
    pub reduce_nonessential_collection: bool,
    pub apply_source_admission_budget: bool,
    pub hold_completeness_dependent_work: bool,
    pub projected_exhaustion_seconds: Option<i64>,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn assess_storage_pressure(mut policy: StoragePressurePolicy, mut database_bytes: i64, mut purge_backlog: i64, mut projection_lag: i64, mut growth_bytes_per_second: Option<i64>) -> Result<StoragePressureAssessment, &'static str> {
    let hard: bool = ((database_bytes) >= (policy.hard_bytes)) || (((purge_backlog) > (policy.max_purge_backlog)) || ((projection_lag) > (policy.max_projection_lag)));
    let mut exhaustion: Option<String> = None;
    Ok(StoragePressureAssessment::default())
}

pub const PUBLIC_EXPORTS: &[&str] = &["StoragePressureAssessment", "StoragePressureLevel", "StoragePressurePolicy", "assess_storage_pressure"];
