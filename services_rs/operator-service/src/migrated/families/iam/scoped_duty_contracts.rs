pub trait ScopedDutyOutbox {
    fn create(&self, principal: String, idempotency_key: String, request: String, justification: String) -> std::collections::BTreeMap<String, String>;
    fn get(&self, case_id: String) -> std::collections::BTreeMap<String, String>;
    fn transition(&self, principal: String, case_id: String, expected_revision: i64, decision: Option<String>, plan_digest: Option<String>) -> std::collections::BTreeMap<String, String>;
    fn projection(&self, agent_name: String, scope_ref: String) -> std::collections::BTreeMap<String, String>;
    fn catalog(&self) -> std::collections::BTreeMap<String, String>;
}

pub const PUBLIC_EXPORTS: &[&str] = &["ScopedDutyOutbox"];
