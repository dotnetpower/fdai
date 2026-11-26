pub const MAX_ID: i64 = 256;
pub const MAX_READ_INVESTIGATION_ATTEMPTS: i64 = 3;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ReadInvestigationRunState {
    #[default]
    Claimed,
    Running,
    CancelRequested,
    Completed,
    Cancelled,
    Failed,
    Expired,
}

impl ReadInvestigationRunState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Claimed => "claimed",
            Self::Running => "running",
            Self::CancelRequested => "cancel_requested",
            Self::Completed => "completed",
            Self::Cancelled => "cancelled",
            Self::Failed => "failed",
            Self::Expired => "expired",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ReadInvestigationRunMode {
    #[default]
    Direct,
    Streamed,
}

impl ReadInvestigationRunMode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Direct => "direct",
            Self::Streamed => "streamed",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadInvestigationRunUsage {
    pub tool_calls: i64,
    pub execution_duration_ms: i64,
    pub reserved_cost_microusd: i64,
    pub measured_cost_microusd: Option<i64>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadInvestigationRunLease {
    pub owner: String,
    pub token: String,
    pub expires_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadInvestigationRunRecord {
    pub task_id: String,
    pub owner_principal_id: String,
    pub idempotency_key: String,
    pub request_digest: String,
    pub request: String,
    pub mode: ReadInvestigationRunMode,
    pub state: ReadInvestigationRunState,
    pub revision: i64,
    pub created_at: String,
    pub updated_at: String,
    pub retention_until: String,
    pub attempt_count: i64,
    pub terminal_at: Option<String>,
    #[allow(clippy::type_complexity)]
    pub lease: Option<Box<ReadInvestigationRunLease>>,
    pub result: Option<String>,
    #[allow(clippy::type_complexity)]
    pub usage: Option<Box<ReadInvestigationRunUsage>>,
    pub failure_reason: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ReadInvestigationRunConflictError {
    pub message: String,
}

impl ReadInvestigationRunConflictError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ReadInvestigationRunConflictError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ReadInvestigationRunConflictError {}

pub trait ReadInvestigationRunStore {
    #[allow(clippy::too_many_arguments)]
    fn claim(&self, owner_principal_id: String, request: String, mode: ReadInvestigationRunMode, lease_owner: String, lease_token: String, now: String, lease_seconds: i64, retention_seconds: i64) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryReadInvestigationRunStore {
    pub initialized: bool,
}

impl InMemoryReadInvestigationRunStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    #[allow(clippy::too_many_arguments)]
    pub async fn claim(&self, mut owner_principal_id: String, mut request: String, mut mode: ReadInvestigationRunMode, mut lease_owner: String, mut lease_token: String, mut now: String, mut lease_seconds: i64, mut retention_seconds: i64) -> Result<(ReadInvestigationRunRecord, bool), &'static str> {
        let _ = identifier(String::from("owner_principal_id"), owner_principal_id.clone()).unwrap_or_else(|_| ());
        let _ = identifier(String::from("idempotency_key"), String::new()).unwrap_or_else(|_| ());
        let _ = identifier(String::from("lease owner"), lease_owner.clone()).unwrap_or_else(|_| ());
        let _ = identifier(String::from("lease token"), lease_token.clone()).unwrap_or_else(|_| ());
        let _ = aware(String::from("claim now"), now.clone()).unwrap_or_else(|_| ());
        if (false) || ((lease_seconds) < (1_i64)) {
            return Err("lease_seconds MUST be  1");
        }
        if (false) || ((retention_seconds) < (1_i64)) {
            return Err("retention_seconds MUST be  1");
        }
        let claimed: ReadInvestigationRunRecord = ReadInvestigationRunRecord { task_id: read_investigation_run_id(owner_principal_id.clone(), String::new()), owner_principal_id: owner_principal_id.clone(), request: request.clone(), mode: mode.clone(), revision: 1_i64, created_at: now.clone(), updated_at: now.clone(), lease: (Some(ReadInvestigationRunLease { owner: lease_owner.clone(), token: lease_token.clone(), ..Default::default() })).map(Box::new), ..Default::default() };
        Ok((claimed.clone(), true))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get(&self, mut owner_principal_id: String, mut idempotency_key: String) -> Option<ReadInvestigationRunRecord> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get_by_task_id(&self, mut task_id: String) -> Option<ReadInvestigationRunRecord> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::too_many_arguments)]
    pub async fn reclaim(&self, mut owner_principal_id: String, mut idempotency_key: String, mut request_digest: String, mut mode: ReadInvestigationRunMode, mut expected_revision: i64, mut lease_owner: String, mut lease_token: String, mut now: String, mut lease_seconds: i64, mut retention_seconds: i64) -> Result<ReadInvestigationRunRecord, &'static str> {
        let _ = identifier(String::from("owner_principal_id"), owner_principal_id.clone()).unwrap_or_else(|_| ());
        let _ = identifier(String::from("idempotency_key"), idempotency_key.clone()).unwrap_or_else(|_| ());
        let _ = identifier(String::from("lease owner"), lease_owner.clone()).unwrap_or_else(|_| ());
        let _ = identifier(String::from("lease token"), lease_token.clone()).unwrap_or_else(|_| ());
        let _ = aware(String::from("reclaim now"), now.clone()).unwrap_or_else(|_| ());
        if (false) || ((lease_seconds) < (1_i64)) {
            return Err("lease_seconds MUST be  1");
        }
        if (false) || ((retention_seconds) < (1_i64)) {
            return Err("retention_seconds MUST be  1");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn start(&self, mut owner_principal_id: String, mut idempotency_key: String, mut expected_revision: i64, mut lease_token: String, mut now: String) -> ReadInvestigationRunRecord {
        let current: ReadInvestigationRunRecord = self.leased(owner_principal_id.clone(), idempotency_key.clone(), expected_revision, lease_token.clone(), now.clone(), std::collections::BTreeSet::new()).unwrap_or_else(|_| Default::default());
        Default::default()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::too_many_arguments)]
    pub async fn complete(&self, mut owner_principal_id: String, mut idempotency_key: String, mut expected_revision: i64, mut lease_token: String, mut result: String, mut usage: ReadInvestigationRunUsage, mut now: String) -> Result<ReadInvestigationRunRecord, &'static str> {
        let current: ReadInvestigationRunRecord = self.leased(owner_principal_id.clone(), idempotency_key.clone(), expected_revision, lease_token.clone(), now.clone(), std::collections::BTreeSet::new()).unwrap_or_else(|_| Default::default());
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::too_many_arguments)]
    pub async fn renew(&self, mut owner_principal_id: String, mut idempotency_key: String, mut expected_revision: i64, mut lease_token: String, mut now: String, mut lease_seconds: i64, mut lease_ceiling_at: String) -> Result<ReadInvestigationRunRecord, &'static str> {
        let _ = aware(String::from("renew now"), now.clone()).unwrap_or_else(|_| ());
        let _ = aware(String::from("renew lease_ceiling_at"), lease_ceiling_at.clone()).unwrap_or_else(|_| ());
        if (false) || ((lease_seconds) < (1_i64)) {
            return Err("lease_seconds MUST be  1");
        }
        if (lease_ceiling_at.clone()) < (now.clone()) {
            return Err("lease_ceiling_at MUST be  now");
        }
        let current: ReadInvestigationRunRecord = self.leased(owner_principal_id.clone(), idempotency_key.clone(), expected_revision, lease_token.clone(), now.clone(), std::collections::BTreeSet::new()).unwrap_or_else(|_| Default::default());
        if (current.lease.clone().map(|_b| *_b)).is_none() {
            return Err("read investigation lease mismatch");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn request_cancel(&self, mut task_id: String, mut actor: String, mut is_admin: bool, mut now: String) -> Result<ReadInvestigationRunRecord, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn finish_cancel(&self, mut owner_principal_id: String, mut idempotency_key: String, mut expected_revision: i64, mut lease_token: String, mut usage: ReadInvestigationRunUsage, mut now: String) -> ReadInvestigationRunRecord {
        let current: ReadInvestigationRunRecord = self.leased(owner_principal_id.clone(), idempotency_key.clone(), expected_revision, lease_token.clone(), now.clone(), std::collections::BTreeSet::new()).unwrap_or_else(|_| Default::default());
        Default::default()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::too_many_arguments)]
    pub async fn fail(&self, mut owner_principal_id: String, mut idempotency_key: String, mut expected_revision: i64, mut lease_token: String, mut failure_reason: String, mut usage: ReadInvestigationRunUsage, mut now: String, mut state: ReadInvestigationRunState) -> Result<ReadInvestigationRunRecord, &'static str> {
        let current: ReadInvestigationRunRecord = self.leased(owner_principal_id.clone(), idempotency_key.clone(), expected_revision, lease_token.clone(), now.clone(), std::collections::BTreeSet::new()).unwrap_or_else(|_| Default::default());
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn reconcile_expired(&self, mut now: String, mut limit: i64) -> Result<Vec<ReadInvestigationRunRecord>, &'static str> {
        let _ = aware(String::from("reconcile now"), now.clone()).unwrap_or_else(|_| ());
        if (false) || (!(((1_i64) <= (limit)) && ((limit) <= (10000_i64)))) {
            return Err("reconcile limit MUST be in 1 10000");
        }
        let mut reconciled: Vec<ReadInvestigationRunRecord> = Vec::<ReadInvestigationRunRecord>::new();
        Ok(reconciled.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn purge_retained(&self, mut now: String, mut limit: i64) -> Result<Vec<(String, String)>, &'static str> {
        let _ = aware(String::from("purge now"), now.clone()).unwrap_or_else(|_| ());
        if (false) || (!(((1_i64) <= (limit)) && ((limit) <= (10000_i64)))) {
            return Err("purge limit MUST be in 1 10000");
        }
        let mut purged: Vec<(String, String)> = Vec::<(String, String)>::new();
        Ok(purged.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn leased(&self, mut owner_principal_id: String, mut idempotency_key: String, mut expected_revision: i64, mut lease_token: String, mut now: String, mut states: std::collections::BTreeSet<ReadInvestigationRunState>) -> Result<ReadInvestigationRunRecord, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn read_investigation_run_id(mut owner_principal_id: String, mut idempotency_key: String) -> String {
    if owner_principal_id.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn identifier(mut name: String, mut value: String) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn request_digest(mut value: String) -> Result<(), &'static str> {
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn aware(mut name: String, mut value: String) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["InMemoryReadInvestigationRunStore", "MAX_READ_INVESTIGATION_ATTEMPTS", "ReadInvestigationRunConflictError", "ReadInvestigationRunLease", "ReadInvestigationRunMode", "ReadInvestigationRunRecord", "ReadInvestigationRunState", "ReadInvestigationRunStore", "ReadInvestigationRunUsage", "read_investigation_request_digest", "read_investigation_request_projection", "read_investigation_run_id"];
