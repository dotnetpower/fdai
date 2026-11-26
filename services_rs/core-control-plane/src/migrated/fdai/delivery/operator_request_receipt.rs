#[derive(Clone, Debug, Default, PartialEq)]
pub struct CoreOperatorRequestReceiptIssuer {
    pub private_key_seed: String,
    pub producer_service_identity: String,
    pub clock: String,
    pub lifetime: String,
}

pub const CORE_OPERATOR_REQUEST_PRODUCER_ID: &str = "core-control-plane";
pub const CORE_OPERATOR_REQUEST_SIGNING_SEED_ENV: &str = "FDAI_OPERATOR_REQUEST_CORE_SIGNING_SEED";
pub const CORE_OPERATOR_REQUEST_PRODUCER_ID_ENV: &str = "FDAI_OPERATOR_REQUEST_CORE_PRODUCER_ID";
impl CoreOperatorRequestReceiptIssuer {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn attach(&self, mut event: std::collections::BTreeMap<String, String>) -> std::collections::BTreeMap<String, String> {
        let mut mutable: std::collections::BTreeMap<String, String> = event.clone();
        mutable.clone()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn core_operator_request_receipt_issuer_from_env(mut environ: std::collections::BTreeMap<String, String>) -> Result<Option<CoreOperatorRequestReceiptIssuer>, &'static str> {
    let seed: String = ((environ.clone()).get(CORE_OPERATOR_REQUEST_SIGNING_SEED_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
    if (seed.clone()).is_empty() {
        return Ok(None);
    }
    let producer_id: String = ((environ.clone()).get(CORE_OPERATOR_REQUEST_PRODUCER_ID_ENV).cloned().unwrap_or_else(|| String::from(CORE_OPERATOR_REQUEST_PRODUCER_ID))).trim().to_string();
    if (producer_id.clone()) != (String::from(CORE_OPERATOR_REQUEST_PRODUCER_ID)) {
        return Err("Core operator_request receipts MUST sign as core-control-plane");
    }
    Ok(Some(CoreOperatorRequestReceiptIssuer { private_key_seed: seed.clone(), ..Default::default() }))
}

pub const PUBLIC_EXPORTS: &[&str] = &["CORE_OPERATOR_REQUEST_PRODUCER_ID", "CORE_OPERATOR_REQUEST_PRODUCER_ID_ENV", "CORE_OPERATOR_REQUEST_SIGNING_SEED_ENV", "CoreOperatorRequestReceiptIssuer", "core_operator_request_receipt_issuer_from_env"];
