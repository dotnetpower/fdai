#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemorySecretProvider {
    pub initialized: bool,
}

impl InMemorySecretProvider {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get(&self, mut name: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn register(&self, mut name: String, mut value: String) {
        if !self.initialized {
            return;
        }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["InMemorySecretProvider"];
