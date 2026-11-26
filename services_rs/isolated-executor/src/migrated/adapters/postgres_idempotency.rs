#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresIdempotencyStoreConfig {
    pub dsn: String,
    pub statement_timeout_ms: i64,
    pub connect_timeout_s: i64,
}

pub const EXECUTOR_ROLE: &str = "fdai_executor";
pub const SELECT_SQL: &str = "SELECT result FROM action_idempotency WHERE idempotency_key = %s";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresIdempotencyStore {
    pub initialized: bool,
}

impl PostgresIdempotencyStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn seen(&self, mut key: String) -> Result<Option<std::collections::BTreeMap<String, String>>, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn assert_schema(&self) -> Result<(), &'static str> {
        let required_columns: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("idempotency_key"), String::from("result"), String::from("recorded_at")]);
        Ok(())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn record(&self, mut key: String, mut result: std::collections::BTreeMap<String, String>) -> bool {
        self.initialized
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn connect(&self, mut kwargs: std::collections::BTreeMap<String, String>) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn prepare(&self, mut connection: String) {
        if !self.initialized {
            return;
        }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresIdempotencyStore", "PostgresIdempotencyStoreConfig"];
