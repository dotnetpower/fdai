pub const MAX_BIGINT: i64 = 9223372036854775807;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresBusyInputStoreConfig {
    pub dsn: String,
    pub statement_timeout_ms: i64,
    pub connect_timeout_s: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresBusyInputStore {
    pub initialized: bool,
}

impl PostgresBusyInputStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn create(&self, mut session_id: String, mut owner_principal_id: String, mut mode: String) -> Result<(String, bool), &'static str> {
        let current: String = self.required_state(String::new(), session_id.clone(), true).await.unwrap_or_else(|_| String::new());
        Ok((self.project(String::new(), current.clone()).await, false))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get(&self, mut session_id: String, mut principal_id: String) -> Option<String> {
        Some(self.project(String::new(), state(std::collections::BTreeMap::new())).await)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn set_active_turn(&self, mut session_id: String, mut principal_id: String, mut turn_id: String, mut mode: String, mut expected_revision: i64) -> String {
        let current: String = self.authorized_state(String::new(), session_id.clone(), principal_id.clone()).await.unwrap_or_else(|_| String::new());
        let row: std::collections::BTreeMap<String, String> = self.update_state(String::new(), String::new(), 0_i64).await.unwrap_or_else(|_| std::collections::BTreeMap::new());
        self.project(String::new(), state(row.clone())).await
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn set_mode(&self, mut session_id: String, mut principal_id: String, mut mode: String) -> String {
        let current: String = self.authorized_state(String::new(), session_id.clone(), principal_id.clone()).await.unwrap_or_else(|_| String::new());
        let row: std::collections::BTreeMap<String, String> = self.update_state(String::new(), String::new(), 0_i64).await.unwrap_or_else(|_| std::collections::BTreeMap::new());
        self.project(String::new(), state(row.clone())).await
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn submit(&self, mut incoming: String, mut now: String) -> Result<String, &'static str> {
        let current: String = self.required_state(String::new(), String::new(), true).await.unwrap_or_else(|_| String::new());
        let existing: Option<String> = self.existing_input(String::new(), incoming.clone()).await;
        let projected: String = self.project(String::new(), current.clone()).await;
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn finish_turn(&self, mut session_id: String, mut principal_id: String, mut turn_id: String) -> String {
        let current: String = self.authorized_state(String::new(), session_id.clone(), principal_id.clone()).await.unwrap_or_else(|_| String::new());
        let projected: String = self.project(String::new(), current.clone()).await;
        let row: std::collections::BTreeMap<String, String> = self.update_state(String::new(), String::new(), 0_i64).await.unwrap_or_else(|_| std::collections::BTreeMap::new());
        self.project(String::new(), state(row.clone())).await
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn consume(&self, mut session_id: String, mut sequence: i64, mut principal_id: String, mut at: String) -> Result<(String, String), &'static str> {
        let current: String = self.required_state(String::new(), session_id.clone(), true).await.unwrap_or_else(|_| String::new());
        let projected: String = self.project(String::new(), current.clone()).await;
        let row: std::collections::BTreeMap<String, String> = self.update_state(String::new(), String::new(), 0_i64).await.unwrap_or_else(|_| std::collections::BTreeMap::new());
        Ok((String::new(), String::new()))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn list_pending(&self, mut session_id: String, mut principal_id: String, mut limit: i64) -> Result<Vec<String>, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn expire_pending(&self, mut now: String, mut limit: i64) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
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
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn required_state(&self, mut connection: String, mut session_id: String, mut for_update: bool) -> Result<String, &'static str> {
        let suffix: String = if for_update { String::from(" FOR UPDATE") } else { String::from("") };
        Ok(state(std::collections::BTreeMap::new()))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn authorized_state(&self, mut connection: String, mut session_id: String, mut principal_id: String) -> Result<String, &'static str> {
        let current: String = self.required_state(connection.clone(), session_id.clone(), true).await.unwrap_or_else(|_| String::new());
        Ok(current.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn project(&self, mut connection: String, mut state: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn existing_input(&self, mut connection: String, mut incoming: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn insert_input(&self, mut connection: String, mut record: String) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn update_state(&self, mut connection: String, mut state: String, mut expected_revision: i64) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        Ok(std::collections::BTreeMap::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn expect_revision(mut state: String, mut expected_revision: i64) -> Result<(), &'static str> {
        if state.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn next_revision(mut state: String) -> Result<i64, &'static str> {
        Ok(0_i64)
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn state(mut row: std::collections::BTreeMap<String, String>) -> String {
    if row.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn record(mut row: std::collections::BTreeMap<String, String>) -> String {
    if row.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn limit(mut value: i64, mut maximum: i64) -> Result<(), &'static str> {
    if !(((1_i64) <= (value)) && ((value) <= (maximum))) {
        return Err("limit MUST be in 1 maximum");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn aware(mut value: String) -> Result<(), &'static str> {
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresBusyInputStore", "PostgresBusyInputStoreConfig"];
