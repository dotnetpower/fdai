#[derive(Clone, Debug, Default, PartialEq)]
pub struct ApprovalContext {
    pub plan_digest: String,
    pub approvals: Vec<String>,
    pub process_id: String,
    pub approval_step_id: String,
    pub attempt: i64,
}

impl ApprovalContext {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !(1_i64..=1000000_i64).contains(&self.attempt) { return Err("attempt out of bounds"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ForwardRecord {
    pub dispatch: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RecoveryRecord {
    pub admission: String,
    pub promotion_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AdmittedAlertAuthority {
    pub proof: String,
    pub approvals: Vec<String>,
    pub dispatch: String,
    pub process_id: String,
    pub approval_step_id: String,
    pub attempt: i64,
    pub approval_snapshot_digest: String,
    pub promotion: String,
    pub approval_valid_until: String,
    pub identity_binding_digest: String,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn alert_dispatch_binding(mut action: String, mut plan: String, mut pr: String, mut authority: AdmittedAlertAuthority, mut evidence_receipt_digest: Option<String>, mut evaluation_admission_digest: Option<String>) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("action_digest"), String::new()), (String::from("plan_digest"), String::new()), (String::from("publication_digest"), String::new()), (String::from("authority_digest"), String::new()), (String::from("authority_receipt_digest"), String::new()), (String::from("approval_snapshot_digest"), authority.approval_snapshot_digest.clone()), (String::from("identity_binding_digest"), authority.identity_binding_digest.clone()), (String::from("promotion_record_digest"), String::new()), (String::from("dispatch_evidence_digest"), String::new()), (String::from("approval_receipt_refs"), String::new()), (String::from("evidence_digest"), String::new()), (String::from("evidence_receipt_digest"), (evidence_receipt_digest.clone()).unwrap_or_default()), (String::from("evaluation_receipt_digest"), String::new()), (String::from("evaluation_admission_digest"), (evaluation_admission_digest.clone()).unwrap_or_default()), (String::from("execution_authority"), String::new())])
}

