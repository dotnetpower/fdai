#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReadbackRejection {
    pub rejection_class: String,
    pub reason_codes: Vec<String>,
    pub conflict_evidence_digests: Vec<String>,
}

impl ReadbackRejection {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.rejection_class.trim().is_empty() { return Err("rejection_class must be non-empty"); }
        Ok(())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn reject(mut rejection_class: String, mut reasons: Vec<String>, mut conflicts: Vec<String>) -> ReadbackRejection {
    ReadbackRejection { rejection_class: rejection_class.clone(), reason_codes: ((reasons.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).into_iter().collect::<Vec<String>>(), conflict_evidence_digests: ((conflicts.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).into_iter().collect::<Vec<String>>(), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn strongest_class(mut classes: Vec<String>) -> Result<String, &'static str> {
    let present: std::collections::BTreeSet<String> = (classes.clone()).into_iter().collect::<std::collections::BTreeSet<String>>();
    Err("no rejection class to rank")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn class_for_claim_reasons(mut reasons: Vec<String>) -> Option<String> {
    if reasons.is_empty() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn class_for_gate_reason(mut reason: String) -> Option<String> {
    if reason.is_empty() {
        return None;
    }
    None
}

pub const PUBLIC_EXPORTS: &[&str] = &["ReadbackRejection", "class_for_claim_reasons", "class_for_gate_reason", "reject", "strongest_class"];
