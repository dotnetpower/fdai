use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct CurrentScopedDutyOwners {
    pub subjects: String,
    pub directory: String,
    pub role_group_ids: BTreeMap<String, String>,
    pub clock: String,
    pub timeout_seconds: f64,
}

impl CurrentScopedDutyOwners {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn is_current_owner(&self, mut person_ref: String, mut at: String) -> bool {
        if person_ref.is_empty() {
            return false;
        }
        false
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["CurrentScopedDutyOwners"];
