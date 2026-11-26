#[derive(Clone, Debug, Default, PartialEq)]
pub struct HumanAccessDirectApiExecutor {
    pub planner: String,
    pub replacement: Option<String>,
}

pub const APPLY_HUMAN_ACCESS_ACTION: &str = "ops.apply-human-access";
pub const REVOKE_HUMAN_ACCESS_ACTION: &str = "ops.revoke-human-access";
impl HumanAccessDirectApiExecutor {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn execute(&self, mut request: String) -> Result<String, &'static str> {
        let mut expected_keys: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("case_id"), String::from("expected_revision")]);
        Ok(String::new())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["APPLY_HUMAN_ACCESS_ACTION", "HUMAN_ACCESS_ACTIONS", "HumanAccessDirectApiExecutor", "REVOKE_HUMAN_ACCESS_ACTION"];
