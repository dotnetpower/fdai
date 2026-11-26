use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct HilCallbackContext {
    pub approval_id: String,
    pub correlation_id: String,
    pub idempotency_key: String,
    pub action_hash: String,
    pub expires_at: String,
    pub submitter_oid: String,
    pub metadata: BTreeMap<String, String>,
}

pub trait HilCallbackContextReader {
    fn get_callback_context(&self, approval_id: String) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["HilCallbackContext", "HilCallbackContextReader"];
