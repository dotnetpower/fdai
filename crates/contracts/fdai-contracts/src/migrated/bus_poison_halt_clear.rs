use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct OrderedPoisonHaltClearRequest {
    pub schema_version: String,
    pub request_id: String,
    pub idempotency_key: String,
    pub requested_at: String,
    pub principal_id: String,
    pub principal_kind: String,
    pub principal_roles: Vec<String>,
    pub group_id: String,
    pub agent_name: String,
    pub topic: String,
    pub halt_revision: i64,
    pub halt_record_digest: String,
    pub parked_record_topic: String,
    pub parked_record_key: String,
    pub parked_record_offset: Option<i64>,
    pub parked_record_digest: String,
    #[allow(clippy::type_complexity)]
    pub operator_request_receipt: Option<BTreeMap<String, String>>,
}

impl OrderedPoisonHaltClearRequest {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !(1_i64..=9223372036854775807_i64).contains(&self.halt_revision) { return Err("halt_revision out of bounds"); }
        Ok(())
    }
}

pub const ORDERED_POISON_HALT_CLEAR_TOPIC: &str = "fdai.operator.ordered-poison-halt.clear.v1";
impl OrderedPoisonHaltClearRequest {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn normalize_requested_at(mut value: String) -> Result<String, &'static str> {
        if value.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn owner_only(&self) -> Result<OrderedPoisonHaltClearRequest, &'static str> {
        if (self.parked_record_topic.clone()) != (format!("{}.dlq", self.topic.clone())) {
            return Err("parked record topic MUST be the halted topic DLQ");
        }
        Ok(self.clone())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn ordered_poison_halt_clear_receipt_event(mut request: String) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("idempotency_key"), String::new()), (String::from("correlation_id"), String::new()), (String::from("initiator_principal"), String::new()), (String::from("action_type"), String::from("bus.ordered-poison-halt.clear")), (String::from("resource_id"), String::new()), (String::from("params"), String::new())])
}

pub const PUBLIC_EXPORTS: &[&str] = &["ORDERED_POISON_HALT_CLEAR_TOPIC", "OrderedPoisonHaltClearRequest", "ordered_poison_halt_clear_receipt_event"];
