#[derive(Clone, Debug, Default, PartialEq)]
pub struct AlertWorkflowBinding {
    pub schema_version: String,
    pub process_id: String,
    pub workflow_ref: String,
    pub workflow_version: String,
    pub workflow_digest: String,
    pub plan_digest: String,
    pub evidence_digest: String,
    pub target_resource_id: String,
    pub requester_ref: String,
    pub requester_principal: String,
    pub correlation_id: String,
    pub trigger_ts: String,
    pub mode: String,
    pub source_revision: String,
    pub execution_authority: String,
}

impl AlertWorkflowBinding {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AlertWorkflowResult {
    pub process_id: String,
    pub workflow_ref: String,
    pub plan_digest: String,
    pub status: String,
    pub mode: String,
    pub execution_authority: bool,
    pub approval_authority: bool,
    pub promotion_authority: bool,
}

impl AlertWorkflowResult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        if self.approval_authority { return Err("approval_authority violated literal bool invariant"); }
        if self.promotion_authority { return Err("promotion_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AlertWorkflowResolution {
    pub binding: Box<AlertWorkflowBinding>,
    pub plan: String,
    pub workflow: String,
    pub evidence: String,
    pub snapshot: String,
    pub events: Vec<String>,
}

pub const ALERT_WORKFLOW_PROMOTION_PURPOSE: &str = "alert-noise-workflow-promotion";
pub const PLAN_CONTEXT_KEY: &str = "event.payload.alert_plan.plan_digest";
pub trait AlertRequesterReader {
    fn resolve(&self, requester_ref: String) -> String;
}

pub trait WorkflowPromotionReader {
    fn read(&self, workflow: String, plan: String, target_resource_id: String, now: String) -> String;
}

pub trait AlertActionBinder {
    fn bind(&self, action: String, event: String) -> String;
}

impl AlertWorkflowBinding {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn context(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_record(&self) -> std::collections::BTreeMap<String, String> {
        let body: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("binding"), String::new()), (String::from("context"), String::new())]);
        std::collections::BTreeMap::from([(String::from("record_digest"), String::new())])
    }
}

impl AlertWorkflowResult {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn process_ref(&self) -> String {
        format!("{}{}", String::from("process:"), self.process_id.clone())
    }
}

