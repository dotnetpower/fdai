use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum HumanAccessExecutionOutcome {
    #[default]
    Planned,
    Applied,
    Failed,
}

impl HumanAccessExecutionOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Planned => "planned",
            Self::Applied => "applied",
            Self::Failed => "failed",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct HumanAccessExecution {
    pub outcome: HumanAccessExecutionOutcome,
    pub plan: String,
    pub receipt: Option<String>,
    pub reason: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct HumanAccessApplyCoordinator {
    pub cases: String,
    pub provisioner: String,
    pub role_group_ids: BTreeMap<String, String>,
}

impl HumanAccessApplyCoordinator {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn execute(&self, mut case_id: String, mut expected_revision: i64, mut actor_ref: String, mut mode: String) -> Result<HumanAccessExecution, &'static str> {
        if (!(true)) || (((actor_ref.clone()).trim().to_string()).is_empty()) {
            return Err("human access apply actor_ref MUST be non-empty");
        }
        Ok(HumanAccessExecution::default())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn rollback_reason(&self, mut plan: String, mut receipt: String, mut failure: String) -> String {
        format!("{}_rolled_back", failure.clone())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["HumanAccessApplyCoordinator", "HumanAccessExecution", "HumanAccessExecutionOutcome"];
