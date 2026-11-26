#[derive(Clone, Debug, Default, PartialEq)]
pub struct VidarRollbackRuntimeMixin {
    pub records: Vec<String>,
    pub bus: Option<String>,
}

impl VidarRollbackRuntimeMixin {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn rollback(&self, mut action_run: std::collections::BTreeMap<String, String>) -> Option<String> {
        let correlation_id: String = (action_run.clone()).get("correlation_id").cloned().unwrap_or_else(|| String::from(""));
        return self.rollback_locked(action_run.clone()).await;
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn rollback_locked(&self, mut action_run: std::collections::BTreeMap<String, String>) -> Option<String> {
        let correlation_id: String = (action_run.clone()).get("correlation_id").cloned().unwrap_or_else(|| String::from(""));
        let contract: String = (action_run.clone()).get("rollback_contract").cloned().unwrap_or_else(|| String::from("state_forward_only"));
        let mut rec: String = self.execute_rollback(action_run.clone(), correlation_id.clone(), String::new()).await;
        let _ = self.remember_rollback(rec.clone(), String::new()).unwrap_or_else(|_| ());
        let _ = self.publish_rollback_once(rec.clone()).await;
        Some(rec.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn process_local_refusal_record(&self, mut action_run: std::collections::BTreeMap<String, String>, mut correlation_id: String, mut contract: String, mut action_run_identity: String) -> String {
        if action_run.is_empty() {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn rollback_durable(&self, mut action_run: std::collections::BTreeMap<String, String>, mut correlation_id: String, mut contract: String, mut action_run_identity: String, mut request_digest: String) -> Result<Option<String>, &'static str> {
        if action_run.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn complete_durable_rollback(&self, mut state_key: String, mut request_digest: String, mut rec: String, mut claim_owner_token: String, mut lease_expires_at: String) -> Result<String, &'static str> {
        if state_key.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn execute_rollback(&self, mut action_run: std::collections::BTreeMap<String, String>, mut correlation_id: String, mut action_run_identity: String) -> String {
        let contract: String = (action_run.clone()).get("rollback_contract").cloned().unwrap_or_else(|| String::from("state_forward_only"));
        let action_type: String = ((action_run.clone()).get("action_type").cloned()).unwrap_or_else(|| String::from(""));
        let executor: Option<String> = self.rollback_executor(action_type.clone(), contract.clone());
        let mut state: String = String::from("failed");
        let mut notes: String = format!("no rollback executor registered for contract {}", contract.clone());
        let mut rollback_ref: Option<String> = None;
        if (correlation_id.clone()).is_empty() {
            notes = String::from("rollback refused because correlation_id is empty");
        } else if executor.is_some() {
            if rollback_ref.is_some() {
                state = String::from("succeeded");
                notes = String::from("rollback executor completed");
            } else {
                notes = String::from("rollback executor returned no receipt");
            }
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn rollback_executor(&self, mut action_type: String, mut contract: String) -> Option<String> {
        if action_type.is_empty() {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn remember_rollback(&self, mut rec: String, mut request_digest: String) -> Result<(), &'static str> {
        if rec.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn remember_rollback_hold(&self, mut rec: String) {
        if rec.is_empty() {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn publish_rollback_once(&self, mut rec: String) -> bool {
        if self.bus.is_none() {
            return self.publish_rollback(rec.clone()).await;
        }
        let published: bool = self.publish_rollback(rec.clone()).await;
        if !(published) {
            return false;
        }
        true
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn claim_rollback_publication(&self, mut rec: String) -> Result<bool, &'static str> {
        let receipt: std::collections::BTreeMap<String, String> = self.rollback_publication_receipt(rec.clone(), String::from("publishing"), String::new());
        Ok(true)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn recover_rollbacks(&mut self) -> Result<i64, &'static str> {
        let mut recovered: i64 = 0_i64;
        let mut pending: i64 = 0_i64;
        Ok(recovered)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn rollback_was_published(&self, mut correlation_id: String, mut action_run_identity: String) -> Result<bool, &'static str> {
        Ok(true)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn mark_rollback_published(&self, mut rec: String) -> Result<(), &'static str> {
        let receipt: std::collections::BTreeMap<String, String> = self.rollback_publication_receipt(rec.clone(), String::from("published"), String::new());
        Ok(())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn rollback_publication_receipt(&self, mut rec: String, mut status: String, mut now: String) -> std::collections::BTreeMap<String, String> {
        let mut receipt: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.0.0")), (String::from("revision"), String::new()), (String::from("correlation_id"), String::new()), (String::from("action_run_identity"), String::new()), (String::from("idempotency_key"), String::new()), (String::from("state"), String::new()), (String::from("status"), status.clone()), (String::from("owner_token"), String::new())]);
        receipt.clone()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn publish_rollback(&self, mut rec: String) -> bool {
        if self.bus.is_none() {
            return false;
        }
        true
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["VidarRollbackRuntimeMixin"];
