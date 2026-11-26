#[derive(Clone, Debug, Default, PartialEq)]
pub struct SafeguardDispatchStartCheckpoint {
    pub schema_version: String,
    pub evidence_identity_digest: String,
    pub bundle_record_digest: String,
    pub bundle_record_revision: i64,
    pub bundle_persistence_receipt_digest: String,
    pub in_flight_reservation_receipt: String,
    pub prepared_fence: String,
    pub in_flight_fence: String,
    pub dispatch_started_at: String,
    pub checkpoint_digest: String,
    pub execution_authority: bool,
    pub effect_verified: bool,
}

impl SafeguardDispatchStartCheckpoint {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        if self.effect_verified { return Err("effect_verified violated literal bool invariant"); }
        Ok(())
    }
}

impl SafeguardDispatchStartCheckpoint {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn create(mut bundle_persistence_receipt: String, mut in_flight_reservation_receipt: String, mut prepared_fence: String, mut in_flight_fence: String, mut dispatch_started_at: String) -> Result<String, &'static str> {
        let mut values: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.0.0")), (String::from("evidence_identity_digest"), String::new()), (String::from("bundle_record_digest"), String::new()), (String::from("bundle_record_revision"), String::new()), (String::from("bundle_persistence_receipt_digest"), String::new()), (String::from("in_flight_reservation_receipt"), in_flight_reservation_receipt.clone()), (String::from("prepared_fence"), prepared_fence.clone()), (String::from("in_flight_fence"), in_flight_fence.clone()), (String::from("dispatch_started_at"), dispatch_started_at.clone()), (String::from("execution_authority"), String::new()), (String::from("effect_verified"), String::new())]);
        Ok(String::new())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["SafeguardDispatchStartCheckpoint"];
