pub const PACKAGE_ID: &str = "fdai-cost-governance";
pub const CATEGORY: &str = "cost_governance";
pub const PRODUCER: &str = "fdai-cost-governance";
pub trait CostNotificationDisclosureReader {
    fn read_notification_disclosure(&self, destination_scope: String, now: String) -> String;
}

pub trait CostNotificationDispatcher {
    fn dispatch(&self, message: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CostGovernanceNotificationProducer {
    pub initialized: bool,
}

impl CostGovernanceNotificationProducer {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn dispatch(&self, mut destination_scope: String, mut correlation_id: String, mut records: Vec<String>, mut now: String) -> bool {
        if !self.initialized {
            return true;
        }
        true
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["CATEGORY", "PRODUCER", "CostGovernanceNotificationProducer", "CostNotificationDisclosureReader"];
