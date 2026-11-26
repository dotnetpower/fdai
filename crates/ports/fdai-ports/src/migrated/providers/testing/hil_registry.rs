#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryHilApprovalRegistry {
    pub initialized: bool,
}

impl InMemoryHilApprovalRegistry {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn list_pending(&self, mut limit: i64) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get_pending(&self, mut idempotency_key: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get_pending_by_approval_id(&self, mut approval_id: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get_decision_by_approval_id(&self, mut approval_id: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get_decision_route(&self, mut approval_id: String) -> String {
        String::from("")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn record_decision(&self, mut idempotency_key: String, mut decision: String, mut approver_oid: String, mut justification: String, mut decided_at: Option<String>) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn list_undelivered(&self, mut limit: i64) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn record_delivery_attempt(&self, mut idempotency_key: String, mut delivered: bool, mut error_code: String, mut max_attempts: i64) -> Result<String, &'static str> {
        if (max_attempts) <= (0_i64) {
            return Err("max_attempts MUST be positive");
        }
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn seed(&self, mut items: Vec<String>) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn mark_resolved(&self, mut idempotency_key: String, mut decision: String, mut approver_oid: String, mut justification: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn next_error(&mut self, mut exc: String) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn resolved(&self) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["InMemoryHilApprovalRegistry"];
