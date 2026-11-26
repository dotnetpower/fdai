#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresPostTurnReviewLedgerConfig {
    pub dsn: String,
    pub statement_timeout_ms: i64,
    pub connect_timeout_s: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresPostTurnReviewLedger {
    pub initialized: bool,
}

impl PostgresPostTurnReviewLedger {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn start(&self, mut record: String) -> (String, bool) {
        (String::new(), false)
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn row_to_record(mut row: std::collections::BTreeMap<String, String>) -> String {
    if row.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresPostTurnReviewLedger", "PostgresPostTurnReviewLedgerConfig"];
