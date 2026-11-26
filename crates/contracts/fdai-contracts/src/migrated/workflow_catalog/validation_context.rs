#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkflowValidationContext {
    pub schema_version: String,
    pub action_type_names: Vec<String>,
    pub rule_ids: Vec<String>,
    pub signal_types: String,
    pub workflow_trigger_events: String,
    pub catalog_revision: String,
    pub catalog_digest: String,
}

pub const WORKFLOW_VALIDATION_CONTEXT_SCHEMA_VERSION: &str = "1.0.0";
impl WorkflowValidationContext {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn canonical_sets(&self) -> Result<WorkflowValidationContext, &'static str> {
        if ((((self.action_type_names.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) != (((self.action_type_names.clone()).len() as i64)) {
            return Err("action_type_names MUST be unique");
        }
        if ((((self.rule_ids.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) != (((self.rule_ids.clone()).len() as i64)) {
            return Err("rule_ids MUST be unique");
        }
        Ok(self.clone())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["WORKFLOW_VALIDATION_CONTEXT_PROJECTION_KEY", "WORKFLOW_VALIDATION_CONTEXT_SCHEMA_VERSION", "WorkflowValidationContext"];
