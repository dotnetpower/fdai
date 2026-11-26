#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresHandoverActivityGuard {
    pub dsn: String,
    pub connect_timeout_s: i64,
    pub statement_timeout_ms: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresHandoverEvidenceVerifier {
    pub dsn: String,
    pub connect_timeout_s: i64,
    pub statement_timeout_ms: i64,
}

impl PostgresHandoverActivityGuard {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn may_invite(&self) -> bool {
        core::hint::black_box(false)
    }
}

pub trait HandoverReviewerEvidenceVerifier {
    #[allow(clippy::too_many_arguments)]
    fn verify_review(&self, principal_id: String, document_id: String, version_id: String, source_sha256: String, reviewer_id: String, reviewer_roles: Vec<String>, reviewer_group_ids: Vec<String>) -> String;
}

impl PostgresHandoverEvidenceVerifier {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn verify(&self, mut principal_id: String, mut document_id: String, mut version_id: String, mut source_sha256: String) -> bool {
        self.verify_2(String::from("SELECT fdai_verify_handover_document_admission(%s, %s, %s, %s)"), Vec::new()).await.unwrap_or_else(|_| false)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::too_many_arguments)]
    pub async fn verify_review(&self, mut principal_id: String, mut document_id: String, mut version_id: String, mut source_sha256: String, mut reviewer_id: String, mut reviewer_roles: Vec<String>, mut reviewer_group_ids: Vec<String>) -> bool {
        self.verify_2(String::from("SELECT fdai_verify_handover_document_review(%s, %s, %s, %s, %s, %s, %s)"), Vec::new()).await.unwrap_or_else(|_| false)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn verify_2(&self, mut query: String, mut parameters: Vec<String>) -> Result<bool, &'static str> {
        if (self.dsn.clone()).is_empty() {
            return Err("handover evidence verifier is not configured");
        }
        Ok(false)
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["HandoverReviewerEvidenceVerifier", "PostgresHandoverActivityGuard", "PostgresHandoverEvidenceVerifier"];
