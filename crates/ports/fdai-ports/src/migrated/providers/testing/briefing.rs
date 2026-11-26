#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryConversationPolicyStore {
    pub initialized: bool,
}

impl InMemoryConversationPolicyStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn put(&self, mut record: String, mut expected_revision: Option<i64>) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn list_for_principal(&self, mut principal_id: String) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn delete(&self, mut principal_id: String, mut policy_id: String, mut expected_revision: i64) -> Result<bool, &'static str> {
        Ok(false)
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryBriefingSubscriptionStore {
    pub initialized: bool,
}

impl InMemoryBriefingSubscriptionStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn create(&self, mut record: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn list_for_principal(&self, mut principal_id: String) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn claim_due(&self, mut now: String, mut limit: i64, mut lease_owner: String, mut lease_seconds: i64) -> Result<Vec<String>, &'static str> {
        if !(((1_i64) <= (limit)) && ((limit) <= (1000_i64))) {
            return Err("limit MUST be in 1 1000");
        }
        if (lease_seconds) < (1_i64) {
            return Err("lease_seconds MUST be  1");
        }
        let mut due: Vec<String> = Vec::<String>::new();
        Ok(due.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn advance(&self, mut subscription_id: String, mut principal_id: String, mut expected_revision: i64, mut next_run_at: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn delete(&self, mut principal_id: String, mut subscription_id: String, mut expected_revision: i64) -> Result<bool, &'static str> {
        Ok(false)
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryBriefingRunStore {
    pub initialized: bool,
}

impl InMemoryBriefingRunStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn create(&self, mut run: String) -> Result<String, &'static str> {
        Ok(run.clone())
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
    #[allow(clippy::type_complexity)]
    pub async fn purge_before(&self, mut before: String, mut limit: i64) -> Result<Vec<String>, &'static str> {
        if !(((1_i64) <= (limit)) && ((limit) <= (1000_i64))) {
            return Err("limit MUST be in 1 1000");
        }
        Ok(Vec::new())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["InMemoryBriefingRunStore", "InMemoryBriefingSubscriptionStore", "InMemoryConversationPolicyStore"];
