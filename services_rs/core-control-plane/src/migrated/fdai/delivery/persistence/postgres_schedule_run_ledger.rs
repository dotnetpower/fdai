#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresScheduleRunLedgerConfig {
    pub dsn: String,
    pub statement_timeout_ms: i64,
    pub connect_timeout_s: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresScheduleRunLedger {
    pub initialized: bool,
}

impl PostgresScheduleRunLedger {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn claim(&self, mut run: String) -> bool {
        self.initialized
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn row_to_run(mut row: std::collections::BTreeMap<String, String>) -> String {
    if row.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresScheduleRunLedger", "PostgresScheduleRunLedgerConfig"];
