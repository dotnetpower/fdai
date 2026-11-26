use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct SemanticAuthenticationReceiptRow {
    pub receipt_digest: String,
    pub request_id: String,
    pub principal_id: String,
    pub receipt: BTreeMap<String, String>,
    pub recorded_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CaseHistoryReadback {
    pub required_role: Option<String>,
}

pub const PURPOSE: &str = "case-history-read";
pub const AUTHENTICATION_SOURCE: &str = "operator-service.authentication-receipts";
pub const GRANT_SOURCE: &str = "deployment.case-scope-grants";
pub trait SemanticAuthenticationReceiptSource {
    fn receipts_for_request(&self, receipt_digest: String, request_id: String) -> String;
}

impl CaseHistoryReadback {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn read(&self, mut context: String) -> String {
        if context.is_empty() {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn scope_matches(&self, mut scope: String, mut context: String) -> bool {
        if scope.is_empty() {
            return true;
        }
        true
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AgentDiscussionReadback {
    pub initialized: bool,
}

impl AgentDiscussionReadback {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn scope_matches(&self, mut scope: String, mut context: String) -> bool {
        self.initialized
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn read(&self, mut context: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AgentDiscussionReadback", "AUTHENTICATION_SOURCE", "GRANT_SOURCE", "PURPOSE", "CaseHistoryReadback", "SemanticAuthenticationReceiptRow", "SemanticAuthenticationReceiptSource"];
