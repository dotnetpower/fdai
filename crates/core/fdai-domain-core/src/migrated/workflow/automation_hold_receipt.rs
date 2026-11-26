#[derive(Clone, Debug, Default, PartialEq)]
pub struct AutomationHoldReleaseReceipt {
    pub action_id: String,
    pub target_digest: String,
    pub process_id: String,
    pub released_hold_revision: i64,
    pub fencing_generation: i64,
    pub recovery_admission_digest: String,
    pub recovery_evidence_digest: String,
    pub compensation_receipt_digests: Vec<String>,
    pub source_revision: String,
    pub released_at: String,
    pub receipt_digest: String,
    pub execution_authority: bool,
}

impl AutomationHoldReleaseReceipt {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

impl AutomationHoldReleaseReceipt {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    #[allow(clippy::too_many_arguments)]
    pub fn create(mut action_id: String, mut target_digest: String, mut process_id: String, mut released_hold_revision: i64, mut fencing_generation: i64, mut recovery_admission_digest: String, mut recovery_evidence_digest: String, mut compensation_receipt_digests: Vec<String>, mut source_revision: String, mut released_at: String) -> AutomationHoldReleaseReceipt {
        if action_id.is_empty() {
            return Default::default();
        }
        Default::default()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("released_at"), String::new())])
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn matching_release_receipt(mut record: String, mut action_id: String, mut process_id: String, mut hold_revision: i64, mut recovery_admission_digest: String) -> Option<AutomationHoldReleaseReceipt> {
    Some(AutomationHoldReleaseReceipt { execution_authority: false, ..Default::default() })
}

pub const PUBLIC_EXPORTS: &[&str] = &["AutomationHoldReleaseReceipt"];
