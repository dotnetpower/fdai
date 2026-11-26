pub trait RuleRevisionChangeAuthorizer {
    fn authorize_revision_change(&self, approval: String, proposal: String) -> String;
}

pub trait RuleRollbackEligibilityVerifier {
    fn rollback_eligibility_expires_at(&self, proposal: String) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["RuleRevisionChangeAuthorizer", "RuleRollbackEligibilityVerifier"];
