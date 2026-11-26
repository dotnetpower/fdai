pub trait IdempotencyStore {
    #[allow(clippy::type_complexity)]
    fn seen(&self, key: String) -> Option<std::collections::BTreeMap<String, String>>;
    fn record(&self, key: String, result: std::collections::BTreeMap<String, String>) -> bool;
}

pub const PUBLIC_EXPORTS: &[&str] = &["IdempotencyStore"];
