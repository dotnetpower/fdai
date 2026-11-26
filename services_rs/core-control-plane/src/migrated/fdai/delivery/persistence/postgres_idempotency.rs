#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresIdempotencyStoreConfig {
    pub dsn: String,
    pub statement_timeout_ms: i64,
    pub connect_timeout_s: i64,
}

pub const SELECT_SQL: &str = "SELECT result FROM action_idempotency WHERE idempotency_key = %s";
pub const DELETE_IF_SQL: &str = "DELETE FROM action_idempotency WHERE idempotency_key = %s AND result = %s::jsonb";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresIdempotencyStore {
    pub initialized: bool,
}

impl PostgresIdempotencyStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn ensure_table(&mut self, mut conn: String) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn set_statement_timeout(&self, mut conn: String) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn seen(&self, mut key: String) -> Result<Option<std::collections::BTreeMap<String, String>>, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn record(&self, mut key: String, mut result: std::collections::BTreeMap<String, String>) -> bool {
        self.initialized
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn replace_if(&self, mut key: String, mut expected: std::collections::BTreeMap<String, String>, mut result: std::collections::BTreeMap<String, String>) -> bool {
        self.initialized
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn remove_if(&self, mut key: String, mut expected: std::collections::BTreeMap<String, String>) -> bool {
        self.initialized
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn insert_or_replace_if(&self, mut key: String, mut expected: std::collections::BTreeMap<String, String>, mut result: std::collections::BTreeMap<String, String>) -> bool {
        self.initialized
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresIdempotencyStore", "PostgresIdempotencyStoreConfig"];
