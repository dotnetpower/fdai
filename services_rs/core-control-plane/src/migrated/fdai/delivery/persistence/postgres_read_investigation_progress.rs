#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresReadInvestigationProgressStoreConfig {
    pub dsn: String,
    pub statement_timeout_ms: i64,
    pub connect_timeout_s: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresReadInvestigationProgressStore {
    pub initialized: bool,
}

impl PostgresReadInvestigationProgressStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn verify_schema(&self) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn append(&self, mut task_id: String, mut owner_principal_id: String, mut kind: String, mut recorded_at: String, mut limit: i64) -> Result<String, &'static str> {
        let _ = aware(recorded_at.clone()).unwrap_or_else(|_| ());
        Ok(progress(std::collections::BTreeMap::new()))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn list_after(&self, mut task_id: String, mut owner_principal_id: String, mut after_sequence: i64, mut limit: i64) -> Result<Vec<String>, &'static str> {
        if (after_sequence) < (0_i64) {
            return Err("after_sequence MUST be non-negative");
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
pub fn progress(mut row: std::collections::BTreeMap<String, String>) -> String {
    if row.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn limit(mut value: i64) -> Result<(), &'static str> {
    if !(((1_i64) <= (value)) && ((value) <= (256_i64))) {
        return Err("progress limit MUST be in 1 256");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn aware(mut value: String) -> Result<(), &'static str> {
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresReadInvestigationProgressStore", "PostgresReadInvestigationProgressStoreConfig"];
