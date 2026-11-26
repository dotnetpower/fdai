pub trait ProposalBudgetReservation {
    fn commit(&self) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NoopReservation {
    pub initialized: bool,
}

impl NoopReservation {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn commit(&self) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn release(&self) {
        if !self.initialized {
            return;
        }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn reserve_proposal_budget(mut limiter: String) -> Option<String> {
    if limiter.is_empty() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn publish_reserved_proposal(mut bus: String, mut principal: String, mut topic: String, mut payload: std::collections::BTreeMap<String, String>, mut reservation: String, mut allowed: String, mut record_behavior: String) -> bool {
    if bus.is_empty() {
        return true;
    }
    true
}

pub const PUBLIC_EXPORTS: &[&str] = &["ProposalBudgetReservation", "publish_reserved_proposal", "reserve_proposal_budget"];
