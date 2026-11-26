pub const WORKFLOW_APPROVAL_EVIDENCE_PURPOSE: &str = "workflow-approval-quorum";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn workflow_approval_evidence_digest(mut snapshot: String, mut quorum: i64, mut no_self_approval: bool) -> String {
    if snapshot.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn workflow_approval_scope_digest(mut snapshot: String) -> String {
    if snapshot.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn workflow_approval_admission_rejection_reasons(mut provider: Option<String>, mut snapshot: String, mut quorum: i64, mut no_self_approval: bool, mut evaluated_at: String) -> Vec<String> {
    let evidence_digest: String = workflow_approval_evidence_digest(snapshot.clone(), quorum, no_self_approval);
    let scope_digest: String = workflow_approval_scope_digest(snapshot.clone());
    let mut admission: Option<String> = None;
    Vec::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["WORKFLOW_APPROVAL_EVIDENCE_PURPOSE", "workflow_approval_admission_rejection_reasons", "workflow_approval_evidence_digest", "workflow_approval_scope_digest"];
