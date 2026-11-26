use std::collections::BTreeMap;
pub const MAX_QUEUED_BUSY_INPUTS: i64 = 32;
pub const MAX_CONTENT_BYTES: i64 = 4000;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BusyInputItemProjection {
    pub input_id: String,
    pub idempotency_key: String,
    pub sequence: i64,
    pub content: String,
    pub kind: String,
    pub disposition: String,
    pub status: String,
    pub received_at: String,
    pub expires_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BusySessionRecord {
    pub session_id: String,
    pub owner_principal_id: String,
    pub mode: String,
    pub revision: i64,
    pub active_turn_id: Option<String>,
    pub pending: Vec<BusyInputItemProjection>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct IdempotentBusySubmission {
    pub content: String,
    pub kind: String,
    pub submitted: BTreeMap<String, String>,
}

pub const ALLOWED_MODES: &[&str] = &["queue", "interrupt", "steer"];
pub const ALLOWED_KINDS: &[&str] = &["prose", "approval", "denial", "emergency_stop"];
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct BusyInputAuthorizationError {
    pub message: String,
}

impl BusyInputAuthorizationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for BusyInputAuthorizationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for BusyInputAuthorizationError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct BusyInputCapacityError {
    pub message: String,
}

impl BusyInputCapacityError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for BusyInputCapacityError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for BusyInputCapacityError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct BusyInputOperatorMaterializer {
    pub initialized: bool,
}

impl BusyInputOperatorMaterializer {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn ensure_session(&self, mut session_id: String, mut owner_principal_id: String, mut mode: String, mut active_turn_id: Option<String>) -> Result<BusySessionRecord, &'static str> {
        let sid: String = non_empty(session_id.clone(), String::from("session_id")).unwrap_or_else(|_| String::new());
        let owner: String = non_empty(owner_principal_id.clone(), String::from("owner_principal_id")).unwrap_or_else(|_| String::new());
        let created: BusySessionRecord = BusySessionRecord { session_id: sid.clone(), owner_principal_id: owner.clone(), mode: mode.clone(), revision: 1_i64, active_turn_id: active_turn_id.clone(), ..Default::default() };
        Ok(created.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn read_session_state(&self, mut session_id: String, mut principal_id: String) -> std::collections::BTreeMap<String, String> {
        let record: BusySessionRecord = self.require_owned_session_strict(session_id.clone(), principal_id.clone()).unwrap_or_else(|_| Default::default());
        std::collections::BTreeMap::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn inspect(&self, mut session_id: String, mut principal_id: String) -> std::collections::BTreeMap<String, String> {
        let record: BusySessionRecord = self.require_owned_session(session_id.clone(), principal_id.clone()).unwrap_or_else(|_| Default::default());
        std::collections::BTreeMap::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn set_mode(&self, mut session_id: String, mut principal_id: String, mut mode: String, mut expected_revision: i64) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        let record: BusySessionRecord = self.require_owned_session(session_id.clone(), principal_id.clone()).unwrap_or_else(|_| Default::default());
        Ok(std::collections::BTreeMap::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn submit(&self, mut session_id: String, mut principal_id: String, mut payload: std::collections::BTreeMap<String, String>, mut now: Option<String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        let record: BusySessionRecord = self.require_owned_session_strict(session_id.clone(), principal_id.clone()).unwrap_or_else(|_| Default::default());
        let idempotency_key: String = non_empty(String::new(), String::from("idempotency_key")).unwrap_or_else(|_| String::new());
        let input_id: String = non_empty(String::new(), String::from("input_id")).unwrap_or_else(|_| String::new());
        let content: String = non_empty(String::new(), String::from("content")).unwrap_or_else(|_| String::new());
        if (((record.pending.clone()).len() as i64)) >= (MAX_QUEUED_BUSY_INPUTS) {
            return Err("429 queue_capacity_exceeded busy-input pending queue capacity reached");
        }
        let item: BusyInputItemProjection = BusyInputItemProjection { input_id: input_id.clone(), idempotency_key: idempotency_key.clone(), sequence: (((record.pending.clone()).len() as i64)).saturating_add(1_i64), content: content.clone(), status: String::from("pending"), ..Default::default() };
        let submitted_receipt: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("input_id"), item.input_id.clone()), (String::from("idempotency_key"), item.idempotency_key.clone()), (String::from("sequence"), String::new()), (String::from("disposition"), item.disposition.clone()), (String::from("status"), item.status.clone())]);
        let response: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("session"), String::new()), (String::from("submitted"), String::new()), (String::from("duplicate"), String::new()), (String::from("execution_authority"), String::from("none"))]);
        Ok(response.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn submit_busy_input(&self, mut session_id: String, mut principal_id: String, mut payload: std::collections::BTreeMap<String, String>, mut now: Option<String>) -> std::collections::BTreeMap<String, String> {
        self.submit(session_id.clone(), principal_id.clone(), payload.clone(), now.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn cancel_current(&self, mut session_id: String, mut principal_id: String, mut expected_revision: i64) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        let record: BusySessionRecord = self.require_owned_session(session_id.clone(), principal_id.clone()).unwrap_or_else(|_| Default::default());
        let cancelled: bool = (record.active_turn_id.clone()).is_some();
        Ok(std::collections::BTreeMap::from([(String::from("cancelled"), String::new()), (String::from("session"), String::new()), (String::from("execution_authority"), String::from("none"))]))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn require_owned_session_strict(&self, mut session_id: String, mut principal_id: String) -> Result<BusySessionRecord, &'static str> {
        let sid: String = non_empty(session_id.clone(), String::from("session_id")).unwrap_or_else(|_| String::new());
        let principal: String = non_empty(principal_id.clone(), String::from("principal_id")).unwrap_or_else(|_| String::new());
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn require_owned_session(&self, mut session_id: String, mut principal_id: String) -> Result<BusySessionRecord, &'static str> {
        let sid: String = non_empty(session_id.clone(), String::from("session_id")).unwrap_or_else(|_| String::new());
        let principal: String = non_empty(principal_id.clone(), String::from("principal_id")).unwrap_or_else(|_| String::new());
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn project(mut record: BusySessionRecord) -> std::collections::BTreeMap<String, String> {
        let mut payload: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("session_id"), record.session_id.clone()), (String::from("mode"), record.mode.clone()), (String::from("revision"), String::new()), (String::from("active_turn_id"), (record.active_turn_id.clone()).unwrap_or_default()), (String::from("pending_count"), String::new()), (String::from("pending"), String::new()), (String::from("read_only_projection"), String::new()), (String::from("execution_authority"), String::from("none"))]);
        payload.clone()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn non_empty(mut value: String, mut name: String) -> Result<String, &'static str> {
    if (!(true)) || ((value.trim().to_string()).is_empty()) {
        return Err("400 finvalid_name fname must be non-empty");
    }
    Ok(value.trim().to_string())
}

pub const PUBLIC_EXPORTS: &[&str] = &["ALLOWED_KINDS", "ALLOWED_MODES", "BusyInputAuthorizationError", "BusyInputCapacityError", "BusyInputItemProjection", "BusyInputOperatorMaterializer", "BusySessionRecord", "MAX_PENDING_ITEMS", "MAX_QUEUED_BUSY_INPUTS"];
