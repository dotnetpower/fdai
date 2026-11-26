#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryStateAtomicMixin {
    pub initialized: bool,
}

impl InMemoryStateAtomicMixin {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::too_many_arguments)]
    pub async fn compare_and_set_state_pair_with_audit(&self, mut key: String, mut value: std::collections::BTreeMap<String, String>, mut expected_revision: i64, mut second_key: String, mut second_value: std::collections::BTreeMap<String, String>, mut expected_second_revision: i64, mut audit_entry: std::collections::BTreeMap<String, String>) -> Result<bool, &'static str> {
        if ((expected_revision) < (0_i64)) || (((expected_second_revision) < (0_i64)) || ((key.clone()) == (second_key.clone()))) {
            return Err("state pair expected revisions or keys are invalid");
        }
        Ok(true)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::too_many_arguments)]
    pub async fn compare_and_set_state_with_audit_and_insert_before(&self, mut key: String, mut value: std::collections::BTreeMap<String, String>, mut expected_revision: i64, mut insert_key: String, mut insert_value: std::collections::BTreeMap<String, String>, mut not_before: String, mut expires_at: String, mut audit_entry: std::collections::BTreeMap<String, String>) -> bool {
        if !self.initialized {
            return true;
        }
        true
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    #[allow(clippy::too_many_arguments)]
    pub async fn compare_and_set_state_pair_with_audit_before(&self, mut key: String, mut value: std::collections::BTreeMap<String, String>, mut expected_revision: i64, mut second_key: String, mut second_value: std::collections::BTreeMap<String, String>, mut expected_second_revision: i64, mut not_before: String, mut expires_at: String, mut insert_key: Option<String>, mut insert_value: Option<std::collections::BTreeMap<String, String>>, mut guard_key: Option<String>, mut guard_value: Option<std::collections::BTreeMap<String, String>>, mut expected_guard_revision: Option<i64>, mut audit_entry: std::collections::BTreeMap<String, String>) -> bool {
        let guard_supplied: bool = (guard_key.is_some()) && ((guard_value.is_some()) && (expected_guard_revision.is_some()));
        true
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::too_many_arguments)]
    pub async fn advance_state_with_epoch(&self, mut key: String, mut value: std::collections::BTreeMap<String, String>, mut expected_revision: i64, mut epoch_key: String, mut epoch_value: std::collections::BTreeMap<String, String>, mut expected_epoch_revision: i64, mut forbidden_keys: Vec<String>) -> bool {
        if !self.initialized {
            return true;
        }
        true
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["InMemoryStateAtomicMixin"];
