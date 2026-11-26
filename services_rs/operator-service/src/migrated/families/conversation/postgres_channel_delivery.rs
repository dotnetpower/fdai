#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresChannelDeliveryConfig {
    pub dsn: String,
    pub statement_timeout_ms: i64,
    pub connect_timeout_s: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresChannelDeliveryStore {
    pub initialized: bool,
}

impl PostgresChannelDeliveryStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn probe_readiness(&self) -> bool {
        if !self.initialized {
            return true;
        }
        true
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn put(&self, mut record: String) -> Result<String, &'static str> {
        let existing: String = delivery(std::collections::BTreeMap::new());
        Ok(existing.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get(&self, mut delivery_id: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn claim(&self, mut delivery_id: String, mut now: String, mut worker_id: String, mut lease_seconds: i64) -> Option<String> {
        let _ = claim_bounds(lease_seconds, 1_i64).unwrap_or_else(|_| ());
        let current: Option<String> = self.locked_delivery(String::new(), delivery_id.clone()).await;
        let Some(mut current) = current.clone() else { return None; };
        self.claim_locked(String::new(), current.clone(), now.clone(), worker_id.clone(), lease_seconds).await.unwrap_or_else(|_| None)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn claim_due(&self, mut now: String, mut worker_id: String, mut lease_seconds: i64, mut limit: i64, mut channel_kind: Option<String>) -> Vec<String> {
        let _ = claim_bounds(lease_seconds, limit).unwrap_or_else(|_| ());
        let mut claimed: Vec<String> = Vec::<String>::new();
        claimed.clone()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::too_many_arguments)]
    pub async fn finish(&self, mut delivery_id: String, mut worker_id: String, mut expected_attempt_count: i64, mut state: String, mut at: String, mut next_due_at: Option<String>, mut error_code: Option<String>, mut acknowledgement: Option<String>) -> Result<String, &'static str> {
        let current: Option<String> = self.locked_delivery(String::new(), delivery_id.clone()).await;
        let Some(mut current) = current.clone() else { return Err("delivery_id"); };
        let expected_attempt_id: String = attempt_id(delivery_id.clone(), expected_attempt_count);
        Ok(delivery(std::collections::BTreeMap::new()))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn reconcile_sending(&self, mut now: String) -> i64 {
        0_i64
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn snapshot(&self, mut limit: i64) -> Result<String, &'static str> {
        if !(((1_i64) <= (limit)) && ((limit) <= (500_i64))) {
            return Err("channel delivery snapshot limit is invalid");
        }
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn delete_expired(&self, mut now: String, mut limit: i64) -> Result<i64, &'static str> {
        if !(((1_i64) <= (limit)) && ((limit) <= (500_i64))) {
            return Err("channel delivery retention limit is invalid");
        }
        Ok(0_i64)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn delete_by_origin(&self, mut origin_ref: String, mut at: String, mut principal_id: Option<String>) -> Result<String, &'static str> {
        let cleaned_origin: String = origin_ref.trim().to_string();
        let cleaned_principal: Option<String> = if principal_id.is_some() { Some(((principal_id.clone()).unwrap_or_default()).trim().to_string()) } else { None };
        if (principal_id.is_some()) && (!((cleaned_principal.clone()).is_some())) {
            return Err("principal_id MUST be non-empty when supplied");
        }
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn is_origin_purged(&self, mut origin_ref: String) -> bool {
        self.initialized
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get_breaker(&self, mut adapter_id: String) -> Option<String> {
        if (adapter_id.clone()).starts_with("origin-tombstone:") {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn put_breaker(&self, mut record: String, mut expected_revision: Option<i64>) -> Result<String, &'static str> {
        Ok(breaker(std::collections::BTreeMap::new()).unwrap_or_else(|_| String::new()))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn locked_delivery(&self, mut connection: String, mut delivery_id: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn claim_locked(&self, mut connection: String, mut current: String, mut now: String, mut worker_id: String, mut lease_seconds: i64) -> Result<Option<String>, &'static str> {
        Ok(Some(delivery(std::collections::BTreeMap::new())))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn connect(&self) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn set_timeout(&self, mut connection: String) {
        if !self.initialized {
            return;
        }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn delivery_values(mut record: String) -> Vec<String> {
    if record.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn immutable_identity(mut record: String) -> Vec<String> {
    if record.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn delivery(mut row: std::collections::BTreeMap<String, String>) -> String {
    if row.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn attempt(mut row: std::collections::BTreeMap<String, String>) -> String {
    if row.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn acknowledgement(mut row: std::collections::BTreeMap<String, String>) -> String {
    if row.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn breaker(mut row: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
    if row.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn breaker_values(mut record: String) -> Vec<String> {
    if record.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn json_object(mut value: String) -> Result<String, &'static str> {
    if !(false) {
        return Err("stored channel delivery response MUST be an object");
    }
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn claim_bounds(mut lease_seconds: i64, mut limit: i64) -> Result<(), &'static str> {
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn attempt_id(mut delivery_id: String, mut sequence: i64) -> String {
    format!("{}:attempt:{}", delivery_id.clone(), sequence)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn psycopg_dsn(mut value: String) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresChannelDeliveryConfig", "PostgresChannelDeliveryStore"];
