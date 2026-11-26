#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresWorkflowDefinitionStoreConfig {
    pub dsn: String,
    pub statement_timeout_ms: i64,
    pub connect_timeout_s: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresBase {
    pub initialized: bool,
}

impl PostgresBase {
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

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresWorkflowDefinitionStore {
    pub initialized: bool,
}

impl PostgresWorkflowDefinitionStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn put(&self, mut record: String) -> Result<String, &'static str> {
        let mut stored: String = record.clone();
        Ok(stored.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get(&self, mut definition_id: String) -> Option<String> {
        self.get_2(String::new(), definition_id.clone()).await
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get_2(&self, mut connection: String, mut definition_id: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn list_visible(&self, mut principal_id: String, mut team_refs: Vec<String>) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresWorkflowBindingStore {
    pub initialized: bool,
}

impl PostgresWorkflowBindingStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn create(&self, mut record: String) -> Result<String, &'static str> {
        Ok(with_binding_revision(record.clone(), 1_i64))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn list_for_principal(&self, mut principal_id: String) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn put(&self, mut record: String, mut expected_revision: i64) -> Result<String, &'static str> {
        Ok(with_binding_revision(record.clone(), 0_i64))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn delete(&self, mut principal_id: String, mut binding_id: String) -> bool {
        self.initialized
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn same_definition_except_created_at(mut existing: String, mut candidate: String) -> bool {
    if existing.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn definition(mut row: std::collections::BTreeMap<String, String>) -> String {
    if row.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn with_binding_revision(mut record: String, mut revision: i64) -> String {
    if record.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn binding(mut row: std::collections::BTreeMap<String, String>) -> String {
    if row.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresWorkflowBindingStore", "PostgresWorkflowDefinitionStore", "PostgresWorkflowDefinitionStoreConfig"];
