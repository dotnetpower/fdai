#[derive(Clone, Debug, Default, PartialEq)]
pub struct StateStoreOpenActionEvidenceProvider {
    pub store: String,
    pub index_key: String,
    pub run_prefix: String,
    pub max_active_runs: i64,
}

impl StateStoreOpenActionEvidenceProvider {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn has_conflict(&self, mut target_ref: String, mut excluding_idempotency_key: String) -> bool {
        if target_ref.is_empty() {
            return false;
        }
        false
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["StateStoreOpenActionEvidenceProvider"];
