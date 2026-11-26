#[derive(Clone, Debug, Default, PartialEq)]
pub struct OperatorRequestReceiptIssuer {
    pub signer: String,
    pub producer_service_identity: String,
    pub clock: String,
    pub lifetime: String,
}

pub trait OperatorRequestReceiptSigner {
    fn sign_operator_request_receipt(&self, signing_bytes: Vec<u8>) -> String;
}

impl OperatorRequestReceiptIssuer {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn issue(&self, mut event: std::collections::BTreeMap<String, String>) -> String {
        if event.is_empty() {
            return String::new();
        }
        String::new()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SeedOperatorRequestReceiptSigner {
    pub initialized: bool,
}

impl SeedOperatorRequestReceiptSigner {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn sign_operator_request_receipt(&self, mut signing_bytes: Vec<u8>) -> Result<Vec<u8>, &'static str> {
        Err("SeedOperatorRequestReceiptSigner signs through OperatorRequestReceiptIss")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn issue(&self, mut event: std::collections::BTreeMap<String, String>, mut producer_service_identity: String, mut issued_at: String, mut expires_at: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["OperatorRequestReceiptIssuer", "OperatorRequestReceiptSigner", "SeedOperatorRequestReceiptSigner"];
