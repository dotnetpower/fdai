#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresOutboxStoreConfig {
    pub dsn: String,
    pub statement_timeout_ms: i64,
    pub connect_timeout_s: i64,
}

pub const SELECT_SQL: &str = "SELECT status, result FROM action_outbox WHERE idempotency_key = %s";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresOutboxStore {
    pub initialized: bool,
}

impl PostgresOutboxStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn prepare(&mut self, mut conn: String) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn claim(&self, mut key: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn complete(&self, mut key: String, mut result: std::collections::BTreeMap<String, String>) {
        if !self.initialized {
            return;
        }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresOutboxStore", "PostgresOutboxStoreConfig"];
