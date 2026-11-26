#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresScheduledContinuationStoreConfig {
    pub dsn: String,
    pub statement_timeout_ms: i64,
    pub connect_timeout_s: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresScheduledConversationAnchorStore {
    pub initialized: bool,
}

impl PostgresScheduledConversationAnchorStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn create(&self, mut anchor: String) -> Result<String, &'static str> {
        Ok(row_to_anchor(std::collections::BTreeMap::new()))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get(&self, mut anchor_id: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn expire(&self, mut anchor_id: String, mut expected_state: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn list_for_principal(&self, mut principal_id: String, mut limit: i64) -> Result<Vec<String>, &'static str> {
        if !(((1_i64) <= (limit)) && ((limit) <= (1000_i64))) {
            return Err("limit MUST be in 1 1000");
        }
        Ok(Vec::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn connect(&self) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn timeout(&self, mut connection: String) {
        if !self.initialized {
            return;
        }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn psycopg_dsn(mut value: String) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn origin_json(mut origin: String) -> String {
    if origin.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn origin(mut raw: String) -> Result<String, &'static str> {
    if raw.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn values(mut anchor: String) -> Vec<String> {
    if anchor.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn row_to_anchor(mut row: std::collections::BTreeMap<String, String>) -> String {
    if row.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresScheduledContinuationStoreConfig", "PostgresScheduledConversationAnchorStore", "psycopg_dsn"];
