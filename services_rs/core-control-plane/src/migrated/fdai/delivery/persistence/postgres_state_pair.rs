#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RollbackTransactionError {
    pub message: String,
}

impl RollbackTransactionError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for RollbackTransactionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for RollbackTransactionError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresStatePairMixin {
    pub initialized: bool,
}

impl PostgresStatePairMixin {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::too_many_arguments)]
    pub async fn compare_and_set_state_pair_with_audit(&self, mut key: String, mut value: std::collections::BTreeMap<String, String>, mut expected_revision: i64, mut second_key: String, mut second_value: std::collections::BTreeMap<String, String>, mut expected_second_revision: i64, mut audit_entry: std::collections::BTreeMap<String, String>) -> Result<bool, &'static str> {
        if ((expected_revision) < (0_i64)) || (((expected_second_revision) < (0_i64)) || ((key.clone()) == (second_key.clone()))) {
            return Err("state pair expected revisions or keys are invalid");
        }
        let first_changed: bool = write_state_revision(String::new(), key.clone(), value.clone(), expected_revision).await;
        let second_changed: bool = write_state_revision(String::new(), second_key.clone(), second_value.clone(), expected_second_revision).await;
        if (!(first_changed)) || (!(second_changed)) {
            return Err("validation_failed");
        }
        Ok(true)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    #[allow(clippy::too_many_arguments)]
    pub async fn compare_and_set_state_with_audit_and_insert(&self, mut key: String, mut value: std::collections::BTreeMap<String, String>, mut expected_revision: i64, mut insert_key: String, mut insert_value: std::collections::BTreeMap<String, String>, mut insert_key_2: Option<String>, mut insert_value_2: Option<std::collections::BTreeMap<String, String>>, mut audit_entry: std::collections::BTreeMap<String, String>) -> Result<bool, &'static str> {
        if (expected_revision) < (0_i64) {
            return Err("expected_revision MUST be  0");
        }
        if !(insert_state(String::new(), insert_key.clone(), insert_value.clone()).await) {
            return Ok(false);
        }
        if (insert_key_2.is_some()) && (insert_value_2.is_some()) {
            if !(upsert_state_when_field_matches(String::new(), (insert_key_2.clone()).unwrap_or_default(), std::collections::BTreeMap::new(), String::from("approval_profile_digest")).await) {
                return Err("validation_failed");
            }
        }
        if !(update_state_revision(String::new(), key.clone(), value.clone(), expected_revision).await) {
            return Err("validation_failed");
        }
        Ok(true)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    #[allow(clippy::too_many_arguments)]
    pub async fn write_state_pair_with_audit_if_absent(&self, mut key: String, mut value: std::collections::BTreeMap<String, String>, mut insert_key: String, mut insert_value: std::collections::BTreeMap<String, String>, mut insert_key_2: Option<String>, mut insert_value_2: Option<std::collections::BTreeMap<String, String>>, mut audit_entry: std::collections::BTreeMap<String, String>) -> Result<bool, &'static str> {
        if !(insert_state(String::new(), key.clone(), value.clone()).await) {
            return Err("validation_failed");
        }
        if !(insert_state(String::new(), insert_key.clone(), insert_value.clone()).await) {
            return Err("validation_failed");
        }
        if (insert_key_2.is_some()) && (insert_value_2.is_some()) {
            if !(upsert_state_when_field_matches(String::new(), (insert_key_2.clone()).unwrap_or_default(), std::collections::BTreeMap::new(), String::from("approval_profile_digest")).await) {
                return Err("validation_failed");
            }
        }
        Ok(true)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::too_many_arguments)]
    pub async fn compare_and_set_state_with_audit_and_insert_before(&self, mut key: String, mut value: std::collections::BTreeMap<String, String>, mut expected_revision: i64, mut insert_key: String, mut insert_value: std::collections::BTreeMap<String, String>, mut not_before: String, mut expires_at: String, mut audit_entry: std::collections::BTreeMap<String, String>) -> Result<bool, &'static str> {
        if (expected_revision) < (0_i64) {
            return Err("expected_revision MUST be  0");
        }
        if !(insert_state(String::new(), insert_key.clone(), insert_value.clone()).await) {
            return Err("validation_failed");
        }
        Ok(true)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    #[allow(clippy::too_many_arguments)]
    pub async fn compare_and_set_state_pair_with_audit_before(&self, mut key: String, mut value: std::collections::BTreeMap<String, String>, mut expected_revision: i64, mut second_key: String, mut second_value: std::collections::BTreeMap<String, String>, mut expected_second_revision: i64, mut not_before: String, mut expires_at: String, mut insert_key: Option<String>, mut insert_value: Option<std::collections::BTreeMap<String, String>>, mut guard_key: Option<String>, mut guard_value: Option<std::collections::BTreeMap<String, String>>, mut expected_guard_revision: Option<i64>, mut audit_entry: std::collections::BTreeMap<String, String>) -> Result<bool, &'static str> {
        let guard_supplied: bool = (guard_key.is_some()) && ((guard_value.is_some()) && (expected_guard_revision.is_some()));
        if (expected_second_revision) == (0_i64) {
            let mut second_changed: bool = insert_state(String::new(), second_key.clone(), second_value.clone()).await;
        } else {
            let mut second_changed: bool = update_state_revision(String::new(), second_key.clone(), second_value.clone(), expected_second_revision).await;
        }
        if guard_supplied {
            if (guard_key.is_none()) || ((guard_value.is_none()) || (expected_guard_revision.is_none())) {
                return Err("state pair guard is incomplete");
            }
            if !(update_state_revision(String::new(), (guard_key.clone()).unwrap_or_default(), std::collections::BTreeMap::new(), 0_i64).await) {
                return Err("validation_failed");
            }
        }
        if (insert_key.is_some()) && ((insert_value.is_some()) && (!(insert_state(String::new(), (insert_key.clone()).unwrap_or_default(), std::collections::BTreeMap::new()).await))) {
            return Err("validation_failed");
        }
        Ok(true)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::too_many_arguments)]
    pub async fn advance_state_with_epoch(&self, mut key: String, mut value: std::collections::BTreeMap<String, String>, mut expected_revision: i64, mut epoch_key: String, mut epoch_value: std::collections::BTreeMap<String, String>, mut expected_epoch_revision: i64, mut forbidden_keys: Vec<String>) -> Result<bool, &'static str> {
        if ((expected_revision) < (0_i64)) || ((expected_epoch_revision) < (1_i64)) {
            return Err("state epoch expected revisions are invalid");
        }
        if (expected_revision) == (0_i64) {
            let mut changed: bool = insert_state(String::new(), key.clone(), value.clone()).await;
        } else {
            let mut changed: bool = update_state_revision(String::new(), key.clone(), value.clone(), expected_revision).await;
        }
        Ok(true)
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn insert_state(mut conn: String, mut key: String, mut value: std::collections::BTreeMap<String, String>) -> bool {
    if conn.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn update_state_revision(mut conn: String, mut key: String, mut value: std::collections::BTreeMap<String, String>, mut expected_revision: i64) -> bool {
    if conn.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn write_state_revision(mut conn: String, mut key: String, mut value: std::collections::BTreeMap<String, String>, mut expected_revision: i64) -> bool {
    if (expected_revision) == (0_i64) {
        return insert_state(conn.clone(), key.clone(), value.clone()).await;
    }
    update_state_revision(conn.clone(), key.clone(), value.clone(), expected_revision).await
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn upsert_state_when_field_matches(mut conn: String, mut key: String, mut value: std::collections::BTreeMap<String, String>, mut field: String) -> bool {
    if conn.is_empty() {
        return false;
    }
    false
}

