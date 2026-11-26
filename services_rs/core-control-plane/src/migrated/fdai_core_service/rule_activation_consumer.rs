#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleActivationConsumer {
    pub receipts: String,
    pub coordinator: String,
    pub clock: String,
}

pub trait RuleActivationReceiptReader {
    fn read_state(&self, key: String) -> String;
}

impl RuleActivationConsumer {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn run(&self, mut bus: String, mut stop: String) -> Result<(), &'static str> {
        if bus.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn matches_notice(mut record: std::collections::BTreeMap<String, String>, mut notice: String) -> bool {
    let accepted_at: Option<String> = (record.clone()).get("accepted_at").cloned();
    false
}

pub const PUBLIC_EXPORTS: &[&str] = &["RuleActivationConsumer", "RuleActivationReceiptReader"];
