pub trait RuleActivationCohortCommitStore {
    #[allow(clippy::too_many_arguments)]
    fn advance_prepare(&self, key: String, value: std::collections::BTreeMap<String, String>, expected_revision: i64, retention_epoch_key: String, retention_epoch_value: std::collections::BTreeMap<String, String>, expected_retention_epoch_revision: i64, retired_keys: Vec<String>) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["RuleActivationCohortCommitStore"];
