#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryOutboxStore {
    pub initialized: bool,
}

impl InMemoryOutboxStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn claim(&self, mut key: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn complete(&self, mut key: String, mut result: std::collections::BTreeMap<String, String>) {
        if !self.initialized {
            return;
        }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["InMemoryOutboxStore"];
