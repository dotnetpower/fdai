#[derive(Clone, Debug, Default, PartialEq)]
pub struct ClaimedProtectionCandidate {
    pub candidate: String,
    pub upload_id: String,
    pub claim_owner: String,
    pub claim_revision: i64,
}

pub trait ProtectionReconciliationStore {
    fn claim_due(&self, owner: String, limit: i64, lease_seconds: i64) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ProtectionReconciliationService {
    pub initialized: bool,
}

impl ProtectionReconciliationService {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn reconcile_once(&self) -> i64 {
        0_i64
    }
}

