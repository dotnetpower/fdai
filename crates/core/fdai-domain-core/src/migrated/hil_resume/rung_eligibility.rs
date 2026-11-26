use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct DirectoryRungEligibility {
    pub directory: String,
    pub role_group_ids: BTreeMap<String, String>,
    pub timeout_seconds: f64,
}

impl DirectoryRungEligibility {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn is_eligible(&self, mut subject_ref: String, mut minimum_role: String, mut context: Option<std::collections::BTreeMap<String, String>>, mut at: Option<String>) -> bool {
        if !(matches!(minimum_role.as_str(), "Approver" | "Owner")) {
            return false;
        }
        false
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["DirectoryRungEligibility"];
