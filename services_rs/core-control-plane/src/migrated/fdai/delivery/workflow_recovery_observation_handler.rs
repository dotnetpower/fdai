#[derive(Clone, Debug, Default, PartialEq)]
pub struct RecoveryEffectObservationHandler {
    pub ingress: String,
}

impl RecoveryEffectObservationHandler {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn observe(&self, mut topic: String, mut payload: std::collections::BTreeMap<String, String>) {
        if topic.is_empty() {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn handle(&self, mut payload: std::collections::BTreeMap<String, String>, mut authenticated_principal: String) -> bool {
        if payload.is_empty() {
            return false;
        }
        false
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["RecoveryEffectObservationHandler"];
