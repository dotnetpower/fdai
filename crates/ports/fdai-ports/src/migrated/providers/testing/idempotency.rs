#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryIdempotencyStore {
    pub initialized: bool,
}

impl InMemoryIdempotencyStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn seen(&self, mut key: String) -> Option<std::collections::BTreeMap<String, String>> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn record(&self, mut key: String, mut result: std::collections::BTreeMap<String, String>) -> bool {
        if !self.initialized {
            return true;
        }
        true
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["InMemoryIdempotencyStore"];
