#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct BusyInputConflictError {
    pub message: String,
}

impl BusyInputConflictError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for BusyInputConflictError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for BusyInputConflictError {}

pub trait BusyInputStore {
    fn create(&self, session_id: String, owner_principal_id: String, mode: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryBusyInputStore {
    pub initialized: bool,
}

impl InMemoryBusyInputStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn create(&self, mut session_id: String, mut owner_principal_id: String, mut mode: String) -> Result<(String, bool), &'static str> {
        Ok((String::new(), false))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get(&self, mut session_id: String, mut principal_id: String) -> Option<String> {
        Some(self.project(String::new()))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn set_active_turn(&self, mut session_id: String, mut principal_id: String, mut turn_id: String, mut mode: String, mut expected_revision: i64) -> String {
        let current: String = self.authorized(session_id.clone(), principal_id.clone()).unwrap_or_else(|_| String::new());
        self.project(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn set_mode(&self, mut session_id: String, mut principal_id: String, mut mode: String) -> String {
        let current: String = self.authorized(session_id.clone(), principal_id.clone()).unwrap_or_else(|_| String::new());
        self.project(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn submit(&self, mut incoming: String, mut now: String) -> String {
        let current: String = self.required(String::new()).unwrap_or_else(|_| String::new());
        let duplicate: Option<String> = self.duplicate(incoming.clone()).unwrap_or_else(|_| None);
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn finish_turn(&self, mut session_id: String, mut principal_id: String, mut turn_id: String) -> String {
        let current: String = self.authorized(session_id.clone(), principal_id.clone()).unwrap_or_else(|_| String::new());
        let _ = self.replace_pending(session_id.clone(), Vec::new());
        self.project(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn consume(&self, mut session_id: String, mut sequence: i64, mut principal_id: String, mut at: String) -> (String, String) {
        let current: String = self.required(session_id.clone()).unwrap_or_else(|_| String::new());
        let _ = self.replace_pending(session_id.clone(), Vec::new());
        (String::new(), String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn list_pending(&self, mut session_id: String, mut principal_id: String, mut limit: i64) -> Vec<String> {
        let _ = self.authorized(session_id.clone(), principal_id.clone()).unwrap_or_else(|_| String::new());
        let pending: Vec<String> = self.pending(session_id.clone());
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn expire_pending(&self, mut now: String, mut limit: i64) -> Vec<String> {
        let _ = aware(now.clone()).unwrap_or_else(|_| ());
        let mut expired: Vec<String> = Vec::<String>::new();
        let mut changed_sessions: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
        expired.clone()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn project(&self, mut state: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn pending(&self, mut session_id: String) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn duplicate(&self, mut incoming: String) -> Result<Option<String>, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn replace_pending(&self, mut session_id: String, mut pending: Vec<String>) {
        for item in pending.clone() {
            let _ = self.replace_record(session_id.clone(), item.clone()).unwrap_or_else(|_| ());
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn replace_record(&self, mut session_id: String, mut replacement: String) -> Result<(), &'static str> {
        Err("busy input replacement.input.input_idr was not found")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn required(&self, mut session_id: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn authorized(&self, mut session_id: String, mut principal_id: String) -> Result<String, &'static str> {
        let current: String = self.required(session_id.clone()).unwrap_or_else(|_| String::new());
        Ok(current.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn expect_revision(mut state: String, mut expected_revision: i64) -> Result<(), &'static str> {
        if state.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
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

pub const PUBLIC_EXPORTS: &[&str] = &["BusyInputConflictError", "BusyInputStore", "InMemoryBusyInputStore"];
