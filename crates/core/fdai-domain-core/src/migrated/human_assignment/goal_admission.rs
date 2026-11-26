pub trait GoalEvidenceAdmission {
    fn verify_subject(&self, subject_ref: String, assignment_case_id: String) -> bool;
    fn verify(&self, subject_ref: String, evidence_ref: String, digest: String, reviewer_ref: String) -> String;
}

pub trait GoalReviewerEligibility {
    fn may_review(&self, reviewer_ref: String, agent_name: String, scope_ref: String, role: String) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["GoalEvidenceAdmission", "GoalReviewerEligibility"];
