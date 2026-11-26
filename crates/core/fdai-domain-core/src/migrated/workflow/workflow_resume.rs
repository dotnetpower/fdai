use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkflowResumeEnvelope {
    pub process_id: String,
    pub workflow_ref: String,
    pub workflow_version: String,
    pub target_resource_id: String,
    pub correlation_id: String,
    pub trigger_ts: String,
    pub mode: String,
    pub context: BTreeMap<String, String>,
}

pub const CONTEXT_TOKEN: &str = "\\$\\{([a-z0-9_.]+)\\}";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct WorkflowResumeError {
    pub message: String,
}

impl WorkflowResumeError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for WorkflowResumeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for WorkflowResumeError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_resume_payload(mut workflow: String, mut action_types: std::collections::BTreeMap<String, String>, mut trigger_ts: String, mut mode: String, mut context: std::collections::BTreeMap<String, String>) -> std::collections::BTreeMap<String, String> {
    let mut referenced: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let mut redacted: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    if (context.clone()).contains_key("requester.principal") {
        referenced.insert(String::from("requester.principal"));
    }
    std::collections::BTreeMap::from([(String::from("trigger_ts"), String::new()), (String::from("mode"), String::new()), (String::from("context"), String::new()), (String::from("context_complete"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_resume_envelope(mut workflow: String, mut snapshot: String, mut created_event: String) -> Result<WorkflowResumeEnvelope, &'static str> {
    Ok(WorkflowResumeEnvelope::default())
}

pub const PUBLIC_EXPORTS: &[&str] = &["WorkflowResumeEnvelope", "WorkflowResumeError", "build_resume_payload", "load_resume_envelope"];
