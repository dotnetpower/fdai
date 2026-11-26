#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PackRegistryError {
    pub message: String,
}

impl PackRegistryError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for PackRegistryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for PackRegistryError {}

pub trait PackSigner {
    fn key_id(&self) -> String;
    fn sign(&self, message: Vec<u8>) -> Vec<u8>;
}

pub trait PackSignatureVerifier {
    fn verify(&self, message: Vec<u8>, signature: Vec<u8>, key_id: String) -> bool;
}

pub trait RemediationPackRegistry {
    fn record(&self, pack: String);
    fn get(&self, pack_id: String) -> Option<String>;
    fn revoke(&self, pack_id: String, reason: String) -> String;
    fn list_active(&self) -> Vec<String>;
    fn record_baseline(&self, pack_id: String, document: std::collections::BTreeMap<String, String>);
    #[allow(clippy::type_complexity)]
    fn get_baseline(&self, pack_id: String) -> Option<std::collections::BTreeMap<String, String>>;
    fn append_review(&self, pack_id: String, document: std::collections::BTreeMap<String, String>);
    #[allow(clippy::type_complexity)]
    fn list_reviews(&self, pack_id: String) -> Vec<std::collections::BTreeMap<String, String>>;
}

pub const PUBLIC_EXPORTS: &[&str] = &["PackRegistryError", "PackSignatureVerifier", "PackSigner", "RemediationPackRegistry"];
