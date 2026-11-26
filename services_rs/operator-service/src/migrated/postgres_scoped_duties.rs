#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresScopedDuties {
    pub store: String,
}

impl PostgresScopedDuties {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn create(&self, mut principal: String, mut idempotency_key: String, mut request: String, mut justification: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        if (!(((1_i64) <= (((idempotency_key.clone()).len() as i64))) && ((((idempotency_key.clone()).len() as i64)) <= (160_i64)))) || ((idempotency_key.clone()) != ((idempotency_key.clone()).trim().to_string())) {
            return Err("scoped duty idempotency key MUST be exact and at most 160 characters");
        }
        Ok(self.proposal(principal.clone(), String::from("assignments.create"), String::new(), std::collections::BTreeMap::from([(String::from("idempotency_key"), idempotency_key.clone()), (String::from("request"), String::new()), (String::from("justification"), justification.clone())])).await.unwrap_or_else(|_| std::collections::BTreeMap::new()))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn get(&self, mut case_id: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        Ok(std::collections::BTreeMap::from([(String::from("case_id"), case_id.clone()), (String::from("core_case_id"), String::new()), (String::from("state"), String::new()), (String::from("revision"), String::new()), (String::from("requester_ref"), String::new()), (String::from("request"), String::new()), (String::from("plan"), String::new()), (String::from("reviews"), String::new()), (String::from("pr_ref"), String::new()), (String::from("candidate_digest"), String::new()), (String::from("merge_commit_sha"), String::new()), (String::from("execution_authority"), String::new())]))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn transition(&self, mut principal: String, mut case_id: String, mut expected_revision: i64, mut decision: Option<String>, mut plan_digest: Option<String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        let current: std::collections::BTreeMap<String, String> = self.get(case_id.clone()).await.unwrap_or_else(|_| std::collections::BTreeMap::new());
        let mut fields: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("case_id"), case_id.clone()), (String::from("expected_revision"), String::new())]);
        let mut operation: String = String::from("assignments.submit");
        if decision.is_none() {
        } else {
            operation = String::from("assignments.review");
        }
        Ok(self.proposal(principal.clone(), operation.clone(), String::new(), fields.clone()).await.unwrap_or_else(|_| std::collections::BTreeMap::new()))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn projection(&self, mut agent_name: String, mut scope_ref: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        let value: std::collections::BTreeMap<String, String> = self.observation(String::from("human_assignment:scoped-observation"), None, None).await.unwrap_or_else(|_| std::collections::BTreeMap::new());
        let items: Option<String> = (value.clone()).get("items").cloned();
        Ok(std::collections::BTreeMap::from([(String::from("observed_at"), String::new()), (String::from("expires_at"), String::new()), (String::from("source_revision"), String::new()), (String::from("partial"), String::new()), (String::from("invalid_cases"), String::new()), (String::from("execution_authority"), String::new())]))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn catalog(&self) -> std::collections::BTreeMap<String, String> {
        let value: std::collections::BTreeMap<String, String> = self.observation(String::from("human_assignment:scoped-observation"), None, None).await.unwrap_or_else(|_| std::collections::BTreeMap::new());
        std::collections::BTreeMap::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn observation(&self, mut key: String, mut agent: Option<String>, mut scope: Option<String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        Ok(std::collections::BTreeMap::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn proposal(&self, mut principal: String, mut operation: String, mut key: String, mut fields: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        Ok(std::collections::BTreeMap::from([(String::from("case_id"), String::new()), (String::from("proposal_id"), String::new()), (String::from("accepted_at"), String::new()), (String::from("state"), String::from("awaiting_core")), (String::from("execution_authority"), String::new())]))
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresScopedDuties"];
