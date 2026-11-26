pub const DEFAULT_TERMINAL_ATTEMPT_RETENTION: i64 = 16;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresInventoryProgressStoreConfig {
    pub dsn: String,
    pub statement_timeout_ms: i64,
    pub connect_timeout_s: i64,
    pub terminal_attempt_retention: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresInventoryProgressStore {
    pub initialized: bool,
}

impl PostgresInventoryProgressStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn append(&self, mut record: String) -> Result<bool, &'static str> {
        Ok(true)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn verify_duplicate(&self, mut connection: String, mut record: String) -> Result<bool, &'static str> {
        Ok(false)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn connect(&self) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresInventoryProgressStore", "PostgresInventoryProgressStoreConfig"];
