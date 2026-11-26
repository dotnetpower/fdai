use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct HumanAccessPlanner {
    pub cases: String,
    pub role_group_ids: BTreeMap<String, String>,
}

impl HumanAccessPlanner {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn plan(&self, mut case_id: String, mut expected_revision: i64) -> Result<String, &'static str> {
        if case_id.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["HumanAccessPlanner"];
