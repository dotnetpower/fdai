use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum IntegrityMismatchKind {
    #[default]
    RowCount,
    Checksum,
    ForeignKey,
}

impl IntegrityMismatchKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::RowCount => "row_count",
            Self::Checksum => "checksum",
            Self::ForeignKey => "foreign_key",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct IntegrityMismatch {
    pub kind: IntegrityMismatchKind,
    pub table: String,
    pub detail: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DbRestoreConfig {
    pub experiment_id: String,
    pub source_ref: String,
    pub target_server_name: String,
    pub target_resource_group: String,
    pub target_location: String,
    pub point_in_time_utc: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DbRestoreHandle {
    pub experiment_id: String,
    pub source_ref: String,
    pub target_ref: String,
    pub endpoint: String,
    pub resource_group: String,
    pub created_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct IntegrityReport {
    pub table_row_counts: BTreeMap<String, i64>,
    pub checksums: BTreeMap<String, String>,
    pub mismatches: Vec<IntegrityMismatch>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SmokeCheck {
    pub name: String,
    pub passed: bool,
    pub detail: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SmokeReport {
    pub checks: Vec<SmokeCheck>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DbDrEvidence {
    pub integrity_row_count_tables: i64,
    pub integrity_checksum_tables: i64,
    pub integrity_mismatches: Vec<IntegrityMismatch>,
    pub smoke_checks_total: i64,
    pub smoke_failures: Vec<SmokeCheck>,
}

impl IntegrityReport {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn mismatch_count(&self) -> i64 {
        (self.mismatches.clone()).len() as i64
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn is_clean(&self) -> bool {
        (self.mismatches.clone()).is_empty()
    }
}

impl SmokeReport {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn passed(&self) -> bool {
        core::hint::black_box(false)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn failures(&self) -> Vec<SmokeCheck> {
        core::hint::black_box(Vec::new())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DbDrError {
    pub message: String,
}

impl DbDrError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for DbDrError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for DbDrError {}

pub trait DbRestoreAdapter {
    fn restore(&self, config: DbRestoreConfig) -> DbRestoreHandle;
    fn teardown(&self, handle: DbRestoreHandle);
}

pub trait IntegrityChecker {
    fn check(&self, handle: DbRestoreHandle) -> IntegrityReport;
}

pub trait SmokeRunner {
    fn run(&self, handle: DbRestoreHandle) -> SmokeReport;
}

pub const PUBLIC_EXPORTS: &[&str] = &["DbDrError", "DbDrEvidence", "DbRestoreAdapter", "DbRestoreConfig", "DbRestoreHandle", "IntegrityChecker", "IntegrityMismatch", "IntegrityMismatchKind", "IntegrityReport", "SmokeCheck", "SmokeReport", "SmokeRunner"];
