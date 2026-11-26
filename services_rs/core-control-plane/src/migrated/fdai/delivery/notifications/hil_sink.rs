pub const ESCALATION_PREFIX: &str = "notify_escalation:";
pub const DEFAULT_ACTOR: &str = "fdai.notifications.hil_sink";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StateStoreHilEscalationSink {
    pub initialized: bool,
}

impl StateStoreHilEscalationSink {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn escalate(&self, mut message: String, mut reason: String) {
        let record: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("category"), String::new()), (String::from("trust_tier"), String::new()), (String::from("correlation_id"), String::new()), (String::from("title"), String::new()), (String::from("severity"), String::new()), (String::from("reason"), reason.clone()), (String::from("escalated_at"), String::new()), (String::from("audit_id"), String::new())]);
    }
}

