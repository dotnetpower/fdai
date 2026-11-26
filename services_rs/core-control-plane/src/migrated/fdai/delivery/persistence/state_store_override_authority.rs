#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StateStoreOperatorOverrideAuthorityVerifier {
    pub initialized: bool,
}

impl StateStoreOperatorOverrideAuthorityVerifier {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn verify_override(&self, mut action_type: String, mut action_type_version: String, mut action_type_digest: String, mut gate_evidence_digest: String, mut approval_receipt_digest: String, mut operator_principal: String) -> bool {
        let operator: String = (operator_principal.clone()).to_lowercase();
        false
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["StateStoreOperatorOverrideAuthorityVerifier"];
