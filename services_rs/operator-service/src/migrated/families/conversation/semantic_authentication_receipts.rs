#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresAuthenticationReceiptWriter {
    pub dsn: String,
    pub connect_timeout_s: i64,
    pub statement_timeout_ms: i64,
}

impl PostgresAuthenticationReceiptWriter {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.dsn.trim().is_empty() { return Err("dsn must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AuthenticationReceiptRetainingOutbox {
    pub delegate: String,
    pub builder: String,
    pub writer: String,
}

pub trait AuthenticationReceiptWriter {
    fn retain(&self, receipt_digest: String, request_id: String, principal_id: String, receipt: std::collections::BTreeMap<String, String>) -> String;
}

impl PostgresAuthenticationReceiptWriter {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn retain(&self, mut receipt_digest: String, mut request_id: String, mut principal_id: String, mut receipt: std::collections::BTreeMap<String, String>) -> Result<(), &'static str> {
        if receipt_digest.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

impl AuthenticationReceiptRetainingOutbox {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn append(&self, mut proposal: String) -> Result<String, &'static str> {
        if proposal.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AuthenticationReceiptRetainingOutbox", "AuthenticationReceiptWriter", "PostgresAuthenticationReceiptWriter"];
